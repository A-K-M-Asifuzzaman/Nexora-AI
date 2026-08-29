# Nexora AI — Architecture

> Status: **Phase 0 baseline.** Authoritative for all implementation.
> Changes require an ADR in `docs/DECISIONS.md`.

---

## 1. Architectural Style

Nexora AI is a **modular monolith**: one deployable FastAPI application, one
PostgreSQL database, hard internal module boundaries.

Rationale (ADR-0001): an ERP's core value is *transactional consistency across
domains*. A POS checkout atomically touches sales, inventory, VAT, accounting
and audit. In a microservice topology that single invariant becomes a
distributed saga with compensating transactions — enormous complexity bought
for zero benefit at this scale. The monolith keeps `BEGIN … COMMIT` as the
consistency primitive.

Module boundaries are drawn so that the monolith *could* be split later. That
optionality is maintained by discipline, not by infrastructure:

- Modules communicate through **service interfaces**, never by importing each
  other's repositories, ORM models or tables.
- Cross-module reads go through the owning module's service.
- Cross-module writes inside one transaction go through the owning module's
  service, which receives the caller's session (see §9).
- No module reaches into another module's tables in SQL.

### 1.1 Layering

```
HTTP  →  Router          thin: authn, authz, validation, serialization
         Service         business rules, invariants, transaction boundaries
         Repository      data access, tenant scoping, locking
         Model           SQLAlchemy ORM, constraints
                DB       PostgreSQL: constraints, triggers, RLS
```

Hard rules:

- **Routers contain no business logic.** A router body should be readable in
  under ten lines: resolve dependencies, call one service method, return.
- **Routers never commit.** Only services own transaction boundaries.
- **Services never touch `Request` / `Response` / HTTP status codes.** They
  raise domain errors; the error layer maps them.
- **Repositories never contain business rules.** They contain queries.
- Business invariants are enforced in the service layer **and**, where
  expressible, in the database. Application validation is a UX affordance;
  the database constraint is the guarantee.

---

## 2. Repository Layout

```
nexora/
├── prompt.md                     shared agent contract
├── CLAUDE.md                     Claude standing rules
├── AGENTS.md                     Codex standing rules
├── README.md
├── .env.example                  canonical config contract
├── docker-compose.yml            dev stack
├── Makefile                      one-word entrypoints for every check
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md           ← this file
│   ├── DATABASE.md
│   ├── API.md
│   ├── ACCOUNTING.md
│   ├── SECURITY.md
│   ├── AI.md
│   ├── DECISIONS.md
│   ├── ROADMAP.md
│   └── AGENT_HANDOFF.md
├── backend/
│   ├── pyproject.toml            deps + ruff + mypy + pytest config
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── main.py               app factory, middleware, routers, handlers
│   │   ├── core/
│   │   │   ├── config.py         pydantic-settings, fail-fast validation
│   │   │   ├── security.py       hashing, token encode/decode
│   │   │   ├── errors.py         AppError hierarchy + handlers
│   │   │   ├── logging.py        structlog config + redaction
│   │   │   ├── context.py        contextvars: request_id, tenant, actor
│   │   │   ├── pagination.py     Page[T], cursor + offset helpers
│   │   │   ├── money.py          Decimal helpers, rounding policy
│   │   │   └── clock.py          injectable UTC clock (testability)
│   │   ├── db/
│   │   │   ├── base.py           DeclarativeBase, naming convention
│   │   │   ├── session.py        engine, sessionmaker, UnitOfWork
│   │   │   ├── mixins.py         UUIDPk, Timestamped, TenantScoped, SoftDelete
│   │   │   ├── types.py          Money, Quantity, Rate column types
│   │   │   └── tenant_guard.py   global tenant filter + RLS GUC setter
│   │   ├── api/
│   │   │   ├── deps.py           auth/tenant/permission dependencies
│   │   │   └── v1/router.py      mounts every module router
│   │   ├── modules/
│   │   │   └── <domain>/
│   │   │       ├── models.py
│   │   │       ├── schemas.py
│   │   │       ├── repository.py
│   │   │       ├── service.py
│   │   │       ├── router.py
│   │   │       ├── permissions.py
│   │   │       └── events.py     audit event constants
│   │   └── workers/
│   │       ├── celery_app.py
│   │       └── tasks/
│   └── tests/
│       ├── conftest.py
│       ├── factories/
│       ├── unit/
│       ├── integration/
│       ├── isolation/            cross-tenant adversarial suite
│       ├── authz/                permission-denial suite
│       ├── concurrency/          committed-transaction race tests
│       └── structural/           automated architecture guards
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/           login, register, forgot, verify
│   │   │   ├── (app)/            authenticated shell
│   │   │   └── api/bff/          Next route handlers: token custody
│   │   ├── features/<domain>/    api/, components/, hooks/, schemas/
│   │   ├── components/ui/        shadcn primitives
│   │   └── lib/                  api-client, auth, permissions, format
│   └── e2e/                      Playwright
├── infra/
│   ├── postgres/init/
│   └── docker/
└── .github/workflows/ci.yml
```

