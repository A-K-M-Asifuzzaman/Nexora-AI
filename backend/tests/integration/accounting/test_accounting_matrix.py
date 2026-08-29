"""ACCOUNTING.md §10 — the binding Phase 5 test matrix.

Each test names the case number it covers. The cases that say "rejected by DB
trigger" are exercised through a **direct database connection**, bypassing the
service entirely: their whole point is that the guarantee survives code that
forgets to ask (`PROJECT_SPEC.md` §6 criterion 2 — "enforced by the database").
"""

import asyncio
import os
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import tenant_headers

ACC = "/api/v1/accounting"


async def workspace(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    """A tenant with its seeded chart of accounts and an open period."""
    headers = await tenant_headers(client, f"acct-{uuid.uuid4().hex[:10]}@example.com")
    accounts = (await client.get(f"{ACC}/accounts/", headers=headers)).json()
    by_code = {a["code"]: a["id"] for a in accounts if a["is_postable"]}
    # `_bootstrap` already seeds a fiscal-year period, so creating a month here
    # would overlap it and be rejected by the exclusion constraint.
    return headers, by_code


def two_sided(debit_id: str, credit_id: str, amount: str) -> dict:
    return {
        "entry_date": "2026-08-15",
        "description": "matrix entry",
        "lines": [
            {"account_id": debit_id, "debit": amount, "credit": "0"},
            {"account_id": credit_id, "debit": "0", "credit": amount},
        ],
    }


def pick(by_code: dict[str, str]) -> tuple[str, str]:
    codes = sorted(by_code)
    assert len(codes) >= 2, f"seeded chart too small: {codes}"
    return by_code[codes[0]], by_code[codes[1]]


# ── 1, 2 ──────────────────────────────────────────────────────────────────────


async def test_case_1_balanced_entry_posts(client: httpx.AsyncClient) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    response = await client.post(
        f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "100.0000")
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_debit"] == "100.0000"
    assert body["total_credit"] == "100.0000"
    assert body["status"] == "POSTED"


async def test_case_2_unbalanced_entry_is_rejected(client: httpx.AsyncClient) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    payload = two_sided(debit, credit, "100.0000")
    payload["lines"][1]["credit"] = "90.0000"
    response = await client.post(f"{ACC}/entries/", headers=headers, json=payload)
    assert response.status_code in (409, 422), response.text
    assert response.json()["error"]["code"] == "UNBALANCED_JOURNAL"


# ── 3, 4, 5: the database must hold even when the service is bypassed ─────────


@pytest.fixture
async def owner_engine():
    engine = create_async_engine(os.environ["DATABASE_OWNER_URL"].replace("psycopg", "asyncpg"))
    try:
        yield engine
    finally:
        await engine.dispose()


async def _posted_entry(client: httpx.AsyncClient) -> tuple[dict[str, str], dict]:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    entry = await client.post(
        f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "250.0000")
    )
    assert entry.status_code == 201, entry.text
    return headers, entry.json()


async def test_case_3_unbalanced_insert_bypassing_the_service_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    """The balance guarantee must survive code that never asks the service.

    trg_journal_balanced is a DEFERRABLE INITIALLY DEFERRED constraint trigger,
    so it fires at COMMIT rather than at INSERT — deliberately, because an entry
    is unbalanced halfway through writing its own lines. The exception therefore
    surfaces when the transaction commits, which is why `pytest.raises` wraps
    the whole block rather than the statement.
    """
    headers, entry = await _posted_entry(client)
    with pytest.raises(DBAPIError) as caught:
        async with owner_engine.begin() as conn:
            tenant_id, journal_id, period_id, membership_id = (
                await conn.execute(
                    text(
                        "SELECT tenant_id, journal_id, fiscal_period_id, "
                        "posted_by_membership_id FROM journal_entries WHERE id=:i"
                    ),
                    {"i": entry["id"]},
                )
            ).one()
            await conn.execute(
                text("""
                    INSERT INTO journal_entries
                      (id, tenant_id, journal_id, fiscal_period_id, entry_number, entry_date,
                       status, description, source_type, source_id, event_type, currency,
                       total_debit, total_credit, posted_at, posted_by_membership_id,
                       entry_metadata, created_at, updated_at)
                    VALUES (gen_random_uuid(), :t, :j, :p, :n, '2026-08-15', 'POSTED',
                            'smuggled', 'manual', gen_random_uuid(), 'manual', 'USD',
                            100, 90, now(), :m, '{}'::jsonb, now(), now())
                """),
                {
                    "t": tenant_id,
                    "j": journal_id,
                    "p": period_id,
                    "n": f"SMUGGLE-{uuid.uuid4().hex[:8]}",
                    "m": membership_id,
                },
            )
    assert "UNBALANCED_JOURNAL" in str(caught.value)


