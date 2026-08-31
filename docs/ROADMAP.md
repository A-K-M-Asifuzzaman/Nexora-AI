# Nexora AI Roadmap

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

**Gate rule:** a phase may not start while a P0 or P1 finding is open in any
phase it depends on.

---

## Phase 0 — Architecture · `[x]` COMPLETE
- [x] Repository / monorepo structure
- [x] Backend module boundaries and dependency rules
- [x] Frontend architecture (BFF token custody)
- [x] PostgreSQL architecture, types, constraints, RLS
- [x] Multi-tenancy strategy (3 enforcement layers)
- [x] Authentication + refresh/session strategy
- [x] RBAC architecture + escalation guards
- [x] Tenant context propagation (request + worker)
- [x] Audit architecture (business vs security streams)
- [x] Error handling architecture + code registry
- [x] Transaction strategy + lock ordering
- [x] Idempotency strategy
- [x] Numbering strategy (gapless)
- [x] Background job strategy (Celery + outbox)
- [x] Object storage strategy
- [x] Redis usage
- [x] Qdrant tenant isolation
- [x] Logging / observability
- [x] Test architecture + structural guards
- [x] Docker development architecture
- [x] CI architecture
- [x] ADR process (21 ADRs recorded)
- [x] Accounting invariants + posting rules
- [x] AI safety architecture
- [x] Phase 1 implementation handoff

## Phase 1 — Foundation (Auth + Tenancy + RBAC + Audit) · `[x]` COMPLETE
- [x] FastAPI app factory, config, error handling, correlation IDs
- [x] `/health`, `/ready`, `/metrics`
- [x] Registration, login, Argon2id hashing
- [x] Access + refresh tokens, rotation, reuse detection
- [x] Logout / logout-all / session revocation
- [x] Email verification + password reset structure
- [x] Tenant, Branch, Warehouse, Membership
- [x] Tenant context dependency + global query filter + RLS
- [x] Roles, Permissions, role mapping, authorization service
- [x] Invitations
- [x] AuditEvent + audit service + SecurityEvent
- [x] Idempotency + outbox tables (drain scheduled by beat — P1-39)
- [x] Next.js shell, auth pages, org creation, org switcher, branch & member UI
- [x] Docker Compose, `.env.example`
- [x] Test suites: unit, integration, isolation, authz, structural
- [x] CI pipeline green

**Exit state:** no P0 or P1 open. One P2 owed — the outbox drain has not been
observed end-to-end against MailHog because Docker was unavailable (P2-40).
Run it when Docker Desktop is up; every recovery flow depends on it.

## Phase 2 — Catalog + Inventory · `[x]` COMPLETE
Binding specification: the phase handoff log → *ARCHITECT HANDOFF — PHASE 2*.
- [x] Products, variants, categories, brands, UoM, tax categories
- [x] SKU / barcode tenant-unique constraints
- [x] Warehouses (semantics)
- [x] Inventory movement ledger (append-only, trigger-enforced)
- [x] Materialized balances + reconciliation job
- [x] Reservations, transfers, adjustments
- [x] Concurrency-safe consumption (`FOR UPDATE`, lock ordering)
- [x] Low-stock configuration
- [x] Catalog + inventory UI
- [x] Concurrency and isolation test suites

**Exit state (verified against live PostgreSQL 16.14, migration `0012` applied):**

```
make verify     lint + typecheck + test + build, all green
backend         153 passed · 84.97% coverage
frontend        28 passed · 9 files
alembic check   no drift
RLS             enabled on all 13 new tables (confirmed in pg_tables)
```

Criterion 3 (no oversell) and criterion 5 (idempotent replay) are both pinned
by tests that assert against the **movement ledger**, not only the cached
balance — a lost update and a correct ledger can reach the same final number.
No P0 or P1 open.

## Phase 3 — Sales + Purchasing · `[x]` COMPLETE
- [x] Customers, Suppliers
- [x] Quotation → Sales Order → Fulfillment → Invoice → Payment
- [x] PO → Goods Receipt → Supplier Bill → Payment
- [x] Explicit state machines, legal transitions only
- [x] Gapless document numbering
- [x] Partial payment / partial receipt
- [x] Returns (sales, via credit notes)
- [x] AR / AP balances
- [x] Management UI + workflow integration tests

