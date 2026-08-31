"""Dashboard and analytics reporting.

Three rules from the architecture govern everything here:

* **All aggregation happens in the database** (`ACCOUNTING.md` §8). No report
  loads raw rows into Python to sum them — "that is both slow and, on a large
  tenant, a memory incident."
* **Every range is bounded** to 366 days (`API.md` §7). An unbounded range on a
  large tenant is a denial of service you inflict on yourself.
* **Cache keys are tenant-prefixed** (`ARCHITECTURE.md` §16). A key that omits
  the tenant is a cross-tenant leak with a TTL on it, and no test reading
  through a single tenant would ever catch it.
"""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.core.redis import RedisClient
from app.db.session import service_transaction

MAX_RANGE = timedelta(days=366)
# Time-based expiry, not write-triggered invalidation: a new sale can take up
# to this long to show up in a cached dashboard. Actively invalidating on
# every write would mean touching every mutating endpoint across sales, POS,
# purchasing, and inventory, each one a place to silently miss — for a
# dashboard read (not a balance a checkout depends on), 120s of staleness is
# the cheaper and more reliable trade.
CACHE_TTL_SECONDS = 120


class ReportingService:
    def __init__(
        self, session: AsyncSession, context: TenantContext, redis: RedisClient | None = None
    ) -> None:
        self.session = session
        self.context = context
        self.redis = redis

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    @staticmethod
    def _validate_range(start: date, end: date) -> None:
        if end < start:
            raise DomainValidationError("INVALID_DATE_RANGE", "Report end must not precede start.")
        if end - start > MAX_RANGE:
            raise DomainValidationError(
                "INVALID_DATE_RANGE", "Report range must not exceed 366 days."
            )

    def _cache_key(self, report: str, **params: object) -> str:
        """`t:{tenant_id}:report:{hash}` — the tenant is *in the key*, not merely
        in the query that filled it."""
        digest = hashlib.sha256(
            json.dumps({"report": report, **params}, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
        return f"t:{self.context.tenant_id}:report:{digest}"

    async def _cached(self, key: str) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(key)
        return json.loads(raw) if raw else None

    async def _store(self, key: str, value: dict[str, Any]) -> None:
        if self.redis is None:
            return
        await self.redis.set(key, json.dumps(value, default=str), ex=CACHE_TTL_SECONDS)

    async def dashboard(self, start: date, end: date) -> dict[str, Any]:
        self._validate_range(start, end)
        key = self._cache_key("dashboard", start=start, end=end)
        if (hit := await self._cached(key)) is not None:
            return hit

        async with service_transaction(self.session):
            await self._set_tenant()
            # One round trip, every figure aggregated by PostgreSQL. Gross profit
            # uses sale_lines.unit_cost — the cost snapshotted at the moment of
            # sale (ADR-0018). A live cost lookup would silently restate the
            # margin of every historical sale whenever a price changed.
            row = (
                await self.session.execute(
                    text("""
                    WITH pos AS (
                        SELECT COALESCE(SUM(s.total_amount), 0) AS revenue,
                               COALESCE(SUM(s.refunded_amount), 0) AS refunds,
                               COUNT(*) AS transactions
                          FROM sales s
                         WHERE s.status = 'COMPLETED'
                           AND s.occurred_at::date BETWEEN :start AND :end
                    ),
                    cogs AS (
                        SELECT COALESCE(SUM(l.quantity * l.unit_cost), 0) AS cost
                          FROM sale_lines l
                          JOIN sales s ON s.id = l.sale_id
                         WHERE s.status = 'COMPLETED'
                           AND s.occurred_at::date BETWEEN :start AND :end
                    ),
                    invoiced AS (
                        SELECT COALESCE(SUM(i.total_amount), 0) AS invoiced,
                               COALESCE(SUM(i.total_amount - i.paid_amount), 0) AS receivable
                          FROM invoices i
                         WHERE i.status IN ('ISSUED','PARTIALLY_PAID','PAID')
                           AND i.issue_date BETWEEN :start AND :end
                    ),
                    billed AS (
                        SELECT COALESCE(SUM(b.total_amount - b.paid_amount), 0) AS payable
                          FROM supplier_bills b
                         WHERE b.status IN ('ISSUED','PARTIALLY_PAID','PAID')
                    ),
                    stock AS (
                        SELECT COALESCE(SUM(bal.quantity_on_hand * p.cost_price), 0) AS value
                          FROM inventory_balances bal
                          JOIN products p ON p.id = bal.product_id
                    )
                    SELECT pos.revenue, pos.refunds, pos.transactions, cogs.cost,
                           invoiced.invoiced, invoiced.receivable, billed.payable, stock.value
                      FROM pos, cogs, invoiced, billed, stock
                """),
                    {"start": start, "end": end},
                )
            ).one()

        revenue, refunds, transactions, cost, invoiced, receivable, payable, stock_value = row
        result = {
            "from_date": str(start),
            "to_date": str(end),
            "pos_revenue": str(revenue),
            "refunds": str(refunds),
            "transactions": int(transactions),
            "cost_of_goods_sold": str(cost),
            "gross_profit": str(Decimal(revenue) - Decimal(cost)),
            "invoiced": str(invoiced),
            "accounts_receivable": str(receivable),
            "accounts_payable": str(payable),
            "inventory_value": str(stock_value),
        }
        await self._store(key, result)
        return result

    async def top_products(self, start: date, end: date, limit: int = 10) -> dict[str, Any]:
        self._validate_range(start, end)
        key = self._cache_key("top_products", start=start, end=end, limit=limit)
        if (hit := await self._cached(key)) is not None:
            return hit

        async with service_transaction(self.session):
            await self._set_tenant()
            rows = (
                await self.session.execute(
                    text("""
                    SELECT p.id, p.sku, p.name,
                           SUM(l.quantity) AS quantity,
                           SUM(l.total_amount) AS revenue,
                           SUM(l.total_amount) - SUM(l.quantity * l.unit_cost) AS margin
                      FROM sale_lines l
                      JOIN sales s ON s.id = l.sale_id
                      JOIN products p ON p.id = l.product_id
                     WHERE s.status = 'COMPLETED'
                       AND s.occurred_at::date BETWEEN :start AND :end
                     GROUP BY p.id, p.sku, p.name
                     ORDER BY revenue DESC
                     LIMIT :limit
                """),
                    {"start": start, "end": end, "limit": limit},
                )
            ).all()

        result = {
            "items": [
                {
                    "product_id": str(r[0]),
                    "sku": r[1],
                    "name": r[2],
                    "quantity": str(r[3]),
                    "revenue": str(r[4]),
                    "margin": str(r[5]),
                }
                for r in rows
            ]
        }
        await self._store(key, result)
        return result

    async def sales_trend(self, start: date, end: date) -> dict[str, Any]:
        self._validate_range(start, end)
        key = self._cache_key("sales_trend", start=start, end=end)
        if (hit := await self._cached(key)) is not None:
            return hit

        async with service_transaction(self.session):
            await self._set_tenant()
            rows = (
                await self.session.execute(
                    text("""
                    SELECT d::date AS day,
                           COALESCE(SUM(s.total_amount), 0) AS revenue,
                           COUNT(s.id) AS transactions
                      FROM generate_series(:start::date, :end::date, interval '1 day') d
                      LEFT JOIN sales s
                        ON s.occurred_at::date = d::date AND s.status = 'COMPLETED'
                     GROUP BY d
                     ORDER BY d
                """),
                    {"start": start, "end": end},
                )
            ).all()

        # generate_series gives a row for every day, so a gap reads as zero
        # rather than vanishing from the chart.
        result = {
            "items": [
                {"date": str(r[0]), "revenue": str(r[1]), "transactions": int(r[2])} for r in rows
            ]
        }
        await self._store(key, result)
        return result

    async def low_stock(self) -> dict[str, Any]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = (
                await self.session.execute(
                    text("""
                    SELECT p.id, p.sku, p.name, w.code,
                           bal.quantity_on_hand, bal.reserved_quantity, p.reorder_point
                      FROM inventory_balances bal
                      JOIN products p ON p.id = bal.product_id
                      JOIN warehouses w ON w.id = bal.warehouse_id
                     WHERE p.reorder_point IS NOT NULL
                       AND bal.quantity_on_hand - bal.reserved_quantity <= p.reorder_point
                     ORDER BY bal.quantity_on_hand - bal.reserved_quantity
                     LIMIT 200
                """)
                )
            ).all()

        return {
            "items": [
                {
                    "product_id": str(r[0]),
                    "sku": r[1],
                    "name": r[2],
                    "warehouse": r[3],
                    "on_hand": str(r[4]),
                    "reserved": str(r[5]),
                    "reorder_point": str(r[6]),
                }
                for r in rows
            ]
        }

    async def pipeline(self) -> dict[str, Any]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = (
                await self.session.execute(
                    text("""
                    SELECT stage, COUNT(*), COALESCE(SUM(amount), 0),
                           COALESCE(SUM(amount * probability), 0)
                      FROM opportunities
                     GROUP BY stage
                     ORDER BY stage
                """)
                )
            ).all()

        return {
            "items": [
                {
                    "stage": r[0],
                    "count": int(r[1]),
                    "amount": str(r[2]),
                    "weighted_amount": str(r[3]),
                }
                for r in rows
            ]
        }
