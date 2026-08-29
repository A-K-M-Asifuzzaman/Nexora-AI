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

## Phase 1 — Foundation (Auth + Tenancy + RBAC + Audit) · `[ ]`
- [ ] FastAPI app factory, config, error handling, correlation IDs
- [ ] `/health`, `/ready`, `/metrics`
- [ ] Registration, login, Argon2id hashing
- [ ] Access + refresh tokens, rotation, reuse detection
- [ ] Logout / logout-all / session revocation
- [ ] Email verification + password reset structure
- [ ] Tenant, Branch, Warehouse, Membership
- [ ] Tenant context dependency + global query filter + RLS
- [ ] Roles, Permissions, role mapping, authorization service
- [ ] Invitations
- [ ] AuditEvent + audit service + SecurityEvent
- [ ] Idempotency + outbox tables
- [ ] Next.js shell, auth pages, org creation, org switcher, branch & member UI
- [ ] Docker Compose, `.env.example`
- [ ] Test suites: unit, integration, isolation, authz, structural
- [ ] CI pipeline green

## Phase 2 — Catalog + Inventory · `[ ]`
- [ ] Products, variants, categories, brands, UoM, tax categories
- [ ] SKU / barcode tenant-unique constraints
- [ ] Warehouses (semantics)
- [ ] Inventory movement ledger (append-only)
- [ ] Materialized balances + reconciliation job
- [ ] Reservations, transfers, adjustments
- [ ] Concurrency-safe consumption (`FOR UPDATE`, lock ordering)
- [ ] Low-stock configuration
- [ ] Catalog + inventory UI
- [ ] Concurrency and isolation test suites

## Phase 3 — Sales + Purchasing · `[ ]`
- [ ] Customers, Suppliers
- [ ] Quotation → Sales Order → Fulfillment → Invoice → Payment
- [ ] Purchase Request → PO → Goods Receipt → Supplier Bill → Payment
- [ ] Explicit state machines, legal transitions only
- [ ] Gapless document numbering
- [ ] Partial payment / partial receipt
- [ ] Returns (sales and purchase)
- [ ] AR / AP balances
- [ ] Management UI + workflow integration tests

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
