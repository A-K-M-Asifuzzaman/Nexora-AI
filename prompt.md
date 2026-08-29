# Nexora AI — Shared Development Prompt for Claude CLI + Codex

> **Purpose:** This single `prompt.md` file is the shared source of truth for two coding agents working on the same project.
>
> - **Claude CLI** = Lead Architect, Domain Designer, Reviewer, Security/Accounting Reviewer
> - **Codex** = Senior Implementation Engineer, Test Engineer, Debugger
>
> Both agents MUST read this file before meaningful work.
>
> The project must be built incrementally as an industry-grade modular monolith. Do not try to generate the whole ERP at once.

---

# 0. Project Identity

## Project Name

**Nexora AI**

## Full Title

**Nexora AI — AI-Powered Multi-Tenant ERP, POS & Business Intelligence Platform**

## Mission

Build a production-oriented multi-tenant SaaS platform for small and medium businesses that combines:

- ERP
- POS
- Product Catalog
- Inventory
- Sales
- Purchasing
- Accounting
- CRM
- VAT
- Reporting
- AI Business Copilot
- Tenant-Isolated RAG
- Forecasting
- Anomaly Detection

This is **NOT** a toy CRUD project.

The project must demonstrate:

- clean architecture
- strict tenant isolation
- strong RBAC
- transactional business workflows
- accounting correctness
- auditability
- secure API design
- maintainable code
- automated tests
- observability
- CI/CD
- production-minded deployment
- safe AI integration

---

# 1. Agent Responsibilities

## Claude CLI — Lead Architect and Reviewer

Claude owns:

- architecture
- domain modeling
- data modeling
- database constraints
- API contracts
- business rules
- accounting correctness
- inventory invariants
- security architecture
- multi-tenancy design
- AI safety design
- RAG security design
- implementation handoff
- code review
- architectural consistency
- technical documentation
- severity classification of defects

Claude SHOULD NOT generate large production implementations unless explicitly asked.

Claude should first:

1. inspect code
2. understand current state
3. define invariants
4. define models
5. define permissions
6. define tenant boundaries
7. define APIs
8. define edge cases
9. define transaction boundaries
10. define tests
11. hand off implementation clearly to Codex

---

## Codex — Senior Implementation Engineer

Codex owns:

- backend implementation
- frontend implementation
- migrations
- tests
- integration tests
- E2E tests
- Docker
- CI
- debugging
- refactors requested by Claude
- fixes after review
- keeping the repository runnable
- implementation documentation

Codex MUST follow architecture documents and this prompt.

Codex MUST NOT silently redesign the architecture.

If implementation reveals an architectural contradiction, Codex must stop and explain the conflict.

---

# 2. Collaboration Workflow

For every major phase:

```text
Claude
  ↓
Architecture / design / invariants / APIs / test matrix
  ↓
Codex
  ↓
Implementation + migrations + tests + docs
  ↓
Claude
  ↓
Architecture / security / business-rule review
  ↓
Codex
  ↓
Fix P0/P1/P2 findings
  ↓
Run all verification
  ↓
Commit
```

Do NOT ask both agents to independently design and implement the same feature.

The rule is:

> **Claude owns architectural consistency. Codex owns implementation velocity.**

---

# 3. Required Shared Repository Files

Maintain these files:

```text
README.md

docs/
├── PROJECT_SPEC.md
├── ARCHITECTURE.md
├── DATABASE.md
├── API.md
├── ACCOUNTING.md
├── SECURITY.md
├── AI.md
├── DECISIONS.md
├── ROADMAP.md
└── AGENT_HANDOFF.md
```

This file should be stored in the project root as:

```text
prompt.md
```

Both agents must read it.

---

# 4. Shared Handoff File

Create:

```text
docs/AGENT_HANDOFF.md
```

Use exactly this structure:

```markdown
# Current Phase

# Current Goal

# Completed

# Architecture Decisions

# Database Changes

# API Changes

# Files Changed

# Tests Added

# Commands Verified

# Known Problems

# Pending Work

# Instructions For Next Agent
```

Before meaningful work:

- read `docs/AGENT_HANDOFF.md`

After meaningful work:

- update `docs/AGENT_HANDOFF.md`

This is the canonical state-transfer file between Claude and Codex.

---

# 5. Tech Stack

## Frontend

- Next.js
- TypeScript
- React
- Tailwind CSS
- shadcn/ui
- TanStack Query where appropriate
- React Hook Form
- Zod
- Recharts
- Playwright

## Backend

- FastAPI
- Python
- Pydantic
- SQLAlchemy 2.x
- Alembic
- PostgreSQL

## Infrastructure

- Redis
- background jobs via Celery or another justified mechanism
- Docker
- Docker Compose
- S3-compatible object storage
- Qdrant
- GitHub Actions

## AI / ML

- LLM provider abstraction
- embeddings
- Qdrant
- hybrid retrieval where justified
- reranking where justified
- scikit-learn
- interpretable forecasting baselines
- anomaly detection baselines
- PyTorch only when simpler tools are insufficient

## Testing

Backend:

- pytest
- pytest-asyncio
- API tests
- integration tests

Frontend:

- Vitest
- React Testing Library
- Playwright

---

# 6. Architectural Style

Use a **modular monolith**.

Do NOT introduce microservices unless there is a demonstrated production need.

The backend should contain clear domain modules:

```text
auth
tenancy
users
rbac
branches
customers
suppliers
catalog
inventory
sales
purchases
pos
accounting
crm
vat
reporting
audit
notifications
documents
ai
forecasting
anomaly_detection
```

Each domain should separate:

- domain models
- schemas
- repositories/data access
- services/business logic
- API/routes
- tests

Routes/controllers should remain thin.

Routes should mainly:

- authenticate
- authorize
- validate
- call service/domain layer
- serialize response

Business logic must not live directly inside route handlers.

---

# 7. Non-Negotiable Engineering Rules

## Multi-Tenancy

Every organization is a tenant.

Tenant hierarchy:

```text
Tenant
 ├── Branches
 ├── Warehouses
 ├── Users
 ├── Products
 ├── Customers
 ├── Suppliers
 ├── Sales
 ├── Purchases
 ├── Accounting
 └── Reports
```

Rules:

- All tenant-owned entities must be associated with `tenant_id`.
- Never trust a client-provided tenant ID.
- Derive tenant context from authenticated membership/session.
- Every repository query must be tenant scoped.
- Every write must enforce tenant scope.
- Cross-tenant tests are mandatory.
- Tenant A must never access Tenant B data.
- Consider PostgreSQL RLS only as defense-in-depth.
- Application-level tenant enforcement remains mandatory.

---

## Financial Data

Never use floating point for money.

Use:

```text
Decimal
PostgreSQL NUMERIC
```

Never use:

```text
float
double
```

for financial amounts.

Posted accounting entries must not be edited directly.

Corrections must use reversal/adjustment entries.

---

## Inventory

Do NOT use a mutable `product.stock` integer as the primary source of truth.

Use an inventory movement ledger.

Inventory movement ledger is canonical.

Current balances may be:

- calculated
- materialized
- cached

