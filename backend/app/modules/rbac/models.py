from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import Timestamped, UUIDPk


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)


class Role(UUIDPk, Timestamped, Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("is_system = (tenant_id IS NULL)", name="system_tenant_consistency"),
        Index(
            "uq_roles_tenant_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where="tenant_id IS NOT NULL",
        ),
        Index("uq_roles_system_code", "code", unique=True, postgresql_where="tenant_id IS NULL"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"), primary_key=True)


class MembershipRole(Base):
    __tablename__ = "membership_roles"

    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
