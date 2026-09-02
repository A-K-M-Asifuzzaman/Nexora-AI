# Nexora AI

**Multi-Tenant ERP, POS & Business Intelligence Platform**

A production-oriented SaaS platform for small and medium businesses that runs
operations and books in one system: POS, catalog, inventory, sales, purchasing,
CRM, double-entry accounting, VAT, reporting, plus an AI copilot,
tenant-isolated document Q&A, forecasting and anomaly detection.

The design commitment underneath all of it: **a POS checkout is one database
transaction** that writes the sale, the stock movement, the payment, the VAT
record, the journal entries and the audit event — or writes none of them.

---

## Status

All 12 phases are complete, migrated, and green in CI: authentication and
tenancy, catalog and inventory, sales and purchasing, POS, accounting, CRM and
reporting, VAT, an AI copilot with tenant-scoped RAG, demand forecasting and
anomaly detection, security hardening (MFA, field encryption, tamper-evident
audit chaining, virus scanning, rate limiting), and production deployment
(Docker images, reverse proxy, backup/restore, release pipeline). Full,
evidence-based exit state for every phase — what was built, what was tested,
what real bugs were found and fixed — is in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Stack

**Backend** FastAPI · Python 3.12 · Pydantic v2 · SQLAlchemy 2.x · Alembic · PostgreSQL 16
**Frontend** Next.js (App Router) · TypeScript · a token-custody BFF proxy layer · react-hook-form + Zod
**Infrastructure** Redis · Celery (worker + beat) · Docker Compose · S3-compatible storage · Qdrant · ClamAV
**AI** Provider abstraction (OpenAI/Anthropic) · whitelisted, permission-checked tools · tenant-scoped RAG · grounding checks
**Testing** pytest · pytest-asyncio · real PostgreSQL (never SQLite) · Vitest · React Testing Library

---

## Quick start

```bash
cp .env.example .env
# Generate the required secrets:
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('BFF_SESSION_SECRET=' + secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print('FIELD_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"

make up             # docker compose up -d --build
docker compose exec backend alembic upgrade head
make seed-demo       # idempotent — reference data, roles, and a full demo tenant
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8000/api/v1/docs *(dev only)* |
| Health | http://localhost:8000/health |
| Mail sink | http://localhost:8025 |
| MinIO console | http://localhost:9001 |

A free, single-host deployment mode — same services, same code, no mocks —
is documented in [`infra/demo/README.md`](infra/demo/README.md). Real
production deployment (managed infrastructure, real secrets, monitoring) is
covered in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Verification

```bash
make format      # ruff format
make lint        # ruff check · eslint
make typecheck   # mypy · tsc --noEmit
make test        # pytest (real Postgres, 80% coverage gate) · vitest
make build       # next build
make verify      # all of the above — must pass before any commit
```

---

## Architecture in one page

**Modular monolith.** One deployable, one database, hard module boundaries
enforced by structural tests. An ERP's core value is transactional consistency
across domains; distributing it would turn every checkout into a saga.

**Three-layer tenant isolation.**
1. Tenant context is *derived* from the authenticated membership — a
   client-supplied `tenant_id` is ignored everywhere.
2. A SQLAlchemy global filter scopes every query automatically, so a forgotten
   `WHERE` clause cannot leak.
3. PostgreSQL RLS as the net under the net (the app connects as a non-owner
   role, so policies genuinely apply).

Cross-tenant access returns **404**, never 403 — a 403 would confirm existence.

**Money is `Decimal`/`NUMERIC` end to end** and crosses the API as *strings*,
because JSON numbers become IEEE-754 doubles in every browser.

**The inventory ledger is the source of truth.** Balances are a cache;
concurrent checkouts lock balance rows `FOR UPDATE` in a deterministic order, so
the last unit sells exactly once.

**Posted journal entries are immutable** — enforced by database triggers, not
just by services. Corrections are reversals.

**The AI never executes SQL.** It selects from permission-checked, tenant-scoped
tools, and a grounding check verifies every figure it states appears in the tool
output.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) | Scope, users, flows, success criteria |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Structure, tenancy, transactions, testing |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Schema, types, constraints, triggers, RLS |
| [`docs/API.md`](docs/API.md) | Endpoints, errors, pagination, permissions |
| [`docs/ACCOUNTING.md`](docs/ACCOUNTING.md) | Invariants, chart of accounts, posting rules |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, controls, **known gaps** |
| [`docs/AI.md`](docs/AI.md) | Copilot tools, RAG isolation, ML honesty rules |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 23 ADRs, each with its cost stated |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Production deployment, backup/restore, known gaps |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phase-by-phase exit state, evidence-based |

---

## Scope boundaries

Stated plainly, because overclaiming in a financial system is a defect:

- **Not a payment processor.** Card payments are references to externally
  processed transactions. No PAN, CVV or track data is stored. No PCI-DSS scope.
- **No tax-authority certification.** The VAT subsystem is generic and
  configurable. **No NBR or Bangladesh Mushak compliance is claimed.** The module
  is isolated so verified jurisdiction support can be added without touching the
  accounting core.
- **Single currency per tenant** in v1 (currency is stored on every record, so
  multi-currency is additive).
- **One tenant = one legal entity.** Branches are operational, not legal,
  divisions.
- **The AI is read-only.** It cannot post entries, move stock, approve refunds,
  or change permissions.

Open security gaps are tracked honestly in [`docs/SECURITY.md`](docs/SECURITY.md) §12.

---

## Development model

Two roles, one architecture:

- **Architect** — architecture, domain modelling, invariants, API contracts,
  security design, code review, defect severity classification.
- **Implementer** — implementation, migrations, tests, Docker, CI, debugging, fixes.

```
design → implement → review (P0–P3) → fix → verify → commit
```

No phase begins while a P0 or P1 finding is open in a phase it depends on.
