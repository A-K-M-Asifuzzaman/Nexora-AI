from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, UUIDPk


class AuditEvent(UUIDPk, TenantScoped, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_id_occurred_at", "tenant_id", "occurred_at"),
        Index(
            "ix_audit_events_tenant_id_resource_type_resource_id",
            "tenant_id",
            "resource_type",
            "resource_id",
        ),
        Index(
            "ix_audit_events_tenant_id_actor_user_id_occurred_at",
            "tenant_id",
            "actor_user_id",
            "occurred_at",
        ),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_membership_id: Mapped[UUID | None] = mapped_column(ForeignKey("memberships.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityEvent(UUIDPk, Base):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_tenant_id_occurred_at", "tenant_id", "occurred_at"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_membership_id: Mapped[UUID | None] = mapped_column(ForeignKey("memberships.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
