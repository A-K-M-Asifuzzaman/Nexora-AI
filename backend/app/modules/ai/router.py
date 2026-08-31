from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.api.ratelimit import AI_ASK_PER_MEMBERSHIP, RequireRateLimit
from app.core.config import Settings, get_settings
from app.core.context import TenantContext
from app.core.errors import AppError
from app.modules.ai.providers_impl import build_provider
from app.modules.ai.schemas import AskRequest, AskResponse, ToolDescription
from app.modules.ai.service import CopilotService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/ai", tags=["ai"])

Use = Annotated[TenantContext, Depends(RequirePermission(Perm.AI_USE))]
Db = Annotated[AsyncSession, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/tools", response_model=list[ToolDescription])
async def tools(context: Use) -> list[ToolDescription]:
    """The whitelist, and what each tool requires.

    Exposed deliberately: a copilot whose capabilities are inspectable is one a
    user can reason about, and the list is not a secret — the permissions are
    enforced regardless of who reads them.
    """
    return [ToolDescription(**t) for t in CopilotService.tool_catalogue()]


@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(RequireRateLimit(AI_ASK_PER_MEMBERSHIP))],
)
async def ask(payload: AskRequest, context: Use, session: Db, settings: Config) -> AskResponse:
    if not settings.ai_enabled:
        raise AppError("AI_DISABLED", "The AI copilot is disabled for this deployment.", 503)
    provider = build_provider(settings)
    result = await CopilotService(session, context, provider, settings).ask(payload.question)
    return AskResponse(**result)
