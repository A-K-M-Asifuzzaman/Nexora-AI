"""Anomaly detection and alert access (`AI.md` §5).

`run_detectors()` is the batch side — called by the scheduled task, one pass
per tenant per day, writing `AnomalyAlert` rows. `list_alerts()`/`get_alert()`
are the read side, and are where the sensitivity rule actually lives: an
alert naming an employee is redacted unless the caller holds `users.manage`,
and reading the unredacted form is itself audited (`AI.md` §5 — "an anomaly
system is also a surveillance system").
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import AppError
from app.db.session import service_transaction
from app.modules.anomaly import detectors
from app.modules.anomaly.models import AlertStatus, AnomalyAlert, Detector, ResourceType, Severity
from app.modules.audit.service import AuditService
from app.modules.rbac.permissions import Perm

_NOT_FOUND = ("ANOMALY_ALERT_NOT_FOUND", "Alert not found.", 404)

# Fixed-threshold ratio rule for cashier voids (AI.md §5's shape for
# refunds/discounts, applied here since a single cashier's daily count is
# usually too small for MAD to be meaningful) and the MAD sensitivity used
# for refund rate specifically (branch-level daily refund rate is noisier
# than the other MAD-based series, so it gets a wider k).
_VOID_RATE_THRESHOLD = 0.15
_REFUND_RATE_MAD_K = 3.5

_TREND_WINDOW_DAYS = 30
_MIN_NONZERO_HISTORY = 5
_CENTS = Decimal("0.0001")


def _has_signal(history: list[float]) -> bool:
    """A history that is mostly zero-filled gaps is not a baseline — it is
    the absence of one. Without this, a tenant's first real day of activity
    reads as an anomaly against 29 empty days it gap-fills to, which is not
    a rare edge case: every tenant's first detector run looks exactly like
    this, and would otherwise flood a brand-new account with false
    CRITICAL alerts on day one."""
    return sum(1 for v in history if v != 0) >= _MIN_NONZERO_HISTORY


def _decimal(value: float) -> Decimal:
    """Detector output is `float` throughout — `statistics` and plain
    division need it, and it never enters an accounting transaction. The
    alert row itself is `NUMERIC(18,4)`, so the value is fixed at this one
    boundary: through `str()`, not a direct `Decimal(float)`, or the binary
    floating-point artifact (0.1 + 0.2 == 0.30000000000000004) becomes the
    number stored and later shown to a user, rather than one rounded away.
    """
    return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _severity_for(deviation: float) -> Severity:
    magnitude = abs(deviation)
    if magnitude >= 6:
        return Severity.CRITICAL
    if magnitude >= 4.5:
        return Severity.HIGH
    if magnitude >= 3.5:
        return Severity.MEDIUM
    return Severity.LOW


class AnomalyService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    # ---------------------------------------------------------------- reads

    async def list_alerts(
        self, status_filter: AlertStatus | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        can_see_identity = Perm.USERS_MANAGE in self.context.permissions
        async with service_transaction(self.session):
            await self._set_tenant()
            query = select(AnomalyAlert).order_by(AnomalyAlert.occurred_at.desc()).limit(limit)
            if status_filter is not None:
                query = query.where(AnomalyAlert.status == status_filter)
            alerts = (await self.session.execute(query)).scalars().all()

            named_employee = any(
                a.resource_type == ResourceType.MEMBERSHIP and not can_see_identity for a in alerts
            )
            if named_employee and not can_see_identity:
                AuditService(self.session).record(
                    self.context, "anomaly.list_redacted", "anomaly_alert", None
                )
        return [self._serialize(a, can_see_identity) for a in alerts]

    async def get_alert(self, alert_id: UUID) -> dict[str, Any]:
        can_see_identity = Perm.USERS_MANAGE in self.context.permissions
        async with service_transaction(self.session):
            await self._set_tenant()
            alert = (
                await self.session.execute(select(AnomalyAlert).where(AnomalyAlert.id == alert_id))
            ).scalar_one_or_none()
            if alert is None:
                raise AppError(*_NOT_FOUND)
            if alert.resource_type == ResourceType.MEMBERSHIP and can_see_identity:
                # Reading an alert that names an employee, in the form that
                # actually names them, is itself an audited action —
                # payroll-grade access discipline, per AI.md §5.
                AuditService(self.session).record(
                    self.context, "anomaly.identity_viewed", "anomaly_alert", alert.id
                )
        return self._serialize(alert, can_see_identity)

    def _serialize(self, alert: AnomalyAlert, reveal_identity: bool) -> dict[str, Any]:
        redact = alert.resource_type == ResourceType.MEMBERSHIP and not reveal_identity
        return {
            "id": alert.id,
            "detector": alert.detector,
            "severity": alert.severity,
            "observed_value": alert.observed_value,
            "expected_low": alert.expected_low,
            "expected_high": alert.expected_high,
            "deviation": alert.deviation,
            "reason": alert.reason,
            "occurred_at": alert.occurred_at,
            "resource_type": alert.resource_type,
            "resource_id": None if redact else alert.resource_id,
            "label": "Redacted (requires user management access)" if redact else alert.label,
            "status": alert.status,
        }

    # ------------------------------------------------------------- actions

    async def set_status(self, alert_id: UUID, new_status: AlertStatus) -> dict[str, Any]:
        async with service_transaction(self.session):
            await self._set_tenant()
            alert = (
                await self.session.execute(select(AnomalyAlert).where(AnomalyAlert.id == alert_id))
            ).scalar_one_or_none()
            if alert is None:
                raise AppError(*_NOT_FOUND)
            alert.status = new_status
            alert.acknowledged_by_membership_id = self.context.membership_id
            alert.acknowledged_at = datetime.now(UTC)
            AuditService(self.session).record(
                self.context,
                f"anomaly.{new_status.value.lower()}",
                "anomaly_alert",
                alert.id,
            )
        return self._serialize(alert, Perm.USERS_MANAGE in self.context.permissions)

    # -------------------------------------------------------------- writes

    async def _create_alert(
        self,
        detector: Detector,
        verdict: detectors.Verdict,
        occurred_at: datetime,
        resource_type: ResourceType,
        resource_id: UUID | None,
        label: str | None,
        reason: str,
    ) -> None:
        self.session.add(
            AnomalyAlert(
                tenant_id=self.context.tenant_id,
                detector=detector,
                severity=_severity_for(verdict.deviation),
                observed_value=_decimal(verdict.observed),
                expected_low=_decimal(verdict.expected_low),
                expected_high=_decimal(verdict.expected_high),
                deviation=_decimal(verdict.deviation),
                reason=reason,
                occurred_at=occurred_at,
                resource_type=resource_type,
                resource_id=resource_id,
                label=label,
            )
        )

    async def run_detectors(self) -> int:
        """One pass over every detector for this tenant. Returns the number
        of alerts created. Idempotent per calendar day: skips a detector for
        a resource that already has an OPEN alert for the same day, so a
        retried or re-triggered run does not duplicate."""
        async with service_transaction(self.session):
            await self._set_tenant()
            created = 0
            created += await self._detect_refund_rate()
            created += await self._detect_discount_depth()
            created += await self._detect_expense_spike()
            created += await self._detect_revenue_drop()
            created += await self._detect_stock_adjustment_volume()
            created += await self._detect_cashier_void_rate()
        return created

    async def _already_alerted_today(self, detector: Detector, resource_id: UUID | None) -> bool:
        resource_clause = (
            AnomalyAlert.resource_id.is_(None)
            if resource_id is None
            else AnomalyAlert.resource_id == resource_id
        )
        row = (
            await self.session.execute(
                select(AnomalyAlert.id).where(
                    AnomalyAlert.detector == detector,
                    resource_clause,
                    AnomalyAlert.occurred_at >= func.date_trunc("day", func.now()),
                )
            )
        ).first()
        return row is not None

    async def _detect_refund_rate(self) -> int:
        # CROSS JOIN branches x days: a plain LEFT JOIN keyed off `sales`
        # alone drops any branch/day with zero sales instead of contributing
        # a real zero, which both breaks gap-filling and, worse, silently
        # shrinks a quiet branch's history below the 5-point minimum below.
        rows = (
            await self.session.execute(
                text("""
                SELECT b.id AS branch_id, day::date,
                       COALESCE(SUM(s.refunded_amount), 0) AS refunded,
                       COALESCE(SUM(s.total_amount), 0) AS total
                  FROM branches b
                  CROSS JOIN generate_series(
                         now() - make_interval(days => :window_days), now(), interval '1 day'
                       ) day
                  LEFT JOIN sales s
                    ON s.branch_id = b.id AND s.occurred_at::date = day::date
                       AND s.status = 'COMPLETED'
                 GROUP BY b.id, day
                 ORDER BY b.id, day
            """),
                {"window_days": _TREND_WINDOW_DAYS},
            )
        ).all()
        return await self._evaluate_ratio_series(
            rows, Detector.REFUND_RATE, resource_type=ResourceType.BRANCH, use_mad=True
        )

    async def _detect_discount_depth(self) -> int:
        rows = (
            await self.session.execute(
                text("""
                SELECT b.id AS branch_id, day::date,
                       COALESCE(SUM(sl.discount_rate * sl.total_amount), 0) AS weighted,
                       COALESCE(SUM(sl.total_amount), 0) AS total
                  FROM branches b
                  CROSS JOIN generate_series(
                         now() - make_interval(days => :window_days), now(), interval '1 day'
                       ) day
                  LEFT JOIN sales s
                    ON s.branch_id = b.id AND s.occurred_at::date = day::date
                       AND s.status = 'COMPLETED'
                  LEFT JOIN sale_lines sl ON sl.sale_id = s.id
                 GROUP BY b.id, day
                 ORDER BY b.id, day
            """),
                {"window_days": _TREND_WINDOW_DAYS},
            )
        ).all()
        return await self._evaluate_ratio_series(
            rows, Detector.DISCOUNT_DEPTH, resource_type=ResourceType.BRANCH, use_mad=True
        )

    async def _evaluate_ratio_series(
        self, rows: Any, detector: Detector, resource_type: ResourceType, use_mad: bool
    ) -> int:

        by_resource: dict[UUID | None, list[float]] = defaultdict(list)
        for resource_id, _day, numerator, denominator in rows:
            ratio = float(numerator) / float(denominator) if denominator else 0.0
            by_resource[resource_id].append(ratio)

        created = 0
        for resource_id, series in by_resource.items():
            if resource_id is None or len(series) < 5:
                continue
            history, observed = series[:-1], series[-1]
            if not _has_signal(history):
                continue
            verdict = (
                detectors.mad_threshold(history, observed, k=_REFUND_RATE_MAD_K)
                if use_mad
                else detectors.z_score(history, observed)
            )
            if not verdict.is_anomaly:
                continue
            if await self._already_alerted_today(detector, resource_id):
                continue
            await self._create_alert(
                detector,
                verdict,
                datetime.now(UTC),
                resource_type,
                resource_id,
                label=None,
                reason=(
                    f"{detector.value.replace('_', ' ').title()} was {observed:.1%}, outside the "
                    f"typical range of {verdict.expected_low:.1%}-{verdict.expected_high:.1%} for "
                    "this branch over the last 30 days."
                ),
            )
            created += 1
        return created

    async def _detect_expense_spike(self) -> int:
        # The expense-only filter has to happen inside the subquery, before
        # the LEFT JOIN: an `a.account_type = 'EXPENSE'` condition attached
        # to the join itself would still pass through every other account
        # type's debit lines unfiltered (a LEFT JOIN keeps the left row when
        # the ON condition fails, it just nulls the right side) — this would
        # have summed the whole ledger's debits, not only expense postings.
        rows = (
            await self.session.execute(
                text("""
                SELECT day::date, COALESCE(SUM(exp.debit), 0) AS expense
                  FROM generate_series(
                         now() - make_interval(days => :window_days), now(), interval '1 day'
                       ) day
                  LEFT JOIN (
                         SELECT je.entry_date, jel.debit
                           FROM journal_entry_lines jel
                           JOIN journal_entries je ON je.id = jel.journal_entry_id
                           JOIN accounts a ON a.id = jel.account_id AND a.account_type = 'EXPENSE'
                       ) exp ON exp.entry_date = day::date
                 GROUP BY day
                 ORDER BY day
            """),
                {"window_days": _TREND_WINDOW_DAYS},
            )
        ).all()
        series = [float(r[1]) for r in rows]
        return await self._evaluate_tenant_series(
            series, Detector.EXPENSE_SPIKE, use_mad=True, label="Daily expense postings"
        )

    async def _detect_revenue_drop(self) -> int:
        rows = (
            await self.session.execute(
                text("""
                SELECT day::date, COALESCE(SUM(s.total_amount), 0) AS revenue
                  FROM generate_series(
                         now() - make_interval(days => :window_days), now(), interval '1 day'
                       ) day
                  LEFT JOIN sales s ON s.occurred_at::date = day::date AND s.status = 'COMPLETED'
                 GROUP BY day
                 ORDER BY day
            """),
                {"window_days": _TREND_WINDOW_DAYS},
            )
        ).all()
        series = [float(r[1]) for r in rows]
        return await self._evaluate_tenant_series(
            series,
            Detector.REVENUE_DROP,
            use_mad=False,
            label="Daily revenue",
            only_drops=True,
        )

    async def _evaluate_tenant_series(
        self,
        series: list[float],
        detector: Detector,
        use_mad: bool,
        label: str,
        only_drops: bool = False,
    ) -> int:
        if len(series) < 5:
            return 0
        history, observed = series[:-1], series[-1]
        if not _has_signal(history):
            return 0
        verdict = (
            detectors.mad_threshold(history, observed)
            if use_mad
            else detectors.z_score(history, observed)
        )
        if only_drops and observed >= verdict.expected_low:
            return 0
        if not verdict.is_anomaly:
            return 0
        if await self._already_alerted_today(detector, None):
            return 0
        await self._create_alert(
            detector,
            verdict,
            datetime.now(UTC),
            ResourceType.TENANT,
            None,
            label=label,
            reason=(
                f"{label} was {observed:.2f}, outside the typical range of "
                f"{verdict.expected_low:.2f}-{verdict.expected_high:.2f} for the last 30 days."
            ),
        )
        return 1

    async def _detect_stock_adjustment_volume(self) -> int:
        # CROSS JOIN warehouses × days so every warehouse gets a zero-filled
        # row for a quiet day, the same gap-filling `sales_trend` relies on —
        # a plain LEFT JOIN with no warehouses table would silently miss any
        # warehouse that happened to have zero adjustments on the most
        # recent day, which is exactly the "quiet day" a spike is judged
        # against.
        rows = (
            await self.session.execute(
                text("""
                SELECT w.id AS warehouse_id, day::date, COUNT(sa.id) AS adjustments
                  FROM warehouses w
                  CROSS JOIN generate_series(
                         now() - make_interval(days => :window_days), now(), interval '1 day'
                       ) day
                  LEFT JOIN stock_adjustments sa
                    ON sa.warehouse_id = w.id AND sa.created_at::date = day::date
                 GROUP BY w.id, day
                 ORDER BY w.id, day
            """),
                {"window_days": _TREND_WINDOW_DAYS},
            )
        ).all()

        by_warehouse: dict[UUID, list[float]] = defaultdict(list)
        for warehouse_id, _day, count in rows:
            by_warehouse[warehouse_id].append(float(count))

        created = 0
        for warehouse_id, series in by_warehouse.items():
            if len(series) < 5:
                continue
            history, observed = series[:-1], series[-1]
            if not _has_signal(history):
                continue
            verdict = detectors.mad_threshold(history, observed)
            # Only a spike is interesting here — fewer adjustments than usual
            # is not a risk signal worth an alert.
            if not verdict.is_anomaly or observed <= verdict.expected_high:
                continue
            if await self._already_alerted_today(Detector.STOCK_ADJUSTMENT_VOLUME, warehouse_id):
                continue
            await self._create_alert(
                Detector.STOCK_ADJUSTMENT_VOLUME,
                verdict,
                datetime.now(UTC),
                ResourceType.BRANCH,
                warehouse_id,
                label=None,
                reason=(
                    f"{int(observed)} stock adjustments today for this warehouse, outside the "
                    f"typical range of {verdict.expected_low:.1f}-{verdict.expected_high:.1f}."
                ),
            )
            created += 1
        return created

    async def _detect_cashier_void_rate(self) -> int:
        rows = (
            await self.session.execute(
                text("""
                SELECT cashier_membership_id,
                       COUNT(*) FILTER (WHERE status = 'VOIDED') AS voided,
                       COUNT(*) AS total
                  FROM sales
                 WHERE occurred_at >= now() - interval '1 day'
                 GROUP BY cashier_membership_id
            """)
            )
        ).all()
        created = 0
        for membership_id, voided, total in rows:
            verdict = detectors.ratio_rule(float(voided), float(total), _VOID_RATE_THRESHOLD)
            if not verdict.is_anomaly:
                continue
            if await self._already_alerted_today(Detector.CASHIER_VOID_RATE, membership_id):
                continue
            await self._create_alert(
                Detector.CASHIER_VOID_RATE,
                verdict,
                datetime.now(UTC),
                ResourceType.MEMBERSHIP,
                membership_id,
                label="Cashier",
                reason=(
                    f"{int(voided)} of {int(total)} sales voided today "
                    f"({verdict.observed:.1%}), above the {_VOID_RATE_THRESHOLD:.0%} threshold."
                ),
            )
            created += 1
        return created