### 2.1 Backend domain modules

```
auth  tenancy  users  rbac  branches  customers  suppliers  catalog
inventory  sales  purchases  pos  accounting  crm  vat  reporting
audit  notifications  documents  ai  forecasting  anomaly_detection
```

Dependency direction is acyclic. Permitted edges (caller → callee):

```
pos       → sales, inventory, accounting, vat, audit
sales     → customers, catalog, inventory, accounting, vat, audit
purchases → suppliers, catalog, inventory, accounting, vat, audit
accounting→ audit
inventory → catalog, audit
everything→ tenancy, rbac, audit, core
```

`tenancy`, `rbac`, `audit` and `core` are **leaf infrastructure**: they must not
import any business module. A structural test enforces this (§13.4).

---

## 3. Multi-Tenancy

**Model: shared database, shared schema, `tenant_id` discriminator column**
(ADR-0002). Rejected alternatives: schema-per-tenant (migration cost grows
linearly with tenants; Alembic becomes a fan-out job), database-per-tenant
(operationally heavy for SMB scale, cross-tenant analytics impossible).

Tenant isolation is enforced at **three independent layers**. Any one of them
failing must not produce a leak.

### Layer 1 — Context derivation (never trust the client)

Tenant identity is **derived**, never accepted:

```
Access token (signed)  →  tid claim
                          ↓
       membership lookup: (user_id, tenant_id, status=ACTIVE)
                          ↓
       TenantContext(tenant_id, membership_id, user_id, role_ids,
                     permissions, branch_scope)
```

A `tenant_id` appearing in a request body, query string, path or header is
**ignored**. If a payload contains `tenant_id`, the request is rejected with
`422` — schemas forbid the field via `model_config = ConfigDict(extra="forbid")`.

`TenantContext` is stored in a `contextvars.ContextVar` set by the auth
dependency and cleared by middleware at the end of the request.

### Layer 2 — Automatic query scoping

Every tenant-owned model inherits `TenantScoped`. A SQLAlchemy
`do_orm_execute` event listener applies a global WHERE clause to every ORM
query touching those entities:

```python
@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state):
    if state.is_select and not state.execution_options.get("skip_tenant_filter"):
        ctx = current_tenant_context()   # raises if unset
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.tenant_id == ctx.tenant_id,
                include_aliases=True,
            )
        )
```

This means a developer who *forgets* `.where(Model.tenant_id == ...)` still
cannot leak data. The `skip_tenant_filter` escape hatch exists for platform
operations (login by email, migrations, cross-tenant admin jobs) and every use
site must carry a comment justifying it; a structural test counts them and
fails if the count rises without an ADR.

Writes are scoped by a `before_flush` listener that stamps `tenant_id` from
context on INSERT and rejects any flush where a dirty `TenantScoped` object's
`tenant_id` differs from context.

### Layer 3 — PostgreSQL Row-Level Security (defense in depth)

RLS is enabled on every tenant-owned table with a policy of the form:

```sql
CREATE POLICY tenant_isolation ON <table>
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

The application connects as a **non-superuser, non-owner** role (`nexora_app`)
so policies actually apply. The UnitOfWork issues
`SET LOCAL app.tenant_id = :tid` at transaction start.

RLS is **not** the primary control (ADR-0003): connection pooling makes GUC
lifetime subtle, and `SET LOCAL` is transaction-scoped, so a bug in transaction
management degrades RLS silently. Application enforcement stays mandatory.
RLS is the net under the net.

### 3.1 Branch scoping

Branch is a *sub-tenant* scope, not a second tenant. A membership may be
restricted to a set of branches (`membership_branches`). Authorization is
therefore two-dimensional:

```
has_permission(perm)  AND  branch_allowed(branch_id)
```

A cashier bound to Branch A holding `sales.create` still cannot check out at
Branch B. Unrestricted memberships (no rows in `membership_branches`) see all
branches — this is the OWNER/ADMIN default.

### 3.2 Tenant hierarchy

```
Tenant
 ├── Branches ── Warehouses
 ├── Users (via Membership)
 ├── Roles (system + custom)
 └── all business entities
```

A `User` is a **global** identity (unique email platform-wide) and is *not*
tenant-scoped. `Membership` is the join that grants tenant access. One user may
belong to many tenants; the active tenant is bound to the access token.

---

## 4. Authentication

Full threat treatment in `docs/SECURITY.md`. Structure:

| Element | Choice | Reason |
|---|---|---|
| Password hash | **Argon2id** (`argon2-cffi`), m=64MiB t=3 p=4 | Memory-hard; OWASP current recommendation |
| Access token | JWT, **15 min**, HS256 (interface allows RS256) | Short-lived so revocation lag is bounded |
| Refresh token | **Opaque** 256-bit random, SHA-256 hashed at rest | No signature to forge; DB is authority; revocable |
| Rotation | On every refresh, with **reuse detection** | Stolen token detected on second use |
| Refresh transport | `httpOnly; Secure; SameSite=Lax` cookie | Not readable by JS → XSS cannot exfiltrate |
| Access transport | `Authorization: Bearer` from memory | Never in `localStorage` |

### 4.1 Session families and reuse detection

```
auth_sessions      one row per login (a "family")
refresh_tokens     chain within a family; each row: token_hash, used_at,
                   replaced_by_id, expires_at
