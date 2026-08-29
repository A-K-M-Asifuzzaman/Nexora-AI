from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money


class Customer(UUIDPk, TenantScoped, Timestamped, Base):
    """A party the tenant sells to (`DATABASE.md` §4, Phase 3)."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("credit_limit >= 0", name="credit_limit_nonnegative"),
        Index("ix_customers_tenant_id_is_active", "tenant_id", "is_active"),
        Index(
            "ix_customers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    tax_number: Mapped[str | None] = mapped_column(String(64))
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    # Zero means "no credit allowed", which is different from unlimited. Nullable
    # would conflate the two, so unlimited is expressed by leaving the check off
    # at the service layer via `credit_limit_enforced`.
    credit_limit: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    credit_limit_enforced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Supplier(UUIDPk, TenantScoped, Timestamped, Base):
    """A party the tenant buys from (`DATABASE.md` §4, Phase 3)."""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_suppliers_tenant_id_is_active", "tenant_id", "is_active"),
        Index(
            "ix_suppliers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    tax_number: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
