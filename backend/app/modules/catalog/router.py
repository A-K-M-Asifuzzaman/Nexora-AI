from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import Page
from app.modules.catalog.schemas import (
    BarcodeCreate,
    BarcodeResponse,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    NamedCreate,
    NamedResponse,
    NamedUpdate,
    ProductCreate,
    ProductDetail,
    ProductResponse,
    ProductUpdate,
    TaxCategoryCreate,
    TaxCategoryResponse,
    TaxCategoryUpdate,
    UnitCreate,
    UnitResponse,
    UnitUpdate,
    VariantCreate,
    VariantResponse,
)
from app.modules.catalog.service import CatalogService
from app.modules.rbac.permissions import Perm

router = APIRouter(tags=["catalog"])
ReadContext = Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_READ))]
ManageContext = Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_MANAGE))]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _page(items: list[Any], total: int, page: int, page_size: int, schema: type[Any]) -> Page[Any]:
    return Page(
        items=[schema.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/categories/", response_model=Page[CategoryResponse])
async def list_categories(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[CategoryResponse]:
    items, total = await CatalogService(session, context).list_categories(page, page_size)
    return _page(items, total, page, page_size, CategoryResponse)


@router.post("/categories/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate, context: ManageContext, session: DbSession
) -> CategoryResponse:
    return CategoryResponse.model_validate(
        await CatalogService(session, context).create_category(payload)
    )


@router.patch("/categories/{resource_id}", response_model=CategoryResponse)
async def update_category(
    resource_id: UUID, payload: CategoryUpdate, context: ManageContext, session: DbSession
) -> CategoryResponse:
    return CategoryResponse.model_validate(
        await CatalogService(session, context).update_category(resource_id, payload)
    )


@router.delete("/categories/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> Response:
    await CatalogService(session, context).deactivate_category(resource_id)
    return Response(status_code=204)


@router.get("/brands/", response_model=Page[NamedResponse])
async def list_brands(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[NamedResponse]:
    items, total = await CatalogService(session, context).list_reference("brand", page, page_size)
    return _page(items, total, page, page_size, NamedResponse)


@router.post("/brands/", response_model=NamedResponse, status_code=201)
async def create_brand(
    payload: NamedCreate, context: ManageContext, session: DbSession
) -> NamedResponse:
    return NamedResponse.model_validate(
        await CatalogService(session, context).create_reference("brand", payload)
    )


@router.patch("/brands/{resource_id}", response_model=NamedResponse)
async def update_brand(
    resource_id: UUID, payload: NamedUpdate, context: ManageContext, session: DbSession
) -> NamedResponse:
    return NamedResponse.model_validate(
        await CatalogService(session, context).update_reference("brand", resource_id, payload)
    )


@router.delete("/brands/{resource_id}", status_code=204)
async def delete_brand(resource_id: UUID, context: ManageContext, session: DbSession) -> Response:
    await CatalogService(session, context).deactivate_reference(resource_id, "brand")
    return Response(status_code=204)


@router.get("/units/", response_model=Page[UnitResponse])
async def list_units(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[UnitResponse]:
    items, total = await CatalogService(session, context).list_reference("unit", page, page_size)
    return _page(items, total, page, page_size, UnitResponse)


@router.post("/units/", response_model=UnitResponse, status_code=201)
async def create_unit(
    payload: UnitCreate, context: ManageContext, session: DbSession
) -> UnitResponse:
    return UnitResponse.model_validate(
        await CatalogService(session, context).create_reference("unit", payload)
    )


@router.patch("/units/{resource_id}", response_model=UnitResponse)
async def update_unit(
    resource_id: UUID, payload: UnitUpdate, context: ManageContext, session: DbSession
) -> UnitResponse:
    return UnitResponse.model_validate(
        await CatalogService(session, context).update_reference("unit", resource_id, payload)
    )


@router.delete("/units/{resource_id}", status_code=204)
async def delete_unit(resource_id: UUID, context: ManageContext, session: DbSession) -> Response:
    await CatalogService(session, context).deactivate_reference(resource_id, "unit")
    return Response(status_code=204)


@router.get("/tax-categories/", response_model=Page[TaxCategoryResponse])
async def list_tax_categories(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[TaxCategoryResponse]:
    items, total = await CatalogService(session, context).list_reference(
        "tax_category", page, page_size
    )
    return _page(items, total, page, page_size, TaxCategoryResponse)


@router.post("/tax-categories/", response_model=TaxCategoryResponse, status_code=201)
async def create_tax_category(
    payload: TaxCategoryCreate, context: ManageContext, session: DbSession
) -> TaxCategoryResponse:
    return TaxCategoryResponse.model_validate(
        await CatalogService(session, context).create_reference("tax_category", payload)
    )


@router.patch("/tax-categories/{resource_id}", response_model=TaxCategoryResponse)
async def update_tax_category(
    resource_id: UUID, payload: TaxCategoryUpdate, context: ManageContext, session: DbSession
) -> TaxCategoryResponse:
    return TaxCategoryResponse.model_validate(
        await CatalogService(session, context).update_reference(
            "tax_category", resource_id, payload
        )
    )


@router.delete("/tax-categories/{resource_id}", status_code=204)
async def delete_tax_category(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> Response:
    await CatalogService(session, context).deactivate_reference(resource_id, "tax_category")
    return Response(status_code=204)


@router.get("/products/", response_model=Page[ProductResponse])
async def list_products(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    is_active: bool | None = None,
) -> Page[ProductResponse]:
    items, total = await CatalogService(session, context).list_products(
        page, page_size, q=q, category_id=category_id, brand_id=brand_id, is_active=is_active
    )
    return _page(items, total, page, page_size, ProductResponse)


@router.post("/products/", response_model=ProductResponse, status_code=201)
async def create_product(
    payload: ProductCreate, context: ManageContext, session: DbSession
) -> ProductResponse:
    return ProductResponse.model_validate(
        await CatalogService(session, context).create_product(payload)
    )


@router.get(
    "/products/barcode/{barcode}", response_model=dict[str, ProductResponse | BarcodeResponse]
)
async def resolve_barcode(
    barcode: str, context: ReadContext, session: DbSession
) -> dict[str, ProductResponse | BarcodeResponse]:
    product, record = await CatalogService(session, context).resolve_barcode(barcode)
    return {
        "product": ProductResponse.model_validate(product),
        "barcode": BarcodeResponse.model_validate(record),
    }


@router.get("/products/{product_id}", response_model=ProductDetail)
async def get_product(product_id: UUID, context: ReadContext, session: DbSession) -> ProductDetail:
    product, variants, barcodes, balances = await CatalogService(session, context).get_product(
        product_id
    )
    return ProductDetail(
        **ProductResponse.model_validate(product).model_dump(),
        variants=[VariantResponse.model_validate(item) for item in variants],
        barcodes=[BarcodeResponse.model_validate(item) for item in barcodes],
        balances=balances,
    )


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID, payload: ProductUpdate, context: ManageContext, session: DbSession
) -> ProductResponse:
    return ProductResponse.model_validate(
        await CatalogService(session, context).update_product(product_id, payload)
    )


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: UUID, context: ManageContext, session: DbSession) -> Response:
    await CatalogService(session, context).deactivate_product(product_id)
    return Response(status_code=204)


@router.post("/products/{product_id}/barcodes", response_model=BarcodeResponse, status_code=201)
async def add_barcode(
    product_id: UUID, payload: BarcodeCreate, context: ManageContext, session: DbSession
) -> BarcodeResponse:
    return BarcodeResponse.model_validate(
        await CatalogService(session, context).add_barcode(product_id, payload)
    )


@router.post("/products/{product_id}/variants", response_model=VariantResponse, status_code=201)
async def add_variant(
    product_id: UUID, payload: VariantCreate, context: ManageContext, session: DbSession
) -> VariantResponse:
    return VariantResponse.model_validate(
        await CatalogService(session, context).add_variant(product_id, payload)
    )