but movements remain source of truth.

---

## POS

POS checkout must be:

- transactional
- idempotent
- concurrency safe

A retry must never duplicate:

- sale
- payment
- stock deduction
- accounting posting
- VAT posting

---

## AI

The LLM must NEVER have unrestricted SQL database access.

Use whitelisted, permission-aware analytics tools.

The AI must never:

- bypass RBAC
- bypass tenant isolation
- invent financial numbers
- claim unsupported business metrics
- retrieve another tenant's data

---

## RAG

Every RAG object must be tenant scoped:

- documents
- chunks
- vectors
- metadata
- citations
- retrieval filters

Tenant A documents must never be retrievable by Tenant B.

---

# 8. Authentication Requirements

Support:

- email/password registration
- secure password hashing
- login
- access tokens
- refresh tokens
- refresh rotation/revocation strategy
- logout
- forgot password
- email verification structure
- account lock/rate limiting where appropriate

Never:

- store plaintext passwords
- expose secrets to frontend
- log tokens
- log passwords

---

# 9. RBAC Design

Initial roles:

```text
OWNER
ADMIN
MANAGER
ACCOUNTANT
CASHIER
SALES
INVENTORY_MANAGER
EMPLOYEE
```

Internally use permissions.

Example permissions:

```text
sales.read
sales.create
sales.update
sales.refund

inventory.read
inventory.adjust
inventory.transfer

accounting.read
accounting.post

users.read
users.invite
users.manage_roles

reports.read

ai.use
documents.upload
documents.read
```

Do not scatter hardcoded role checks across business code.

Preferred model:

```text
Role → Permission Mapping
Membership → Role
Authorization Service → Permission Check
```

---

# 10. Audit Logging

Sensitive actions must create immutable audit events.

Record:

- tenant_id
- actor_user_id
- action
- resource_type
- resource_id
- timestamp
- metadata
- IP if available
- request correlation ID

Examples:

```text
sale.refunded
stock.adjusted
stock.transferred
journal.posted
journal.reversed
user.role_changed
invoice.voided
payment.reversed
supplier.created
tenant.settings_changed
```

Normal users must not be able to silently modify audit history.

---

# 11. Module 1 — Organization / Tenant Foundation

Implement:

- Tenant
- Organization profile
- Branch
- Warehouse
- Membership
- User invitations
- Business settings
- Currency
- Timezone
- Tax settings
- Invoice numbering
- Fiscal settings

Flow:

```text
Create Company
   ↓
Create Tenant
   ↓
Create Owner Membership
   ↓
Create Branch
   ↓
Invite Employees
   ↓
Assign Roles
```

---

# 12. Module 2 — Product Catalog

Entities:

- Product
- ProductVariant if justified
- Category
- Brand
- UnitOfMeasure
- Barcode
- SKU
- Price
- Cost
- TaxCategory

Features:

- create/edit product
- SKU
- barcode
- variants
- category
- brand
- cost
- selling price
- tax/VAT configuration
- active/inactive status
- search
- filters
- pagination
- bulk import structure

Constraints should include:

- tenant-unique SKU
- tenant-unique barcode where required

---

# 13. Module 3 — Inventory

Use inventory movements.

Movement types may include:

```text
PURCHASE_RECEIPT
SALE
SALE_RETURN
PURCHASE_RETURN
TRANSFER_OUT
TRANSFER_IN
ADJUSTMENT_IN
ADJUSTMENT_OUT
OPENING_BALANCE
RESERVATION
RESERVATION_RELEASE
```

Each movement should include appropriate fields:

- tenant_id
- branch_id if applicable
- warehouse_id
- product_id
- quantity
- unit_cost where appropriate
- reference_type
- reference_id
- timestamp
- actor

Support:

- warehouse stock
- stock history
- stock adjustment
- stock transfer
- low-stock threshold
- reserved stock
- available stock
- inventory valuation
- movement history

Critical invariant:

```text
available_quantity >= 0
```

unless negative inventory is explicitly enabled in tenant settings.

Concurrency must be handled.

Example:

```text
Stock = 1

POS Terminal A buys 1
POS Terminal B buys 1 simultaneously
```

Only one checkout may consume the final available quantity.

---

# 14. Module 4 — Customers and Suppliers

## Customer

Support:

- contact details
- billing address
- shipping address
- credit limit
- outstanding balance
- purchase history
- notes
- status

## Supplier

Support:

- contact details
- purchase history
- outstanding payable
- notes
- status

---

# 15. Module 5 — Sales

Workflow:

```text
Quotation
   ↓
Sales Order
   ↓
Fulfillment
   ↓
Invoice
   ↓
Payment
```

Possible Sales Order states:

```text
DRAFT
CONFIRMED
PARTIALLY_FULFILLED
FULFILLED
CANCELLED
```

Possible Invoice states:

```text
DRAFT
ISSUED
PARTIALLY_PAID
PAID
VOID
```

Support:

- discounts
- taxes
- partial payment
- credit sale
- returns
- refunds
- customer balance
- invoice PDF
- payment allocation

Use Decimal for all money.

---

# 16. Module 6 — Purchasing

Workflow:

```text
Purchase Request
   ↓
Purchase Order
   ↓
Goods Receipt
   ↓
Supplier Bill
   ↓
Payment
```

Receiving goods must affect inventory.

Supplier bills must affect Accounts Payable.

Support:

- purchase order states
- partial receipt
- full receipt
- supplier returns
- supplier bill
- partial payment
- full payment

---

# 17. Module 7 — POS

The POS should support:

- fast product search
- barcode scanning
- cart
- quantity editing
- discounts
- VAT
- customer assignment
- cash payment
- card payment
- mobile payment
- split payment
- receipt
- hold/resume sale
- returns
- partial refunds
- full refunds

Checkout transaction may involve:

```text
Sale
SaleLine
InventoryMovement
Payment
VAT
JournalEntry
Receipt
AuditEvent
```

Critical parts must be atomic.

If one critical step fails, the transaction must roll back.

Use idempotency keys.

---

# 18. Module 8 — Accounting

Implement genuine double-entry bookkeeping.

Core entities:

- Account
- ChartOfAccount
- Journal
- JournalEntry
- JournalEntryLine
- FiscalPeriod
- Payment
- PaymentAllocation
- AccountsReceivable
- AccountsPayable
- Reversal

Account types:

```text
ASSET
LIABILITY
EQUITY
REVENUE
EXPENSE
```

Fundamental invariant:

```text
SUM(DEBITS) == SUM(CREDITS)
```

for every posted journal entry.

Posted entries cannot be edited directly.

Corrections must use reversal entries.

Example cash sale:

```text
Cash / Bank             DR
    Sales Revenue              CR
    VAT Payable                CR
```

Cost recognition:

```text
Cost of Goods Sold      DR
    Inventory                  CR
```

Reports:

- Trial Balance
- General Ledger
- Profit & Loss
- Balance Sheet
- Accounts Receivable Aging
- Accounts Payable Aging

Accounting correctness is more important than UI complexity.

---

# 19. Module 9 — CRM

Entities:

- Lead
- Opportunity
- Activity
- Note

Pipeline:

```text
NEW
CONTACTED
QUALIFIED
PROPOSAL
WON
LOST
```

Allow activities:

- call
- email
- meeting
- follow-up

Support conversion from lead/opportunity to customer where appropriate.

---

# 20. Module 10 — VAT

Start with a generic configurable VAT subsystem.

Do **NOT** claim NBR or Bangladesh regulatory compliance unless rules are independently verified.

Support:

- product VAT rate
- tax category
- VAT-inclusive pricing
- VAT-exclusive pricing
- input VAT
- output VAT
- tax invoice
- VAT summary
- VAT reports
- rounding policy

Design the VAT subsystem so Bangladesh-specific Mushak functionality can later be added without rewriting the accounting core.

---

# 21. Module 11 — Reporting

Dashboard should include:

- Revenue
- Gross Profit
- Net Profit
- Expenses
- Receivables
- Payables
- Inventory Value
- Top Products
- Sales Trends
- Branch Performance
- Low Stock
- Refund Trends

Reports must:

- enforce tenant scope
- enforce permissions
- support date filters
- avoid unbounded queries
- use database-side aggregation where appropriate

---

# 22. Module 12 — AI Business Copilot

Users should be able to ask:

```text
Why did profit decrease this month?

Which products are nearly out of stock?

Which customers owe us the most?

Compare Branch A and Branch B.

What were our highest expenses this month?
```

The AI MUST NOT have unrestricted SQL access.

Preferred architecture:

```text
User
 ↓
AI Router
 ↓
Permission Check
 ↓
Whitelisted Analytics Tool
 ↓
Tenant-Scoped Database Query
 ↓
Structured JSON
 ↓
LLM Explanation
```

Approved tool examples:

```text
get_sales_summary()
get_profit_summary()
get_inventory_summary()
get_customer_receivables()
get_supplier_payables()
get_branch_comparison()
get_product_performance()
get_expense_summary()
```

Every tool must:

- derive tenant from authenticated context
- verify user permission
- validate date range
- query only required information
- return structured data
- never leak other tenant data

The LLM should explain validated data.

The LLM must not invent business numbers.

---

# 23. Module 13 — Tenant-Isolated RAG

Businesses may upload:

- company policies
- HR manuals
- supplier contracts
- SOPs
- product manuals
- internal guidelines
- VAT guidance
- operational documents

Pipeline:

```text
Upload
 ↓
Validate
 ↓
Extract
 ↓
Chunk
 ↓
Embed
 ↓
Tenant-Scoped Vector Index
 ↓
Retrieve
 ↓
Rerank if justified
 ↓
LLM
 ↓
Answer + Citations
```

Security rules:

- document belongs to tenant
- chunks inherit tenant
- embeddings/vectors carry tenant metadata
- retrieval filters by tenant
- citations only link to authorized source
- optionally support document-level ACL inside a tenant
- malicious document content must not override system/tool policies

Add adversarial tests proving Tenant B cannot retrieve Tenant A chunks.

---

# 24. Module 14 — Forecasting

Provide product demand forecasting.

Start with interpretable baselines.

Possible models:

- naive previous-period baseline
- moving average
- exponential smoothing
- regression
- lightweight time-series models

Use chronological backtesting.

Metrics:

- MAE
- RMSE
- MAPE only where mathematically appropriate

Do not use a complex model unless it beats a naive baseline.

Every forecasting feature should clearly distinguish:

- historical actuals
- forecast
- uncertainty/limitations

---

# 25. Module 15 — Anomaly Detection

Detect anomalies such as:

- unusual refund count
- abnormal discount
- unusual expense
- sudden revenue drop
- suspicious stock adjustment
- abnormal return rate

Start with explainable baselines.

Methods may include:

- rolling thresholds
- z-score
- robust statistics
- Isolation Forest

Each alert should contain:

- observed value
- baseline/expected range
- deviation
- reason
- severity
- timestamp
- tenant
- relevant branch/user/resource when allowed

Avoid opaque black-box alerts.

---

# 26. Security Requirements

Threat model includes:

1. unauthenticated external attacker
2. malicious tenant
3. malicious employee
4. compromised cashier
5. compromised manager
6. malicious uploaded file
7. malicious RAG document
8. prompt injection
9. replayed checkout/payment request
10. IDOR/BOLA
11. enumeration attacks
12. race conditions

Protect against:

- cross-tenant access
- broken object-level authorization
- IDOR
- SQL injection
- XSS
- CSRF where relevant
- mass assignment
- insecure direct object access
- secret leakage
- unsafe file upload
- brute force
- replay attack
- duplicate checkout
- privilege escalation

File uploads must:

- validate MIME
- validate extension
- enforce size limit
- randomize stored filename
- never trust original filename
- provide a virus scanning integration point if feasible

Never log:

- password
- access token
- refresh token
- API key
- payment secret
- sensitive credentials

---

# 27. Database Requirements

Use:

- UUID primary keys where appropriate
- `created_at`
- `updated_at`
- `tenant_id` where appropriate
- foreign keys
- unique constraints
- check constraints
- deliberate indexes

Likely indexes:

```text
tenant_id
tenant_id + created_at
tenant_id + status
tenant_id + product_id
tenant_id + customer_id
tenant_id + supplier_id
tenant_id + invoice_number
tenant_id + warehouse_id
```

Examples of useful constraints:

- tenant-unique SKU
- tenant-unique invoice number
- positive quantities
- valid monetary values
- foreign key integrity
- valid state transitions in application layer
- balanced journals before posting

---

# 28. Transaction Requirements

Critical workflows must use database transactions.

Examples:

- complete POS sale
- receive purchase
- create invoice
- post payment
- stock transfer
- refund
- journal posting
- sales return
- supplier payment
- customer payment

Avoid partially completed business operations.

---

# 29. Idempotency

Use idempotency protection for operations vulnerable to retries.

Examples:

- POS checkout
- payment creation
- refund processing
- invoice creation when triggered remotely
- webhook handling
- external payment confirmation

Same idempotency key + same request should return the prior result.

Same idempotency key + materially different payload should fail safely.

---

# 30. API Requirements

Use versioned REST APIs.

Example:

```text
/api/v1/auth
/api/v1/tenants
/api/v1/branches
/api/v1/products
/api/v1/inventory
/api/v1/customers
/api/v1/suppliers
/api/v1/sales
/api/v1/purchases
/api/v1/pos
/api/v1/accounting
/api/v1/crm
/api/v1/vat
/api/v1/reports
/api/v1/ai
/api/v1/documents
```

Use predictable pagination.

Do not return unlimited lists.

Use a consistent error shape, e.g.:

```json
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Insufficient inventory.",
    "details": {}
  }
}
```

---

# 31. Observability

Implement:

- structured logging
- request/correlation IDs
- health endpoint
- readiness endpoint
- metrics
- error tracking integration interface
- meaningful domain event logs

Potential endpoints:

```text
/health
/ready
/metrics
```

Do not leak sensitive data in logs.

---

# 32. Frontend Requirements

Create a professional B2B UI.

Main navigation:

```text
Dashboard
POS
Sales
Purchases
Inventory
Products
Customers
Suppliers
Accounting
CRM
Reports
AI Assistant
Documents
Settings
```

Requirements:

- responsive
- accessible
- fast
- loading states
- empty states
- error states
- confirmation for destructive actions
- pagination
- filtering
- search
- keyboard-friendly POS
- clean business tables
- clear permissions handling
- no excessive animation

Focus on productivity.

---

# 33. Testing Requirements

High-priority backend tests:

- authentication
- refresh token behavior
- tenant creation
- membership
- RBAC
- tenant isolation
- inventory movement
- stock reservation
- stock transfer
- POS transaction
- sale return
- purchase receipt
- journal balancing
- payment allocation
- refund
- idempotency
- audit events

Required cross-tenant test:

```text
Tenant A creates Product A.

Tenant B attempts:

GET Product A
UPDATE Product A
DELETE Product A

All must fail.
```

Accounting test:

```text
Debit = 100
Credit = 90

Posting MUST fail.
```

Inventory test:

```text
Stock = 5

Attempt sale quantity = 7

Sale MUST fail
unless negative inventory is explicitly enabled.
```

Concurrency test:

```text
Available stock = 1

Two concurrent checkouts request quantity 1.

Only one checkout may succeed.
```

Idempotency test:

```text
Send checkout request twice with same idempotency key.

Only one sale/payment/stock movement must exist.
```

---

# 34. CI/CD

GitHub Actions should run:

- backend formatting/lint
- backend tests
- backend type checks where configured
- frontend lint
- frontend typecheck
- frontend tests
- production frontend build
- migration validation
- optional E2E smoke test

Critical checks must block merge.

---

# 35. Docker

Development Docker Compose should provide:

```text
frontend
backend
postgres
redis
qdrant
object-storage
```

Add only services actually used.

Provide:

```text
.env.example
```

Never commit secrets.

---

# 36. Documentation

Maintain:

```text
README.md
docs/ARCHITECTURE.md
docs/DATABASE.md
docs/API.md
docs/ACCOUNTING.md
docs/SECURITY.md
docs/AI.md
docs/DECISIONS.md
docs/ROADMAP.md
docs/AGENT_HANDOFF.md
```

Use lightweight ADRs in `docs/DECISIONS.md` or a dedicated ADR directory.

Document why important choices were made.

---

# 37. Code Quality Rules

Prioritize:

- clarity
- correctness
- typing
- testability
- maintainability
- modularity

Avoid:

- god classes
- giant service files
- duplicate logic
- premature abstractions
- unnecessary microservices
- generic `utils` dumping grounds
- unrelated refactors
- secret hardcoding
- TODO placeholders for core behavior
- mock production behavior

---

# 38. Definition of Done

A feature is complete only when:

1. domain model is correct
2. migration exists where required
3. repository/data access exists
4. service/business logic exists
5. authorization is enforced
6. tenant isolation is enforced
7. API exists
8. UI exists where required
9. validation exists
10. error states are handled
11. tests exist
12. audit logging exists where appropriate
13. documentation is updated
14. format/lint/typecheck/tests pass
15. production build passes where relevant

UI-only completion is not completion.

---

# 39. Project Roadmap

Use this roadmap:

```text
Phase 0  — Architecture
Phase 1  — Foundation: Auth + Tenancy + RBAC + Audit
Phase 2  — Product Catalog + Inventory
Phase 3  — Customers + Suppliers + Sales + Purchase
Phase 4  — POS
Phase 5  — Accounting
Phase 6  — CRM + Reporting
Phase 7  — VAT
Phase 8  — AI Business Copilot
Phase 9  — RAG
Phase 10 — Forecasting + Anomaly Detection
Phase 11 — Security Hardening
Phase 12 — Production Deployment
```

Do not start a major downstream phase while unresolved P0/P1 defects remain in a dependency phase.

---

# 40. Claude CLI Global Prompt

Claude should operate under the following permanent instruction:

```text
You are the lead software architect and senior reviewer for Nexora AI.

Read prompt.md and docs/AGENT_HANDOFF.md completely before meaningful work.

Also read the relevant architecture documents:
- docs/ARCHITECTURE.md
- docs/DATABASE.md
- docs/API.md
- docs/ACCOUNTING.md
- docs/SECURITY.md
- docs/AI.md
- docs/DECISIONS.md

Your primary responsibilities are:

1. architecture
2. domain modeling
3. database modeling
4. API design
5. business rules
6. security design
7. accounting correctness
8. inventory correctness
9. multi-tenant correctness
10. reviewing implementations produced by Codex
11. identifying architectural debt before it spreads
12. creating precise implementation handoffs

Do NOT immediately write large amounts of production code.

For each task:

STEP 1:
Inspect relevant existing code.

STEP 2:
Summarize current implementation briefly.

STEP 3:
Define:
- requirements
- invariants
- data model
- constraints
- authorization rules
- tenant rules
- edge cases
- transaction boundaries
- concurrency concerns
- idempotency concerns
- API contracts
- testing requirements

STEP 4:
Update architectural documentation where necessary.

STEP 5:
Create a clear implementation handoff for Codex.

Only directly modify substantial production code if explicitly instructed or if a small architectural foundation fix is necessary.

IMPORTANT RULES:

Do not rewrite working components without justification.

Do not introduce microservices.

Do not weaken tenant isolation.

Do not put business logic inside route handlers.

Do not use floats for money.

Do not allow posted accounting entries to be mutated.

Do not let LLMs execute arbitrary SQL.

Do not trust client-provided tenant IDs.

Always consider race conditions for:
- stock
- checkout
- payments
- numbering sequences
- refunds

When reviewing Codex changes, classify findings:

P0 — security breach, data corruption, accounting corruption, tenant leakage
P1 — serious correctness or production reliability issue
P2 — maintainability, performance, test gap, or moderate design issue
P3 — minor improvement

For every finding provide:
- severity
- file
- approximate location
- issue
- impact
- recommended fix

Do not approve a phase if P0 or P1 issues remain.

At the end of design/review work produce:

IMPLEMENTATION HANDOFF FOR CODEX

including:
- goal
- files to create
- files to modify
- models
- migrations
- constraints
- endpoints
- services
- permissions
- audit events
- tests
- edge cases
- acceptance criteria
- commands to verify

Update docs/AGENT_HANDOFF.md.

Treat Nexora AI as a real SaaS product handling business and financial data.
```

---

# 41. Codex Global Prompt

Codex should operate under the following permanent instruction:

```text
You are the senior implementation engineer for Nexora AI.

Before making meaningful changes:

1. Read prompt.md
2. Read docs/AGENT_HANDOFF.md
3. Read docs/ARCHITECTURE.md
4. Read docs/DATABASE.md
5. Read docs/API.md
6. Read docs/ACCOUNTING.md when relevant
7. Read docs/SECURITY.md
8. Read docs/AI.md when relevant
9. Read docs/DECISIONS.md
10. Inspect existing repository code
11. Read Claude's current implementation handoff

Do not redesign architecture unless you discover a critical inconsistency.

If the handoff conflicts with current architecture:
STOP and explain the conflict instead of silently inventing another design.

Your job is to implement the requested feature completely.

Every implementation must consider:

- tenant isolation
- authorization
- input validation
- database constraints
- transaction boundaries
- concurrency
- idempotency
- audit logging
- error handling
- tests
- typing
- migration safety
- documentation

Do not leave TODO placeholders for core functionality.

Do not use mock behavior in production code.

Do not hardcode tenant IDs, user IDs, secrets, roles, or sample business values.

Do not use floating point for monetary values.

Use Decimal / database NUMERIC.

Do not directly update inventory quantities outside the approved inventory architecture.

Do not create or post unbalanced accounting entries.

Do not execute arbitrary LLM-generated SQL.

Never bypass authorization because an endpoint is "internal".

IMPLEMENTATION PROCESS:

1. Inspect.
2. Summarize implementation plan briefly.
3. Implement domain model.
4. Add migration.
5. Add constraints/indexes.
6. Implement repository/data access.
7. Implement service/domain logic.
8. Implement API.
9. Implement frontend where required.
10. Add unit tests.
11. Add integration tests.
12. Add tenant-isolation tests.
13. Add authorization tests.
14. Add concurrency/idempotency tests where relevant.
15. Run formatters.
16. Run linters.
17. Run type checks.
18. Run tests.
19. Run production build where relevant.
20. Update documentation.
21. Update docs/AGENT_HANDOFF.md.
22. Summarize results.

When a command fails:
investigate the cause.
Do not disable validation just to make CI green.

At completion return:

IMPLEMENTED
- ...

DATABASE CHANGES
- ...

API CHANGES
- ...

SECURITY CONSIDERATIONS
- ...

TESTS ADDED
- ...

COMMANDS RUN
- ...

KNOWN LIMITATIONS
- ...

CLAUDE REVIEW REQUEST
- ...

Do not claim completion unless verification actually passes.
```

---

# 42. Phase 0 — Claude Prompt

Run this first with Claude:

```text
We are starting Phase 0 of Nexora AI.

Read prompt.md completely.

Do not implement application features yet.

Design the production-oriented architecture for a modular monolith.

Establish:

1. repository / monorepo structure
2. backend module boundaries
3. frontend architecture
4. PostgreSQL architecture
5. multi-tenancy strategy
6. authentication architecture
7. refresh-token/session strategy
8. RBAC architecture
9. tenant context propagation
10. audit architecture
11. error handling architecture
12. transaction strategy
13. idempotency strategy
14. background job strategy
15. object storage strategy
16. Redis usage
17. Qdrant tenant isolation
18. logging/observability
19. test architecture
20. Docker development architecture
21. CI architecture
22. ADR process

Pay special attention to:

- preventing cross-tenant data access
- avoiding domain coupling
- accounting transactional requirements
- inventory concurrency
- future scalability without premature microservices
- financial-data correctness
- safe AI integration

Create/update:

docs/ARCHITECTURE.md
docs/DATABASE.md
docs/API.md
docs/SECURITY.md
docs/AI.md
docs/DECISIONS.md
docs/ROADMAP.md
docs/AGENT_HANDOFF.md

Then generate a precise Phase 1 implementation handoff for Codex.

Do not build Phase 1 yet.
```

---

# 43. Phase 1 — Codex Prompt

```text
Implement Nexora AI Phase 1 based strictly on prompt.md, architecture documents,
and Claude's current handoff.

PHASE 1: PLATFORM FOUNDATION

Backend:
- FastAPI application structure
- configuration management
- PostgreSQL connection
- SQLAlchemy
- Alembic
- structured error handling
- request correlation IDs
- health endpoint
- readiness endpoint

Authentication:
- user registration
- secure password hashing
- login
- access token
- refresh token
- logout/revocation structure
- forgot-password structure
- email-verification structure

Multi-tenancy:
- Tenant
- Membership
- Branch
- tenant context
- tenant middleware/dependency
- organization creation

RBAC:
- Role
- Permission
- role-permission mapping
- membership role assignment
- authorization service/dependency

Audit:
- AuditEvent
- audit service
- audit generation for sensitive operations

Frontend:
- Next.js app
- authentication pages
- organization creation
- organization switcher if architecture supports it
- base dashboard layout
- navigation shell
- branch management UI
- membership/user management foundation

DevOps:
- Docker Compose
- PostgreSQL
- Redis
- backend
- frontend
- .env.example

Required tests:

1. user registration/login
2. password security behavior
3. tenant creation
4. membership creation
5. Tenant A cannot access Tenant B
6. role permission denial
7. branch tenant isolation
8. audit generation
9. refresh token invalidation/revocation behavior

Do not implement ERP business modules yet.

Run all verification commands and report actual results.

Update docs/AGENT_HANDOFF.md.
```

---

# 44. Phase 1 — Claude Review Prompt

```text
Review Codex's Phase 1 implementation.

Do not start Phase 2.

Perform an architecture, security, tenancy and maintainability review.

Specifically inspect/test:

- cross-tenant access
- IDOR/BOLA
- role escalation
- tenant context derivation
- authorization placement
- JWT/refresh design
- password handling
- secrets handling
- error information leakage
- audit logging
- transaction boundaries
- database constraints
- indexes
- migration quality
- frontend authentication assumptions
- test quality

Classify findings P0/P1/P2/P3.

Where practical, run tests.

Finish with a concrete FIX HANDOFF FOR CODEX.

Do not approve Phase 1 if P0 or P1 findings remain.

Update docs/AGENT_HANDOFF.md.
```

---

# 45. Generic Codex Fix Prompt

After a Claude review:

```text
Read Claude's latest review and docs/AGENT_HANDOFF.md.

Fix all P0 and P1 findings first.

Then fix justified P2 findings that are in scope.

Do not perform unrelated refactors.

For every fix:
- preserve architecture
- add/update tests reproducing the defect
- verify tenant boundaries
- verify authorization
- verify migrations if affected

Run:
- formatting
- lint
- typecheck
- backend tests
- frontend tests
- production build where relevant

Update docs/AGENT_HANDOFF.md.

Report each review finding as:
FIXED / NOT FIXED / DEFERRED WITH REASON.
```

---

# 46. Phase 2 — Claude Design Prompt

```text
Design Nexora AI Phase 2:

PRODUCT CATALOG + INVENTORY.

Do not implement it yet.

Design:

Product
ProductVariant if necessary
Category
Brand
UnitOfMeasure
Barcode
Warehouse
InventoryMovement
InventoryBalance/materialized balance strategy
StockReservation
StockAdjustment
StockTransfer

Define inventory invariants.

Address concurrency explicitly.

Example problem:

Two POS terminals simultaneously attempt to purchase the final item.

Design a solution preventing incorrect negative inventory.

Define:

- models
- constraints
- indexes
- transaction boundaries
- locking/concurrency strategy
- API
- permissions
- audit events
- tests
- pagination/search strategy

Inventory movement ledger must be source of truth.

Produce a precise Codex implementation handoff.

Update docs/AGENT_HANDOFF.md.
```