**Exit state (verified against live PostgreSQL 16.14, migration `0013` applied):**

```
make verify     lint + typecheck + test + build, all green
backend         191 passed · 85.28% coverage
frontend        31 passed
alembic         check clean; downgrade base → upgrade head clean
API surface     121 operations; 36 are Phase 3
```

Numbering is proven under contention, not assumed: 20 concurrent allocations in
20 separate transactions yield 20 distinct contiguous numbers, and the test was
confirmed to fail against a naive read-then-write allocator.

**Deliberately not built, with reasons:**

- **Purchase returns (debit notes).** `DATABASE.md` §4 lists `credit_notes` only,
  which is the sales side. A purchase return needs a table §4 does not name, so
  it is an architecture decision rather than an omission — it needs an ADR.
- **Purchase requests.** The roadmap line says "Purchase Request → PO", but §4
  lists no `purchase_requests` table. Same call: §4 governs.

No P0 or P1 open. One layering concern recorded for review: `payment_allocations`
references both `invoices` and `supplier_bills`, coupling sales and purchasing
through the database. No Python import cycle exists, so the AST guard cannot see
it — but it is real, and it caused a runtime failure before `import_all_models()`
was wired into `create_app`.

## Phase 4 — POS · `[x]` COMPLETE (pending implementer review)
- [x] Terminals, sessions (open/close, cash reconciliation)
- [x] Barcode + fast search, cart, discounts, VAT
- [x] Cash / card / mobile / split payment
- [x] Idempotent, atomic checkout
- [x] Receipt, hold/resume
- [x] Returns, full and partial refunds
- [x] Keyboard-first UI
- [x] Rollback, duplicate-key, concurrent-final-item tests

**Note:** built alongside Phase 5 in the same pass and never given its own
roadmap update at the time — this entry was backfilled after the fact, not
re-verified against a fresh exit-state run. Real journal postings and VAT
register wiring for POS checkout/refund were added later, in the Phase 9/10
hardening pass (see `_post_sale`/`_record_vat_for_sale` in
`app/modules/pos/service.py`).

## Phase 5 — Accounting · `[x]` COMPLETE (pending implementer review)
- [x] Chart of Accounts + system accounts seeded per tenant
- [x] Journals, entries, lines, DB-enforced balance
- [x] Posted-entry immutability triggers
- [x] Fiscal periods with exclusion constraint
- [x] Reversals
- [x] Payment allocation, AR/AP control accounts
- [x] Weighted average cost + COGS
- [x] General Ledger, Trial Balance, P&L, Balance Sheet, AR/AP Aging
- [x] Posting integration for sales, purchases, POS
- [x] 22-case accounting test matrix (`ACCOUNTING.md` §10)

**Note:** posting integration was checked off at the time this phase was
first closed, but the wiring was incomplete — POS checkout/refund, sales
fulfillment/invoice/payment, and purchase receipt/bill/payment could all
reach "completed" status without ever posting a journal entry. Found and
fixed in the Phase 9/10 hardening pass (commit `c0859a6`), proven with 7
new integration tests asserting real trial-balance effects rather than
document status. See `AGENT_HANDOFF.md`.

**Exit state (live PostgreSQL 16.14, migration `0017` applied — pre-dates
the posting-integration fix above):**

```
make verify     lint + typecheck + test + build, all green
backend         225 passed · 85.38% coverage
frontend        38 passed
alembic         check clean; downgrade base → upgrade head clean
```

