# Nexora AI — Architecture Decision Records

Format: Context → Decision → Consequences. Consequences must state the **cost**,
not only the benefit; an ADR that lists no downside has not been thought through.

The implementer does not author ADRs. If implementation shows one is wrong, the implementer stops and
records the conflict in `the handoff log` under `# Known Problems`.

---

## ADR-0001 — Modular monolith, not microservices
**Status:** Accepted · Phase 0

**Context.** An ERP's core operations span domains atomically: a POS checkout
touches sales, inventory, VAT, accounting and audit in one business event.

**Decision.** One FastAPI deployable, one PostgreSQL database, hard module
boundaries enforced by structural tests.

**Consequences.** `BEGIN … COMMIT` stays the consistency primitive instead of a
distributed saga with compensating transactions. Cost: the whole application
scales as a unit, and boundary discipline depends on tests rather than network
separation — a lazy import can violate a boundary that a service mesh would have
made impossible. Mitigated by the acyclic-import guard (ARCHITECTURE §13.4).

---

## ADR-0002 — Shared database, shared schema, `tenant_id` discriminator
**Status:** Accepted · Phase 0

**Context.** Three standard multi-tenancy models: shared schema, schema-per-tenant,
database-per-tenant.

**Decision.** Shared schema with a `tenant_id` column on every tenant-owned table.

**Consequences.** Migrations run once. Cross-tenant platform analytics remain
possible. Onboarding a tenant is an INSERT, not a provisioning job. Cost: isolation
is now a *code* property rather than an infrastructure one, so it must be defended
by the three layers in ARCHITECTURE §3 and by an adversarial test suite. A single
missing WHERE clause would be a breach — which is precisely why Layer 2 makes that
clause automatic.

---

## ADR-0003 — RLS as defense-in-depth, not the primary control
**Status:** Accepted · Phase 0

**Context.** PostgreSQL RLS can enforce tenant isolation at the database.

**Decision.** Enable RLS on all tenant-owned tables via a `SET LOCAL
app.tenant_id` GUC, but keep application-level enforcement mandatory.

**Consequences.** Two independent controls must both fail to produce a leak.
Cost: the GUC is transaction-scoped, so with connection pooling a transaction
management bug degrades RLS *silently* — it fails open, not closed. That is
exactly why it cannot be the primary control. The app must also connect as a
non-owner role or `FORCE ROW LEVEL SECURITY` is a no-op (DATABASE §6) — an easy
and invisible misconfiguration, so it is asserted by a test.

---

## ADR-0004 — UUIDv7 primary keys
**Status:** Accepted · Phase 0

**Context.** Sequential integers leak volume and are trivially enumerable.
UUIDv4 is random and fragments B-tree indexes on high-insert tables.

**Decision.** UUIDv7 (time-ordered) generated application-side.

**Consequences.** Non-enumerable keys with index locality; inserts append rather
than scattering. Cost: the key embeds a creation timestamp, which is already
exposed as `created_at`, and keys are 16 bytes rather than 8.

---

## ADR-0005 — Argon2id for passwords
**Status:** Accepted · Phase 0

**Decision.** Argon2id (`m=64MiB, t=3, p=4`).

**Consequences.** Memory-hard, current OWASP recommendation. Rejected bcrypt: it
silently truncates at 72 bytes, so a long passphrase is weaker than the user
believes and nothing surfaces the fact. Rejected PBKDF2: not memory-hard. Cost:
~64 MiB per concurrent hash, which bounds login concurrency and must be
considered when sizing the API container.

---

## ADR-0006 — Opaque rotating refresh tokens with reuse detection
**Status:** Accepted · Phase 0

**Decision.** Refresh tokens are 256-bit random opaque strings, SHA-256 hashed at
rest, rotated on every use, grouped into session families. Reuse of a consumed
token revokes the entire family.

**Consequences.** The database is the authority, so revocation is immediate and
theft becomes detectable. Cost: a refresh requires a database write, and a client
that races two refreshes can revoke its own session — accepted, since the client
serializes refreshes through a single-flight lock.

SHA-256 rather than Argon2 here is deliberate: the token is 256 bits of CSPRNG
entropy, not a low-entropy human secret, so a fast hash is not brute-forceable
and keeps the hot refresh path cheap.

---

## ADR-0007 — Short access-token TTL plus Redis denylist
**Status:** Accepted · Phase 0