```

Refresh flow:

1. Look up token by hash. Not found → `401`.
2. Already `used_at IS NOT NULL` → **reuse detected**: revoke the entire
   session family, emit `security.refresh_reuse_detected`, return `401`.
3. Otherwise mark used, issue a new refresh token linked via `replaced_by_id`,
   issue a new access token.

This is the standard rotating-refresh pattern; the family revoke is what turns
theft into a detectable, self-limiting event.

### 4.2 Access-token revocation

Logout and role changes cannot retroactively invalidate a signed JWT. Two
mitigations: 15-minute TTL, and a Redis denylist keyed on `sid` (session id)
with TTL equal to the remaining access-token lifetime. The auth dependency
checks the denylist. Cost: one Redis `EXISTS` per request. Accepted (ADR-0007).

### 4.3 Tenant binding and switching

The access token carries `tid`. The refresh session is **tenant-agnostic**.
`POST /api/v1/auth/switch-tenant` validates membership and mints a new access
token for the requested tenant. This keeps the tenant claim signed, so tenant
identity survives on the token rather than being re-derived from a mutable
header.

### 4.4 Enumeration resistance

Registration, login, forgot-password and invitation-acceptance return
**identical** responses and **comparable timing** whether or not the account
exists. Password verification runs against a dummy hash when the user is absent
so the response time does not fingerprint existence.

---

## 5. RBAC

```
Permission  (global catalog, seeded, immutable codes)
Role        system roles (tenant_id NULL) + custom roles (tenant_id set)
RolePermission
Membership  (user × tenant)
MembershipRole  (M:N — effective permissions = union)
MembershipBranch (optional branch restriction)
```

Design rules:

- **No hardcoded role checks in business code.** Ever. Business code asks for a
  *permission*. `if role == "ADMIN"` is a defect, classified P2 minimum.
- OWNER has full access because its seeded role holds every permission — **not**
  because of a code-level bypass. A bypass branch is untestable and eventually
  wrong.
- System roles are immutable: no tenant may edit `OWNER`'s permission set.
  Tenants needing variation clone into a custom role.
- **Invariant: a tenant always has ≥1 ACTIVE membership with the OWNER role.**
  Enforced in service + integration test. Removing the last owner → `409`.

### 5.1 Privilege-escalation guards

Three rules, all tested:

1. A user may not modify **their own** roles.
2. A user may not grant a role whose permission set is not a **subset** of
   their own effective permissions. (Blocks `users.manage_roles` → self-promotion
   to full accounting access.)
3. Only OWNER may assign OWNER.

### 5.2 Permission resolution and caching

Resolving permissions per request is a 3-table join. It is cached in Redis:

```
key:  perms:{membership_id}:{roles_version}
TTL:  300s
```

`roles_version` is a counter on the membership bumped by any role/permission
mutation, so invalidation is automatic rather than best-effort — a stale cache
key simply stops being read. (ADR-0008: chosen over embedding permissions in
the JWT, which cannot be revoked before token expiry.)

### 5.3 Enforcement point

```python
@router.post("/", dependencies=[Depends(RequirePermission(Perm.SALES_CREATE))])
```

Object-level authorization (BOLA) is separate and lives in the service: after
loading a resource, the service verifies branch scope and any ownership rule.
Route-level permission alone is never sufficient for a resource-addressed
endpoint.

---

## 6. Tenant Context Propagation

```
HTTP request
  → RequestIdMiddleware        sets request_id contextvar (from X-Request-ID or new)
  → auth dependency            decodes JWT, loads membership, builds TenantContext
  → contextvar set             visible to repositories, tenant guard, audit, logging
  → UnitOfWork opens txn       issues SET LOCAL app.tenant_id
  → service executes
  → response                   X-Request-ID echoed
  → middleware clears contextvars
```

**Background jobs** have no request. A Celery base task requires
`tenant_id` and `actor_user_id` in its kwargs, re-establishes `TenantContext`
in `before_start`, and **refuses to execute** if absent. Tasks must never be
written to iterate all tenants inside one context; a fan-out task enqueues one
child task per tenant.

---

## 7. Audit Architecture

Two distinct streams, deliberately separated:

**Business audit (`audit_events`)** — written **in the same transaction** as
the operation. If the business operation rolls back, its audit row rolls back
with it; an audit row therefore *proves* the operation committed. This is the
property that makes the trail trustworthy.

**Security events (`security_events`)** — written in an **independent**
transaction, because they mostly record things that *failed*: authz denials,
login failures, refresh reuse, rate-limit trips. These must survive the
rollback of the operation that triggered them.

Immutability is enforced at the database (`docs/DATABASE.md` §7):

- `REVOKE UPDATE, DELETE ON audit_events FROM nexora_app;`
- plus a `BEFORE UPDATE OR DELETE` trigger raising an exception, so even a
  privilege misconfiguration fails closed.

Recorded fields: `tenant_id, actor_user_id, actor_membership_id, action,
resource_type, resource_id, request_id, ip, user_agent, metadata (JSONB),
occurred_at`.

`metadata` is redacted through the same denylist as logging — no tokens, no
password fields, no full card data, ever.

Hash-chaining for tamper *evidence* is deferred to Phase 11 (ADR-0016): it
serializes writes per tenant and the contention cost is not justified before a
threat model demands it.

---

## 8. Error Handling

One shape, everywhere (`docs/API.md` §4):

```json
{ "error": { "code": "INSUFFICIENT_STOCK", "message": "...", "details": {} },
  "request_id": "01J..." }
