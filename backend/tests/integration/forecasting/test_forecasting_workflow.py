"""Phase 10 forecasting (`AI.md` §4): the INSUFFICIENT_HISTORY contract for
a new product, and one full-stack proof that a real forecast comes back
correctly shaped once enough history exists.

Seeding weekly history needs data no HTTP endpoint can backdate — checkout
always sells "now" — so each week's sale is cloned from one real checkout,
backdated directly in the database, the same pattern the anomaly workflow
tests use for a voided sale.
"""

import os
import uuid

import httpx
import pytest
from sqlalchemy import text

from tests.integration.conftest import tenant_headers
from tests.integration.pos.test_pos_workflow import checkout as pos_checkout
from tests.integration.pos.test_pos_workflow import workspace as pos_workspace

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")

FORECASTING = "/api/v1/forecasting"


async def _seed_backdated_week(
    db_session, tenant_id: str, template_sale_id: str, *, weeks_ago: int, quantity: str
) -> None:
    """Clone `template_sale_id` (a real checkout) and its lines, backdated
    `weeks_ago` weeks — only `quantity` is varied; the cloned money fields
    are unused by `_weekly_demand`, which reads quantity alone.

    `db_session` is a direct connection, never routed through a service's
    own `_set_tenant()` — `sales` has row-level security, so without this
    the SELECT half of the INSERT...SELECT sees no rows at all.
    """
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id}
    )
    new_sale_id = (
        await db_session.execute(
            text("""
                INSERT INTO sales (
                    id, tenant_id, sale_number, session_id, terminal_id, branch_id,
                    warehouse_id, customer_id, cashier_membership_id, status, occurred_at,
                    net_amount, discount_amount, tax_amount, total_amount, cost_amount,
                    refunded_amount, notes, created_at, updated_at
                )
                SELECT gen_random_uuid(), tenant_id, sale_number || :week_label,
                       session_id, terminal_id, branch_id, warehouse_id, customer_id,
                       cashier_membership_id, status,
                       occurred_at - make_interval(weeks => :weeks_ago),
                       net_amount, discount_amount, tax_amount, total_amount, cost_amount,
                       refunded_amount, notes, now(), now()
                  FROM sales WHERE id = :sale_id
                RETURNING id
            """),
            # Two separate parameters, not one reused as both text and int:
            # asyncpg infers a single type per bind position, and the two
            # usages here want different ones.
            {"sale_id": template_sale_id, "weeks_ago": weeks_ago, "week_label": f"-w{weeks_ago}"},
        )
    ).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO sale_lines (
                id, tenant_id, sale_id, product_id, quantity, unit_price, discount_rate,
                tax_rate, net_amount, tax_amount, total_amount, unit_cost,
                refunded_quantity, created_at, updated_at
            )
            SELECT gen_random_uuid(), tenant_id, :new_sale_id, product_id, :quantity,
                   unit_price, discount_rate, tax_rate, net_amount, tax_amount,
                   total_amount, unit_cost, 0, now(), now()
              FROM sale_lines WHERE sale_id = :sale_id
        """),
        {"sale_id": template_sale_id, "new_sale_id": new_sale_id, "quantity": quantity},
    )
    await db_session.commit()


class TestInsufficientHistory:
    async def test_a_brand_new_product_returns_insufficient_history_not_a_crash(
        self, client: httpx.AsyncClient
    ) -> None:
        headers, ids = await pos_workspace(client)
        response = await client.get(f"{FORECASTING}/products/{ids['product_id']}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "INSUFFICIENT_HISTORY"
        assert body["periods_available"] == 0
        assert body["periods_required"] == 8

    async def test_forecasting_requires_authentication(self, client: httpx.AsyncClient) -> None:
        assert (await client.get(f"{FORECASTING}/products/{uuid.uuid4()}")).status_code == 401


class TestForecast:
    async def test_enough_history_returns_a_correctly_shaped_forecast(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        headers, ids = await pos_workspace(client, stock="200")
        tenant_id = (await client.get("/api/v1/auth/me", headers=headers)).json()[
            "active_tenant_id"
        ]
        template = (await pos_checkout(client, headers, ids, quantity="1")).json()

        # 9 more weeks behind this one, gently rising, so a naive floor is
        # clearly beatable and MASE has a real scale to divide by.
        for week in range(1, 10):
            await _seed_backdated_week(
                db_session, tenant_id, template["id"], weeks_ago=week, quantity=str(week)
            )

        response = await client.get(
            f"{FORECASTING}/products/{ids['product_id']}",
            headers=headers,
            params={"periods_ahead": 3},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "status" not in body  # not the INSUFFICIENT_HISTORY shape
        assert body["product_id"] == ids["product_id"]
        assert body["periods_ahead"] == 3
        assert len(body["point_forecast"]) == 3
        assert len(body["prediction_interval_low"]) == 3
        assert len(body["prediction_interval_high"]) == 3
        assert len(body["historical_actuals"]) == 10
        assert body["model_used"]
        assert len(body["backtest_scores"]) >= 1
        assert body["limitation_note"]
        # Money-string discipline extends to every numeric figure here too.
        assert isinstance(body["point_forecast"][0]["value"], str)

        # A prediction interval must actually contain its own point forecast.
        for low, mid, high in zip(
            body["prediction_interval_low"],
            body["point_forecast"],
            body["prediction_interval_high"],
            strict=True,
        ):
            assert float(low["value"]) <= float(mid["value"]) <= float(high["value"])

    async def test_a_short_history_note_warns_about_the_wide_interval(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        headers, ids = await pos_workspace(client, stock="200")
        tenant_id = (await client.get("/api/v1/auth/me", headers=headers)).json()[
            "active_tenant_id"
        ]
        template = (await pos_checkout(client, headers, ids, quantity="1")).json()
        for week in range(1, 8):
            await _seed_backdated_week(
                db_session, tenant_id, template["id"], weeks_ago=week, quantity="1"
            )
        response = await client.get(f"{FORECASTING}/products/{ids['product_id']}", headers=headers)
        body = response.json()
        assert "Short history" in body["limitation_note"]


class TestIsolation:
    async def test_a_products_history_is_not_visible_to_another_tenant(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        headers, ids = await pos_workspace(client, stock="200")
        tenant_id = (await client.get("/api/v1/auth/me", headers=headers)).json()[
            "active_tenant_id"
        ]
        template = (await pos_checkout(client, headers, ids, quantity="1")).json()
        for week in range(1, 10):
            await _seed_backdated_week(
                db_session, tenant_id, template["id"], weeks_ago=week, quantity=str(week)
            )

        other = await tenant_headers(client, f"forecast-other-{uuid.uuid4().hex[:10]}@example.com")
        response = await client.get(f"{FORECASTING}/products/{ids['product_id']}", headers=other)
        # There is no separate "product not found" check here — this module
        # adds no table and is purely a computation over `sale_lines`
        # (module docstring). RLS is what actually carries tenant isolation:
        # every one of the first tenant's sale_lines is invisible to the
        # second, so the same id that just forecast real history for tenant
        # A reads as no history at all for tenant B, not tenant A's answer.
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "INSUFFICIENT_HISTORY"
        assert response.json()["periods_available"] == 0
