from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class TenantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    minor_units: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(12))


class Tenant(UUIDPk, Timestamped, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_year_start_month"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    tax_identifier: Mapped[str | None] = mapped_column(String(64))
    base_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status"), nullable=False, default=TenantStatus.ACTIVE
    )
    allow_negative_inventory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    fiscal_year_start_month: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )


class Membership(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        Index("ix_memberships_tenant_id_status", "tenant_id", "status"),
        Index("ix_memberships_user_id_status", "user_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membership_status"), nullable=False
    )
    roles_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    invited_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MembershipBranch(Base):
    __tablename__ = "membership_branches"

    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), primary_key=True
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True
    )


class Invitation(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_invitations_tenant_id_status", "tenant_id", "status"),
        Index(
            "uq_invitations_pending_email",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND status = 'PENDING'"),
        ),
    )

    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, name="invitation_status"),
        nullable=False,
        default=InvitationStatus.PENDING,
    )