17 tests cover the §10 matrix. Cases 3, 4, 5 and 18 run through a **direct
database connection**, bypassing the service entirely — their whole point is
that the guarantee survives code that forgets to ask (criterion 2: "enforced by
the database").

**Known gap:** matrix case 8 cannot be expressed literally. No seeded system
role holds `accounting.post` without also holding `accounting.post_closed`
(OWNER/ADMIN/ACCOUNTANT get all four; MANAGER gets read only, so it would 403
before reaching the period check). The test asserts what §5 actually states
instead. Either seed a role with `post` but not `post_closed`, or accept it.

## Phase 6 — CRM + Reporting · `[x]` COMPLETE (pending implementer review)
- [x] Leads, Opportunities, Activities, Notes, pipeline, conversion
- [x] Dashboard: revenue, gross profit, AR/AP, inventory value
- [x] Top products, sales trends, low stock, pipeline
- [x] Database-side aggregation, bounded queries, report caching
- [x] Report isolation + authorization tests

**Exit state (live PostgreSQL 16.14, migration `0018` applied):**

```
make verify     lint + typecheck + test + build, all green
backend         241 passed · 85.47% coverage
frontend        38 passed
alembic         check clean; downgrade base → upgrade head clean, 0 leftover enums
```

**`DATABASE.md` §4 specifies no Phase 6 tables** — it runs Phase 5 → Phase 7.
`leads`, `opportunities`, `crm_activities` and `crm_notes` are proposed in the
Phase 6 handoff rather than given, and are the weakest-justified schema in the
project so far: the Phase 3/4 line tables §4 omitted at least had a named
parent in §4, and these do not. **If this needed an ADR first, it
is right to say so.**

Not built: branch performance and refund-trend reports. The data supports both;
they are additional queries, not new structure.

## Phase 7 — VAT · `[x]` COMPLETE (pending implementer review)
- [x] Configurable rates + tax categories
- [x] Inclusive / exclusive pricing
- [x] Input / output VAT
- [x] VAT summary and register reports
- [x] Return handling, documented rounding policy
- [x] Jurisdiction-specific reporting isolated in the `vat` module

**Exit state (live PostgreSQL 16.14, migration `0019` applied):**

```
make verify     lint + typecheck + test + build, all green
backend         258 passed · 85.71% coverage
frontend        38 passed
alembic         check clean; downgrade base → upgrade head clean, 0 leftover enums
```

Rates are **effective-dated**, not edited: an invoice issued under 15% stays a
15% invoice after the rate moves, and the return for that period still
reconciles. Return box totals are **stored**, not derived on read — a return is
a statement made to an authority on a date, and recomputing it later from live
data would quietly change what you are on record as having said.

Per `ACCOUNTING.md` §9.4 no jurisdiction is hardcoded, and the system claims no
regulatory compliance. Not built: a tax-invoice document layout, which is
presentation rather than structure.

## Phase 8 — AI Business Copilot · `[x]` BACKEND COMPLETE (pending implementer review)
- [x] Provider abstraction, model config
- [x] Tool registry with mandatory permission declaration
- [x] 8 whitelisted analytics tools
- [x] Bounded date ranges, tool invocation logging
- [x] Untrusted-content framing, numeric grounding check
- [ ] Chat UI — **not built**
- [x] Unauthorized-tool and injection tests

**Exit state (migration `0020` applied):**

```
make verify     lint + typecheck + test + build, all green
backend         284 passed · 85.09% coverage
frontend        38 passed
```

**Provider:** running configuration is OpenAI; `AI.md` §2.6 still names
Anthropic as the documented default. Both are implemented behind one
`LLMProvider` protocol and selected by `LLM_PROVIDER`. **No security property
depends on which is configured** — no SQL is generated (ADR-0017), every tool
re-checks its permission against the authenticated context, ranges cap at 366
days, and answers are grounding-checked.

Every guardrail test runs **without an LLM call**, deliberately: the guarantees
are deterministic and provider-independent, so proving them must not depend on a
paid external service.

**Not built:** the chat UI, and the per-tenant token budget in `AI.md` §6.

## Phase 9 — RAG · `[x]` COMPLETE (pending Codex review)
- [x] Upload, validation, content-based sniffing, S3 storage
- [x] Async extract → chunk → embed → index
- [x] `TenantVectorStore` (sole Qdrant caller)
- [x] Tenant-filtered retrieval + document ACL
- [x] Citations with click-time re-authorization
- [x] Deletion / reindex / orphan reconciliation
- [x] Document manager UI; RAG chat unified into the existing Phase 8 copilot
      (`search_documents` is tool #9 there, not a separate chat surface —
      matches `AI.md` treating RAG as one more copilot capability)
- [x] Adversarial isolation and injection tests

**Exit state (live PostgreSQL 16.14 + Qdrant 1.15.5 + MinIO, migration `0021`
applied):**

```
backend pytest tests/integration/documents  19 passed
backend pytest (full suite)                 303 passed (284 pre-existing + 19 new)
backend ruff / mypy                         clean
frontend lint / typecheck / build / test    clean; 38 passed
browser E2E (Playwright, desktop + mobile)  upload → INDEXED → delete; 0 console/5xx errors
```

Content-based validation is deliberately not full MIME sniffing — CSV,
Markdown and plain text are byte-for-byte indistinguishable in general, no
signature check can tell them apart. It does catch a PDF magic-number
mismatch and binary content wearing a `text/*` label, which is the
actually-exploitable case.

Four defects found and fixed, none of them caught by writing the feature the
first time — see `AGENT_HANDOFF.md`'s Phase 9 section for the full account:
an eager `app = create_app()` at import time that could permanently poison
`get_settings()`'s cache depending on test order; `DocumentStorage`/
`TenantVectorStore` provisioning methods that existed with no caller; the
Celery indexing task never setting PostgreSQL's RLS session GUC, so it would
have failed on every real invocation; and every document endpoint requiring a
working LLM provider even to list documents, because the embedder was
constructed eagerly.

Not built: a per-tenant token/storage budget (mentioned in `AI.md` §6, not a
Phase 9 roadmap line item).

## Phase 10 — Forecasting + Anomaly Detection · `[x]`
- [x] Naive, moving average, exponential smoothing baselines
- [x] Walk-forward backtesting; MAE / RMSE / MASE
- [x] Complex model only if it beats naive
- [x] Actual vs forecast vs uncertainty presentation
- [x] Robust-statistics anomaly detectors
- [x] Explainable alerts (observed, expected, deviation, reason, severity)
- [x] False-positive evaluation on seeded scenarios

**Exit state (live PostgreSQL 16, migration `0022` applied):**

```
backend pytest tests/integration/anomaly       15 passed
backend pytest tests/integration/forecasting    5 passed
backend pytest tests/unit (detectors/algorithms/backtest)  24 passed
backend pytest (full suite, --cov)             388 passed, 87% coverage
backend ruff / mypy                            clean
```

Three defects found and fixed, none of them caught by writing the feature
the first time — this had never executed against a live database before —
see `AGENT_HANDOFF.md`'s Phase 10 section for the full account: every
detector query crashing on its first real invocation (an interval built by
string-concatenating a bound `int` against a `||` operator expecting text);
every tenant's first day of real activity reading as a false CRITICAL
anomaly against an all-zero 30-day baseline, which is not a rare case but
the guaranteed first-run experience for every tenant; and the seeded role
permissions having drifted from the design this same handoff already
specified.

Not built: `CASHIER_VOID_RATE` detects on `sales.status = 'VOIDED'`, and
POS has no operation that ever sets it — voiding a sale is a real, separate
feature outside this phase's scope. The detector and its test are correct
against the schema and will fire the moment that status becomes reachable.

**Frontend added in a follow-up pass:** `InsightsPanel` (forecast chart +
uncertainty table + backtest scores; anomaly alert inbox with redaction,
acknowledge/dismiss, manual run) wired into the workspace nav. Browser-
verified end to end (register → org → catalog → forecast → alerts, desktop
and mobile). One bug found and fixed in that pass: the forecast product
picker didn't notice a product created in the sibling Catalog panel during
the same session without a reload — fixed via a small custom DOM event
Catalog now dispatches on create.

## Phase 11 — Security Hardening · `[ ]`
- [ ] Full threat-model re-audit
- [ ] Tenant attack + IDOR/BOLA sweep
- [ ] File upload hardening + virus scanning wired
- [ ] AI/RAG prompt-injection review
- [ ] MFA/TOTP
- [ ] Audit hash-chaining (ADR-0016)
- [ ] Rate-limit tuning, dependency review
- [ ] Close every gap in `SECURITY.md` §12 or re-accept it explicitly

## Phase 12 — Production Deployment · `[ ]`
- [ ] Production Docker, non-root, multi-stage
- [ ] Environment separation + secret management
- [ ] Reverse proxy, TLS, security headers
- [ ] Postgres backup + restore rehearsal
- [ ] Migration + rollback procedure
- [ ] Qdrant / object storage persistence
- [ ] Metrics, error tracking, alerting
- [ ] CI/CD release flow
- [ ] Seeded demo tenant
- [ ] Production README + smoke tests
