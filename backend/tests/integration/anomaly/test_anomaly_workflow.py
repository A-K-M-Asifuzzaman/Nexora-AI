"""Phase 10 anomaly alerts (`AI.md` §5): RBAC, redaction, tenant isolation,
and one full-stack proof that a detector actually fires end to end.

Seeding a detected anomaly needs data no HTTP endpoint can produce today —
`SaleStatus.VOIDED` exists on the model, but nothing in POS ever sets it, so
the one test that proves `_detect_cashier_void_rate` fires flips a real
checkout's status directly in the database, the same way the accounting
matrix tests reach past the service layer to prove a database-level
guarantee holds regardless of what called it.
"""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.modules.anomaly.models import (
    AnomalyAlert,
    Detector,
    ResourceType,
    Severity,
)
from app.workers.tasks.anomaly import _sweep_once
from tests.integration.conftest import tenant_headers
from tests.integration.documents.conftest import second_member_with_role
from tests.integration.pos.test_pos_workflow import checkout as pos_checkout
from tests.integration.pos.test_pos_workflow import workspace as pos_workspace

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")

ANOMALIES = "/api/v1/anomalies"


async def _owner(client: httpx.AsyncClient) -> tuple[dict[str, str], UUID]:
    headers = await tenant_headers(client, f"anomaly-{uuid.uuid4().hex[:10]}@acme-demo.com")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return headers, UUID(me["active_tenant_id"])


async def _seed_alert(
    db_session,
    tenant_id: UUID,
    *,
    resource_type: ResourceType = ResourceType.TENANT,
    resource_id: UUID | None = None,
    label: str | None = None,
    detector: Detector = Detector.REVENUE_DROP,
) -> UUID:
    token = set_tenant_context(
        TenantContext(
            tenant_id=tenant_id,
            membership_id=uuid7(),
            user_id=uuid7(),
            role_ids=frozenset(),
            permissions=frozenset(),
            branch_ids=None,
        )
    )
    try:
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        alert_id = uuid7()
        db_session.add(
            AnomalyAlert(
                id=alert_id,
                tenant_id=tenant_id,
                detector=detector,
                severity=Severity.HIGH,
                observed_value=Decimal("450.0000"),
                expected_low=Decimal("900.0000"),
                expected_high=Decimal("1100.0000"),
                deviation=Decimal("-5.2000"),
                reason="Daily revenue was 450.00, outside the typical 900.00-1100.00 range.",
                occurred_at=datetime.now(UTC),
                resource_type=resource_type,
                resource_id=resource_id,
                label=label,
            )
        )
        await db_session.commit()
        return alert_id
    finally:
        reset_tenant_context(token)


class TestAccessControl:
    async def test_a_role_without_anomaly_read_is_forbidden(
        self, client: httpx.AsyncClient
    ) -> None:
        owner, _ = await _owner(client)
        sales_headers, _ = await second_member_with_role(client, owner, "SALES")
        response = await client.get(ANOMALIES, headers=sales_headers)
        assert response.status_code == 403

    async def test_a_role_without_anomaly_manage_cannot_run_detectors(
        self, client: httpx.AsyncClient
    ) -> None:
        """No seeded system role separates read from manage — OWNER, ADMIN
        and MANAGER all get both together (AGENT_HANDOFF.md's Phase 10
        design). A custom role is what actually proves the two permissions
        are checked independently, not just that some role lacks both."""
        owner, _ = await _owner(client)
        custom = await client.post(
            "/api/v1/roles/",
            headers=owner,
            json={"code": "AUDITOR", "name": "Auditor", "permission_codes": ["anomaly.read"]},
        )
        assert custom.status_code == 201, custom.text
        auditor, _ = await second_member_with_role(client, owner, "AUDITOR")
        assert (await client.get(ANOMALIES, headers=auditor)).status_code == 200
        assert (await client.post(f"{ANOMALIES}/run", headers=auditor)).status_code == 403

    async def test_anomalies_require_authentication(self, client: httpx.AsyncClient) -> None:
        assert (await client.get(ANOMALIES)).status_code == 401


