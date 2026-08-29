from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductVariant,
    TaxCategory,
    UnitOfMeasure,
)

CatalogModel = TypeVar("CatalogModel", Category, Brand, UnitOfMeasure, TaxCategory)


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_reference(
        self, model: type[CatalogModel], page: int, page_size: int
    ) -> tuple[list[CatalogModel], int]:
        total = await self.session.scalar(select(func.count()).select_from(model)) or 0
        rows = await self.session.scalars(
            select(model)
            .order_by(model.created_at.desc(), model.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def get_reference(
        self, model: type[CatalogModel], resource_id: UUID, *, for_update: bool = False
    ) -> CatalogModel | None:
        statement = select(model).where(model.id == resource_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(CatalogModel | None, await self.session.scalar(statement))

    async def category_parent_chain(self, category_id: UUID) -> list[Category]:
        chain: list[Category] = []
        current_id: UUID | None = category_id
        while current_id is not None:
            current = await self.get_reference(Category, current_id)
            if current is None:
                break
            chain.append(current)
            current_id = current.parent_id
        return chain

    async def category_has_children_or_products(self, category_id: UUID) -> bool:
        children = (
            await self.session.scalar(
                select(func.count()).select_from(Category).where(Category.parent_id == category_id)
            )
            or 0
        )
        products = (
            await self.session.scalar(
                select(func.count()).select_from(Product).where(Product.category_id == category_id)
            )
            or 0
        )
        return bool(children or products)

    async def reference_has_products(self, field: str, resource_id: UUID) -> bool:
        column = {
            "brand": Product.brand_id,
            "unit": Product.uom_id,
            "tax_category": Product.tax_category_id,
        }[field]
        return bool(
            await self.session.scalar(
                select(func.count()).select_from(Product).where(column == resource_id)
            )
        )

    async def list_products(
        self,
        page: int,
        page_size: int,
        *,
        q: str | None,
        category_id: UUID | None,
        brand_id: UUID | None,
        is_active: bool | None,
    ) -> tuple[list[Product], int]:
        filters = []
        if q:
            pattern = f"%{q}%"
            filters.append(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
        if category_id:
            filters.append(Product.category_id == category_id)
        if brand_id:
            filters.append(Product.brand_id == brand_id)
        if is_active is not None:
            filters.append(Product.is_active.is_(is_active))
        count: Select[tuple[int]] = select(func.count()).select_from(Product).where(*filters)
        statement = (
            select(Product)
            .where(*filters)
            .order_by(Product.created_at.desc(), Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = await self.session.scalar(count) or 0
        return list(await self.session.scalars(statement)), total

    async def get_product(self, product_id: UUID, *, for_update: bool = False) -> Product | None:
        statement = select(Product).where(Product.id == product_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Product | None, await self.session.scalar(statement))

    async def product_has_movements(self, product_id: UUID) -> bool:
        result = await self.session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM inventory_movements WHERE product_id = :product_id)"
            ).bindparams(product_id=product_id)
        )
        return bool(result)

    async def variants(self, product_id: UUID) -> list[ProductVariant]:
        return list(
            await self.session.scalars(
                select(ProductVariant)
                .where(ProductVariant.product_id == product_id)
                .order_by(ProductVariant.created_at, ProductVariant.id)
            )
        )

    async def barcodes(self, product_id: UUID) -> list[ProductBarcode]:
        return list(
            await self.session.scalars(
                select(ProductBarcode)
                .where(ProductBarcode.product_id == product_id)
                .order_by(ProductBarcode.is_primary.desc(), ProductBarcode.created_at)
            )
        )

    async def balances(self, product_id: UUID) -> list[dict[str, str]]:
        rows = await self.session.execute(
            text(
                "SELECT warehouse_id, quantity_on_hand, reserved_quantity "
                "FROM inventory_balances WHERE product_id = :product_id ORDER BY warehouse_id"
            ).bindparams(product_id=product_id)
        )
        return [
            {
                "warehouse_id": str(row.warehouse_id),
                "quantity_on_hand": str(row.quantity_on_hand),
                "reserved_quantity": str(row.reserved_quantity),
                "available": str(row.quantity_on_hand - row.reserved_quantity),
            }
            for row in rows
        ]

    async def barcode(self, barcode: str) -> ProductBarcode | None:
        return cast(
            ProductBarcode | None,
            await self.session.scalar(
                select(ProductBarcode).where(ProductBarcode.barcode == barcode)
            ),
        )

    async def variant(self, variant_id: UUID) -> ProductVariant | None:
        return cast(
            ProductVariant | None,
            await self.session.scalar(
                select(ProductVariant).where(ProductVariant.id == variant_id)
            ),
        )

    def add(self, instance: object) -> None:
        self.session.add(instance)
