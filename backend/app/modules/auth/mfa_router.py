"""MFA/TOTP endpoints (SECURITY.md §12).

`/setup`, `/enable`, `/disable` require an ordinary bearer token — MFA is
self-service, gated by identity alone, not a permission (a user manages their
own second factor; nobody manages anyone else's). `/challenge` is the odd one
out: it runs *before* a session exists, authenticated only by possessing the
short-lived challenge token `/auth/login` issued, so it takes no bearer token
at all.
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentIdentity,
    get_current_identity,
    get_db,
    get_security_events,
    get_settings_from_app,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.redis import RedisClient
from app.core.security import SecurityService
from app.modules.audit import security_service as sec
from app.modules.audit.security_service import SecurityEventService
from app.modules.auth.mfa import MfaChallengeStore, MfaService
from app.modules.auth.ratelimit import MFA_CHALLENGE_PER_IP, MFA_CHALLENGE_PER_TOKEN
from app.modules.auth.router import (
    _client_ip,
    _rate_limiter,
    _service,
    _set_refresh_cookie,
    _summaries,
)
from app.modules.auth.schemas import (
    MfaDisableRequest,
    MfaEnableRequest,
    MfaEnableResponse,
    MfaSetupResponse,
    MfaVerifyRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth/mfa", tags=["auth"])

Identity = Annotated[CurrentIdentity, Depends(get_current_identity)]
Db = Annotated[AsyncSession, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings_from_app)]
Events = Annotated[SecurityEventService, Depends(get_security_events)]


def _mfa(session: AsyncSession, settings: Settings) -> MfaService:
    return MfaService(session, settings)


@router.post("/setup", response_model=MfaSetupResponse)
async def setup(identity: Identity, session: Db, settings: Config) -> MfaSetupResponse:
    current = await _service(session, settings).current_user(identity.claims.user_id)
    result = await _mfa(session, settings).setup(identity.claims.user_id, current.user.email)
    return MfaSetupResponse(secret=result.secret, otpauth_uri=result.otpauth_uri)


@router.post("/enable", response_model=MfaEnableResponse)
async def enable(
    payload: MfaEnableRequest, identity: Identity, session: Db, settings: Config, events: Events
) -> MfaEnableResponse:
    result = await _mfa(session, settings).enable(identity.claims.user_id, payload.code)
    await events.record(
        sec.MFA_ENABLED,
        "user",
        actor_user_id=identity.claims.user_id,
        resource_id=identity.claims.user_id,
    )
    return MfaEnableResponse(recovery_codes=result.recovery_codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable(
    payload: MfaDisableRequest, identity: Identity, session: Db, settings: Config, events: Events
) -> None:
    """Requires the password again, not just an access token — a stolen
    bearer token alone must not be able to strip a user's second factor."""
    current = await _service(session, settings).current_user(identity.claims.user_id)
    security = SecurityService(settings)
    if not security.verify_password(current.user.password_hash, payload.password):
        raise AppError("INVALID_CREDENTIALS", "Invalid email or password.", 401)
    mfa = _mfa(session, settings)
    if not await mfa.verify_code(identity.claims.user_id, payload.code):
        raise AppError("MFA_CODE_INVALID", "The code is incorrect or expired.", 401)
    await mfa.disable(identity.claims.user_id)
    await events.record(
        sec.MFA_DISABLED,
        "user",
        actor_user_id=identity.claims.user_id,
        resource_id=identity.claims.user_id,
    )


@router.post("/challenge", response_model=TokenResponse)
async def challenge(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    session: Db,
    settings: Config,
    events: Events,
) -> TokenResponse:
    ip = _client_ip(request)
    redis = cast(RedisClient, request.app.state.redis)
    await _rate_limiter(request, settings).enforce_all(
        (MFA_CHALLENGE_PER_TOKEN, payload.challenge_token),
        (MFA_CHALLENGE_PER_IP, ip),
    )
    store = MfaChallengeStore(redis, settings)
    user_id = await store.resolve(payload.challenge_token)
    if user_id is None:
        raise AppError(
            "MFA_CHALLENGE_INVALID", "This challenge has expired or was already used.", 401
        )
    if not await _mfa(session, settings).verify_code(user_id, payload.code):
        await events.record(sec.MFA_CHALLENGE_FAILED, "user", actor_user_id=user_id, ip=ip)
        raise AppError("MFA_CODE_INVALID", "The code is incorrect or expired.", 401)
    # Single-use once the code is right — a second replay of the same
    # challenge token, correct code or not, must not open a second session.
    await store.consume(payload.challenge_token)
    agent = request.headers.get("user-agent")
    result = await _service(session, settings).complete_mfa_login(user_id, ip=ip, user_agent=agent)
    await events.record(
        sec.MFA_CHALLENGE_SUCCEEDED, "user", actor_user_id=user_id, resource_id=user_id, ip=ip
    )
    _set_refresh_cookie(response, result.tokens.refresh_token, settings)
    return TokenResponse(
        access_token=result.tokens.access_token,
        expires_in=settings.access_token_expire_minutes * 60,
        active_tenant_id=result.tokens.tenant_id,
        memberships=_summaries(result),
    )
