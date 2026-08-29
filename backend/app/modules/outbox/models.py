from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPk


class OutboxEvent(UUIDPk, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_pending",
            "sent_at",
            "available_at",
            postgresql_where="sent_at IS NULL",
        ),
        Index("ix_outbox_events_tenant_id_created_at", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