---

# 47. Phase 2 — Codex Implementation Prompt

```text
Implement Nexora AI Phase 2 according to prompt.md and Claude's approved handoff.

Implement:

- Product Catalog
- Categories
- Brands
- Units of Measure
- SKU/barcode support
- Warehouses
- Inventory movement ledger
- Stock adjustments
- Stock transfers
- Stock reservations
- Stock availability calculations
- Low-stock configuration
- Audit events
- Backend APIs
- Frontend catalog/inventory interfaces

Add concurrency-safe inventory operations.

Required tests:

- cross-tenant product access
- cross-tenant warehouse access
- stock in
- stock out
- transfer
- adjustment
- reservation
- reservation release
- insufficient inventory
- concurrent inventory consumption
- tenant-unique SKU/barcode constraints
- audit events

Run full verification.

Update docs/AGENT_HANDOFF.md.
```

---

# 48. Phase 3 — Claude Design Prompt

```text
Design Nexora AI Phase 3.

Domains:

Customers
Suppliers
Quotation
SalesOrder
Fulfillment
Invoice
Payment
PurchaseOrder
GoodsReceipt
SupplierBill

Map explicit state machines.

Define legal transitions.

Define:

- transaction boundaries
- inventory impacts
- AR/AP impacts
- audit events
- permissions
- numbering schemes
- idempotency requirements
- cancellation behavior
- returns
- partial payment behavior
- partial receipt behavior
- tests

Avoid invalid shortcuts between states.

Produce Codex implementation handoff.

Update docs/AGENT_HANDOFF.md.
```

---

# 49. Phase 3 — Codex Implementation Prompt

```text
Implement Phase 3 using Claude's approved design.

Implement:

Customers
Suppliers
Quotations
Sales Orders
Fulfillment
Invoices
Payments
Purchase Orders
Goods Receipts
Supplier Bills

Requirements:

- explicit state machines
- tenant isolation
- RBAC
- transactional updates
- Decimal money
- numbering rules
- partial payment support
- partial receipt support
- inventory integration
- audit events
- pagination/filtering
- frontend management screens

Add integration tests for complete sales and purchase workflows.

Run full verification.

Update docs/AGENT_HANDOFF.md.
```

---

# 50. Phase 4 — Claude POS Design Prompt

```text
Design the Nexora AI POS domain as a transactionally correct system.

A POS checkout can involve:

Sale
SaleLine
InventoryMovement
Payment
VAT
JournalEntry
Receipt
AuditEvent

Determine what must happen atomically.

Design:

- idempotency
- concurrent checkout protection
- barcode lookup
- cart
- customer assignment
- discounts
- VAT
- cash
- card
- mobile payment
- split payment
- hold/resume
- receipt
- returns
- full refund
- partial refund
- failure rollback
- cashier permissions
- branch/warehouse binding

Create a detailed test matrix.

Do not implement.

Produce Codex handoff.

Update docs/AGENT_HANDOFF.md.
```

---

# 51. Phase 4 — Codex POS Implementation Prompt

```text
Implement Phase 4 POS using Claude's approved specification.

Focus on correctness before UI polish.

POS UI should be keyboard friendly.

Implement:

- product/barcode search
- cart
- customer selection
- quantity
- discounts
- VAT
- payments
- split payments
- checkout
- receipt
- hold/resume
- returns
- refunds

Checkout must be idempotent and transactional.

Write integration tests proving that failed checkout cannot partially:

- reduce inventory
- create payment
- create sale
- create accounting record
- create VAT record

Also test:

- duplicate checkout requests
- same idempotency key
- concurrent final-item purchase
- cross-tenant checkout attack
- unauthorized refund
- partial refund

Run full verification.

Update docs/AGENT_HANDOFF.md.
```

---

# 52. Phase 5 — Claude Accounting Design Prompt

```text
Design Nexora AI's accounting subsystem.

Treat accounting correctness as a critical financial invariant.

Design:

ChartOfAccount
Account
Journal
JournalEntry
JournalEntryLine
FiscalPeriod
Receivable
Payable
PaymentAllocation
Reversal

Support:

General Ledger
Trial Balance
Profit & Loss
Balance Sheet
AR Aging
AP Aging

Fundamental rule:

SUM(debit) = SUM(credit)

for every posted journal entry.

Design automatic journal mappings for:

- cash sale
- credit sale
- inventory sale
- purchase
- supplier payment
- customer payment
- expense
- refund
- sales return
- purchase return

Posted entries cannot be edited directly.

Corrections must use reversal entries.

Design database protections in addition to application validation where feasible.

Define:

- account types
- posting rules
- fiscal periods
- closed-period behavior
- currency assumptions
- rounding rules
- COGS treatment
- inventory valuation assumptions
- reversal semantics
- test matrix

Explain accounting assumptions explicitly.

Produce a complete Codex implementation plan.

Do not implement before resolving ambiguity.

Update docs/ACCOUNTING.md and docs/AGENT_HANDOFF.md.
```

---

# 53. Phase 5 — Codex Accounting Implementation Prompt

```text
Implement the accounting subsystem strictly from Claude's approved design.

Implement:

- Chart of Accounts
- Accounts
- Journals
- Journal Entries
- Journal Lines
- Fiscal Periods
- Receivables
- Payables
- Payment Allocations
- Reversals
- General Ledger
- Trial Balance
- Profit & Loss
- Balance Sheet
- AR Aging
- AP Aging

Requirements:

- Decimal/NUMERIC only
- posted journals immutable
- debit == credit before posting
- reversal instead of destructive edit
- tenant isolation
- RBAC
- audit events
- transaction safety

Add accounting integration with approved sales/purchase/POS events.

Required tests include:

- balanced posting succeeds
- unbalanced posting fails
- posted journal cannot be edited
- reversal works
- cash sale posting
- credit sale posting
- purchase posting
- refund posting
- tenant isolation
- permission denial

Run all verification.

Update docs/AGENT_HANDOFF.md.
```

---

# 54. Phase 6 — CRM + Reporting Prompt

Claude should design report permissions/queries first if needed, then Codex implements.

Codex implementation target:

```text
Implement approved CRM and reporting architecture.

CRM:
- leads
- opportunities
- activities
- pipeline
- notes
- conversion to customer

Reports:
- sales trends
- gross profit
- net profit
- expenses
- receivables
- payables
- inventory valuation
- branch performance
- product performance
- low-stock
- refund trends

Requirements:

- tenant scoped
- permission aware
- date filters
- pagination where appropriate
- database-side aggregation
- reasonable indexes
- no loading huge raw datasets into application memory

Add tests for report isolation and authorization.

Update docs/AGENT_HANDOFF.md.
```

---

# 55. Phase 7 — VAT Prompt