```

`AppError` hierarchy → HTTP mapping:

| Class | HTTP | Notes |
|---|---|---|
| `ValidationError` | 422 | field-level `details` |
| `AuthenticationError` | 401 | never says *why* |
| `PermissionDenied` | 403 | in-tenant permission failure |
| `ResourceNotFound` | 404 | also returned for **cross-tenant** access |
| `ConflictError` | 409 | state-machine violation, optimistic-lock loss |
| `BusinessRuleViolation` | 422 | e.g. `UNBALANCED_JOURNAL` |
| `RateLimited` | 429 | `Retry-After` |
| `ExternalServiceError` | 502/503 | LLM, storage, email |

**Cross-tenant access returns `404`, not `403`** (ADR-0009). A `403` confirms
the object exists, which is an information leak that turns an IDOR probe into a
working enumeration oracle. Uniform `404` denies the attacker that signal.

Unhandled exceptions → `500` with a generic message plus `request_id`. Stack
traces never reach the client. The `request_id` is the support handle.

---

## 9. Transactions and Unit of Work

- **One transaction per request** by default, opened by the UoW dependency.
- **The service layer owns commit.** Routers never commit; repositories never
  commit.
- Nested logical units use `SAVEPOINT` (`session.begin_nested()`).
- No I/O to external systems (LLM, email, S3 write, webhook) inside a business
  transaction. Side effects are enqueued and dispatched **after** commit via a
  transactional outbox (`outbox_events`) drained by a worker. Otherwise a
  rollback still sent the email, or a timeout on the LLM held row locks.

Operations required to be atomic (single transaction, no exceptions):

```
POS checkout        sale + lines + movements + payments + VAT + journal + audit + idempotency
Goods receipt       receipt + lines + movements + valuation + journal + audit
Invoice issue       invoice + numbering + AR + journal + audit
Payment posting     payment + allocations + AR/AP + journal + audit
Stock transfer      TRANSFER_OUT + TRANSFER_IN + both balances + audit
Refund              return + movements + payment reversal + reversing journal + audit
```

### 9.1 Lock ordering

Any transaction taking multiple row locks acquires them in a **deterministic
global order** to prevent deadlock:

```
1. tenant settings / sequences   (last, and held briefly — see §10)
2. inventory_balances  ORDER BY (warehouse_id, product_id)
3. customer / supplier balance rows  ORDER BY id
```

Inventory balance rows are locked `FOR UPDATE` sorted by `(warehouse_id,
product_id)`. Two concurrent carts containing the same products in different
input order therefore cannot deadlock.

---

## 10. Numbering Sequences

Invoice, receipt, journal and order numbers must be **gapless per tenant per
series per fiscal year** — a requirement of most tax regimes and of auditors.

PostgreSQL `SEQUENCE` is unsuitable: it is non-transactional by design and
leaves gaps on rollback. Instead a `document_sequences` table holds
`(tenant_id, series, period, next_value)` and allocation is:

```sql
UPDATE document_sequences SET next_value = next_value + 1
WHERE tenant_id = :t AND series = :s AND period = :p
RETURNING next_value - 1;
```

This serializes concurrent allocation on one row. To keep the lock window
minimal, **number allocation is the last step before commit**, never the first
(ADR-0010). Contention is bounded by transaction length, and the gapless
guarantee is worth it. Throughput at SMB scale (tens of checkouts/second) is
comfortably served.

---

## 11. Idempotency

Applies to: POS checkout, payment creation, refunds, remote invoice creation,
webhooks.

`idempotency_keys` table, unique on `(tenant_id, endpoint, key)`:

```
key, endpoint, tenant_id, request_hash, status(IN_PROGRESS|COMPLETED),
response_status, response_body JSONB, resource_id, created_at, expires_at (24h)
```

Algorithm:

1. `INSERT … ON CONFLICT DO NOTHING` with `status=IN_PROGRESS` **in the same
   transaction as the business operation**.
2. Insert won → execute the operation; on success write the response snapshot
   and set `COMPLETED`; commit atomically with the business rows.
3. Insert lost + existing `COMPLETED` + **matching `request_hash`** → replay the
   stored response verbatim.
4. Insert lost + `COMPLETED` + **different `request_hash`** → `422
   IDEMPOTENCY_KEY_REUSE`. Same key must never mean two different operations.
5. Insert lost + `IN_PROGRESS` → `409 REQUEST_IN_PROGRESS`, client retries.

Because the key row and the business rows commit together, it is impossible to
have a recorded key without its sale, or a sale without its key.

---

## 12. Inventory Concurrency

The **movement ledger is the source of truth** (`inventory_movements`,
append-only, never updated). `inventory_balances` is a materialized cache row
per `(tenant_id, warehouse_id, product_id)` carrying `on_hand`, `reserved`,
and derived `available = on_hand − reserved`.

The canonical race — *stock = 1, two terminals sell 1 simultaneously* — is
resolved by pessimistic row locking:

```sql
SELECT * FROM inventory_balances
 WHERE tenant_id=:t AND warehouse_id=:w AND product_id = ANY(:products)
 ORDER BY warehouse_id, product_id
 FOR UPDATE;
