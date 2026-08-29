"""The eight whitelisted analytics tools (`AI.md` §2.3).

Every tool here obeys the same three rules:

* **No SQL surface.** No tool accepts a query, a table, a column or an
  expression. The model chooses *which question*, never *how it is asked*
  (ADR-0017).
* **Bounded.** Date spans cap at 366 days and result rows at a documented
  limit, so "summarise everything since inception" is not available as an
  exfiltration primitive (§2.2.3).
* **Tenant re-derived.** Every query runs through the service layer under the
  authenticated tenant context; nothing the model says selects a tenant.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.modules.ai.registry import registry
from app.modules.rbac.permissions import Perm
from app.modules.reporting.service import ReportingService
from app.modules.vat.service import VatService

MAX_SPAN = timedelta(days=366)


def _range(args: dict[str, Any]) -> tuple[date, date]:
    """Parse and bound a date range. Rejects rather than silently clamping —
    a truncated answer that looks complete is worse than an error."""
    try:
        start = date.fromisoformat(str(args["from_date"]))
        end = date.fromisoformat(str(args["to_date"]))
    except (KeyError, ValueError) as exc:
        raise DomainValidationError(
            "INVALID_DATE_RANGE", "from_date and to_date must be ISO dates."
        ) from exc
    if end < start:
        raise DomainValidationError("INVALID_DATE_RANGE", "to_date must not precede from_date.")
    if end - start > MAX_SPAN:
        raise DomainValidationError("INVALID_DATE_RANGE", "Range must not exceed 366 days.")
    return start, end


def _limit(args: dict[str, Any], ceiling: int, default: int) -> int:
    value = int(args.get("limit", default))
    if value < 1:
        raise DomainValidationError("INVALID_LIMIT", "limit must be at least 1.")
    return min(value, ceiling)


_RANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "from_date": {"type": "string", "description": "ISO start date, inclusive."},
        "to_date": {"type": "string", "description": "ISO end date, inclusive."},
    },
    "required": ["from_date", "to_date"],
    "additionalProperties": False,
}


_RANGE_PROPERTIES: dict[str, Any] = {
    "from_date": {"type": "string", "description": "ISO start date, inclusive."},
    "to_date": {"type": "string", "description": "ISO end date, inclusive."},
}


def _with(extra: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {**_RANGE_PROPERTIES, **extra},
        "required": required or ["from_date", "to_date"],
        "additionalProperties": False,
    }
    return schema


@registry.tool(
    name="get_sales_summary",
    description="Total sales, transaction count and average order value for a period.",
    permissions=(Perm.REPORTS_READ,),
    schema=_RANGE_SCHEMA,
)
async def get_sales_summary(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    start, end = _range(args)
    data = await ReportingService(session, context).dashboard(start, end)
    return {
        "from_date": data["from_date"],
        "to_date": data["to_date"],
        "revenue": data["pos_revenue"],
        "refunds": data["refunds"],
        "transactions": data["transactions"],
        "invoiced": data["invoiced"],
    }


@registry.tool(
    name="get_profit_summary",
    description="Revenue, cost of goods sold and gross profit for a period.",
    # Both permissions, per §2.3: a SALES role may see revenue but not margin.
    permissions=(Perm.REPORTS_READ, Perm.ACCOUNTING_READ),
    schema=_RANGE_SCHEMA,
)
async def get_profit_summary(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    start, end = _range(args)
    data = await ReportingService(session, context).dashboard(start, end)
    return {
        "from_date": data["from_date"],
        "to_date": data["to_date"],
        "revenue": data["pos_revenue"],
        "cost_of_goods_sold": data["cost_of_goods_sold"],
        "gross_profit": data["gross_profit"],
    }


@registry.tool(
    name="get_inventory_status",
    description="Stock on hand and value, optionally only items at or below reorder point.",
    permissions=(Perm.INVENTORY_READ,),
    schema={
        "type": "object",
        "properties": {
            "low_stock_only": {"type": "boolean", "description": "Only items needing reorder."}
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def get_inventory_status(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    service = ReportingService(session, context)
    if args.get("low_stock_only"):
        return await service.low_stock()
    today = date.today()
    data = await service.dashboard(today - timedelta(days=1), today)
    return {"inventory_value": data["inventory_value"]}


@registry.tool(
    name="get_customer_receivables",
    description="Outstanding customer balances, largest first.",
    permissions=(Perm.REPORTS_READ,),
    schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Rows to return, max 100."}},
        "required": [],
        "additionalProperties": False,
    },
)
async def get_customer_receivables(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    from app.modules.sales.service import SalesService

    limit = _limit(args, ceiling=100, default=20)
    rows, outstanding = await SalesService(session, context).receivables()
    return {
        "total_outstanding": str(outstanding),
        "customers": [
            {
                "name": r[1],
                "invoiced": str(r[2]),
                "paid": str(r[3]),
                "outstanding": str(r[2] - r[3]),
            }
            for r in rows[:limit]
        ],
    }


@registry.tool(
    name="get_supplier_payables",
    description="Outstanding supplier balances, largest first.",
    permissions=(Perm.REPORTS_READ,),
    schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Rows to return, max 100."}},
        "required": [],
        "additionalProperties": False,
    },
)
async def get_supplier_payables(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    from app.modules.purchasing.service import PurchasingService

    limit = _limit(args, ceiling=100, default=20)
    rows, outstanding = await PurchasingService(session, context).payables()
    return {
        "total_outstanding": str(outstanding),
        "suppliers": [
            {"name": r[1], "billed": str(r[2]), "paid": str(r[3]), "outstanding": str(r[2] - r[3])}
            for r in rows[:limit]
        ],
    }


@registry.tool(
    name="compare_branches",
    description="Sales revenue by day across a period, for trend comparison.",
    permissions=(Perm.REPORTS_READ,),
    schema=_RANGE_SCHEMA,
)
async def compare_branches(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    start, end = _range(args)
    return await ReportingService(session, context).sales_trend(start, end)


@registry.tool(
    name="get_top_products",
    description="Best-selling products by revenue for a period, with margin.",
    permissions=(Perm.REPORTS_READ,),
    schema=_with({"limit": {"type": "integer", "description": "Rows to return, max 50."}}),
)
async def get_top_products(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    start, end = _range(args)
    limit = _limit(args, ceiling=50, default=10)
    return await ReportingService(session, context).top_products(start, end, limit)


@registry.tool(
    name="get_expense_summary",
    description="VAT position for a period: output VAT charged and input VAT reclaimable.",
    permissions=(Perm.ACCOUNTING_READ,),
    schema=_RANGE_SCHEMA,
)
async def get_expense_summary(
    session: AsyncSession, context: TenantContext, args: dict[str, Any]
) -> dict[str, Any]:
    start, end = _range(args)
    return await VatService(session, context).summary(start, end)