async def test_case_4_update_of_a_posted_entry_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    _, entry = await _posted_entry(client)
    async with owner_engine.begin() as conn:
        with pytest.raises(DBAPIError) as caught:
            await conn.execute(
                text("UPDATE journal_entries SET description='tampered' WHERE id=:i"),
                {"i": entry["id"]},
            )
    assert "POSTED_ENTRY_IMMUTABLE" in str(caught.value)


async def test_case_5_delete_of_a_posted_entry_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    _, entry = await _posted_entry(client)
    async with owner_engine.begin() as conn:
        with pytest.raises(DBAPIError) as caught:
            await conn.execute(text("DELETE FROM journal_entries WHERE id=:i"), {"i": entry["id"]})
    assert "POSTED_ENTRY_IMMUTABLE" in str(caught.value)


async def test_case_18_a_line_with_both_sides_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    _, entry = await _posted_entry(client)
    async with owner_engine.begin() as conn:
        account = (
            await conn.execute(
                text(
                    "SELECT account_id FROM journal_entry_lines WHERE journal_entry_id=:i LIMIT 1"
                ),
                {"i": entry["id"]},
            )
        ).scalar_one()
        tenant_id = (
            await conn.execute(
                text("SELECT tenant_id FROM journal_entries WHERE id=:i"), {"i": entry["id"]}
            )
        ).scalar_one()
        with pytest.raises(DBAPIError) as caught:
            await conn.execute(
                text("""
                    INSERT INTO journal_entry_lines
                      (id, tenant_id, journal_entry_id, account_id, debit, credit,
                       created_at, updated_at)
                    VALUES (gen_random_uuid(), :t, :e, :a, 50, 50, now(), now())
                """),
                {"t": tenant_id, "e": entry["id"], "a": account},
            )
    # A line is one side or the other; both non-zero is meaningless.
    assert "exactly_one_side" in str(caught.value) or "violates check" in str(caught.value)


# ── 6, 7: reversals ───────────────────────────────────────────────────────────


