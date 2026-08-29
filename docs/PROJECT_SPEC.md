# Nexora AI — Project Specification

**Nexora AI — AI-Powered Multi-Tenant ERP, POS & Business Intelligence Platform**

---

## 1. Problem

Small and medium businesses run on a patchwork: a POS that does not talk to
inventory, a spreadsheet for accounts, a notebook for receivables, and a VAT
return assembled by hand at period end. Each seam is a place where numbers stop
agreeing, and by the time the disagreement is noticed the source is weeks old.

Existing ERPs solve this at enterprise price points and enterprise
implementation timelines. What is missing at the SMB end is a system where the
till, the stock ledger and the general ledger are the *same* transaction.

## 2. What Nexora AI Is

A multi-tenant SaaS platform where a business runs its operations and its books
in one system:

- **Operations** — POS, catalog, inventory, sales, purchasing, CRM
- **Finance** — double-entry accounting, VAT, receivables, payables, reporting
- **Intelligence** — a copilot that explains the numbers, document Q&A over the
  company's own files, demand forecasting, anomaly detection

The design commitment underneath all of it: **a POS checkout is one database
transaction** that writes the sale, the stock movement, the payment, the VAT
record, the journal entries and the audit event — or writes none of them.

## 3. What Nexora AI Is Not

- Not a payment processor. Card payments are recorded as references to
  externally-processed transactions. No PAN, CVV or track data is stored.
  No PCI-DSS scope is claimed.
- Not certified for any tax jurisdiction. The VAT subsystem is generic and
  configurable. **No NBR or Bangladesh Mushak compliance is claimed** — the
  module is structured so verified jurisdiction support can be added later
  without touching the accounting core.
- Not an autonomous agent. The AI reads validated data and explains it. It
  cannot post entries, move stock, approve refunds, or run SQL.
- Not multi-currency in v1. One tenant, one base currency (currency is stored
  on every record so this is an additive change later).
- Not multi-entity. One tenant is one legal entity; branches are operational,
  not legal, divisions.

## 4. Users

| Role | What they do daily | What they must never do |
|---|---|---|
| Owner | Everything; sees all branches and all financials | — |
| Admin | User and configuration management | Change tenant-level financial settings |
| Manager | Runs a branch: stock, sales, staff performance | See other branches unless granted |
| Accountant | Posts, reconciles, closes periods, files VAT | Edit a posted entry (reversal only) |
| Cashier | Rings up sales at one branch, takes payment | Refund without permission; sell at another branch |
| Sales | Quotations, orders, customer relationships | See cost or margin data |
| Inventory Manager | Receives, transfers, adjusts, counts | Post to the general ledger |
| Employee | Reads what they are explicitly granted | Anything else |

## 5. Core Business Flows

```
Onboarding      Register → Create Organization → Default Branch + Warehouse
                → Invite Staff → Assign Roles

Procure         Purchase Request → PO → Goods Receipt (stock ↑, GRNI)
                → Supplier Bill (AP) → Payment

Sell (B2B)      Quotation → Sales Order → Fulfillment (stock ↓)
                → Invoice (AR, VAT) → Payment → Allocation

Sell (retail)   Scan → Cart → Payment → Checkout
                [ one atomic transaction: sale, stock, payment, VAT,
                  journal, receipt, audit ]

Correct         Return → Restock (optional) → Refund → Reversing entries

Close           Reconcile → Trial Balance → P&L / Balance Sheet
                → VAT return → Close period

Understand      Dashboard · Copilot Q&A · Document Q&A · Forecast · Anomalies
```

## 6. Success Criteria

The project is successful when it demonstrably has:

1. **Tenant isolation** — an adversarial suite proving Tenant B cannot read,
   write or enumerate any Tenant A resource, through any surface including AI
   and RAG.
2. **Accounting correctness** — every posted entry balances, enforced by the
   database; posted entries are immutable; the trial balance always ties.
3. **Inventory correctness** — the movement ledger is the source of truth;
   concurrent checkouts cannot oversell; balances reconcile to movements.
4. **Transactional integrity** — no partially-completed business operation
   exists after any failure, proven by rollback tests.
5. **Idempotency** — a replayed checkout produces exactly one sale.
6. **Authorization** — every endpoint enforces a permission; escalation is
   blocked and tested.
7. **Auditability** — every sensitive action leaves an immutable trail.
8. **Safe AI** — every figure the copilot states is traceable to a
   permission-checked tool call.
9. **Verifiability** — format, lint, typecheck, tests and production build all
   pass in CI, and CI blocks merge.

Note what is absent from that list: feature count, and UI polish. A beautiful
POS that oversells under concurrency is a failed build of this system.

## 7. Constraints

- Modular monolith. No microservices without a demonstrated production need.
- No floating point for money, anywhere, at any layer.
- Posted accounting entries are never mutated.
- Inventory changes only through the movement ledger.
- The LLM never executes SQL and never bypasses RBAC or tenant scope.
- Client-supplied tenant identifiers are never trusted.
- No TODO placeholders standing in for core behaviour.
- No mock behaviour in production code paths.

## 8. Delivery Model

Two agents, one architecture (`prompt.md` §1–2):

- **Claude CLI** — architecture, domain and data modelling, invariants, API
  contracts, security design, review and severity classification.
- **Codex** — implementation, migrations, tests, Docker, CI, debugging, fixes.

Cycle per phase: **design → implement → review → fix → verify → commit.**
Never two agents implementing halves of the same feature.

Phase gate: no phase begins while a P0 or P1 finding is open in a dependency.

## 9. Reference Documents

| Document | Contains |
|---|---|
| `docs/ARCHITECTURE.md` | System structure, tenancy, transactions, testing |
| `docs/DATABASE.md` | Schema, types, constraints, triggers, RLS, indexing |
| `docs/API.md` | Endpoints, error envelope, pagination, permissions |
| `docs/ACCOUNTING.md` | Invariants, chart of accounts, posting rules, rounding |
| `docs/SECURITY.md` | Threat model, controls, known gaps |
| `docs/AI.md` | Copilot tools, RAG isolation, forecasting honesty rules |
| `docs/DECISIONS.md` | 21 ADRs with costs stated |
| `docs/ROADMAP.md` | Phase checklist |
| `docs/AGENT_HANDOFF.md` | Live state transfer between agents |
