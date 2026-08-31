"""Authentication endpoints (API.md §5.1).

Two properties this module exists to preserve:

* The refresh token is **never** in a response body. It is set as an httpOnly
  cookie scoped to `Path=/api/v1/auth`, so it is unreadable by JavaScript and is
  not attached to ordinary API calls (ADR-0006, ADR-0014).
* Registration and login responses are **uniform** — the same shape and status
  whether or not the account exists, so neither can be used to enumerate
  accounts (SECURITY.md §2).
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentIdentity,
    get_current_identity,
    get_db,
    get_redis,
    get_security_events,
    get_settings_from_app,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.redis import RedisClient
from app.core.security import SecurityService
from app.modules.audit import security_service as sec
from app.modules.audit.security_service import SecurityEventService
from app.modules.auth.mfa import MfaChallengeStore
from app.modules.auth.ratelimit import (
    FORGOT_PER_IDENTITY,
    FORGOT_PER_IP,
    LOGIN_PER_IDENTITY,
    LOGIN_PER_IP,
    REGISTER_PER_IP,
    AuthRateLimiter,
)
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    EmailRequest,
    LoginRequest,
    MembershipSummary,
    MfaChallengeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SwitchTenantRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService, Login, MfaChallengeRequired

router = APIRouter(prefix="/auth", tags=["auth"])


def _service(session: AsyncSession, settings: Settings) -> AuthService:
    return AuthService(session, settings, SecurityService(settings))


def _rate_limiter(request: Request, settings: Settings) -> AuthRateLimiter:
    return AuthRateLimiter(
        cast(RedisClient, request.app.state.redis), enabled=settings.rate_limit_enabled
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
    )


def _summaries(login: Login) -> list[MembershipSummary]:
    return [
        MembershipSummary(tenant_id=m.tenant_id, tenant_name=name, roles=sorted(roles))
        for m, name, roles in login.memberships
    ]


async def _denylist_session(redis: RedisClient, session_id: UUID, settings: Settings) -> None:
    """Stop already-issued access tokens for a revoked session (ADR-0007).

    Revoking the refresh session alone leaves any outstanding access token valid
    until it expires. The entry only needs to outlive that window.
    """
    await redis.setex(
        f"denylist:session:{session_id}", settings.access_token_expire_minutes * 60 + 60, "1"
    )


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> dict[str, str]:
    await _rate_limiter(request, settings).enforce_all((REGISTER_PER_IP, _client_ip(request)))
    user = await _service(session, settings).register(payload)
    await events.record(
        sec.USER_REGISTERED,
        "user",
        actor_user_id=user.id,
        resource_id=user.id,
        ip=_client_ip(request),
    )
    # Identical response whether or not the address was already registered.
    return {"status": "accepted"}


@router.post("/login", response_model=None)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> TokenResponse | MfaChallengeResponse:
    ip = _client_ip(request)
    agent = request.headers.get("user-agent")
    # Per-identity stops a targeted guess; per-IP stops a broad sweep.
    await _rate_limiter(request, settings).enforce_all(
        (LOGIN_PER_IDENTITY, payload.email.lower()),
        (LOGIN_PER_IP, ip),
    )
    try:
        result = await _service(session, settings).login(payload, ip=ip, user_agent=agent)
    except AppError as exc:
        await events.record(sec.LOGIN_FAILED, "user", ip=ip, metadata={"code": exc.code})
        raise
    if isinstance(result, MfaChallengeRequired):
        # The password half genuinely succeeded — this is not a failure event,
        # but it is not `LOGIN_SUCCEEDED` either: no session opened yet.
        await events.record(sec.MFA_CHALLENGE_ISSUED, "user", actor_user_id=result.user_id, ip=ip)
        token = await MfaChallengeStore(
            cast(RedisClient, request.app.state.redis), settings
        ).create(result.user_id)
        return MfaChallengeResponse(
            challenge_token=token, expires_in=settings.mfa_challenge_ttl_seconds
        )
    await events.record(
        sec.LOGIN_SUCCEEDED,
        "user",
        actor_user_id=result.user.id,
        resource_id=result.user.id,
        ip=ip,
    )
    _set_refresh_cookie(response, result.tokens.refresh_token, settings)
    return TokenResponse(
        access_token=result.tokens.access_token,
        expires_in=settings.access_token_expire_minutes * 60,
        active_tenant_id=result.tokens.tenant_id,
        memberships=_summaries(result),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> TokenResponse:
    raw = request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        raise AppError("TOKEN_INVALID", "Refresh token is missing.", 401)
    service = _service(session, settings)
    # No tenant is taken from the request. ARCHITECTURE.md §4.3 makes the
    # refresh session tenant-agnostic precisely so tenant identity is "not
    # re-derived from a mutable header", and this route previously read
    # `X-Active-Tenant` and minted a token for it with no membership check.
    # Verified: a user could mint a token bound to an organization they do not
    # belong to. Nothing leaked — the RBAC layer re-resolves membership and
    # returned 403 NO_ACTIVE_TENANT — but the token should never have carried
    # the claim, and one future caller trusting `tid` without re-resolving would
    # have made it a cross-tenant read.
    #
    # Re-binding after a refresh is the BFF's job (`bff-upstream.ts`), which is
    # the only party holding session state the browser cannot forge.
    try:
        rotated = await service.rotate_refresh_token(raw, None)
    except AppError as exc:
        if exc.code == "REFRESH_REUSE_DETECTED":
            await events.record(sec.REFRESH_REUSE_DETECTED, "auth_session", ip=_client_ip(request))
        _clear_refresh_cookie(response, settings)
        raise
    _set_refresh_cookie(response, rotated.refresh_token, settings)
    current = await service.current_user(rotated.user_id)
    return TokenResponse(
        access_token=rotated.access_token,
        expires_in=settings.access_token_expire_minutes * 60,
        active_tenant_id=rotated.tenant_id,
        memberships=[
            MembershipSummary(tenant_id=m.tenant_id, tenant_name=name, roles=sorted(roles))
            for m, name, roles in current.memberships
        ],
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> None:
    await _service(session, settings).logout(identity.claims.session_id)
    await _denylist_session(redis, identity.claims.session_id, settings)
    await events.record(sec.LOGOUT, "auth_session", actor_user_id=identity.claims.user_id)
    _clear_refresh_cookie(response, settings)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> None:
    revoked = await _service(session, settings).logout_all(identity.claims.user_id)
    for session_id in revoked:
        await _denylist_session(redis, session_id, settings)
    await events.record(sec.LOGOUT, "auth_session", actor_user_id=identity.claims.user_id)
    _clear_refresh_cookie(response, settings)


@router.get("/me", response_model=UserResponse)
async def me(
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> UserResponse:
    current = await _service(session, settings).current_user(identity.claims.user_id)
    return UserResponse(
        id=current.user.id,
        email=current.user.email,
        full_name=current.user.full_name,
        email_verified_at=current.user.email_verified_at,
        active_tenant_id=identity.claims.tenant_id,
        memberships=[
            MembershipSummary(tenant_id=m.tenant_id, tenant_name=name, roles=sorted(roles))
            for m, name, roles in current.memberships
        ],
    )


@router.post("/switch-tenant", response_model=TokenResponse)
async def switch_tenant(
    payload: SwitchTenantRequest,
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> TokenResponse:
    service = _service(session, settings)
    token = await service.switch_tenant(
        identity.claims.user_id, identity.claims.session_id, payload.tenant_id
    )
    current = await service.current_user(identity.claims.user_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        active_tenant_id=payload.tenant_id,
        memberships=[
            MembershipSummary(tenant_id=m.tenant_id, tenant_name=name, roles=sorted(roles))
            for m, name, roles in current.memberships
        ],
    )


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    payload: EmailRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> dict[str, str]:
    # Same budget as forgot-password: both send mail to an address the caller
    # merely asserts, so both are usable to spam a third party.
    await _rate_limiter(request, settings).enforce_all(
        (FORGOT_PER_IDENTITY, payload.email.lower()),
        (FORGOT_PER_IP, _client_ip(request)),
    )
    await _service(session, settings).issue_verification_token(payload.email)
    # Same response whether or not the address exists, or is already verified.
    return {"status": "accepted"}


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    payload: VerifyEmailRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> dict[str, str]:
    user = await _service(session, settings).verify_email(payload.token)
    await events.record(sec.USER_EMAIL_VERIFIED, "user", actor_user_id=user.id, resource_id=user.id)
    return {"status": "verified"}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: EmailRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> dict[str, str]:
    await _rate_limiter(request, settings).enforce_all(
        (FORGOT_PER_IDENTITY, payload.email.lower()),
        (FORGOT_PER_IP, _client_ip(request)),
    )
    await _service(session, settings).issue_password_reset(payload.email)
    # ALWAYS 202 (API.md §5.1). Anything conditional here is an account oracle.
    return {"status": "accepted"}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> None:
    revoked = await _service(session, settings).reset_password(payload.token, payload.new_password)
    for session_id in revoked:
        await _denylist_session(redis, session_id, settings)
    await events.record(sec.USER_PASSWORD_RESET, "user")
    _clear_refresh_cookie(response, settings)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    events: Annotated[SecurityEventService, Depends(get_security_events)],
) -> None:
    revoked = await _service(session, settings).change_password(
        identity.claims.user_id,
        payload.current_password,
        payload.new_password,
        keep_session_id=identity.claims.session_id,
    )
    for session_id in revoked:
        await _denylist_session(redis, session_id, settings)
    await events.record(sec.USER_PASSWORD_CHANGED, "user", actor_user_id=identity.claims.user_id)