**Context.** A signed JWT cannot be un-signed. Logout and role changes need to
take effect.

**Decision.** 15-minute access tokens, plus a Redis denylist of revoked session
ids checked per request.

**Consequences.** Revocation is effective within the access-token lifetime and
usually immediately. Cost: one Redis `EXISTS` per authenticated request, and a
Redis outage degrades revocation to the 15-minute TTL. Accepted; the alternative
(a database lookup per request) is worse, and stateless-only is unacceptable for
a system where a fired employee's access must actually end.

---

## ADR-0008 — Permissions resolved server-side and cached, not embedded in the JWT
**Status:** Accepted · Phase 0

**Context.** Embedding permissions in the token removes a lookup per request.

**Decision.** The token carries only `sub`, `sid`, `tid`. Permissions resolve
from the database, cached in Redis under `perms:{membership_id}:{roles_version}`.

**Consequences.** A revoked permission takes effect on the next request, not on
the next login — which is the correct behaviour when someone is demoted or
dismissed. Cost: a cache lookup per request. Invalidation is *automatic* rather
than best-effort: bumping `roles_version` changes the cache key, so a stale entry
simply stops being read and no explicit purge can be forgotten.

---

## ADR-0009 — Cross-tenant access returns 404, not 403
**Status:** Accepted · Phase 0

**Decision.** A request for a resource belonging to another tenant is
indistinguishable from a request for a resource that does not exist.

**Consequences.** An attacker enumerating ids learns nothing. Cost: a genuine
support case ("I can't see the invoice") is marginally harder to diagnose from
the client side — mitigated by the `request_id` in every response and by
`tenant.cross_access_attempt` in `security_events`, which is where the truth
lives. `403` remains correct for in-tenant permission failures, where existence
is not a secret.

---

## ADR-0010 — Gapless numbering via a locked counter table, allocated last
**Status:** Accepted · Phase 0

**Context.** Invoice numbers must be gapless per tenant per series per year.
PostgreSQL `SEQUENCE` is non-transactional and leaves gaps on rollback.

**Decision.** A `document_sequences` row updated with `next_value = next_value + 1
RETURNING`, allocated as the **last** step before commit.

**Consequences.** Gapless numbering, which auditors and most tax regimes require.
Cost: allocation serializes per (tenant, series, period). Allocating last keeps
the lock window to the tail of the transaction rather than its whole duration.
At SMB throughput this is comfortable; if a tenant ever outgrows it, the fix is a
per-branch series, not a lock-free design that reintroduces gaps.

---

## ADR-0011 — Pessimistic locking for inventory consumption
**Status:** Accepted · Phase 0

**Context.** Two POS terminals selling the last unit simultaneously must not both
succeed.

**Decision.** `SELECT … FOR UPDATE` on `inventory_balances` rows, locked in
deterministic `(warehouse_id, product_id)` order.

**Consequences.** The race is closed by the database, not by application timing.
Deterministic ordering makes deadlock between two multi-item carts impossible.
Cost: contention on hot SKUs serializes checkouts. Accepted, because the
alternative — optimistic locking with retry — surfaces as a failed checkout at
the till, which is the worst possible place to ask a cashier to try again.

---

## ADR-0012 — Celery for background jobs
**Status:** Accepted · Phase 0

**Decision.** Celery with a Redis broker; queues `default`, `documents`, `ml`,
`emails`, `maintenance`.

**Consequences.** Mature retries, scheduling (`beat`) and routing, so document
embedding cannot starve receipt emails. Cost: an extra process type to run and
monitor, and Redis-as-broker is at-least-once — hence every task must be
idempotent, which is stated as a hard rule rather than left to discover.

---

## ADR-0013 — Single Qdrant collection with a tenant partition key
**Status:** Accepted · Phase 0

**Context.** Qdrant supports collection-per-tenant or a payload-filtered shared
collection.

**Decision.** One collection with `tenant_id` indexed as a tenant partition key,
accessed exclusively through a `TenantVectorStore` wrapper that constructs the
filter itself.

**Consequences.** Scales to many tenants without per-collection memory overhead,
and schema evolution is one operation instead of N. Cost: isolation depends on a
filter always being applied — so the API is shaped to make an unfiltered search
*unexpressible*: no public method accepts a caller-supplied raw filter, and a
structural test forbids importing `qdrant_client` anywhere else.

---

