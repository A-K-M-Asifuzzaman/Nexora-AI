"""Phase 7 — VAT rates, register and returns."""

import uuid
from decimal import Decimal

import httpx

from tests.integration.conftest import tenant_headers

VAT = "/api/v1/vat"


async def workspace(client: httpx.AsyncClient) -> dict[str, str]:
    return await tenant_headers(client, f"vat-{uuid.uuid4().hex[:10]}@example.com")


async def add_rate(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    code: str,
    rate: str,
    valid_from: str,
    valid_to: str | None = None,
) -> dict:
    body = {"code": code, "name": f"{code} rate", "rate": rate, "valid_from": valid_from}
    if valid_to:
        body["valid_to"] = valid_to
    response = await client.post(f"{VAT}/rates/", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_rate_is_resolved_by_date_not_by_latest(client: httpx.AsyncClient) -> None:
    """A rate change must never restate VAT already charged."""
    headers = await workspace(client)
    await add_rate(
        client, headers, code="STD", rate="0.150000", valid_from="2026-01-01", valid_to="2026-06-30"
    )
    await add_rate(client, headers, code="STD", rate="0.175000", valid_from="2026-07-01")

    before = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-03-15"},
    )
    after = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-09-15"},
    )
    assert before.json()["vat"] == "150.0000", before.text
    assert after.json()["vat"] == "175.0000", after.text


async def test_inclusive_and_exclusive_pricing(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(client, headers, code="STD", rate="0.150000", valid_from="2026-01-01")

    excl = (
        await client.post(
            f"{VAT}/price",
            headers=headers,
            json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-08-15"},
        )
    ).json()
    assert (excl["net"], excl["vat"], excl["gross"]) == ("1000.0000", "150.0000", "1150.0000")

    incl = (
        await client.post(
            f"{VAT}/price",
            headers=headers,
            json={
                "amount": "1150.0000",
                "rate_code": "STD",
                "on_date": "2026-08-15",
                "inclusive": True,
            },
        )
    ).json()
    assert (incl["net"], incl["vat"], incl["gross"]) == ("1000.0000", "150.0000", "1150.0000")
    # Money crosses as strings (ADR-0015).
    assert all(isinstance(incl[k], str) for k in ("net", "vat", "gross"))


async def test_unknown_rate_code_is_not_found(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "100.0000", "rate_code": "NOPE", "on_date": "2026-08-15"},
    )
    assert response.status_code == 404


async def test_rate_outside_its_validity_window_is_not_found(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(
        client, headers, code="OLD", rate="0.100000", valid_from="2020-01-01", valid_to="2020-12-31"
    )
    response = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "100.0000", "rate_code": "OLD", "on_date": "2026-08-15"},
    )
    assert response.status_code == 404


async def test_return_totals_and_filing_claims_the_period(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    prepared = await client.post(
        f"{VAT}/returns/",
        headers=headers,
        json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
    )
    assert prepared.status_code == 201, prepared.text
    body = prepared.json()
    assert body["status"] == "DRAFT"
    # An empty period is zeroes, not nulls.
    assert Decimal(body["net_vat"]) == Decimal("0")

    filed = await client.post(f"{VAT}/returns/{body['id']}/file", headers=headers)
    assert filed.status_code == 200, filed.text
    assert filed.json()["status"] == "FILED"
    assert filed.json()["filed_at"] is not None

    # Filing twice would restate a statement already made to an authority.
    again = await client.post(f"{VAT}/returns/{body['id']}/file", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "RETURN_ALREADY_FILED"


async def test_a_period_cannot_be_returned_twice(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    period = {"period_start": "2026-08-01", "period_end": "2026-08-31"}
    assert (await client.post(f"{VAT}/returns/", headers=headers, json=period)).status_code == 201
    duplicate = await client.post(f"{VAT}/returns/", headers=headers, json=period)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RETURN_EXISTS"


async def test_return_period_must_be_ordered(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.post(
        f"{VAT}/returns/",
        headers=headers,
        json={"period_start": "2026-08-31", "period_end": "2026-08-01"},
    )
    assert response.status_code == 422


async def test_reporting_ranges_are_bounded(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.get(
        f"{VAT}/summary?from_date=2020-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


async def test_summary_and_transactions_are_empty_for_a_new_tenant(
    client: httpx.AsyncClient,
) -> None:
    headers = await workspace(client)
    summary = (
        await client.get(f"{VAT}/summary?from_date=2026-08-01&to_date=2026-08-31", headers=headers)
    ).json()
    assert summary["items"] == []
    rows = (
        await client.get(
            f"{VAT}/transactions/?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    assert rows == []


async def test_vat_is_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(client, headers, code="STD", rate="0.150000", valid_from="2026-01-01")
    other = await workspace(client)
    assert (await client.get(f"{VAT}/rates/", headers=other)).json() == []
    # Tenant B cannot price against tenant A's rate code either.
    priced = await client.post(
        f"{VAT}/price",
        headers=other,
        json={"amount": "100.0000", "rate_code": "STD", "on_date": "2026-08-15"},
    )
    assert priced.status_code == 404


async def test_vat_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{VAT}/rates/")).status_code == 401
    assert (await client.get(f"{VAT}/returns/")).status_code == 401
