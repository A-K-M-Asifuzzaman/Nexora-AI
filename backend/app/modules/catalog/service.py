from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.catalog import events
from app.modules.catalog.models import (
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductVariant,
    TaxCategory,
    UnitOfMeasure,
)
from app.modules.catalog.repository import CatalogRepository
from app.modules.catalog.schemas import (
    BarcodeCreate,
    CategoryCreate,
    CategoryUpdate,
    NamedCreate,
    NamedUpdate,
    ProductCreate,
    ProductUpdate,
    TaxCategoryCreate,
    TaxCategoryUpdate,
    UnitCreate,
    UnitUpdate,
    VariantCreate,
)


class CatalogService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = CatalogRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def list_categories(self, page: int, page_size: int) -> tuple[list[Category], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_reference(Category, page, page_size)

    @staticmethod
    def _reference_model(
        resource: str,
    ) -> type[Any]:
        return {"brand": Brand, "unit": UnitOfMeasure, "tax_category": TaxCategory}[resource]

    async def list_reference(
        self, resource: str, page: int, page_size: int
    ) -> tuple[list[Any], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_reference(
                self._reference_model(resource), page, page_size
            )

    async def create_category(self, payload: CategoryCreate) -> Category:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                if payload.parent_id:
                    chain = await self.repository.category_parent_chain(payload.parent_id)
                    if not chain or chain[0].id != payload.parent_id:
                        raise NotFoundError()
                    if len(chain) >= 5:
                        raise ConflictError(
                            "CATEGORY_CYCLE", "Category depth cannot exceed five levels."
                        )
                category = Category(
                    id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump()
                )
                self.repository.add(category)
                self.audit.record(self.context, events.CATEGORY_CREATED, "category", category.id)
            return category
        except IntegrityError as exc:
            raise ConflictError(
                "DUPLICATE_RESOURCE", "Category name already exists under this parent."
            ) from exc

    async def update_category(self, category_id: UUID, payload: CategoryUpdate) -> Category:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                category = await self.repository.get_reference(
                    Category, category_id, for_update=True
                )
                if category is None:
                    raise NotFoundError()
                changes = payload.model_dump(exclude_unset=True)
                if "parent_id" in changes and changes["parent_id"] is not None:
                    parent_id = cast(UUID, changes["parent_id"])
                    chain = await self.repository.category_parent_chain(parent_id)
                    if not chain or category_id in {item.id for item in chain}:
                        raise ConflictError("CATEGORY_CYCLE", "A category cannot contain itself.")
                    if len(chain) >= 5:
                        raise ConflictError(
                            "CATEGORY_CYCLE", "Category depth cannot exceed five levels."
                        )
                for field, value in changes.items():
                    setattr(category, field, value)
                self.audit.record(
                    self.context,
                    events.CATEGORY_UPDATED,
                    "category",
                    category.id,
                    {"fields": sorted(changes)},
                )
            return category
        except IntegrityError as exc:
            raise ConflictError(
                "DUPLICATE_RESOURCE", "Category name already exists under this parent."
            ) from exc

    async def deactivate_category(self, category_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            category = await self.repository.get_reference(Category, category_id, for_update=True)
            if category is None:
                raise NotFoundError()
            if await self.repository.category_has_children_or_products(category_id):
                raise ConflictError("RESOURCE_IN_USE", "Category has children or products.")
            category.is_active = False
            self.audit.record(self.context, events.CATEGORY_DEACTIVATED, "category", category.id)

    async def create_reference(
        self, resource: str, payload: NamedCreate | UnitCreate | TaxCategoryCreate
    ) -> Any:
        model = self._reference_model(resource)
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                instance = model(
                    id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump()
                )
                self.repository.add(instance)
                self.audit.record(
                    self.context, events.REFERENCE_CREATED, model.__tablename__, instance.id
                )
            return instance
        except IntegrityError as exc:
            raise ConflictError(
                "DUPLICATE_RESOURCE", "Catalog code or name already exists."
            ) from exc

    async def update_reference(
        self,
        resource: str,
        resource_id: UUID,
        payload: NamedUpdate | UnitUpdate | TaxCategoryUpdate,
    ) -> Any:
        model = self._reference_model(resource)
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                instance = await self.repository.get_reference(model, resource_id, for_update=True)
                if instance is None:
                    raise NotFoundError()
                changes = payload.model_dump(exclude_unset=True)
                for field, value in changes.items():
                    setattr(instance, field, value)
                self.audit.record(
                    self.context,
                    events.REFERENCE_UPDATED,
                    model.__tablename__,
                    instance.id,
                    {"fields": sorted(changes)},
                )
            return instance
        except IntegrityError as exc:
            raise ConflictError(
                "DUPLICATE_RESOURCE", "Catalog code or name already exists."
            ) from exc

    async def deactivate_reference(self, resource_id: UUID, resource: str) -> None:
        model = self._reference_model(resource)
        async with service_transaction(self.session):
            await self._set_tenant()
            instance = await self.repository.get_reference(model, resource_id, for_update=True)
            if instance is None:
                raise NotFoundError()
            if await self.repository.reference_has_products(resource, resource_id):
                raise ConflictError("RESOURCE_IN_USE", "Catalog value is used by products.")
            instance.is_active = False
            self.audit.record(
                self.context, events.REFERENCE_DEACTIVATED, model.__tablename__, instance.id
            )

    async def list_products(
        self, page: int, page_size: int, **filters: Any
    ) -> tuple[list[Product], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_products(page, page_size, **filters)

    async def get_product(
        self, product_id: UUID
    ) -> tuple[Product, list[ProductVariant], list[ProductBarcode], list[dict[str, str]]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            product = await self.repository.get_product(product_id)
            if product is None:
                raise NotFoundError()
            return (
                product,
                await self.repository.variants(product_id),
                await self.repository.barcodes(product_id),
                await self.repository.balances(product_id),
            )

    async def create_product(self, payload: ProductCreate) -> Product:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                await self._validate_product_links(payload)
                product = Product(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    cost_price=0,
                    **payload.model_dump(),
                )
                self.repository.add(product)
                self.repository.add(
                    ProductVariant(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        product_id=product.id,
                        sku=product.sku,
                        name="Default",
                        attributes={},
                    )
                )
                self.audit.record(self.context, events.PRODUCT_CREATED, "product", product.id)
            return product
        except IntegrityError as exc:
            raise ConflictError("SKU_DUPLICATE", "Product or variant SKU already exists.") from exc

    async def update_product(self, product_id: UUID, payload: ProductUpdate) -> Product:
        if "cost_price" in payload.model_fields_set:
            raise ConflictError(
                "INVALID_STATE_TRANSITION",
                "Product cost is maintained only by inventory receipt logic.",
            )
        async with service_transaction(self.session):
            await self._set_tenant()
            product = await self.repository.get_product(product_id, for_update=True)
            if product is None:
                raise NotFoundError()
            await self._validate_product_links(payload)
            changes = payload.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(product, field, value)
            self.audit.record(
                self.context,
                events.PRODUCT_UPDATED,
                "product",
                product.id,
                {"fields": sorted(changes)},
            )
        return product

    async def deactivate_product(self, product_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            product = await self.repository.get_product(product_id, for_update=True)
            if product is None:
                raise NotFoundError()
            if await self.repository.product_has_movements(product_id):
                raise ConflictError(
                    "RESOURCE_IN_USE", "Products with inventory movements cannot be deleted."
                )
            product.is_active = False
            self.audit.record(self.context, events.PRODUCT_DEACTIVATED, "product", product.id)

    async def add_barcode(self, product_id: UUID, payload: BarcodeCreate) -> ProductBarcode:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                if await self.repository.get_product(product_id) is None:
                    raise NotFoundError()
                if payload.product_variant_id:
                    variant = await self.repository.variant(payload.product_variant_id)
                    if variant is None or variant.product_id != product_id:
                        raise NotFoundError()
                barcode = ProductBarcode(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    product_id=product_id,
                    **payload.model_dump(),
                )
                self.repository.add(barcode)
                self.audit.record(
                    self.context, events.PRODUCT_BARCODE_ADDED, "product_barcode", barcode.id
                )
            return barcode
        except IntegrityError as exc:
            raise ConflictError("BARCODE_DUPLICATE", "Barcode already exists.") from exc

    async def add_variant(self, product_id: UUID, payload: VariantCreate) -> ProductVariant:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                if await self.repository.get_product(product_id) is None:
                    raise NotFoundError()
                variant = ProductVariant(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    product_id=product_id,
                    **payload.model_dump(),
                )
                self.repository.add(variant)
                self.audit.record(
                    self.context, events.PRODUCT_VARIANT_ADDED, "product_variant", variant.id
                )
            return variant
        except IntegrityError as exc:
            raise ConflictError("SKU_DUPLICATE", "Variant SKU already exists.") from exc

    async def resolve_barcode(self, barcode_value: str) -> tuple[Product, ProductBarcode]:
        async with service_transaction(self.session):
            await self._set_tenant()
            barcode = await self.repository.barcode(barcode_value)
            if barcode is None:
                raise NotFoundError()
            product = await self.repository.get_product(barcode.product_id)
            if product is None:
                raise NotFoundError()
            return product, barcode

    async def _validate_product_links(self, payload: ProductCreate | ProductUpdate) -> None:
        values = payload.model_dump(exclude_unset=True)
        links: tuple[tuple[Any, str], ...] = (
            (Category, "category_id"),
            (Brand, "brand_id"),
            (UnitOfMeasure, "uom_id"),
            (TaxCategory, "tax_category_id"),
        )
        for model, field in links:
            resource_id = values.get(field)
            if (
                resource_id is not None
                and await self.repository.get_reference(model, resource_id) is None
            ):
                raise NotFoundError()
