from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext, request_id_var
from app.core.errors import DomainValidationError
from app.core.pagination import CursorPage, decode_cursor, encode_cursor
from app.db.session import service_transaction
from app.modules.audit.models import AuditEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditEventResponse


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_events(
        self,
        *,
        limit: int,
        cursor: str | None,
        action: str | None,
        resource_type: str | None,
        resource_id: UUID | None,
        actor_user_id: UUID | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> CursorPage[AuditEventResponse]:
        if from_time and to_time and from_time > to_time:
            raise DomainValidationError(message="The 'from' timestamp must precede 'to'.")
        decoded_cursor: tuple[datetime, UUID] | None = None
        if cursor:
            try:
                timestamp, event_id = decode_cursor(cursor)
                occurred_at = datetime.fromisoformat(timestamp)
                if occurred_at.tzinfo is None:
                    raise ValueError("Cursor timestamp must include a timezone")
                decoded_cursor = (occurred_at, UUID(event_id))
            except (ValueError, TypeError) as exc:
                raise DomainValidationError(message="Invalid audit cursor.") from exc
        async with service_transaction(self.session):
            rows = await AuditRepository(self.session).list_events(
                limit=limit,
                cursor=decoded_cursor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                actor_user_id=actor_user_id,
                from_time=from_time,
                to_time=to_time,
            )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(last.occurred_at.isoformat(), str(last.id))
        return CursorPage(
            items=[AuditEventResponse.model_validate(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def record(
        self,
        context: TenantContext,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            actor_membership_id=context.membership_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id_var.get(),
            metadata_=metadata or {},
        )
        self.session.add(event)
        return event
