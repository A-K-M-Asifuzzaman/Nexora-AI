from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import Page
from app.modules.branches.schemas import BranchCreate, BranchResponse, BranchUpdate
from app.modules.branches.service import BranchService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/branches", tags=["branches"])


@router.get("/", response_model=Page[BranchResponse])
async def list_branches(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.BRANCHES_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[BranchResponse]:
    items, total = await BranchService(session, context).list(page, page_size)
    return Page(
        items=[BranchResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.BRANCHES_CREATE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BranchResponse:
    return BranchResponse.model_validate(await BranchService(session, context).create(payload))


@router.get("/{branch_id}", response_model=BranchResponse)
async def get_branch(
    branch_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.BRANCHES_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BranchResponse:
    return BranchResponse.model_validate(await BranchService(session, context).get(branch_id))


@router.patch("/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: UUID,
    payload: BranchUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.BRANCHES_UPDATE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BranchResponse:
    branch = await BranchService(session, context).update(branch_id, payload)
    return BranchResponse.model_validate(branch)


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_branch(
    branch_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.BRANCHES_DELETE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await BranchService(session, context).deactivate(branch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
