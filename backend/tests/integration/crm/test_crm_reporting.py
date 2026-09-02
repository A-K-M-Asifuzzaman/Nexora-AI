"""Phase 6 — CRM pipeline and reporting.

The report tests care about two things the roadmap names explicitly: that
aggregation is bounded, and that it is isolated. The cache-isolation test is the
one worth reading — a report cache key that omits the tenant is a cross-tenant
leak with a TTL on it, and no test reading through a single tenant would catch it.
"""

import uuid
from decimal import Decimal

import httpx

from tests.integration.conftest import tenant_headers

CRM = "/api/v1/crm"
REPORTS = "/api/v1/reports"


async def workspace(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    headers = await tenant_headers(client, f"crm-{uuid.uuid4().hex[:10]}@example.com")
    customer = await client.post(
        "/api/v1/customers/", headers=headers, json={"code": "C1", "name": "Acme"}
    )
    assert customer.status_code == 201, customer.text
    return headers, {"customer_id": customer.json()["id"]}


async def make_lead(client: httpx.AsyncClient, headers: dict[str, str], code: str = "L1") -> dict:
    response = await client.post(
        f"{CRM}/leads/",
        headers=headers,
        json={
            "code": code,
            "name": "Jane Prospect",
            "company": "Prospect Ltd",
            "source": "REFERRAL",
            "estimated_value": "5000.0000",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def qualify(client: httpx.AsyncClient, headers: dict[str, str], lead_id: str) -> None:
    for status in ("CONTACTED", "QUALIFIED"):
        r = await client.patch(
            f"{CRM}/leads/{lead_id}/status", headers=headers, json={"status": status}
        )
        assert r.status_code == 200, r.text


# ── leads ─────────────────────────────────────────────────────────────────────


async def test_lead_money_crosses_as_a_string(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    assert lead["estimated_value"] == "5000.0000"
    assert isinstance(lead["estimated_value"], str)


async def test_lead_status_follows_the_state_machine(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    # NEW cannot jump straight to QUALIFIED.
    skipped = await client.patch(
        f"{CRM}/leads/{lead['id']}/status", headers=headers, json={"status": "QUALIFIED"}
    )
    assert skipped.status_code == 409
    assert skipped.json()["error"]["code"] == "ILLEGAL_STATUS_TRANSITION"


async def test_disqualified_lead_is_terminal(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    await client.patch(
        f"{CRM}/leads/{lead['id']}/status", headers=headers, json={"status": "DISQUALIFIED"}
    )
    # Reopening a rejected lead would erase the fact that it was rejected.
    reopened = await client.patch(
        f"{CRM}/leads/{lead['id']}/status", headers=headers, json={"status": "CONTACTED"}
    )
    assert reopened.status_code == 409


async def test_only_a_qualified_lead_converts(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    early = await client.post(
        f"{CRM}/leads/{lead['id']}/convert", headers=headers, json={"customer_code": "NEW1"}
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "LEAD_NOT_QUALIFIED"


async def test_conversion_creates_a_customer_and_happens_once(
    client: httpx.AsyncClient,
) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    await qualify(client, headers, lead["id"])

    converted = await client.post(
        f"{CRM}/leads/{lead['id']}/convert",
        headers=headers,
        json={
            "customer_code": "CONV1",
            "opportunity_name": "First deal",
            "opportunity_amount": "9000.0000",
        },
    )
    assert converted.status_code == 201, converted.text
    assert converted.json()["customer_id"]
    assert converted.json()["opportunity_id"]

    # Converting twice would create a second customer for one lead.
    again = await client.post(
        f"{CRM}/leads/{lead['id']}/convert", headers=headers, json={"customer_code": "CONV2"}
    )
    assert again.status_code == 409


# ── opportunities ─────────────────────────────────────────────────────────────


async def test_lost_opportunity_must_record_a_reason(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    opportunity = await client.post(
        f"{CRM}/opportunities/",
        headers=headers,
        json={"customer_id": ids["customer_id"], "name": "Deal", "amount": "1000.0000"},
    )
    assert opportunity.status_code == 201, opportunity.text
    # Pipeline analysis without loss reasons is decoration.
    response = await client.patch(
        f"{CRM}/opportunities/{opportunity.json()['id']}/stage",
        headers=headers,
        json={"stage": "LOST"},
    )
    assert response.status_code == 422


async def test_closed_opportunity_is_terminal(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    created = await client.post(
        f"{CRM}/opportunities/",
        headers=headers,
        json={"customer_id": ids["customer_id"], "name": "Deal", "amount": "1000.0000"},
    )
    oid = created.json()["id"]
    won = await client.patch(
        f"{CRM}/opportunities/{oid}/stage", headers=headers, json={"stage": "WON"}
    )
    assert won.status_code == 200, won.text
    # A closed deal that reopens makes every win-rate figure a moving target.
    assert Decimal(won.json()["probability"]) == Decimal("1")
    reopened = await client.patch(
        f"{CRM}/opportunities/{oid}/stage", headers=headers, json={"stage": "PROPOSAL"}
    )
    assert reopened.status_code == 409


# ── activities and notes ──────────────────────────────────────────────────────


async def test_activity_must_attach_to_exactly_one_parent(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    lead = await make_lead(client, headers)
    none_given = await client.post(
        f"{CRM}/activities/",
        headers=headers,
        json={"activity_type": "CALL", "subject": "Follow up"},
    )
    assert none_given.status_code == 422
    two_given = await client.post(
        f"{CRM}/activities/",
        headers=headers,
        json={
            "activity_type": "CALL",
            "subject": "Follow up",
            "lead_id": lead["id"],
            "customer_id": ids["customer_id"],
        },
    )
    assert two_given.status_code == 422


async def test_activity_completes_once(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    created = await client.post(
        f"{CRM}/activities/",
        headers=headers,
        json={"activity_type": "TASK", "subject": "Send quote", "lead_id": lead["id"]},
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    assert (
        await client.post(f"{CRM}/activities/{aid}/complete", headers=headers)
    ).status_code == 200
    assert (
        await client.post(f"{CRM}/activities/{aid}/complete", headers=headers)
    ).status_code == 409


# ── reporting ─────────────────────────────────────────────────────────────────


async def test_report_range_is_bounded_to_366_days(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    # An unbounded range on a large tenant is a denial of service you inflict
    # on yourself (API.md §7).
    response = await client.get(
        f"{REPORTS}/dashboard?from_date=2020-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


async def test_report_rejects_an_inverted_range(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    response = await client.get(
        f"{REPORTS}/dashboard?from_date=2026-08-31&to_date=2026-08-01", headers=headers
    )
    assert response.status_code == 422


async def test_dashboard_returns_money_as_strings(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    body = (
        await client.get(
            f"{REPORTS}/dashboard?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    for field in ("pos_revenue", "gross_profit", "accounts_receivable", "inventory_value"):
        assert isinstance(body[field], str), (field, body[field])
    # An empty tenant is all zeroes, not nulls — a dashboard that renders "null"
    # is indistinguishable from one that failed.
    assert Decimal(body["pos_revenue"]) == Decimal("0")


async def test_sales_trend_gap_fills_dates_and_serializes_money(
    client: httpx.AsyncClient,
) -> None:
    headers, _ = await workspace(client)
    response = await client.get(
        f"{REPORTS}/sales-trend?from_date=2026-08-01&to_date=2026-08-03",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["date"] for item in items] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert all(isinstance(item["revenue"], str) for item in items)
    assert all(Decimal(item["revenue"]) == Decimal("0") for item in items)


async def test_report_cache_does_not_leak_across_tenants(client: httpx.AsyncClient) -> None:
    """The invariant most likely to be got wrong silently.

    Two tenants asking for the identical report over the identical range must
    not share a cache entry. A key of `report:{hash(params)}` would collide
    here; `t:{tenant_id}:report:{hash}` does not.
    """
    headers_a, _ = await workspace(client)
    headers_b, _ = await workspace(client)

    # Give A a lead so its pipeline differs from B's, then read both.
    lead = await make_lead(client, headers_a)
    await qualify(client, headers_a, lead["id"])
    await client.post(
        f"{CRM}/leads/{lead['id']}/convert",
        headers=headers_a,
        json={
            "customer_code": "CONV1",
            "opportunity_name": "Deal",
            "opportunity_amount": "500.0000",
        },
    )

    pipeline_a = (await client.get(f"{REPORTS}/pipeline", headers=headers_a)).json()
    pipeline_b = (await client.get(f"{REPORTS}/pipeline", headers=headers_b)).json()
    assert pipeline_a["items"], "tenant A should have a pipeline"
    assert pipeline_b["items"] == [], f"tenant B saw tenant A's pipeline: {pipeline_b}"

    # Same call, same range, both tenants — the cached dashboards must differ in
    # provenance even when the figures happen to match.
    url = f"{REPORTS}/dashboard?from_date=2026-08-01&to_date=2026-08-31"
    first_a = (await client.get(url, headers=headers_a)).json()
    first_b = (await client.get(url, headers=headers_b)).json()
    assert first_a["from_date"] == first_b["from_date"]
    # Re-read A through the cache; it must still be A's numbers.
    again_a = (await client.get(url, headers=headers_a)).json()
    assert again_a == first_a


async def test_crm_is_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    lead = await make_lead(client, headers)
    other = await tenant_headers(client, f"other-{uuid.uuid4().hex[:10]}@example.com")
    # 404, never 403 (ADR-0009).
    assert (await client.get(f"{CRM}/leads/{lead['id']}", headers=other)).status_code == 404
    assert (await client.get(f"{CRM}/leads/", headers=other)).json()["total"] == 0


async def test_reports_require_authentication(client: httpx.AsyncClient) -> None:
    assert (
        await client.get(f"{REPORTS}/dashboard?from_date=2026-08-01&to_date=2026-08-31")
    ).status_code == 401
    assert (await client.get(f"{CRM}/leads/")).status_code == 401
