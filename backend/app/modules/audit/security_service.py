"""Security-event stream (ARCHITECTURE.md §7, ADR-0023).

Deliberately separate from `AuditService`. Business audit rows ride the
business transaction, so an audit row *proves* its operation committed. Security
events mostly record things that **failed** — a rejected login, a detected token
reuse, a denied authorization — and those must survive the rollback of the
operation that produced them. So they are written on their own session, in their
own transaction.

`tenant_id` is nullable here because pre-tenant identity events (registration,
email verification, password reset) have no tenant by definition.
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import request_id_var
from app.core.net import coerce_ip
from app.modules.audit.models import SecurityEvent

# Identity / platform
USER_REGISTERED = "user.registered"
USER_EMAIL_VERIFIED = "user.email_verified"
USER_PASSWORD_CHANGED = "user.password_changed"  # noqa: S105 -- event name, not a credential
USER_PASSWORD_RESET = "user.password_reset"  # noqa: S105 -- event name, not a credential

# Authentication
LOGIN_SUCCEEDED = "auth.login_succeeded"
LOGIN_FAILED = "auth.login_failed"
LOGOUT = "auth.logout"
ACCOUNT_LOCKED = "auth.account_locked"
REFRESH_REUSE_DETECTED = "auth.refresh_reuse_detected"  # noqa: S105 -- event name

# Authorization / tenancy
AUTHZ_DENIED = "authz.denied"
RATELIMIT_EXCEEDED = "ratelimit.exceeded"
CROSS_TENANT_ATTEMPT = "tenant.cross_access_attempt"


class SecurityEventService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def record(
        self,
        action: str,
        resource_type: str,
        *,
        tenant_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_membership_id: UUID | None = None,
        resource_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write one security event on an independent session.

        Never raises into the caller: a failure to record must not convert a
        handled authentication failure into a 500. The event is best-effort; the
        control it accompanies is not.
        """
        try:
            async with self.factory() as session, session.begin():
                session.add(
                    SecurityEvent(
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                        actor_membership_id=actor_membership_id,
                        action=action,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        request_id=request_id_var.get(),
                        ip=coerce_ip(ip),
                        user_agent=user_agent,
                        metadata_=metadata or {},
                    )
                )
        except Exception:  # noqa: BLE001 -- must never mask the real outcome
            # Swallowed deliberately, but never silently: a broken security-event
            # pipeline is itself a security problem and has to be visible.
            structlog.get_logger(__name__).error(
                "security_event.record_failed", event_action=action, exc_info=True
            )
