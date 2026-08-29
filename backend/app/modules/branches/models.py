from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class Branch(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_branches_tenant_id_is_active", "tenant_id", "is_active"),
        Index(
            "uq_branches_one_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class Warehouse(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_warehouses_tenant_id_is_active", "tenant_id", "is_active"),
    )

    branch_id: Mapped[UUID | None] = mapped_column(ForeignKey("branches.id"))
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
