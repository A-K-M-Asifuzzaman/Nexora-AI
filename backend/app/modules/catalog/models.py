from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money, Quantity, Rate, UnitCost


class Category(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "categories"
    __table_args__ = (
        # NULLS NOT DISTINCT is load-bearing, not decoration. A plain
        # UNIQUE (tenant_id, parent_id, name) does not constrain root
        # categories at all, because parent_id IS NULL there and NULL never
        # equals NULL in a unique constraint. Measured on PostgreSQL 16.14:
        # two identical root categories inserted cleanly. PG 15+ syntax.
        UniqueConstraint("tenant_id", "parent_id", "name", postgresql_nulls_not_distinct=True),
        Index("ix_categories_tenant_id_name", "tenant_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Brand(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        Index("ix_brands_tenant_id_is_active", "tenant_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class UnitOfMeasure(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "units_of_measure"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("precision BETWEEN 0 AND 6", name="precision_range"),
        Index("ix_units_of_measure_tenant_id_is_active", "tenant_id", "is_active"),
    )

    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    precision: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class TaxCategory(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "tax_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("rate >= 0 AND rate <= 1", name="rate_range"),
        Index("ix_tax_categories_tenant_id_is_active", "tenant_id", "is_active"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Rate, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Product(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku"),
        # A negative cost or price is never meaningful and would propagate
        # silently into margin and COGS from Phase 5 onward.
        CheckConstraint("cost_price >= 0", name="cost_price_nonnegative"),
        CheckConstraint("selling_price >= 0", name="selling_price_nonnegative"),
        CheckConstraint("reorder_point IS NULL OR reorder_point >= 0", name="reorder_nonnegative"),
        Index("ix_products_tenant_id_is_active", "tenant_id", "is_active"),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    brand_id: Mapped[UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="RESTRICT"))
    uom_id: Mapped[UUID] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    tax_category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tax_categories.id", ondelete="RESTRICT")
    )
    cost_price: Mapped[Decimal] = mapped_column(
        UnitCost, nullable=False, default=0, server_default="0"
    )
    selling_price: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    reorder_point: Mapped[Decimal | None] = mapped_column(Quantity)
    is_stock_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class ProductVariant(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku"),
        # Referenced by the composite FK on product_barcodes so a barcode
        # cannot name a variant belonging to a different product.
        UniqueConstraint("id", "product_id", name="uq_product_variants_id_product"),
        Index("ix_product_variants_tenant_id_product_id", "tenant_id", "product_id"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class ProductBarcode(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "product_barcodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "barcode"),
        # Without this, a barcode could carry product A while naming a variant
        # of product B — a scan would then resolve to one product and display
        # another's variant. Two independent FKs cannot express that they must
        # agree; a composite one can.
        ForeignKeyConstraint(
            ["product_variant_id", "product_id"],
            ["product_variants.id", "product_variants.product_id"],
            name="fk_product_barcodes_variant_matches_product",
            ondelete="RESTRICT",
        ),
        Index("ix_product_barcodes_tenant_id_product_id", "tenant_id", "product_id"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # No standalone FK here: the composite constraint above owns this column's
    # referential integrity. A second FK to product_variants.id would permit
    # the mismatch the composite one exists to prevent.
    product_variant_id: Mapped[UUID | None] = mapped_column()
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
