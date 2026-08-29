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
Binding specification: `the handoff log` → *ARCHITECT HANDOFF — PHASE 2*.
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

## Phase 4 — POS · `[ ]`
- [ ] Terminals, sessions (open/close, cash reconciliation)
- [ ] Barcode + fast search, cart, discounts, VAT
- [ ] Cash / card / mobile / split payment
- [ ] Idempotent, atomic checkout
- [ ] Receipt, hold/resume
- [ ] Returns, full and partial refunds
- [ ] Keyboard-first UI
- [ ] Rollback, duplicate-key, concurrent-final-item tests

## Phase 5 — Accounting · `[ ]`
- [ ] Chart of Accounts + system accounts seeded per tenant
- [ ] Journals, entries, lines, DB-enforced balance
- [ ] Posted-entry immutability triggers
- [ ] Fiscal periods with exclusion constraint
- [ ] Reversals
- [ ] Payment allocation, AR/AP control accounts
- [ ] Weighted average cost + COGS
- [ ] General Ledger, Trial Balance, P&L, Balance Sheet, AR/AP Aging
- [ ] Posting integration for sales, purchases, POS
- [ ] 22-case accounting test matrix (`ACCOUNTING.md` §10)

## Phase 6 — CRM + Reporting · `[ ]`
- [ ] Leads, Opportunities, Activities, Notes, pipeline, conversion
- [ ] Dashboard: revenue, gross/net profit, expenses, AR/AP, inventory value
- [ ] Top products, sales trends, branch performance, low stock, refund trends
- [ ] Database-side aggregation, bounded queries, report caching
- [ ] Report isolation + authorization tests

## Phase 7 — VAT · `[ ]`
- [ ] Configurable rates + tax categories
- [ ] Inclusive / exclusive pricing
- [ ] Input / output VAT
- [ ] Tax invoice, VAT summary and reports
- [ ] Return handling, documented rounding policy
- [ ] Jurisdiction-specific reporting isolated behind an interface

## Phase 8 — AI Business Copilot · `[ ]`
- [ ] Provider abstraction, model config
- [ ] Tool registry with mandatory permission declaration
- [ ] 8 whitelisted analytics tools
- [ ] Bounded date ranges, tool invocation logging
- [ ] Untrusted-content framing, numeric grounding check
- [ ] Chat UI
- [ ] Cross-tenant, unauthorized-tool, injection tests

## Phase 9 — RAG · `[ ]`
- [ ] Upload, validation, MIME sniffing, S3 storage
- [ ] Async extract → chunk → embed → index
- [ ] `TenantVectorStore` (sole Qdrant caller)
- [ ] Tenant-filtered retrieval + document ACL
- [ ] Citations with click-time re-authorization
- [ ] Deletion / reindex / orphan reconciliation
- [ ] Document manager + RAG chat UI
- [ ] Adversarial isolation and injection tests

## Phase 10 — Forecasting + Anomaly Detection · `[ ]`
- [ ] Naive, moving average, exponential smoothing baselines
- [ ] Walk-forward backtesting; MAE / RMSE / MASE
- [ ] Complex model only if it beats naive
- [ ] Actual vs forecast vs uncertainty presentation
- [ ] Robust-statistics anomaly detectors
- [ ] Explainable alerts (observed, expected, deviation, reason, severity)
- [ ] False-positive evaluation on seeded scenarios

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