```text
Design and implement a configurable VAT subsystem.

Do NOT claim Bangladesh regulatory or NBR compliance.

Build the technical foundation for:

- VAT rate configuration
- tax categories
- VAT-exclusive price
- VAT-inclusive price
- input VAT
- output VAT
- sales tax invoice
- VAT summary
- VAT reports
- purchase VAT
- sale returns
- purchase returns

Keep regulatory-specific reporting isolated so verified Bangladesh Mushak support
can later be introduced without rewriting the accounting core.

VAT calculations must use Decimal.

Document rounding policy.

Required tests:

- inclusive VAT
- exclusive VAT
- zero-rated item
- mixed VAT rates
- discounts under defined policy
- sale return
- purchase return
- tenant isolation

Update docs/AGENT_HANDOFF.md.
```

---

# 56. Phase 8 — Claude AI Copilot Design Prompt

```text
Design the Nexora AI Business Copilot.

Critical constraint:

The LLM must NOT have unrestricted SQL execution.

Use an approved-tool architecture.

Examples:

get_sales_summary
get_profit_summary
get_inventory_status
get_receivables
get_payables
compare_branches
get_top_products
get_expense_summary

Every tool must:

- derive tenant context from authenticated user
- check permission
- validate input
- enforce bounded date range
- query only necessary information
- return structured JSON

The LLM turns structured results into explanations.

Design protection against:

- prompt injection
- cross-tenant data exposure
- tool abuse
- huge date-range abuse
- hallucinated metrics
- unauthorized branch access
- indirect attempts to retrieve restricted accounting data

Numbers shown to users must originate from validated tools.

Produce implementation handoff.

Update docs/AI.md and docs/AGENT_HANDOFF.md.
```

---

# 57. Phase 8 — Codex AI Copilot Implementation Prompt

```text
Implement the AI Business Copilot exactly according to Claude's approved tool architecture.

Requirements:

- no arbitrary SQL
- whitelisted tools only
- tenant context derived from auth
- permission checks per tool
- structured tool outputs
- bounded date ranges
- safe error handling
- model/provider abstraction
- traceable tool execution
- no financial-number hallucination

Implement a professional frontend chat/analysis interface.

Add tests for:

- cross-tenant tool access
- unauthorized financial tool access
- prompt asking for another company's data
- invalid date range
- tool parameter validation
- AI response grounded in tool result
- safe handling when data is unavailable

Update docs/AGENT_HANDOFF.md.
```

---

# 58. Phase 9 — Claude RAG Design Prompt

```text
Design tenant-isolated RAG for business documents.

Requirements:

documents belong to tenant
chunks belong to tenant
vectors belong to tenant
retrieval enforces tenant
citations link to source
document permission can optionally be narrower than tenant

Pipeline:

upload
validate
extract
chunk
embed
index
retrieve
rerank if justified
generate
cite

Threat-model prompt injection contained within uploaded documents.

Design:

- document model
- chunk metadata
- vector metadata
- tenant filters
- ACL if used
- upload validation
- citation structure
- deletion/reindex behavior
- background indexing
- retrieval test strategy

Design tests proving Tenant B cannot retrieve Tenant A embeddings/chunks.

Produce Codex handoff.

Update docs/AI.md, docs/SECURITY.md and docs/AGENT_HANDOFF.md.
```

---

# 59. Phase 9 — Codex RAG Implementation Prompt

```text
Implement tenant-isolated RAG based on Claude's approved design.

Implement:

- document upload
- validation
- object storage
- extraction pipeline
- chunking
- embeddings
- Qdrant indexing
- tenant metadata
- tenant-filtered retrieval
- optional reranking if approved
- answer generation
- citations
- deletion/reindex
- frontend document manager
- frontend RAG chat

Add adversarial tests for:

- Tenant B searching Tenant A document content
- manipulated metadata
- unauthorized document access
- malicious prompt inside uploaded document
- citation access control

Run full verification.

Update docs/AGENT_HANDOFF.md.
```

---

# 60. Phase 10 — Forecasting Prompt

```text
Build demand forecasting for products.

Start with:

- naive previous-period baseline
- moving average
- exponential smoothing
- simple ML model where justified

Backtest chronologically.

Report:

- MAE
- RMSE
- MAPE where appropriate

Only deploy a more complex model if it beats the naive baseline.

Forecasting must be tenant scoped.

Support:

- product
- branch/warehouse where appropriate
- date horizon
- confidence/limitations messaging

Do not label weak heuristics as advanced AI.

Add tests and evaluation notebooks/scripts as appropriate.

Update docs/AI.md and docs/AGENT_HANDOFF.md.
```

---

# 61. Phase 10 — Anomaly Detection Prompt

```text
Build explainable anomaly detection for:

- refunds
- discounts
- expenses
- sales
- stock adjustments

Start with statistical baselines.

Optionally compare Isolation Forest.

Every anomaly must include:

- observed value
- expected baseline
- deviation
- reason
- severity
- timestamp

Evaluate false positives on synthetic/seeded scenarios.

Tenant isolation is mandatory.

Do not generate opaque alerts without explanation.

Update docs/AI.md and docs/AGENT_HANDOFF.md.
```

---

# 62. Phase 11 — Claude Security Review Prompt

```text
Perform a pre-production security review of Nexora AI.

Threat model:

1. external unauthenticated attacker
2. malicious employee
3. malicious tenant
4. compromised cashier account
5. compromised manager account
6. malicious uploaded document
7. prompt injection
8. replayed payment/POS requests
9. enumeration attacks
10. race conditions

Audit:

- authentication
- authorization
- tenant isolation
- IDOR/BOLA
- RBAC
- rate limits
- file uploads
- SQL queries
- AI tools
- RAG
- XSS
- CSRF
- CORS
- secrets
- logging
- Docker
- database
- Redis
- object storage
- Qdrant
- audit trail
- idempotency
- financial integrity
- inventory concurrency

Find actual code-level issues.

Classify P0/P1/P2/P3.

Generate a precise Codex remediation handoff.

Do not approve production readiness while P0/P1 findings remain.

Update docs/SECURITY.md and docs/AGENT_HANDOFF.md.
```

---

# 63. Phase 12 — Production Deployment

Production readiness should include:

- production Docker configuration
- environment separation
- secure secret handling
- HTTPS assumptions
- reverse proxy/load balancer compatibility
- PostgreSQL backups
- migration process
- Redis configuration
- Qdrant persistence
- object storage
- health/readiness
- structured logs
- metrics
- error tracking
- dependency scanning
- CI/CD release flow
- rollback plan
- seeded demo tenant
- production README
- smoke tests

Do not hardcode infrastructure credentials.

Document deployment choices clearly.

---

# 64. Git Strategy

Keep Git workflow simple:

```text
main
  ↑
develop
  ↑
feature/*
```

Example branches:

```text
feature/auth-foundation
feature/multi-tenancy
feature/catalog
feature/inventory
feature/sales
feature/purchases
feature/pos
feature/accounting
feature/crm
feature/vat
feature/ai-copilot
feature/rag
feature/forecasting
feature/anomaly-detection
```

Commit examples:

```text
feat(auth): implement refresh token rotation

feat(inventory): add immutable stock movement ledger

feat(pos): add idempotent checkout workflow

feat(accounting): implement balanced journal posting

test(tenancy): prevent cross-tenant product access

fix(pos): prevent concurrent overselling

docs(accounting): document journal posting rules
```

---

# 65. ROADMAP.md Template