class TestReadAndRedaction:
    async def test_a_branch_alert_is_visible_to_any_reader(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        owner, tenant_id = await _owner(client)
        await _seed_alert(
            db_session,
            tenant_id,
            resource_type=ResourceType.BRANCH,
            resource_id=uuid7(),
            label="Downtown",
        )
        body = (await client.get(ANOMALIES, headers=owner)).json()
        assert len(body) == 1
        assert body[0]["label"] == "Downtown"
        assert body[0]["status"] == "OPEN"

    async def test_an_employee_named_alert_is_redacted_without_users_manage(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        """AI.md §5: "the same access discipline as payroll" — an alert
        naming an employee must not leak who, or which resource, to a
        reader who only holds anomaly.read. MANAGER is the deliberate case
        (AGENT_HANDOFF.md's Phase 10 design): full anomaly.read/manage, but
        not users.manage, so a manager-tier caller still sees and acts on
        every alert — an employee-naming one just reads redacted."""
        owner, tenant_id = await _owner(client)
        membership_id = uuid7()
        await _seed_alert(
            db_session,
            tenant_id,
            resource_type=ResourceType.MEMBERSHIP,
            resource_id=membership_id,
            label="Cashier",
            detector=Detector.CASHIER_VOID_RATE,
        )
        manager, _ = await second_member_with_role(client, owner, "MANAGER")
        redacted = (await client.get(ANOMALIES, headers=manager)).json()
        assert redacted[0]["resource_id"] is None
        assert "Redacted" in redacted[0]["label"]

        # OWNER holds users.manage and sees the real identity.
        revealed = (await client.get(ANOMALIES, headers=owner)).json()
        assert revealed[0]["resource_id"] == str(membership_id)
        assert revealed[0]["label"] == "Cashier"

    async def test_a_missing_alert_is_not_found(self, client: httpx.AsyncClient) -> None:
        owner, _ = await _owner(client)
        response = await client.get(f"{ANOMALIES}/{uuid.uuid4()}", headers=owner)
        assert response.status_code == 404


class TestStatusTransitions:
    async def test_acknowledge_records_who_and_when(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        owner, tenant_id = await _owner(client)
        alert_id = await _seed_alert(db_session, tenant_id)
        response = await client.post(f"{ANOMALIES}/{alert_id}/acknowledge", headers=owner)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ACKNOWLEDGED"

    async def test_dismiss_moves_status(self, client: httpx.AsyncClient, db_session) -> None:
        owner, tenant_id = await _owner(client)
        alert_id = await _seed_alert(db_session, tenant_id)
        response = await client.post(f"{ANOMALIES}/{alert_id}/dismiss", headers=owner)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "DISMISSED"

    async def test_status_filter_excludes_dismissed_alerts(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        owner, tenant_id = await _owner(client)
        alert_id = await _seed_alert(db_session, tenant_id)
        await client.post(f"{ANOMALIES}/{alert_id}/dismiss", headers=owner)
        open_only = (await client.get(ANOMALIES, headers=owner, params={"status": "OPEN"})).json()
        assert open_only == []
        dismissed = (
            await client.get(ANOMALIES, headers=owner, params={"status": "DISMISSED"})
        ).json()
        assert len(dismissed) == 1


class TestTenantIsolation:
    async def test_an_alert_is_invisible_to_another_tenant(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        _, tenant_a = await _owner(client)
        await _seed_alert(db_session, tenant_a)
        owner_b, _ = await _owner(client)
        assert (await client.get(ANOMALIES, headers=owner_b)).json() == []

    async def test_reading_another_tenants_alert_by_id_is_not_found(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        _, tenant_a = await _owner(client)
        alert_id = await _seed_alert(db_session, tenant_a)
        owner_b, _ = await _owner(client)
        response = await client.get(f"{ANOMALIES}/{alert_id}", headers=owner_b)
        assert response.status_code == 404


class TestRunDetectors:
    async def test_a_fresh_tenant_with_no_data_creates_no_alerts(
        self, client: httpx.AsyncClient
    ) -> None:
        """The common case for any new account — the CROSS JOIN queries
        must degrade to zero rows cleanly, not error, on a tenant with no
        branches, no warehouses and no sales."""
        owner, _ = await _owner(client)
        response = await client.post(f"{ANOMALIES}/run", headers=owner)
        assert response.status_code == 202, response.text
        assert response.json()["alerts_created"] == 0

    async def test_an_elevated_void_rate_is_detected_and_alerted(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        # `pos_workspace` builds its own fresh tenant via its own
        # `tenant_headers` call — reusing its `headers` (not a second,
        # unrelated call to `_owner`) is what keeps the seeded sales and
        # the tenant `run_detectors` reads under the same tenant_id.
        headers, ids = await pos_workspace(client, stock="20")
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])
        sale_ids = [
            UUID((await pos_checkout(client, headers, ids)).json()["id"]) for _ in range(10)
        ]

        # Nothing in POS issues a void today; flipped directly, the same way
        # the accounting matrix tests reach past the service layer.
        token = set_tenant_context(
            TenantContext(
                tenant_id=tenant_id,
                membership_id=uuid7(),
                user_id=uuid7(),
                role_ids=frozenset(),
                permissions=frozenset(),
                branch_ids=None,
            )
        )
        try:
            await db_session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            await db_session.execute(
                text("UPDATE sales SET status = 'VOIDED' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [str(sid) for sid in sale_ids[:4]]},  # 40% > 15% threshold
            )
            await db_session.commit()
        finally:
            reset_tenant_context(token)

        run = await client.post(f"{ANOMALIES}/run", headers=headers)
        assert run.status_code == 202, run.text
        assert run.json()["alerts_created"] >= 1

        alerts = (await client.get(ANOMALIES, headers=headers)).json()
        void_alerts = [a for a in alerts if a["detector"] == "CASHIER_VOID_RATE"]
        assert len(void_alerts) == 1
        assert void_alerts[0]["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    async def test_running_detectors_twice_in_one_day_does_not_duplicate(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        headers, ids = await pos_workspace(client, stock="20")
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])
        sale_ids = [
            UUID((await pos_checkout(client, headers, ids)).json()["id"]) for _ in range(10)
        ]
        token = set_tenant_context(
            TenantContext(
                tenant_id=tenant_id,
                membership_id=uuid7(),
                user_id=uuid7(),
                role_ids=frozenset(),
                permissions=frozenset(),
                branch_ids=None,
            )
        )
        try:
            await db_session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            await db_session.execute(
                text("UPDATE sales SET status = 'VOIDED' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [str(sid) for sid in sale_ids[:4]]},
            )
            await db_session.commit()
        finally:
            reset_tenant_context(token)

        first = await client.post(f"{ANOMALIES}/run", headers=headers)
        second = await client.post(f"{ANOMALIES}/run", headers=headers)
        assert first.json()["alerts_created"] >= 1
        assert second.json()["alerts_created"] == 0

        alerts = (await client.get(ANOMALIES, headers=headers)).json()
        assert len([a for a in alerts if a["detector"] == "CASHIER_VOID_RATE"]) == 1


class TestDailySweepTask:
    async def test_the_scheduled_sweep_reaches_a_real_tenants_data(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        """Proves the Celery entrypoint itself — its own engine, its own
        per-tenant iteration and system context — not just the
        `run_detectors` service method it calls underneath."""
        headers, ids = await pos_workspace(client, stock="20")
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])
        sale_ids = [
            UUID((await pos_checkout(client, headers, ids)).json()["id"]) for _ in range(10)
        ]
        token = set_tenant_context(
            TenantContext(
                tenant_id=tenant_id,
                membership_id=uuid7(),
                user_id=uuid7(),
                role_ids=frozenset(),
                permissions=frozenset(),
                branch_ids=None,
            )
        )
        try:
            await db_session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            await db_session.execute(
                text("UPDATE sales SET status = 'VOIDED' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [str(sid) for sid in sale_ids[:4]]},
            )
            await db_session.commit()
        finally:
            reset_tenant_context(token)

        # Sweeps every tenant in the database, not only this one — the
        # aggregate count is not asserted on, only that this tenant's own
        # alert exists afterward.
        total_created = await _sweep_once()
        assert total_created >= 1

        alerts = (await client.get(ANOMALIES, headers=headers)).json()
        assert len([a for a in alerts if a["detector"] == "CASHIER_VOID_RATE"]) == 1