```

Terminal B blocks until A commits, then re-reads `available = 0` and fails with
`INSUFFICIENT_STOCK`. Exactly one checkout succeeds.

Optimistic locking was rejected for checkout (ADR-0011): it converts contention
into user-visible retry failures at the till, which is unacceptable UX for the
one operation a cashier repeats all day. Pessimistic locking with a short,
deterministic critical section is correct here.

**Why there is no blanket `CHECK (on_hand >= 0)`:** negative inventory is a
per-tenant setting, and legitimate corrections (a return processed before its
sale syncs, an opening-balance adjustment) create transient negatives. The
guarantee is instead: row lock + service check against tenant settings +
`CHECK (reserved_quantity >= 0)` + a nightly reconciliation job asserting
`SUM(movements) == balances` per (tenant, warehouse, product), which alarms on
drift. Drift indicates a code path bypassing the ledger — a P0.

---

## 13. Testing Architecture

### 13.1 Layers

| Suite | Scope | DB |
|---|---|---|
| `unit/` | pure logic: money rounding, state machines, VAT math | none |
| `integration/` | service + repository + real constraints | real PostgreSQL |
| `isolation/` | Tenant A vs Tenant B adversarial matrix | real PostgreSQL |
| `authz/` | every endpoint × insufficient-permission actor | real PostgreSQL |
| `concurrency/` | committed parallel transactions | real PostgreSQL, 2+ connections |
| `structural/` | architecture guards (below) | metadata only |
| `e2e/` | Playwright happy paths + POS | full stack |

**SQLite is never used.** It cannot express the constraints, triggers, RLS,
`FOR UPDATE` semantics or `NUMERIC` behaviour this system depends on. Testing
against it would validate a database we do not ship.

### 13.2 Isolation strategy

Default: each test runs inside a transaction rolled back at teardown (fast).
Concurrency tests **cannot** use that pattern — they need real committed
visibility across connections — so they are marked `@pytest.mark.concurrency`,
run against a dedicated schema, and truncate between tests.

### 13.3 The mandatory adversarial fixture

`tests/isolation/` uses a fixture producing two fully-populated tenants and
asserts, for **every** tenant-owned resource:

```
Tenant B: GET /resource/{A_id}    → 404
Tenant B: PATCH /resource/{A_id}  → 404
Tenant B: DELETE /resource/{A_id} → 404
Tenant B: list                    → never contains an A id
```

New modules add themselves to a parametrized registry; a structural test fails
if a `TenantScoped` model has no entry.

### 13.4 Structural guard tests

Automated architecture enforcement, not prose:

1. **No float money** — walk `Base.metadata`; fail if any column is `Float`/
   `REAL`/`DOUBLE PRECISION`. Money must be `NUMERIC`.
2. **Every route is authenticated** — introspect `app.routes`; every route
   outside an explicit public allowlist must carry an auth dependency. Catches
   the forgotten-`Depends` class of vulnerability permanently.
3. **Every `TenantScoped` model** has `tenant_id`, an index leading with
   `tenant_id`, and an isolation-registry entry.
4. **Module dependency graph is acyclic** and respects §2.1 edges (AST import
   scan).
5. **Escape-hatch budget** — count `skip_tenant_filter` uses; fail if above the
   recorded allowlist.
6. **No business logic in routers** — router modules may not import
   `repository` or `models` directly.

---

## 14. Background Jobs

**Celery + Redis** (ADR-0012). Chosen over RQ for scheduled work (`beat`),
retry/backoff policy, and queue routing that lets document embedding not starve
receipt emails. Chosen over a bespoke asyncio loop because at-least-once
delivery, visibility timeouts and retries are exactly the things one gets wrong
by hand.

Queues: `default`, `documents` (extract/chunk/embed), `ml` (forecasting,
anomaly scans), `emails`, `maintenance` (reconciliation, cleanup).

Every task: idempotent (may run twice), tenant-scoped by explicit kwargs,
bounded runtime, logs with `request_id` inherited from the enqueuing request.

The **transactional outbox** (§9) is drained by a `maintenance` worker: rows in
`outbox_events` are read, dispatched, marked sent. This gives "commit then
deliver" semantics without two-phase commit.

---

## 15. Object Storage

S3-compatible; MinIO in dev, any S3 API in production. Key layout:

```
s3://nexora-{env}/tenants/{tenant_id}/documents/{uuid}{ext}
```

Rules: server-side generated random filename; the original name is stored as
*metadata only* and is HTML-escaped on display; upload validated by extension
**and** sniffed MIME **and** size cap; download served exclusively through
short-TTL presigned URLs minted **after** an authorization check. Buckets are
private; no object is ever public. Full rules in `docs/SECURITY.md` §8.

---

## 16. Redis Usage

| Use | Key pattern | TTL |
|---|---|---|
| Rate limiting | `rl:{scope}:{identifier}` | window |
| Permission cache | `perms:{membership_id}:{roles_version}` | 300s |
| Access-token denylist | `deny:sid:{session_id}` | ≤ access TTL |
| Report cache | `t:{tenant_id}:report:{hash}` | 60–300s |
| Celery broker/result | — | — |

Every application key is tenant-prefixed where tenant-derived. Redis is treated
as **volatile**: losing it degrades performance and forces re-login of denylist
edge cases, but never loses business data.

---

## 17. Qdrant Tenant Isolation

Single collection `nexora_documents` with a **payload index on `tenant_id`
declared as a tenant partition key**, per Qdrant's multitenancy guidance
(ADR-0013). Collection-per-tenant was rejected: thousands of collections carry
real memory/segment overhead and make schema evolution an N-collection
migration.

The isolation guarantee comes from making an unfiltered search
**unreachable in code**:

```python
class TenantVectorStore:
    """The ONLY module permitted to call the Qdrant client."""
    def search(self, ctx: TenantContext, query_vector, limit, doc_filter=None):
        must = [FieldCondition(key="tenant_id", match=MatchValue(value=str(ctx.tenant_id)))]
        ...