Create `docs/ROADMAP.md`:

```markdown
# Nexora AI Roadmap

## Phase 0 — Architecture
- [ ] Repository structure
- [ ] Backend architecture
- [ ] Frontend architecture
- [ ] Database architecture
- [ ] Security architecture
- [ ] AI architecture
- [ ] CI/Docker design

## Phase 1 — Foundation
- [ ] Authentication
- [ ] Tenant
- [ ] Branch
- [ ] Membership
- [ ] RBAC
- [ ] Audit

## Phase 2 — Catalog + Inventory
- [ ] Products
- [ ] Categories
- [ ] Brands
- [ ] Warehouses
- [ ] Stock Ledger
- [ ] Reservations
- [ ] Transfers
- [ ] Adjustments

## Phase 3 — Sales + Purchase
- [ ] Customers
- [ ] Suppliers
- [ ] Quotations
- [ ] Sales Orders
- [ ] Invoices
- [ ] Payments
- [ ] Purchase Orders
- [ ] Goods Receipts
- [ ] Supplier Bills

## Phase 4 — POS
- [ ] Cart
- [ ] Barcode Search
- [ ] Checkout
- [ ] Split Payments
- [ ] Receipt
- [ ] Hold/Resume
- [ ] Returns
- [ ] Refunds

## Phase 5 — Accounting
- [ ] Chart of Accounts
- [ ] Journal
- [ ] General Ledger
- [ ] Trial Balance
- [ ] P&L
- [ ] Balance Sheet
- [ ] AR
- [ ] AP
- [ ] Reversals

## Phase 6 — CRM + Reporting
- [ ] CRM
- [ ] Sales Reports
- [ ] Profit Reports
- [ ] Inventory Reports
- [ ] Branch Reports

## Phase 7 — VAT
- [ ] Tax Categories
- [ ] Input VAT
- [ ] Output VAT
- [ ] VAT Reports

## Phase 8 — AI Copilot
- [ ] Tool Router
- [ ] Safe Analytics Tools
- [ ] Permissions
- [ ] Chat UI

## Phase 9 — RAG
- [ ] Upload
- [ ] Extraction
- [ ] Chunking
- [ ] Embeddings
- [ ] Retrieval
- [ ] Citations

## Phase 10 — ML Intelligence
- [ ] Forecasting
- [ ] Evaluation
- [ ] Anomaly Detection
- [ ] Alert Explanations

## Phase 11 — Security Hardening
- [ ] Tenant attack tests
- [ ] IDOR/BOLA review
- [ ] File upload hardening
- [ ] AI/RAG prompt injection review
- [ ] Dependency review
- [ ] Rate limiting

## Phase 12 — Production
- [ ] Production Docker
- [ ] CI/CD
- [ ] Backup plan
- [ ] Metrics
- [ ] Error tracking
- [ ] Deployment docs
```

---

# 66. Suggested Root `CLAUDE.md`

If using Claude Code/CLI, create a root `CLAUDE.md` with:

```markdown
# Nexora AI Development Rules

Always read:

- prompt.md
- docs/ARCHITECTURE.md
- docs/AGENT_HANDOFF.md

before significant work.

## Architecture

This is a modular monolith.

Do not introduce microservices without explicit approval.

Business logic belongs in domain/service layers.

API routes must remain thin.

## Tenant Security

Never trust tenant_id from request body/query.

Tenant context comes from authenticated membership.

Every tenant-owned resource query must be tenant scoped.

Cross-tenant access is a security vulnerability.

## Financial Data

Never use float for money.

Use Decimal/NUMERIC.

Never mutate a posted journal entry.

Every posted journal entry must balance.

## Inventory

Inventory movement ledger is source of truth.

Never directly change stock as an unrelated mutable integer.

Use transaction-safe inventory services.

## POS

Checkout must be transactional and idempotent.

Prevent overselling caused by concurrency.

## AI

LLM must never execute unrestricted SQL.

AI cannot bypass RBAC.

RAG retrieval must always enforce tenant scope.

Do not let AI invent financial numbers.

## Tests

Features require tests.

Critical flows require integration tests.

Tenant isolation requires explicit adversarial tests.

## Repository

Avoid unrelated refactors.

Avoid dead code.

Avoid giant files.

Do not commit secrets.

Update docs/AGENT_HANDOFF.md after significant work.
```

---

# 67. Suggested Codex Instruction File

If Codex supports a repository instruction file, use:

```markdown
# Nexora AI — Codex Rules

You are the implementation engineer.

Always read:

- prompt.md
- docs/ARCHITECTURE.md
- docs/DATABASE.md
- docs/API.md
- docs/SECURITY.md
- docs/AGENT_HANDOFF.md

Respect documented architecture.

Never bypass a failing test just to make CI green.

When implementation exposes architectural ambiguity, stop and document it instead of inventing incompatible behavior.

Every feature must leave the repository in a runnable state.

Before finishing:

- format
- lint
- typecheck
- test
- build

Report actual command results.

Update docs/AGENT_HANDOFF.md.
```

---

# 68. Final Shared Rule

For each major module use this exact cycle:

```text
                ┌──────────────────┐
                │      CLAUDE      │
                │ Design / Review  │
                └────────┬─────────┘
                         │
                         ▼
                Requirements
                DB model
                APIs
                Invariants
                Security
                Tests
                         │
                         ▼
                ┌──────────────────┐
                │      CODEX       │
                │  Implementation  │
                └────────┬─────────┘
                         │
                         ▼
                   Code + Tests
                         │
                         ▼
                ┌──────────────────┐
                │      CLAUDE      │
                │   Code Review    │
                └────────┬─────────┘
                         │
                  P0/P1/P2/P3
                         │
                         ▼
                ┌──────────────────┐
                │      CODEX       │
                │      Fixes       │
                └────────┬─────────┘
                         │
                         ▼
              Tests / Lint / Build
                         │
                         ▼
                      COMMIT
```

Never use this pattern:

```text
Claude builds half
+
Codex builds half independently
```

because two agents independently designing different halves of an ERP will produce inconsistent models and business rules.

Use:

> **Claude = architect/reviewer**  
> **Codex = implementer/tester**

---

# 69. First Action

After creating the repository:

1. Save this file as `prompt.md`.
2. Give both agents access to it.
3. Run **Phase 0 with Claude first**.
4. Let Claude create architecture documents and the handoff.
5. Run **Phase 1 with Codex**.
6. Send the result back to Claude for review.
7. Repeat the cycle phase by phase.

Do not ask either agent:

```text
Build the full ERP now.
```

The correct development order is:

```text
Architecture
    ↓
Auth + Tenancy + RBAC
    ↓
Catalog + Inventory
    ↓
Sales + Purchasing
    ↓
POS
    ↓
Accounting
    ↓
CRM + Reporting
    ↓
VAT
    ↓
AI Copilot
    ↓
RAG
    ↓
Forecasting + Anomaly Detection
    ↓
Security Hardening
    ↓
Production Deployment
```

This keeps Nexora AI maintainable, testable, auditable, and suitable as a serious portfolio-grade enterprise SaaS project.
