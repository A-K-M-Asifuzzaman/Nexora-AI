from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_events(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
        action: str | None,
        resource_type: str | None,
        resource_id: UUID | None,
        actor_user_id: UUID | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> list[AuditEvent]:
        statement: Select[tuple[AuditEvent]] = select(AuditEvent)
        if cursor is not None:
            occurred_at, event_id = cursor
            statement = statement.where(
                or_(
                    AuditEvent.occurred_at < occurred_at,
                    and_(AuditEvent.occurred_at == occurred_at, AuditEvent.id < event_id),
                )
            )
        filters = (
            (AuditEvent.action == action) if action else None,
            (AuditEvent.resource_type == resource_type) if resource_type else None,
            (AuditEvent.resource_id == resource_id) if resource_id else None,
            (AuditEvent.actor_user_id == actor_user_id) if actor_user_id else None,
            (AuditEvent.occurred_at >= from_time) if from_time else None,
            (AuditEvent.occurred_at <= to_time) if to_time else None,
        )
        statement = statement.where(*(item for item in filters if item is not None))
        result = await self.session.scalars(
            statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
        )
        return list(result)
