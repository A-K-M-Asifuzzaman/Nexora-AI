from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class IdempotencyKey(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "endpoint", "key"),
        Index("ix_idempotency_keys_tenant_id_expires_at", "tenant_id", "expires_at"),
    )

    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