```

There is no public method that accepts a caller-supplied raw filter. A
structural test asserts no module outside `modules/documents/vector_store.py`
imports `qdrant_client`. Adversarial retrieval tests (Tenant B queries text
that exists only in Tenant A's documents, expecting zero hits) are mandatory in
Phase 9.

---

## 18. Observability

- **Structured JSON logs** via `structlog`. Every line carries `request_id`,
  `tenant_id`, `user_id`, `route`, `status`, `duration_ms`.
- **Redaction filter** with a key denylist (`password`, `token`, `refresh`,
  `authorization`, `secret`, `api_key`, `card`, `cvv`) applied to log *and*
  audit metadata. Redaction is by key name at the serializer, so a new call site
  cannot forget it.
- `GET /health` — liveness, **no dependency checks**, always cheap.
- `GET /ready` — readiness: DB `SELECT 1`, Redis `PING`, migration head match.
- `GET /metrics` — Prometheus, bound to internal network / protected in prod.
- Error tracking behind a `ErrorTracker` interface (Sentry-compatible), so the
  vendor is swappable and disabled in tests.

Correlation: `X-Request-ID` accepted from an edge proxy if well-formed, else
generated; propagated into Celery tasks and included in every error response.

---

## 19. Frontend Architecture

Next.js App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query +
React Hook Form + Zod.

### 19.1 Token custody — BFF pattern (ADR-0014)

The browser never stores tokens. Next.js Route Handlers under `/api/bff/*` act
as a thin proxy:

- Refresh token lives in an `httpOnly` cookie readable only by the BFF.
- The BFF attaches the access token to upstream FastAPI calls.
- Access token is held server-side per session; the browser holds nothing.

Cost: one extra network hop. Benefit: an XSS in the SPA cannot steal a refresh
token, which is the difference between a session compromise and a persistent
account compromise. CSRF is handled by `SameSite=Lax` plus a double-submit
token on state-changing BFF routes.

### 19.2 Money on the frontend

**The API serializes monetary values as JSON strings**, never numbers
(ADR-0015). `0.1 + 0.2 !== 0.3` in IEEE-754, and JSON numbers are parsed into
JS `number`. Amounts are strings end-to-end; arithmetic on the client uses
`decimal.js`; display uses `Intl.NumberFormat` on the decimal string. The
client does not recompute invoice totals — it renders server-computed values.

### 19.3 Structure

```
features/<domain>/
  api/          typed fetchers + TanStack Query hooks
  schemas/      Zod schemas mirroring backend contracts
  components/   domain UI
  hooks/
lib/
  api-client    fetch wrapper: request id, error envelope parsing, 401 refresh
  permissions   usePermissions(), <Can permission="sales.create">
  format        money, date, quantity formatters
```

Permission-aware UI hides what the user cannot do — a UX affordance, never a
security control. The server authorizes independently of what the UI rendered.

Required states for every data view: loading (skeleton), empty (with the
primary action), error (with retry), permission-denied. Destructive actions
require typed confirmation. POS is fully keyboard-operable.

---

## 20. Docker (development)

```
frontend   Next.js dev server
backend    FastAPI + uvicorn --reload
worker     Celery worker
postgres   16, healthcheck, named volume
redis      7
qdrant     latest stable, named volume
minio      S3-compatible + one-shot bucket bootstrap
mailhog    SMTP sink for verification/reset mail
```

Backend and worker share one image, differing only in command. `depends_on`
uses `condition: service_healthy`. No secret is baked into an image; everything
arrives via env. `.env.example` is the canonical config contract and must list
every variable the app reads — `Settings` fails fast at startup on a missing
required var.

---

## 21. CI Architecture

`.github/workflows/ci.yml`, jobs run in parallel, all required to merge:

| Job | Gate |
|---|---|
| `backend-quality` | `ruff format --check`, `ruff check`, `mypy` |
| `backend-tests` | postgres+redis services, `alembic upgrade head`, `pytest --cov` |
| `migrations` | `alembic upgrade head` → `alembic check` (model drift) → `downgrade -1` → `upgrade head` |
| `frontend-quality` | `eslint`, `tsc --noEmit` |
| `frontend-tests` | `vitest run` |
| `frontend-build` | `next build` |
| `security` | `pip-audit`, `npm audit --audit-level=high`, `gitleaks` |
| `e2e` | Playwright smoke against the compose stack |

The `alembic check` step is what prevents the classic ERP failure mode of
models and migrations silently diverging.

**A failing check is never resolved by weakening the check.** Deleting a test,
adding `# type: ignore` without justification, or lowering a threshold to get
green is a P1 finding in review.

---

## 22. ADR Process

Every architecturally significant decision gets a numbered entry in
`docs/DECISIONS.md`:

```
## ADR-00XX — Title
Status: Accepted | Superseded by ADR-00YY
Context:      the forces at play
Decision:     what we chose
Consequences: what this costs us, what it buys, what it forecloses
```

"Architecturally significant" = changes a module boundary, a data model
invariant, a security control, a transaction boundary, or a dependency.

Codex does not author ADRs. If implementation reveals that an ADR is wrong,
Codex **stops** and records the conflict in `docs/AGENT_HANDOFF.md` under
`# Known Problems`.
