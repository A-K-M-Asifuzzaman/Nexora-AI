# Nexora AI — Development Rules

Always read before significant work:

- `prompt.md`
- `docs/AGENT_HANDOFF.md`
- `docs/ARCHITECTURE.md`
- the domain document relevant to the task (`DATABASE`, `API`, `ACCOUNTING`, `SECURITY`, `AI`)

## Role

Claude is **lead architect and reviewer**. Codex is **implementer**.
Claude designs, defines invariants, reviews, and classifies defects.
Claude does not write large production implementations unless explicitly asked.

## Architecture

Modular monolith. No microservices without an ADR.
Business logic lives in the service layer. Routes stay thin: authenticate,
authorize, validate, call one service, serialize.
Routers never commit. Services own transaction boundaries.
Repositories contain queries, not rules.
Module dependency graph is acyclic; `tenancy`, `rbac`, `audit`, `core` are leaves.

## Tenant Security

Never trust `tenant_id` from a request body, query, path or header.
Tenant context is derived from the authenticated membership.
Every tenant-owned model inherits `TenantScoped` and is auto-filtered.
Cross-tenant access returns **404**, never 403.
Cross-tenant access is a security vulnerability, classified P0.

## Financial Data

Never `float` for money. `Decimal` in Python, `NUMERIC` in PostgreSQL.
Money crosses the API as **strings**, never JSON numbers.
Every posted journal entry balances — enforced by the database.
Never mutate a posted entry. Correct by reversal only.
Rounding is `ROUND_HALF_UP`, per line, then summed.

## Inventory

The movement ledger is the source of truth. Balances are a cache.
Never mutate a stock integer directly.
Consumption locks balance rows `FOR UPDATE` in `(warehouse_id, product_id)` order.

## POS

Checkout is atomic and idempotent.
Concurrency must not permit overselling.
A retry must never duplicate a sale, payment, movement, VAT record or posting.

## AI

The LLM never executes SQL. Whitelisted tools only.
Authorization lives in the tool, not the prompt.
RAG retrieval always enforces tenant scope.
The AI never invents a financial number — grounding is checked.

## Tests

Features require tests. Critical flows require integration tests.
Tenant isolation requires explicit adversarial tests.
Real PostgreSQL only; never SQLite.
Structural guards enforce architecture: no float money, every route
authenticated, every scoped model registered, acyclic imports.

## Review

Classify every finding: **P0** security/data/accounting corruption or tenant
leakage · **P1** serious correctness or reliability · **P2** maintainability,
performance, test gap · **P3** minor.

For each finding give: severity, file, location, issue, impact, recommended fix.
Do not approve a phase while P0 or P1 findings remain.

## Repository

No unrelated refactors. No dead code. No giant files. No secrets.
Never weaken a check to make CI green — that is a P1 finding.
Update `docs/AGENT_HANDOFF.md` after significant work.
