"""Demand forecasting (`AI.md` §4).

Historical demand is computed from the same tables `reporting.sales_trend`
already aggregates — no new tables, matching Phase 6's "reporting adds no
tables" precedent, since a forecast is a computation over existing sales
history, not a stored fact.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.modules.forecasting import backtest
from app.modules.forecasting.algorithms import (
    CalendarRegression,
    ExponentialSmoothing,
    Holt,
    HoltWinters,
    Model,
    MovingAverage,
    Naive,
)

MIN_PERIODS = 8
DEFAULT_PERIODS_AHEAD = 4
Z_95 = 1.96


class InsufficientHistoryError(Exception):
    def __init__(self, periods_available: int) -> None:
        self.periods_available = periods_available


class ForecastingService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def _weekly_demand(self, product_id: str) -> tuple[list[date], list[float]]:
        """Net quantity sold (gross minus refunded) per ISO week, going back
        two years, gap-filled to zero the same way `sales_trend` fills days —
        a week with no sales is a real zero, not a missing point."""
        await self._set_tenant()
        rows = (
            await self.session.execute(
                text("""
                SELECT week::date AS week_start,
                       COALESCE(SUM(sl.quantity - sl.refunded_quantity), 0) AS net_quantity
                  FROM generate_series(
                         date_trunc('week', now() - interval '104 weeks')::date,
                         date_trunc('week', now())::date,
                         interval '1 week'
                       ) week
                  LEFT JOIN sales s
                    ON date_trunc('week', s.occurred_at) = week
                   AND s.status = 'COMPLETED'
                  LEFT JOIN sale_lines sl
                    ON sl.sale_id = s.id AND sl.product_id = :product_id
                 GROUP BY week
                 ORDER BY week
            """),
                {"product_id": product_id},
            )
        ).all()
        dates = [r[0] for r in rows]
        values = [float(r[1]) for r in rows]
        return dates, values

    def _candidates(self, periods: int) -> list[Model]:
        candidates: list[Model] = [Naive(), MovingAverage(4), ExponentialSmoothing(), Holt()]
        if periods >= 16:
            candidates.append(HoltWinters(season_length=4))
        candidates.append(CalendarRegression())
        return candidates

    async def forecast(
        self, product_id: str, periods_ahead: int = DEFAULT_PERIODS_AHEAD
    ) -> dict[str, Any]:
        dates, values = await self._weekly_demand(product_id)
        # Trailing zero-weeks before the product's first ever sale are not
        # "history" — trim them so a brand-new product with 3 real weeks of
        # data is correctly INSUFFICIENT_HISTORY rather than diluted by 101
        # weeks of zeros that predate it existing.
        first_nonzero = next((i for i, v in enumerate(values) if v > 0), None)
        if first_nonzero is not None:
            dates, values = dates[first_nonzero:], values[first_nonzero:]
        else:
            dates, values = [], []

        if len(values) < MIN_PERIODS:
            raise InsufficientHistoryError(len(values))

        candidates = self._candidates(len(values))
        selection = backtest.select_best(candidates, values, dates)
        winning_model = next(m for m in candidates if m.name == selection.winner)

        errors = backtest.walk_forward_errors(winning_model, values, dates)
        residual_std = statistics.pstdev(errors) if len(errors) > 1 else 0.0

        future_dates = [dates[-1] + timedelta(weeks=i + 1) for i in range(periods_ahead)]
        fitted = winning_model.fit(values, dates)
        point_forecast = fitted.predict(future_dates)

        note = f"Based on {len(values)} weeks of history."
        if len(values) < 12:
            note += (
                " Short history — interval is wide and the model choice may change as "
                "more data arrives."
            )

        return {
            "product_id": product_id,
            "periods_ahead": periods_ahead,
            "historical_actuals": list(zip(dates, values, strict=True)),
            "point_forecast": list(zip(future_dates, point_forecast, strict=True)),
            "prediction_interval_low": list(
                zip(future_dates, [v - Z_95 * residual_std for v in point_forecast], strict=True)
            ),
            "prediction_interval_high": list(
                zip(future_dates, [v + Z_95 * residual_std for v in point_forecast], strict=True)
            ),
            "model_used": selection.winner,
            "backtest_scores": selection.scores,
            "limitation_note": note,
        }