## ADR-0014 — BFF token custody on the frontend
**Status:** Accepted · Phase 0

**Context.** SPAs commonly store tokens in `localStorage`, where any XSS reads
them.

**Decision.** Next.js Route Handlers proxy API calls; the refresh token lives in
an `httpOnly` cookie the browser's JavaScript cannot read.

**Consequences.** An XSS can act as the user *while the page is open* but cannot
exfiltrate a durable credential — the difference between a session incident and
a persistent account compromise. Cost: an extra network hop, and the Next server
becomes a stateful component that must be sized and monitored. CSRF re-enters as
a concern and is handled with `SameSite=Lax` + double-submit tokens + `Origin`
checks.

---

## ADR-0015 — Money serialized as JSON strings
**Status:** Accepted · Phase 0

**Context.** JSON numbers become IEEE-754 doubles in JavaScript.
`0.1 + 0.2 !== 0.3`.

**Decision.** All monetary values cross the API as strings (`"1234.5600"`).
Requests carrying a JSON float in a money field are rejected with `422`.

**Consequences.** Precision is preserved end to end; the guarantee established in
`NUMERIC` columns is not thrown away at the serialization boundary. Cost: clients
must use `decimal.js` for arithmetic and cannot naively `JSON.parse` and add.
Accepted — the client should not be recomputing invoice totals anyway; it renders
server-computed values.

---

## ADR-0016 — Audit hash-chaining deferred to Phase 11
**Status:** Accepted · Phase 0

**Context.** A hash chain over audit rows gives tamper *evidence* against an
attacker with direct database access.

**Decision.** Phase 1 ships append-only enforcement (revoked grants + a blocking
trigger). Chaining is deferred.

**Consequences.** Application-level tampering is already impossible. Cost: an
attacker with `nexora_owner` credentials could alter history undetected. Accepted
for now because chaining serializes audit writes per tenant, and that contention
is a real cost on the hottest write path — paid when the threat model justifies
it, not before.

---

## ADR-0017 — The LLM never generates or executes SQL
**Status:** Accepted · Phase 0 · **Permanent**

**Decision.** The AI selects from a registry of hand-written, parameterized,
tenant-scoped, permission-checked tools. Text-to-SQL is rejected outright.

**Consequences.** The blast radius of a prompt injection is bounded by what the
authenticated user could already do. Cost: every new analytical question needs a
new tool, so the copilot's capability grows by engineering rather than by
prompting. That trade is correct for a system holding other companies' financial
records: there is no validator that can reliably prove an arbitrary generated
query is tenant-safe.

---

## ADR-0018 — Perpetual inventory with weighted average cost
**Status:** Accepted · Phase 0

**Decision.** Moving-average cost per `(tenant_id, product_id)`, COGS recognised
at each sale.

**Consequences.** Real-time margin, which is the point of the gross-profit
dashboard tile. Weighted average avoids FIFO's cost-layer machinery and matches
SMB accountant expectations. Cost: less precise cost matching than FIFO during
sharp price movements, and it is not permitted under US GAAP LIFO regimes.
`product_cost_layers` is reserved in the schema so FIFO remains an additive
change rather than a rewrite.

---

## ADR-0019 — Real PostgreSQL in tests; SQLite is never used
**Status:** Accepted · Phase 0

**Decision.** Every integration test runs against PostgreSQL 16.

**Consequences.** Tests exercise the constraints, triggers, RLS policies,
`FOR UPDATE` semantics and `NUMERIC` behaviour that the system actually depends
on. Cost: tests need a database service, so they are slower than in-memory and
CI needs a Postgres container. Non-negotiable: an SQLite suite would validate a
database we do not ship, and would pass while every trigger in DATABASE §7 was
silently absent.

---

## ADR-0020 — Transactional outbox for post-commit side effects
**Status:** Accepted · Phase 0

**Context.** Emails, webhooks and LLM calls inside a business transaction either
hold row locks across network I/O, or fire for operations that then roll back.

**Decision.** Side effects are written to `outbox_events` inside the transaction
and dispatched by a worker after commit.

**Consequences.** "Commit then deliver" without two-phase commit; no external
call ever holds a database lock. Cost: delivery is at-least-once and slightly
delayed, so consumers must tolerate duplicates — an explicit requirement on every
outbox consumer rather than an accident.

---