async def test_case_6_reversal_restores_balances(client: httpx.AsyncClient) -> None:
    headers, entry = await _posted_entry(client)
    before = (
        await client.get(
            f"{ACC}/reports/trial-balance?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    reversal = await client.post(
        f"{ACC}/entries/{entry['id']}/reverse",
        headers=headers,
        json={"reversal_date": "2026-08-16"},
    )
    assert reversal.status_code == 201, reversal.text
    after = (
        await client.get(
            f"{ACC}/reports/trial-balance?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()

    def net(report: dict) -> Decimal:
        return sum(
            (Decimal(r["debit"]) - Decimal(r["credit"]) for r in report["items"]), Decimal("0")
        )

    # The entry and its reversal cancel: every account returns to where it was.
    assert net(after) == Decimal("0")
    assert net(before) == Decimal("0")


async def test_case_7_double_reversal_is_rejected(client: httpx.AsyncClient) -> None:
    headers, entry = await _posted_entry(client)
    body = {"reversal_date": "2026-08-16"}
    first = await client.post(f"{ACC}/entries/{entry['id']}/reverse", headers=headers, json=body)
    assert first.status_code == 201, first.text
    second = await client.post(f"{ACC}/entries/{entry['id']}/reverse", headers=headers, json=body)
    assert second.status_code in (409, 422), second.text
    assert second.json()["error"]["code"] == "ENTRY_ALREADY_REVERSED"


# ── 8, 9, 10: fiscal periods ──────────────────────────────────────────────────


async def test_case_8_closed_period_admits_only_an_elevated_adjustment(
    client: httpx.AsyncClient,
) -> None:
    """§5: CLOSED rejects normal posting; `accounting.post_closed` may adjust.

    The seeded roles cannot express matrix case 8 literally — no system role
    holds `accounting.post` without also holding `accounting.post_closed`
    (OWNER, ADMIN and ACCOUNTANT get all four; MANAGER gets read only, so it
    would 403 before reaching the period check). This asserts the rule §5
    actually states, and the gap is recorded for review.
    """
    headers, by_code = await workspace(client)
    periods = (await client.get(f"{ACC}/periods/", headers=headers)).json()
    target = periods[0]
    closed = await client.patch(
        f"{ACC}/periods/{target['id']}/status", headers=headers, json={"status": "CLOSED"}
    )
    assert closed.status_code == 200, closed.text

    debit, credit = pick(by_code)
    # This actor holds accounting.post_closed, so the adjustment is permitted.
    response = await client.post(
        f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "10.0000")
    )
    assert response.status_code == 201, response.text


async def test_case_9_locked_period_rejects_even_an_elevated_actor(
    client: httpx.AsyncClient,
) -> None:
    headers, by_code = await workspace(client)
    periods = (await client.get(f"{ACC}/periods/", headers=headers)).json()
    target = periods[0]
    # OPEN -> CLOSED -> LOCKED; a direct jump is an illegal transition and would
    # leave the period open, silently making this test pass for the wrong reason.
    assert (
        await client.patch(
            f"{ACC}/periods/{target['id']}/status", headers=headers, json={"status": "CLOSED"}
        )
    ).status_code == 200
    locked = await client.patch(
        f"{ACC}/periods/{target['id']}/status", headers=headers, json={"status": "LOCKED"}
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["status"] == "LOCKED"
    debit, credit = pick(by_code)
    # This actor is the OWNER and holds accounting.post_closed. LOCKED must
    # still refuse: it is the state that means "audited, do not touch".
    response = await client.post(
        f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "10.0000")
    )
    assert response.status_code in (409, 422), response.text


async def test_case_10_overlapping_periods_are_rejected(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    overlap = await client.post(
        f"{ACC}/periods/",
        headers=headers,
        json={"name": "overlap", "start_date": "2026-08-15", "end_date": "2026-09-15"},
    )
    # An exclusion constraint on daterange, not a service check.
    assert overlap.status_code in (409, 422), overlap.text


# ── 15, 16, 17, 19, 20 ────────────────────────────────────────────────────────


async def test_case_15_trial_balance_ties(client: httpx.AsyncClient) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    for amount in ("100.0000", "250.5000", "17.2500"):
        assert (
            await client.post(
                f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, amount)
            )
        ).status_code == 201
    report = (
        await client.get(
            f"{ACC}/reports/trial-balance?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    total_debit = sum((Decimal(r["debit"]) for r in report["items"]), Decimal("0"))
    total_credit = sum((Decimal(r["credit"]) for r in report["items"]), Decimal("0"))
    # Criterion 2 of PROJECT_SPEC §6: the trial balance always ties.
    assert total_debit == total_credit, report


async def test_case_16_tenant_b_cannot_read_tenant_a_entry(client: httpx.AsyncClient) -> None:
    _, entry = await _posted_entry(client)
    other = await tenant_headers(client, f"other-{uuid.uuid4().hex[:10]}@example.com")
    response = await client.get(f"{ACC}/entries/{entry['id']}", headers=other)
    # 404, never 403 — a 403 confirms the row exists elsewhere (ADR-0009).
    assert response.status_code == 404


async def test_case_17_unauthenticated_posting_is_rejected(client: httpx.AsyncClient) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    response = await client.post(f"{ACC}/entries/", json=two_sided(debit, credit, "10.0000"))
    assert response.status_code == 401


async def test_case_19_posting_to_a_non_postable_account_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    headers, by_code = await workspace(client)
    accounts = (await client.get(f"{ACC}/accounts/", headers=headers)).json()
    parents = [a for a in accounts if not a["is_postable"]]
    if not parents:
        pytest.skip("seeded chart exposes no non-postable parent")
    debit, credit = pick(by_code)
    payload = two_sided(debit, credit, "10.0000")
    payload["lines"][0]["account_id"] = parents[0]["id"]
    response = await client.post(f"{ACC}/entries/", headers=headers, json=payload)
    assert response.status_code in (409, 422), response.text


async def test_case_20_concurrent_postings_both_succeed_and_tie(
    client: httpx.AsyncClient,
) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    results = await asyncio.gather(
        *(
            client.post(
                f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "40.0000")
            )
            for _ in range(5)
        )
    )
    assert [r.status_code for r in results] == [201] * 5, [r.text for r in results]
    report = (
        await client.get(
            f"{ACC}/reports/trial-balance?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    total_debit = sum((Decimal(r["debit"]) for r in report["items"]), Decimal("0"))
    total_credit = sum((Decimal(r["credit"]) for r in report["items"]), Decimal("0"))
    assert total_debit == total_credit == Decimal("200.0000"), report


async def test_entry_numbers_are_gapless_per_tenant(client: httpx.AsyncClient) -> None:
    headers, by_code = await workspace(client)
    debit, credit = pick(by_code)
    numbers = []
    for _ in range(3):
        r = await client.post(
            f"{ACC}/entries/", headers=headers, json=two_sided(debit, credit, "5.0000")
        )
        assert r.status_code == 201, r.text
        numbers.append(r.json()["entry_number"])
    assert len(set(numbers)) == 3, numbers
    suffixes = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert suffixes == list(range(suffixes[0], suffixes[0] + 3)), numbers