## ADR-0022 — `ENABLE` row-level security, never `FORCE`
**Status:** Accepted · Phase 1 · **Amends ADR-0003 and DATABASE §6**

**Context.** DATABASE §6 originally specified both `ENABLE ROW LEVEL SECURITY`
and `FORCE ROW LEVEL SECURITY` on every tenant-owned table. Implementation
proved this unworkable: `alembic upgrade head` fails at the seed revision with
`new row violates row-level security policy for table "roles"`.

`ENABLE` applies policies to every role except the table owner. `FORCE`
additionally applies them to the owner — which is `nexora_owner`, the role that
runs migrations and seeding. System roles carry `tenant_id IS NULL`, and no
value of `app.tenant_id` can satisfy a `WITH CHECK (tenant_id = <guc>)`
predicate against NULL, so seeding could never succeed.

**Decision.** Use `ENABLE ROW LEVEL SECURITY` only. Keep `nexora_app` as a
non-owner role. Replace the protection `FORCE` was intended to provide with an
explicit test asserting the app role is neither the table owner nor `BYPASSRLS`,
and that an unset `app.tenant_id` returns zero rows.

**Consequences.** Migrations, seeding and owner-run maintenance work normally,
while the application remains fully policed — verified: unset GUC → 0 rows;
GUC set → only that tenant's rows; cross-tenant INSERT → rejected by `WITH
CHECK`. Cost: an owner-credentialed process is no longer constrained by RLS. That
cost is nominal, because such a process can `DROP POLICY` or `ALTER TABLE … NO
FORCE` anyway — `FORCE` never defended against that adversary, it only broke
legitimate work.

The real lesson is the one ADR-0003 already stated and this incident confirms:
RLS is defense-in-depth. Its configuration is subtle enough to get wrong in a way
that is invisible until something fails loudly, which is precisely why
application-level enforcement stays mandatory.

---

## ADR-0023 — Platform identity events are security events, not tenant audit
**Status:** Accepted · Phase 1 · **Resolves the conflict the implementer raised**

**Context.** The Phase 1 handoff requires a `user.registered` audit event and a
verification email dispatched through the outbox. But registration happens
*before* any tenant exists, while `audit_events.tenant_id` and
`outbox_events.tenant_id` are both `NOT NULL`. The requirements cannot all hold.
Correctly identified by the implementer during implementation.

**Decision.**

1. `audit_events.tenant_id` **stays `NOT NULL`.** It is the column every RLS
   policy and the entire Layer 2 filter depend on. A nullable tenant would force
   policies to read `tenant_id IS NULL OR …`, which would make platform rows
   visible to every tenant — trading a schema inconvenience for a data leak.
2. Pre-tenant identity events — `user.registered`, `user.email_verified`,
   `user.password_reset`, `user.password_changed` — are **platform** events, not
   tenant business events. They move to `security_events`, which already has a
   nullable `tenant_id` and is already written outside the business transaction.
   **No schema change.**
3. Tenant-scoped membership events (`member.invitation_accepted`,
   `member.role_changed`) always have a tenant and stay in `audit_events`.
4. `outbox_events.tenant_id` becomes **nullable**, and `outbox_events` is
   **removed from RLS**. It is an internal dispatch queue with no tenant-facing
   read path; RLS on it protects nothing and only obstructs the drain worker. The
   worker reads it with `skip_tenant_filter`.

**Consequences.** The conflict resolves with one nullable column and one dropped
policy, and no weakening of tenant isolation anywhere. Cost: platform identity
events live in a different table from tenant audit, so a "everything that ever
happened to this user" view must union two tables. That is the correct trade —
the two streams have genuinely different lifecycles, different retention needs,
and different transaction semantics (§7 of ARCHITECTURE), and merging them was
the actual mistake.

---

## ADR-0021 — Structural tests as architecture enforcement
**Status:** Accepted · Phase 0

**Context.** Architectural rules stated only in prose decay under delivery
pressure, and two agents working in parallel decay them faster.

**Decision.** Encode the rules as executable tests: no float money, every route
authenticated, every `TenantScoped` model registered for isolation testing,
acyclic module imports, a budget on tenant-filter escape hatches, no repository
imports in routers.

**Consequences.** A violation fails CI at the moment it is introduced, with a
message naming the rule — far cheaper than catching it in review three phases
later. Cost: the guards need maintenance, and a badly written guard is friction
without value. Each one must therefore name the specific defect class it
prevents.
