# Current Phase

**Phase 0 — COMPLETE. Phase 1 — READY FOR CODEX.**

> ### File ownership while both agents are active
>
> | Path | Owner | Rule |
> |---|---|---|
> | `docs/**`, `prompt.md`, `CLAUDE.md`, `AGENTS.md` | **Claude** | Codex appends only to the Codex sections of this file |
> | `backend/**`, `frontend/**`, `infra/**`, `.github/**` | **Codex** | Claude reviews, does not implement |
>
> Codex sections of this file: `# Completed`, `# Files Changed`, `# Tests Added`,
> `# Commands Verified`, `# Known Problems`.
>
> If the handoff conflicts with an architecture document, **stop** and record it
> under `# Known Problems`. Do not invent a third design.

# Current Goal

Implement **Phase 1 — Platform Foundation**: authentication, multi-tenancy,
RBAC, audit, and the frontend shell, leaving the repository runnable and every
verification command green.

**Do not implement any ERP business module.** No products, no inventory, no
sales, no accounting. Phase 1 is the foundation those modules will stand on, and
its isolation guarantees must be proven before anything is built on top.

# Completed

**Phase 0 (Claude):**
- [x] `docs/PROJECT_SPEC.md` — scope, users, flows, success criteria
- [x] `docs/ARCHITECTURE.md` — 22 sections covering the full Phase 0 mandate
- [x] `docs/DATABASE.md` — conventions, numeric types, Phase 1 schema to column level, RLS, triggers
- [x] `docs/API.md` — endpoints, error envelope + code registry, pagination, permissions, rate limits
- [x] `docs/ACCOUNTING.md` — invariants, chart of accounts, posting rules, rounding, 22-case test matrix
- [x] `docs/SECURITY.md` — 12-actor threat model, controls, honest gap register
- [x] `docs/AI.md` — tool architecture, RAG isolation, forecasting/anomaly honesty rules
- [x] `docs/DECISIONS.md` — ADR-0001 … ADR-0021, each with costs stated
- [x] `docs/ROADMAP.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `.env.example`, `.gitignore`

**Phase 1 (Codex):**
- [x] Backend packaging and strict lint/type/test configuration
- [x] Core settings, security, logging, errors, money, pagination, Redis primitives
- [x] Async SQLAlchemy base, unit of work, tenant read/write guard, numeric types
- [x] Phase 1 ORM model definitions (20 tables represented in metadata)
- [x] Nine ordered Alembic revisions with downgrades, triggers, RLS, and seed data
- [x] Refresh-token rotation service with row locking and reuse-family revocation
- [x] JWT/session authentication dependencies and server-side RBAC context resolution
- [x] Redis permission caching keyed by membership `roles_version`
- [x] Branch-scope resolution and reusable permission/branch dependencies
- [x] Atomic tenant onboarding API (tenant + OWNER + branch + warehouse + audit)
- [x] Permission-checked, tenant/branch-scoped branch CRUD with last-branch guard
- [x] Claude Review 1 P0 tenant-guard fixes retained and structurally tested
- [x] Claude Review 2 P1-14/15/16 and ADR-0023 migration/config fixes
- [x] Safe validation/catch-all error envelopes and validated request IDs
- [x] P1-18 closed: auth, RLS GUC, authorization, and services share one request session
- [x] PostgreSQL RLS role/ownership/fail-closed/immutable-grant integration tests
- [x] Permission-protected, tenant-scoped, cursor-paginated audit read API
- [x] Request context/security-header middleware and platform health routes
- [x] Initial unit and structural tests
- [x] Removed stale `types-redis`; startup/OpenAPI auth structural smoke test added
- [x] Role/permission APIs with explicit system-or-tenant read scope and tenant-only writes
- [x] Custom-role privilege-subset guard, immutability/assignment guards, audit, and cache-version bumps
- [x] Role manual-scope registry and live PostgreSQL cross-tenant visibility test
- [x] Member list/detail, role/branch assignment, status, and removal APIs
- [x] Member escalation guards: self-role, permission subset, OWNER assignment, last active OWNER
- [x] Member mutations audit changes and bump `roles_version` when authorization changes
- [x] Next.js 16 frontend foundation pinned to Node 22 LTS
- [x] Responsive product landing page and reusable login/register experience
- [x] Frontend ESLint, strict TypeScript, Vitest, standalone production build, clean npm audit
- [x] Python 3.12 backend/worker and Node 22 frontend container definitions
- [x] Compose stack with migration gate, health checks, PostgreSQL 16, Redis 7, MinIO, Qdrant, MailHog
- [x] Environment-driven non-owner PostgreSQL bootstrap and executable Make verification targets
- [x] Eight-job GitHub Actions pipeline for backend, frontend, migrations, security, and smoke testing
- [x] All 8 required structural architecture guards implemented and passing
- [x] Anonymous-request behavioral sweep proves every protected operation returns 401
- [x] Development refresh-cookie delivery fixed for HTTP; rotation/reuse regression suite green
- [x] Removed unused schema that exposed a plaintext `refresh_token` field
- [x] Redis-backed Next.js BFF with signed opaque browser sessions and AES-GCM credential storage
- [x] Double-submit CSRF enforcement on state-changing BFF proxy operations
- [x] Functional login/register forms and authenticated responsive workspace shell
- [x] BFF refresh/retry, tenant-switch token replacement, and logout session cleanup
- [x] Permission-protected current-tenant profile/settings read and audited update APIs
- [x] Tenant bootstrap exception explicitly registered; all post-onboarding queries ID-scoped
- [x] Permission-checked warehouse CRUD with tenant isolation, branch scope, and audit events
- [x] Invitation literal route precedence fixed; redemption verified against migration 0011 RLS
- [x] Live frontend organization onboarding/switcher and branch list/create management shell
- [x] Distributed BFF refresh single-flight lock with owner-safe release and stale-session recheck
- [x] Refresh bounds ordered and asserted at load; timeout separated from failure so a slow refresh no longer logs the user out
- [x] Live team invitation UI with server-provided role selection and permission-safe degradation
- [ ] Migrations, repositories/services/API, integration suites, frontend, infrastructure

# Architecture Decisions

21 ADRs in `docs/DECISIONS.md`. The ones that bind Phase 1 directly:

| ADR | Decision |
|---|---|
| 0002 | Shared schema + `tenant_id` discriminator |
| 0003 | RLS is defense-in-depth; app enforcement is mandatory |
| 0004 | UUIDv7 primary keys |
| 0005 | Argon2id password hashing |
| 0006 | Opaque rotating refresh tokens with reuse detection |
| 0007 | 15-min access tokens + Redis session denylist |
| 0008 | Permissions resolved server-side, cached by `roles_version` |
| 0009 | Cross-tenant access returns 404, not 403 |
| 0014 | BFF token custody on the frontend |
| 0015 | Money serialized as JSON strings |
| 0019 | Real PostgreSQL in tests; never SQLite |
| 0021 | Structural tests enforce architecture |

# Database Changes

None yet — Phase 1 migrations are Codex's first deliverable.
Target schema is specified to column level in `docs/DATABASE.md` §3.

# API Changes

None yet. Target contract is `docs/API.md` §5.

# Files Changed

Phase 0 (Claude): all files listed under `# Completed`.

Phase 1 (Codex, in progress):
- `backend/pyproject.toml`
- `backend/alembic.ini`, `backend/alembic/**`
- `backend/app/core/**`
- `backend/app/db/**`
- `backend/app/api/**`
- `backend/app/main.py`
- `backend/app/modules/{auth,tenancy,branches,rbac,audit,platform,idempotency,outbox}/**`
- `backend/app/modules/members/**`
- `backend/tests/unit/**`
- `backend/tests/structural/test_models.py`
- `backend/tests/structural/{test_application_startup,test_manual_tenant_scope}.py`
- `backend/tests/isolation/**`
- `backend/tests/integration/test_rls.py`
- `infra/postgres/init/01-roles.sql`
- `frontend/**`
- `backend/Dockerfile`, `backend/.dockerignore`, `backend/app/workers/**`
- `frontend/Dockerfile`, `frontend/.dockerignore`
- `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`
- `infra/postgres/init/01-roles.sh`
- `backend/tests/structural/test_architecture_guards.py`
- `backend/tests/integration/branches/test_warehouses.py`
- `frontend/src/components/workspace-shell.tsx`, `frontend/src/components/workspace-shell.test.tsx`
- `frontend/src/lib/bff-session.ts`, `frontend/src/lib/bff-upstream.ts`
- `frontend/src/lib/bff-session.test.ts`, `frontend/src/lib/bff-refresh.test.ts`
- `.github/workflows/ci.yml`
- `.env.example`, `docs/API.md` §4.1 (Claude, BUILD 14)

# Tests Added

None yet.

Phase 1 (Codex, initial slice):
- 11 core security, refresh rotation/reuse, money, and cursor-pagination unit tests
- 2 structural metadata tests for float types and tenant-leading indexes
- 3 structural listener-registration tests (Claude)
- 6 error/config/request-ID safety tests
- 2 tenant-onboarding mass-assignment/timezone validation tests
- 3 PostgreSQL RLS configuration and immutable-audit privilege tests
- 2 audit date-range/cursor validation tests
- 2 application startup/business-route authentication structural tests
- 2 role manual-tenant-scope structural tests
- 1 live PostgreSQL role cross-tenant visibility test
- 3 member escalation-guard unit tests (self-role, unheld permission, last OWNER)
- 1 frontend component accessibility test
- 6 structural checks for registry coverage, acyclic imports, router layering, SQL safety, secret schemas, and escape-hatch budget
- 1 behavioral anonymous-access sweep across every protected OpenAPI operation
- 2 live tenant-settings tests for cross-tenant isolation and immutable-field rejection
- 3 warehouse integration tests covering CRUD, cross-tenant access/linking, and mass assignment
- 1 frontend onboarding-state test; Vitest alias made safe for workspace paths containing spaces
- 5 real-Redis BFF refresh-lock tests covering exclusivity, release, session separation, and lock ownership
- 6 BFF holder/waiter tests: bound ordering, slow-holder handoff, timeout preserving the session, upstream rejection clearing it, refresh abort, vanished session (4 verified failing pre-fix)
- 1 frontend team-invitation test asserting the server role id and email payload

# Commands Verified

```
git init                          ✅
python3 --version → 3.12.6        ✅
node --version    → v25.2.0       ✅
docker --version  → 29.6.2        ✅
psql --version    → 16.14         ✅
```

Codex initial backend slice:
```
.venv/bin/ruff format .                         ✅ 46 files unchanged on final run
.venv/bin/ruff check .                          ✅ All checks passed
.venv/bin/mypy app                              ✅ 42 source files, no issues
.venv/bin/pytest tests/unit tests/structural -q ✅ 11 passed, 1 dependency deprecation warning
```

Codex migration/auth slice:
```
.venv/bin/alembic history                       ✅ single linear chain, 9 revisions
.venv/bin/ruff check .                          ✅ All checks passed
.venv/bin/mypy app                              ✅ 45 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                  ✅ 13 passed; Python 3.14 dependency warnings
docker run postgres:16-alpine                   ❌ Docker daemon not running
pg_isready localhost:5432 / :55432              ❌ no local PostgreSQL server
```

Codex authz dependency slice:
```

Codex review-fix/onboarding/branches slice:
```

Codex single-session/RLS slice:
```

Codex audit-feed slice:
```
.venv/bin/ruff format/check                        ✅ 84 files / all checks passed
.venv/bin/mypy app                                 ✅ 61 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                    ✅ 31 passed; dependency warnings
```

Codex role-management/startup-guard slice:
```
.venv/bin/ruff format/check                        ✅ 83 files / all checks passed
.venv/bin/mypy app                                 ✅ 66 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                    ✅ 35 passed; dependency warnings
DATABASE_URL=... .venv/bin/python -m pytest tests/integration -q
                                                    ✅ 8 passed; dependency warnings
```

Codex member-management slice:
```
.venv/bin/ruff format/check                        ✅ 90 files / all checks passed
.venv/bin/mypy app                                 ✅ 72 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                    ✅ 38 passed; dependency warnings
DATABASE_URL=... .venv/bin/python -m pytest tests/integration -q
                                                    ✅ 8 passed; dependency warnings
```

Codex frontend-foundation slice:
```
npm run lint                                      ✅ zero warnings
npm run typecheck                                 ✅ no TypeScript errors
npm run test                                      ✅ 1 test passed
npm run build                                     ✅ Next.js 16.3.3; 4 static routes
npm audit --audit-level=high                      ✅ 0 vulnerabilities
Node runtime contract                             ✅ package engines pinned to 22.x
```

Codex runtime/CI slice:
```
docker compose config --quiet                     ✅ valid Compose configuration
sh -n infra/postgres/init/01-roles.sh              ✅ valid bootstrap script
CI workflow parse                                 ✅ 8 jobs present
.venv/bin/ruff format --check / ruff check         ✅ 107 files / all checks passed
.venv/bin/mypy app                                 ✅ 77 source files, no issues
.venv/bin/pytest tests/unit tests/structural -q    ✅ 46 passed; dependency warnings
frontend lint/typecheck/test/build                 ✅ all passed
docker info                                        ❌ daemon socket unavailable
```

Codex structural/auth-regression slice:
```
.venv/bin/ruff format/check                        ✅ 103 files / all checks passed
.venv/bin/mypy app                                 ✅ 77 source files, no issues
.venv/bin/pytest tests/unit tests/structural -q    ✅ 53 passed; dependency warnings
alembic upgrade head                               ✅ migration 0010 applied
.venv/bin/pytest tests/integration -q              ✅ 35 passed; dependency warnings
```

Codex frontend-BFF slice:
```
npm run lint                                      ✅ zero warnings
npm run typecheck                                 ✅ route generation + strict TS passed
npm run test                                      ✅ 1 test passed
npm run build                                     ✅ 9 routes; static + dynamic BFF/workspace
npm audit --audit-level=high                      ✅ 0 vulnerabilities
```

Codex tenant-settings slice:
```
.venv/bin/ruff format/check                        ✅ 109 files / all checks passed
.venv/bin/mypy app                                 ✅ 79 source files, no issues
.venv/bin/pytest tests/unit tests/structural -q    ✅ 53 passed; dependency warnings
.venv/bin/pytest tests/integration -q              ✅ 53 passed; dependency warnings
```

Codex warehouse/invitation-integration slice:
```
.venv/bin/ruff format --check / ruff check         ✅ 123 files / all checks passed
.venv/bin/mypy app                                 ✅ 89 source files, no issues
.venv/bin/pytest tests/unit tests/structural -q    ✅ 53 passed; dependency warnings
alembic upgrade head                               ✅ migration 0011 applied
.venv/bin/pytest tests/integration -q              ✅ 72 passed; dependency warnings
```

Codex frontend organization/branch-management slice:
```
npm run lint                                      ✅ zero warnings
npm run typecheck                                 ✅ route generation + strict TS passed
npm run test                                      ✅ 2 tests passed
npm run build                                     ✅ Next.js 16.3.3; 9 routes
```

Codex BFF refresh single-flight slice:
```
npm run lint                                      ✅ zero warnings
npm run typecheck                                 ✅ route generation + strict TS passed
npm run test                                      ✅ 7 passed across 3 files; real Redis lock exercised
npm run build                                     ✅ Next.js 16.3.3; 9 routes
npm audit --audit-level=high                      ✅ 0 vulnerabilities
```

Codex frontend team-invitation slice:
```
npm run lint                                      ✅ zero warnings
npm run typecheck                                 ✅ route generation + strict TS passed
npm run test                                      ✅ 8 passed across 3 files
npm run build                                     ✅ Next.js 16.3.3; 9 routes
npm audit --audit-level=high                      ✅ 0 vulnerabilities
```
DATABASE_URL=... .venv/bin/python -m pytest tests/integration -q
                                                    ✅ 7 passed
.venv/bin/ruff format/check                        ✅ 80 files / all checks passed
.venv/bin/mypy app                                 ✅ 58 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                    ✅ 29 passed; dependency warnings
```
alembic downgrade base → upgrade head              ✅ all 9 revisions
alembic check                                      ✅ no new upgrade operations
.venv/bin/ruff format/check                        ✅ 79 files / all checks passed
.venv/bin/mypy app                                 ✅ 58 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                    ✅ 29 passed; dependency warnings
```
.venv/bin/ruff format .                         ✅ 63 files unchanged
.venv/bin/ruff check .                          ✅ All checks passed
.venv/bin/mypy app                              ✅ 48 source files, no issues
.venv/bin/python -m pytest tests/unit tests/structural -q
                                                  ✅ 13 passed; Python 3.14 dependency warnings
```

# Known Problems

**RESOLVED — P1-33 / P1-34 / P1-35 concurrent BFF refresh.** Parallel BFF
requests no longer submit the same rotating refresh token. A Redis single-flight
lock is owner-token protected, released atomically only by its holder, and
followed by a session recheck inside the critical section.

Review 13 found the guarantee was conditional on timing that nothing enforced.
Both halves are now closed (BUILD 14): the upstream refresh is aborted at
`BFF_REFRESH_TIMEOUT_MS`, strictly below the lock TTL, so the lock can no longer
lapse under a running refresh (**P1-35**); and the waiter budget now exceeds the
lock TTL while a timeout is reported as its own outcome, so a slow-but-successful
refresh returns a retryable `503` instead of destroying the session (**P1-34**).
The ordering `timeout < lock TTL < wait` is asserted at module load, not
documented. Real-Redis tests for both run in frontend CI.

**RESOLVED — P2-6 Role manual tenant scoping.** Role reads explicitly include
only global system roles plus the active tenant's custom roles; resource writes
match the active tenant only. Structural registry checks and a live two-tenant
PostgreSQL visibility test pin this exception to the normal `TenantScoped` rule.

**P2 — Node 25 is not an LTS release.** Next.js supports LTS lines; pin the
Docker image and CI to **Node 22 LTS** rather than inheriting the host's Node 25.
Local development on 25 is fine, but the build that ships must match CI.

**RESOLVED by ADR-0023 — pre-tenant registration audit/outbox.**
The Phase 1 handoff requires `user.registered` in the transactional business
audit stream and requires verification email through the transactional outbox.
However, registration explicitly supports users with no membership or tenant,
while `audit_events.tenant_id` and `outbox_events.tenant_id` are both `NOT NULL`.
Pre-tenant identity events now use `security_events`; `outbox_events.tenant_id`
is nullable and the internal outbox is outside tenant-facing RLS, as directed.

**Environment — Docker daemon unavailable, local PostgreSQL fallback working.**
The full downgrade/upgrade/drift cycle now passes against PostgreSQL 16 in the
dedicated `nexora_codex_verify` scratch database. Docker Compose verification
still awaits Docker Desktop.

**Architecture conflict — pre-auth membership discovery under RLS.** The login
response must return all memberships, but `memberships` RLS only permits rows
matching `app.tenant_id`; no tenant is active before login, so the application
role sees zero rows and cannot construct the required response. A safe design
needs an architect-approved bootstrap mechanism (for example a narrowly scoped
SECURITY DEFINER function or a separate signed user-context RLS policy). Codex
will not use owner credentials or disable RLS in the login path.

**Architecture conflict — verification/reset tokens through the outbox.** Token
tables correctly store only SHA-256 hashes, while deferred email delivery needs
the raw one-time token after commit. Putting it directly in `outbox_events.payload`
would persist a plaintext credential. The architecture needs an approved secret
envelope/encryption mechanism or a distinct delivery design before registration,
verification, reset, invitation, and resend email flows can be completed safely.

# Pending Work

All of Phase 1, per the handoff below.

---

---

# CLAUDE BUILD 14 — P1-34, P1-35, P2-36 closed

Both P1s from Review 13 are fixed. This is `frontend/**`, which the ownership
table assigns to Codex; done on explicit instruction, recorded here so the lane
crossing is visible rather than silent — same as P1-25.

```
npm run lint       clean
npm run typecheck  clean
npm run test       14 passed across 4 files (real Redis)
npm run build      Next.js 16.3.3; 9 routes
```

## The fix

The three bounds are now named, configurable, and **ordered by an assertion at
module load** rather than by a comment:

```ts
if (!(REFRESH_TIMEOUT_MS < REFRESH_LOCK_TTL_MS && REFRESH_LOCK_TTL_MS < REFRESH_WAIT_MS)) {
  throw new Error("BFF refresh bounds must satisfy timeout < lock TTL < wait");
}
```

| Bound | Was | Now |
|---|---|---|
| Upstream refresh | unbounded | **10 s**, `AbortSignal.timeout` |
| Lock TTL | 15 s | 15 s |
| Waiter budget | 2.5 s | **20 s** |

That assertion is the actual deliverable. The individual numbers matter less
than the fact that the relationship between them can no longer be broken —
including by an env override, since all three read from the environment and the
check runs after they are resolved.

**P1-35** — the refresh now carries `signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS)`,
so the holder is guaranteed to release or fail before the lock can lapse. An
aborted refresh **fails closed**: the backend may or may not have rotated before
we gave up, so the stored token can no longer be trusted, and presenting it again
would be indistinguishable from replay.

**P1-34** — `rotate` returns a discriminated `RefreshOutcome` instead of
`string | null`:

```ts
{ status: "refreshed"; accessToken: string } | { status: "failed" } | { status: "timeout" }
```

Only `failed` clears the session. `timeout` returns `503` with `Retry-After: 1`
and leaves the session alone. Collapsing those two states into one `null` was the
whole defect — the timing mismatch only made it reachable.

New code `REFRESH_IN_PROGRESS`, registered in `API.md` §4.1 with the note that it
is the one auth code that is not terminal. Clients must branch on the code, not
on "a refresh did not yield a token" — that inference is what made a slow backend
look like a revoked session.

## Tests — six, and I checked they fail on the old code

`bff-refresh.test.ts` covers the holder/waiter interaction that `bff-session.test.ts`
does not reach. Written against a reconstruction of the pre-fix tree, four fail,
each for its own reason:

```
× keeps the bounds ordered refresh < lock TTL < wait      constants absent
× leaves the session intact when the wait times out       expected 401 to be 503   (2562ms)
× aborts a refresh that outruns its timeout               test timeout            (10005ms)
× reports a vanished session as failed                    expected null to equal {status:'failed'}
```

The two middle lines are the findings themselves, measured: **2562 ms** is the
old 2.5 s budget expiring and clearing a live session; **10005 ms** is the
unbounded refresh never returning at all.

The test file shrinks the three bounds through the same env vars production
reads, so the ordering invariant still holds under test — the timings are
smaller, the relationship between them is not weakened.

One test (`hands a waiter the token published by a holder slower than the lock
TTL`) passed on the old code in 126 ms, for the wrong reason: with the constants
absent its `setTimeout` delay was `NaN` and fired immediately. It is a valid
forward test but it is not a regression pin, and it is worth remembering that a
test can pass on broken code by never running the scenario it names.

`vitest.setup.ts` still mocks nothing globally; the `next/headers` mock is
per-file because each file needs its own cookie jar. Anything else reaching
`readSession` will need the same six lines.

## Also changed

- `.env.example` — the three bounds documented with the invariant and why each
  half of it exists.
- `docs/API.md` §4.1 — `REFRESH_IN_PROGRESS` registered.

## Still open, unchanged

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI unaffected) | P2 |
| P2-32 | per-IP limits collapse behind a proxy | **pre-production blocker** |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

No P0 or P1 open.

**Next, unchanged: the outbox dispatch worker.** Verification, reset and
invitation mail all queue and are never sent, so every one of those flows is
still unusable by a real user. It is the largest remaining gap in Phase 1.

---

# CLAUDE REVIEW 13 — BFF single-flight lock reviewed; two P1 left open

The lock itself is right. `SET NX PX` for acquisition, a random owner token, a
compare-and-delete Lua release, and the recheck inside the critical section are
each the correct primitive, and the release script is the detail most
implementations get wrong. The five tests use real Redis, and CI now stands one
up. I re-ran everything claimed and it holds:

```
npm run lint       clean
npm run typecheck  clean
npm run test       7 passed across 3 files (real Redis)
```

But the mechanism is built out of **three timeouts that were never reconciled
with each other**, and two of the three orderings are wrong. The lock prevents
the replay it was written for; it introduces a second path to the same
user-visible outcome, and leaves a third open.

The three values, as they stand:

| Bound | Value | Where |
|---|---|---|
| Waiter budget | 25 × 100 ms = **2.5 s** | `bff-session.ts:128` |
| Lock TTL | **15 s** | `bff-session.ts:109` |
| Upstream refresh | **unbounded** | `bff-upstream.ts:52` |

The correct ordering is `waiter budget > lock TTL > refresh timeout`. The actual
ordering is the reverse of it at both ends.

---

## P1-34 — a waiter that times out logs the user out

**Files:** `bff-session.ts:127-137` · `bff-upstream.ts:79-82`

`awaitRotatedToken` gives up after 25 polls at 100 ms. Measured, not inferred:

```
>>> waiter returned null after 2547ms
>>> lock TTL is 15000ms; upstream refresh fetch has no timeout
```

The waiter's `null` is indistinguishable from a failed refresh, and
`proxyUpstream:81` treats it as one:

```ts
if (!token) { await clearSession(); return ... 401 SESSION_REVOKED }
```

So if the holder's refresh takes longer than **2.55 s** — a cold backend, a slow
DB, one network hiccup — every queued request calls `clearSession()`. That drops
the browser's session cookie *and* deletes the Redis session key. Depending on
which side of the holder's `writeSession` it lands, it either destroys the
freshly rotated session or leaves it orphaned in Redis with the cookie gone.

Either way the user is logged out — by a refresh that **succeeded**. That is the
same outcome P1-33 was opened to fix, reached by a different route. A 2.5 s
budget guarding a 15 s lock is not a safety margin; it is a guarantee that any
slow refresh becomes a logout.

**Fix — two parts, both needed.**

1. The waiter must not outlive its usefulness *before* the holder does. Its
   budget has to exceed the lock TTL plus a margin, so it never gives up while a
   holder can still legitimately be working.
2. `rotate` must distinguish **"the wait timed out"** from **"the refresh
   failed"**. Only the second may clear the session. A timeout is a retryable
   condition and should surface as `503` with `Retry-After`, leaving the session
   intact — the request failed, the session did not.

Collapsing those two states into one `null` is the actual defect; the timing
mismatch is what makes it reachable.

## P1-35 — nothing bounds the critical section to the lock TTL

**File:** `bff-upstream.ts:52-54`

The refresh `fetch` carries no `signal`. Nothing stops it exceeding the lock's
15 s TTL, and the lock is not renewed while it runs.

At 15 s the lock expires under the still-running holder. The next request
acquires it cleanly and performs the recheck on line 50 — which **passes**,
because the first holder has not published anything yet, so the stored access
token is still the stale one. It proceeds to `fetch` with the same refresh
token. Reuse detection fires and the family is revoked.

The recheck cannot catch this. It compares against what the holder has
*published*, and the whole condition is that the holder has not published yet.
The single-flight guarantee therefore holds only *if the refresh finishes inside
15 s*, and nothing in the code enforces that premise.

**Fix:** `signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS)` with the timeout
strictly below the lock TTL, so the holder is guaranteed to have released or
failed before the lock can lapse. A lock TTL that does not bound the operation it
protects is decoration.

## P2-36 — the tests pin the primitive, not the mechanism

`bff-session.test.ts` covers `acquireRefreshLock` / `releaseRefreshLock` well:
exclusivity, re-acquisition, per-session independence, and ownership on release.
All five are real assertions against real Redis.

None of them touch `rotate()` or `awaitRotatedToken`. The thing under test is
"Redis `SET NX` is exclusive" — which was never in doubt. The behaviour the
finding is about is the *interaction* between holder and waiter, and it is
untested.

The reason it is untested is mechanical: `vitest.setup.ts` mocks nothing, so
`next/headers` `cookies()` is unavailable and any function reaching `readSession`
cannot be called from a test at all. I confirmed both P1s above only by adding a
temporary `next/headers` mock, which is what the suite needs permanently.

Required, once P1-34 and P1-35 are fixed:

- holder slower than the waiter budget → waiter still returns the rotated token,
  and the session survives
- refresh genuinely rejected upstream → session cleared, `401`
- wait timed out → `503`, session **not** cleared
- refresh exceeding the lock TTL → aborted, not left running

The first and third are the ones that would have caught this. The same lesson as
BUILD 10: a test that has never failed for the right reason is not yet a test.

## Note on the handoff entry

`# Known Problems` lists P1-33 as RESOLVED and `# Completed` ticks the lock. The
lock is real and the entry is fair, but it is now qualified above — the
concurrent-replay window is narrowed, not closed, while P1-35 stands.

## Open

**All three closed in BUILD 14 below, at your direction.**

| # | Finding | Severity |
|---|---|---|
| P1-34 | waiter timeout clears a live session | **P1 — fixed** |
| P1-35 | refresh unbounded; lock TTL can lapse mid-flight | **P1 — fixed** |
| P2-36 | no test covers holder/waiter interaction | P2 — fixed |
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI unaffected) | P2 |
| P2-32 | per-IP limits collapse behind a proxy | **pre-production blocker** |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

Both P1s are in `frontend/**`, which the ownership table assigns to Codex. Not
implementing them per that rule — they are small and surgical, so say the word if
you would rather I close them directly, as with P1-25.

Phase 1 priority is unchanged otherwise: the **outbox dispatch worker** is still
the largest gap — verification, reset and invitation mail all queue and are never
sent, so every one of those flows is unusable by a real user.

---

# CLAUDE BUILD 12 — invitations; Phase 1 backend API surface complete

Every endpoint group in `API.md` §5 now exists: auth, tenants, branches,
members, roles, invitations, audit, platform.

```
ruff format --check .   129 files
ruff check .            clean
mypy app                clean (85 files)
pytest --cov            86.07% ✅   122 passed
alembic check           no drift
```

## Added

| File | Contents |
|---|---|
| `app/modules/invitations/**` | **new** — schemas, repository, service, router, events |
| `alembic/versions/0011_invitation_redemption.py` | **new** — token-scoped RLS policy |
| `tests/integration/invitations/test_invitations.py` | **new** — 16 tests |

## Security properties, and why

**The role comes from the stored invitation, never the request.** `accept` is
unauthenticated and token-bearing; a `role_id` in that body would be self-service
privilege escalation with no credential at all. `InvitationAccept` has no such
field and `extra="forbid"` rejects one — pinned by
`test_accept_cannot_choose_its_own_role`.

**The inviter cannot invite into a role richer than their own.** The same subset
rule as `PATCH /members/{id}/roles`. Without it, invitations are a one-line
bypass of the guard on that endpoint.

**An existing account is linked, never re-credentialed.** `_resolve_user` returns
the existing user untouched and ignores the supplied password. Otherwise anyone
who could invite a known address would hold a password-reset primitive for it.

**Redeem, revoke and resend are single-use / state-checked**, and unknown,
revoked, expired and already-accepted all return one identical message — telling
them apart tells an attacker whether a token was ever real.

---

## Migration 0011 — the same shape of problem as 0010

Accept failed with `TOKEN_INVALID` on a valid token. `invitations` carries the
RLS tenant policy, but redemption is a public request from someone with no
membership and no tenant context — and **the invitation is the thing that says
which tenant they are joining**. The tenant policy cannot be satisfied, because
satisfying it needs the answer the query is asking for.

The bearer token is the authorization here: 256 bits of CSPRNG entropy,
delivered by mail, stored only as SHA-256. So the policy is keyed on the token
hash:

```sql
CREATE POLICY invitation_redeem ON invitations
USING      (token_hash = NULLIF(current_setting('app.invitation_token', true), ''))
WITH CHECK (token_hash = NULLIF(current_setting('app.invitation_token', true), ''));
```

It exposes **exactly the one row the caller already holds the secret for** and
widens nothing else. `WITH CHECK` permits marking it accepted; `token_hash` is
unchanged on that path, so an invitation can never be rewritten into someone
else's.

This is now twice that a legitimate pre-tenant operation collided with the RLS
tenant policy (0010 memberships, 0011 invitations). The pattern is worth stating
plainly for later phases: **any flow that must run before a tenant is selected
needs its own narrow, differently-keyed policy** — not a relaxation of the tenant
one. Both fixes here are keyed on something the caller has already proven (their
user id from a signed token; a token hash they hold), and both are read-scoped.

## The escape-hatch guard, again

It flagged all three new `skip_tenant_filter` uses. Two of them
(`existing_membership`, `member_emails`) are explicitly parameterised by the
tenant id read off the *verified* invitation — scoped, just not by ambient
context. All three are now in the budget with that reasoning recorded.

That guard has now caught every batch of work I have done. It is the highest
value-per-line test in the suite.

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI unaffected) | P2 |
| P2-32 | per-IP limits collapse behind a proxy | **pre-production blocker** |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

No P0 or P1 open.

**Phase 1 backend is functionally complete.** What remains for the phase:

1. **Outbox dispatch worker** — verification, reset and invitation mail all queue
   and are never sent. Every one of those flows is unusable by a real user until
   this exists. Highest priority.
2. Frontend (yours, in progress).
3. Authenticated-default rate limits (`API.md` §9) — only the auth surface is
   covered.
4. The P2 test-quality findings above.

---

# CLAUDE BUILD 11 — rate limiting enforced

`SlidingWindowRateLimiter` was well built and **wired to nothing** — the same
defect shape as the unimported tenant guard: a security control present as dead
code, with the limits specified in `API.md` §9 and enforced nowhere. It sat on
the auth surface, which is the one an unauthenticated attacker can reach.

```
ruff check .   clean
mypy app       clean (79 files)
pytest --cov   85.73% ✅   104 passed
```

## Added

| File | Contents |
|---|---|
| `app/modules/auth/ratelimit.py` | **new** — declarative limits + `AuthRateLimiter` |
| `app/modules/auth/router.py` | limits applied to login, register, forgot-password, resend-verification |
| `tests/integration/auth/test_rate_limits.py` | **new** — 5 tests |

Observed behaviour on eight consecutive failed logins:

```
[401, 401, 401, 401, 423, 429, 429, 429]
                      ^     ^
          account backoff   sliding-window limiter
```

Both layers engage, and they are independent: the per-account backoff bounds a
targeted guess even if Redis is unavailable, while the limiter bounds volume even
against an account that does not exist.

**Limits fail closed** (SECURITY.md §6). A `RedisError` yields `503`, not a pass —
an attacker who can degrade Redis must not thereby remove the brute-force
ceiling. Read endpoints make the opposite trade; auth does not.

`resend-verification` shares forgot-password's budget: both send mail to an
address the caller merely asserts, so both are usable to spam a third party.

## Test isolation

Enabling limits broke 29 integration tests instantly — every test reaches the
app from `127.0.0.1`, so they share one per-IP bucket and the third registration
onwards 429s. The suite would have been testing the limiter rather than the
feature under test.

The shared `client` fixture now builds the app with `rate_limit_enabled=False`,
and `test_rate_limits.py` builds its own app with limiting on and clears the
Redis keys per test — so a limit already tripped elsewhere cannot make it pass
for the wrong reason.

---

## P2-32 — per-IP limits will collapse into one bucket behind a proxy

**Files:** `app/modules/auth/router.py` (`_client_ip`), `app/main.py`

`_client_ip` returns `request.client.host` and nothing anywhere honours
`X-Forwarded-For`. Under the deployment model in `ARCHITECTURE.md` §20 and
`SECURITY.md` §11 — TLS terminating at a reverse proxy — that address is **the
proxy's**, identical for every user.

Consequences, both bad:

- every per-IP limit becomes a single global bucket, so normal aggregate traffic
  locks out all users at once;
- the per-IP control believed to be in place provides no per-attacker limit at
  all.

The same flaw makes `auth_sessions.ip` and `security_events.ip` record the proxy
for every row, which quietly destroys the forensic value of the security stream.

**Fix:** run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy CIDR>`,
or parse `X-Forwarded-For` with an explicit trusted-hop count. Never trust the
header unconditionally — it is client-supplied, so an unguarded implementation
turns a per-IP limit into a per-request-header limit, which is no limit at all.

Not urgent in development (no proxy) but **must be closed before Phase 12**, and
it belongs in the Phase 11 security review.

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI unaffected) | P2 |
| P2-32 | per-IP limits collapse behind a proxy | **P2, pre-production blocker** |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

No P0 or P1 open.

**Remaining for Phase 1:** invitations (`API.md` §5.5) is the last missing
module, plus the outbox dispatch worker (mail queues but is never sent) and the
frontend. Authenticated-default and AI limits from `API.md` §9 are not yet
applied — only the auth surface is covered.

---

# CLAUDE BUILD 10 — auth surface complete

All twelve endpoints in `API.md` §5.1 now exist:

```
change-password  forgot-password  login     logout      logout-all  me
refresh          register         resend-verification   reset-password
switch-tenant    verify-email
```

```
ruff format --check .   116 files
ruff check .            clean
mypy app                clean (78 files)
pytest --cov            84.39% ✅   99 passed
```

## Added

| File | Contents |
|---|---|
| `app/modules/outbox/service.py` | **new** — `OutboxService.enqueue_email` |
| `app/modules/auth/service.py` | `issue_verification_token`, `verify_email`, `issue_password_reset`, `reset_password`, `change_password` |
| `app/modules/auth/repository.py` | token add/consume + `invalidate_outstanding_reset_tokens` |
| `app/modules/auth/schemas.py` | `EmailRequest`, `VerifyEmailRequest`, `ResetPasswordRequest`, `ChangePasswordRequest` |
| `tests/integration/auth/test_password_and_verification.py` | **new** — 11 tests |

## Decisions worth knowing

**Mail is enqueued inside the token's transaction** (ADR-0020). My first cut
enqueued from the router after the service committed; that splits the guarantee —
a crash between them leaves a live reset token with no mail (user stranded) or
mail with no token (dead link). Both now commit together.

**`forgot-password` and `resend-verification` always return 202**, with the
existence check inside the service returning `None` rather than raising. Keeping
the enumeration decision at the boundary means a future refactor of the service
cannot accidentally leak it through an exception type.

**A reset revokes every session; a change revokes all but the caller's.** A reset
answers "someone may have my credentials", so the attacker's sessions must go
too. A deliberate change shouldn't log you out of the device in your hand.

**Issuing a reset token retires outstanding ones** — otherwise every reset email
ever sent stays live for its full TTL.

**Invalid, expired and already-used tokens return one identical message.**
Distinguishing them tells an attacker whether a token was ever real.

## The escape-hatch guard earned its keep

Your `test_tenant_filter_escape_hatch_matches_reviewed_budget` failed on my two
new `skip_tenant_filter` uses:

```
Tenant escape-hatch budget changed:
added={('modules/auth/repository.py', 'consume_reset_token'),
       ('modules/auth/repository.py', 'consume_verification_token')}
```

Exactly the intended behaviour — new uses surface for review instead of
accumulating. Both are legitimate (identity tokens have no tenant and are
redeemed before any tenant context exists) and are now in the budget **with the
reason recorded**, not silently waved through.

## A mistake worth recording

Two of my patches were applied by Python string-replace, and one silently did not
match because ruff had already reformatted the target line. The result: the
verification flow persisted its token but never enqueued its mail — a 202 with no
email, which no unit test would catch. It was found only because an integration
test read the outbox.

The lesson is not "be careful"; it is that **a `str.replace` that fails is
indistinguishable from one that succeeds**. Structural edits need a tool that
errors on a missed match.

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI unaffected) | P2 |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

P2-23 is closed — you added `test_every_protected_operation_rejects_anonymous_requests`,
and I extended both allowlists for the four new public recovery endpoints, each
with its justification.

No P0 or P1 open.

**Remaining for Phase 1:** invitations (`API.md` §5.5) — the last missing module —
then the frontend against a real API, then rate limiting (`API.md` §9) which is
specified and not yet enforced on the auth endpoints. The outbox has no dispatch
worker yet, so mail queues but is never sent; that is fine for Phase 1 but should
not reach Phase 12.

---

# CLAUDE BUILD 9 — CI would have failed; auth tests + two 500s fixed

Your CI workflow is good — 8 jobs, Node 22 LTS pinned, `ALTER DEFAULT
PRIVILEGES` correctly ordered before migrations, and everything it references
(`docker-compose.yml`, the `migrate` service, all four frontend scripts) exists.

But I ran its exact commands, and **`backend-tests` would have failed**:

```
FAIL Required test coverage of 80% not reached. Total coverage: 61.91%
```

54 tests passed while a third of the app was untested — most of it the auth
router I had just written and verified only by hand. That was my gap.

## Now

```
ruff format --check . / ruff check .   clean
mypy app                                clean (77 files)
pytest --cov --cov-fail-under=80        83.66% ✅   81 passed
```

Coverage 61.91% → **83.66%**; tests 54 → **81**.

## Added

| File | Contents |
|---|---|
| `tests/integration/conftest.py` | async client + `register_and_login` / `create_organization` / `tenant_headers` helpers |
| `tests/integration/auth/test_auth_flows.py` | 17 tests — enumeration resistance, token custody, rotation/reuse, revocation, tenant selection, validation |
| `tests/integration/rbac/test_authorization_guards.py` | 10 tests — self-modification guards, last-owner, cross-tenant 404s, role management |

The conftest establishes the pattern for P2-30: **`httpx.AsyncClient` over
`ASGITransport` in one loop, never `TestClient`.** Build the remaining suites on
this.

Notable coverage: the reuse-detection test asserts the *legitimate* holder is
locked out too — that is the intended behaviour and worth pinning, since a future
"fix" to make it friendlier would silently remove the protection. The
migration-0010 regression is pinned as
`test_membership_is_visible_after_creating_an_organization`.

## P1-27 — `/members/` ambiguous join (fixed)

`select(Membership, User).join(User)` → `AmbiguousForeignKeysError`, because
`memberships` has two FKs to `users`. Both call sites now pass the onclause
explicitly. `/members/` and `/members/{id}` return 200.

## P1-31 — `PATCH /api/v1/roles/{id}` returned 500 (fixed)

**File:** `app/modules/rbac/role_service.py`

`update()` built its response **after** `service_transaction` committed.
`roles.updated_at` is maintained by the `trg_roles_updated_at` trigger, so the
in-memory value is stale after the UPDATE; reading it post-commit triggers a lazy
refresh outside the async greenlet:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called;
can't call await_only() here.
```

Response is now constructed inside the transaction. `create()` and `delete()`
were already fine.

**The pattern worth internalising:** P1-27 and P1-31 are the same defect class as
the members bug — endpoints that were written, type-checked, linted and never
once called against a database. Every one of them was found by the *first* test
that exercised it. Integration coverage is not paperwork here; it is the only
thing that has caught these.

## Two of my own test bugs, for the record

- Asserted a password did not appear in a validation response using the literal
  `"short"` — which matches pydantic's own `string_too_short` error type. False
  failure; the sanitisation was correct all along. Now uses a distinctive value
  and additionally asserts `"input"` is absent.
- Assumed `/branches/` returned a bare list; it is offset-paginated under
  `items` per API.md §3.

Both are the reason a test that has never failed for the right reason is not yet
a test.

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-23 | auth guard proves declaration, not enforcement | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser (CI bootstraps its own role, so CI is fine) | P2 |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |

P2-30 is resolved by the new conftest. No P0 or P1 open.

**Next:** the five remaining auth flows (verify-email, resend-verification,
forgot-password, reset-password, change-password), then invitations, then the
frontend against a real API. `Makefile` is still absent although CI does not use
it.

---

# CLAUDE BUILD 8 — auth router implemented by Claude

You went to the frontend with the auth router unwritten for the fourth cycle, so
nothing shipped was reachable — no `/auth/login` meant every endpoint returned
401 forever. I built it. This is outside the normal architect lane; the reason is
recorded here so it is visible rather than silent.

## Implemented

| File | Contents |
|---|---|
| `app/modules/auth/router.py` | **new** — 7 endpoints |
| `app/modules/auth/service.py` | `register`, `login`, `logout`, `logout_all`, `switch_tenant`, `current_user`, backoff |
| `app/modules/auth/repository.py` | `add_user`, `get_user_by_id`, `add_session`, `revoke_all_sessions`, `active_memberships`, `get_active_membership` |
| `app/modules/auth/schemas.py` | `SwitchTenantRequest`; `UserResponse` extended |
| `app/modules/audit/security_service.py` | **new** — the security-event stream (ADR-0023) |
| `app/core/net.py` | **new** — `coerce_ip` |
| `app/api/deps.py` | `get_security_events`; publishes `app.user_id` |
| `alembic/versions/0010_membership_self_access.py` | **new** — see below |
| `tests/structural/test_application_startup.py` | public-operation allowlist extended, each entry justified |

Endpoints: `register`, `login`, `refresh`, `logout`, `logout-all`, `me`,
`switch-tenant`. **Not yet built:** `verify-email`, `resend-verification`,
`forgot-password`, `reset-password`, `change-password` — the token models exist,
the flows do not.

`rotate_refresh_token` was already yours and was already correct; I built around
it unchanged.

## Verified end to end against live PostgreSQL

```
register          202
register (dup)    202   identical — no enumeration
login wrong pw    INVALID_CREDENTIALS
login unknown     INVALID_CREDENTIALS   same code, dummy-hash timing
login ok          200   refresh_token in body: False
  cookie          HttpOnly ✅  Path=/api/v1/auth ✅  SameSite=lax ✅
me                200   password_hash leaked: False
create org        201   tenant.created audited
me memberships    1
switch-tenant     200
branches / roles  200   MAIN + OWNER resolved
refresh           200   refresh token rotated
REPLAY old token  401 REFRESH_REUSE_DETECTED
valid token after 401   whole family revoked ✅
logout → me       401   via Redis denylist

54 tests · ruff clean · mypy clean (77 files) · 10 revisions · alembic check clean
```

---

## The architecture defect this surfaced — mine, now fixed

**A user could never reach the organization they had just created.**

`memberships` carries the RLS tenant policy like every other tenant-owned table.
But "which tenants do I belong to?" is asked *before* a tenant is selected and
its answer **spans tenants**, so the tenant policy can never satisfy it. Measured:

```
membership exists, status=ACTIVE          (as owner)
nexora_app, no app.tenant_id  →  0 rows
nexora_app, app.tenant_id set →  1 row
```

So after `POST /tenants` the user got `memberships: []`, `active_tenant_id: null`,
and `switch-tenant` → 403. Permanently locked out. `DATABASE.md` §6 put
`memberships` under RLS without accounting for the bootstrap query — my error.

**Fix (migration 0010):** a second, OR'd, **SELECT-only** policy keyed on an
`app.user_id` GUC set from the signed `sub` claim at authentication:

```sql
CREATE POLICY membership_self_read ON memberships FOR SELECT
  USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
```

No `WITH CHECK`, so writes are not widened — creating or altering a membership
still requires the tenant policy. Tenant isolation is unchanged; a user simply
gains read access to rows that are already theirs.

## Three latent bugs the auth path exposed

1. **`INET` columns discard on non-IP input.** `auth_sessions.ip` and
   `security_events.ip` are `INET`; a client address that is not an IP (proxy
   misconfiguration, unix socket, test client) raised `DataError`. For
   `security_events` it silently dropped the event — losing the record of a failed
   login because its source address did not parse is exactly backwards. Now
   coerced via `core/net.coerce_ip`.
2. **Onboarding flushed after its tenant context was reset.** The
   `finally: reset_tenant_context(...)` ran before `service_transaction`
   committed, so every `TenantScoped` row failed `MISSING_TENANT_CONTEXT`. Also
   needed a flush before the audit event (`actor_membership_id` FK) and before
   `membership_roles` (its RLS policy subqueries `memberships`). Three explicit
   flushes now, each commented with the constraint it satisfies.
3. **`AuthSession.created_at` has no default** and must be set by the caller.

---

## P1-27 — `/api/v1/members/` returns 500 (yours)

**File:** `app/modules/members/repository.py:30,34`

```python
select(Membership, User).join(User)
```

```
sqlalchemy.exc.AmbiguousForeignKeysError: Can't determine join between
'memberships' and 'users'; tables have more than one foreign key constraint
```

`memberships` has two FKs to `users` — `user_id` and `invited_by_user_id`.
**Fix:** `.join(User, User.id == Membership.user_id)` on both lines. The endpoint
500s today; no test caught it because none calls it against a database.

## P2-28 — blanket `except IntegrityError` mislabels every constraint failure

**File:** `app/modules/tenancy/service.py`

Any `IntegrityError` in `create_organization` becomes
`DUPLICATE_RESOURCE "Organization slug already exists."`. While debugging, a
**foreign-key** violation on `audit_events` was reported as a duplicate slug on
an empty database. Narrow it to the slug constraint by name and re-raise the rest.

## P2-29 — `01-roles.sh` only works as a superuser

`ALTER ROLE ... NOSUPERUSER` requires superuser. Under Docker `POSTGRES_USER` is
one, so compose works — but with `ON_ERROR_STOP=1` the script aborts before its
`GRANT`s anywhere else, including CI. Guard the `ALTER` or document that the
bootstrap must run as superuser.

## P2-30 — integration tests cannot use `TestClient`

Sync `TestClient` runs each request in a new event loop while the engine's
pooled asyncpg connections belong to the first: the second request in any test
dies with `got Future attached to a different loop`. Use
`httpx.AsyncClient(transport=ASGITransport(app))` inside one loop (as the
verification above does), or `NullPool` in tests. Worth settling before the
integration suites are written on the wrong foundation.

---

## Open

| # | Finding | Severity |
|---|---|---|
| P1-27 | `/members/` 500 — ambiguous FK join | **P1** |
| P2-21 | source-string tenant-scope guard → behavioural test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-23 | auth guard proves declaration, not enforcement | P2 |
| P2-28 | blanket IntegrityError mislabelling | P2 |
| P2-29 | `01-roles.sh` needs superuser | P2 |
| P2-30 | TestClient unusable for integration tests | P2 |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |
| — | Node 22 LTS pin | P2 |

**Next:** P1-27 (one line), then the five remaining auth flows
(verify-email, resend-verification, forgot-password, reset-password,
change-password), then invitations, then `docker-compose.yml` + `Makefile` + CI,
then the integration/isolation/authz suites — with P2-30 settled first. Frontend
last, now that there is a real API behind it.

Scratch DB `nexora_final` is migrated with a seeded org for manual poking.

---

# CLAUDE REVIEW 7 — P1-25 fixed by Claude; sequencing concern

## P1-25 fixed (privilege escalation)

You moved to the frontend with this open, and it is a self-escalation across a
documented security boundary, so I closed it. `members/service.py` was stable
(you were in `frontend/`), so there should be no conflict.

**Changed:**

| File | Change |
|---|---|
| `app/modules/members/service.py` | self-guard on `update_branches` + `_require_grantable_branches` |
| `tests/unit/test_member_branch_scope.py` | **new** — 8 tests |
| `docs/API.md` §4.1 | added the codes + a new §4.1.1 on the two containment rules |

The subset helper runs **before** any database access — deliberately. Rejecting
an escalation should never depend on a round trip succeeding first.

```
tests/unit/test_member_branch_scope.py    8 passed
full suite                                54 passed
ruff / mypy                               clean / clean (72 files)
```

Tests cover both directions, including the ones that must not regress: an
unrestricted OWNER/ADMIN can still grant any branch and can still set another
member to unrestricted.

`PRIVILEGE_ESCALATION` and `ROLE_ASSIGNED` — codes you introduced in
`RoleService` — were also missing from the registry. Added.

---

## Sequencing — worth raising

Current order of work: models → migrations → tenancy → branches → RBAC →
members → **frontend**. The auth router has been skipped three times.

Nothing shipped so far is reachable. There is no `/auth/login`, so no token can
be obtained, so every one of the 16 business endpoints returns `401`
permanently. A frontend built now has no API to call and cannot be exercised
end to end — its auth pages, the BFF token custody in ADR-0014, and the session
handling all need real endpoints to be anything more than markup.

`prompt.md` §43 lists authentication first in Phase 1 for this reason, and the
handoff's acceptance criteria are written against a working login.

**Recommended order from here:**

1. `auth` router — `API.md` §5.1, all twelve endpoints. Rotation and reuse
   detection are the highest-risk code in the phase; the tests exist already
   (`tests/unit/test_refresh_rotation.py`).
2. Invitations (`API.md` §5.5) — completes the onboarding loop.
3. `docker-compose.yml`, `Makefile`, CI workflow — pin **Node 22 LTS**.
4. Integration/isolation/authz suites for the shipped modules.
5. Frontend, against a real API.

If the frontend is deliberately being staged ahead of that, say so in
`# Known Problems` and I will stop raising it — but it should be a decision,
not drift.

---

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural API test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-23 | auth guard proves declaration, not enforcement | P2 |
| P3-24 | hardcoded system-role count | P3 |
| P3-26 | self-suspension permitted | P3 |
| — | Node 22 LTS pin | P2 |

No P0 or P1 open.

---

# CLAUDE REVIEW 6 — members module (reviewed mid-flight)

`MemberService` implements three of the four ARCHITECTURE §5.1 guards correctly:
self-role-edit blocked, permission subset rule enforced, OWNER-only-grants-OWNER,
plus last-owner protection with `FOR UPDATE` locking and idempotent `remove()`.
`replace_roles` bumps `roles_version`, so ADR-0008's cache invalidates properly.

Two things I suspected and **checked before reporting — both fine**: branch
changes not bumping `roles_version` is harmless (only `permissions` is cached;
`role_ids` and `branch_ids` are read fresh per request), and `replace_roles`
does bump.

One is real.

---

## P1-25 — branch-scope self-escalation via `PATCH /members/{id}/branches`

**Files:** `app/modules/members/service.py:89-100` · `schemas.py:18` · `router.py:48-55`

`update_roles` blocks self-modification (`service.py:54`). **`update_branches`
does not.** The asymmetry is the defect — the same shape as the read/write
asymmetry in the original tenant guard.

Attack, one request, no special setup:

```
Actor: holds users.manage_roles, restricted to Branch A
PATCH /api/v1/members/{their_own_membership_id}/branches
{ "branch_ids": [] }
```

- `branch_ids: set[UUID]` has no `min_length`, so `[]` is accepted
- `replace_branches` deletes every `MembershipBranch` row
- **No rows = access to all branches** (DATABASE.md §3.7; the response field
  `unrestricted_branches = not record.branch_ids` confirms this reading)
- `branch_ids` is read fresh each request, so it takes effect immediately

The actor escalates from one branch to every branch in the tenant. This crosses
a boundary the architecture states explicitly (§3.1: *"A cashier bound to Branch
A holding `sales.create` still cannot check out at Branch B"*), and it is
reachable by a branch-scoped ADMIN — a normal setup for a multi-branch business.

`users.manage_roles` being privileged is not mitigation: guard #1 exists
precisely because holding a management permission must not let you promote
*yourself*.

### Fix — two rules, mirroring how roles are already handled

```python
async def update_branches(self, membership_id, branch_ids):
    # 1. same guard update_roles already has
    if membership_id == self.context.membership_id:
        raise PermissionDeniedError(
            "CANNOT_MODIFY_OWN_BRANCHES", "You cannot modify your own branch access."
        )
    async with service_transaction(self.session):
        ...
        # 2. branch subset rule — the analogue of the permission subset rule.
        #    A restricted actor cannot grant branches they do not themselves hold,
        #    including the unrestricted (empty) set.
        if self.context.branch_ids is not None:
            if not branch_ids or not branch_ids.issubset(self.context.branch_ids):
                raise PermissionDeniedError(
                    "CANNOT_GRANT_UNHELD_BRANCH",
                    "You cannot grant branch access you do not hold.",
                )
```

Rule 2 matters independently of rule 1: without it, a Branch-A-restricted admin
can still widen *another* user to Branch B. Permissions already have a subset
rule; branch scope is the second dimension of the same authorization model
(§3.1) and needs the parallel one.

Add `CANNOT_MODIFY_OWN_BRANCHES` and `CANNOT_GRANT_UNHELD_BRANCH` to the
API.md §4.1 registry — I will do that once the fix lands.

### Tests required

- actor restricted to Branch A sets own `branch_ids: []` → `403`
- actor restricted to Branch A sets own `branch_ids: [A]` → `403` (self-edit)
- actor restricted to Branch A grants another member Branch B → `403`
- actor restricted to Branch A grants another member Branch A → `200`
- **unrestricted** actor grants any branch → `200` (must not regress)
- unrestricted actor sets another member to `[]` → `200`

---

## P3-26 — self-suspension is permitted

`update_status` has no self-guard, so a user with `users.manage` can suspend
themselves. Self-inflicted denial of service rather than escalation, and the
last-owner check already prevents the damaging case. Worth a guard for symmetry
when convenient.

---

Everything from Review 5 (P2-21 … P3-24) remains open. Still no auth router, so
none of this is reachable in practice yet — which is also why P1-25 has not
shipped anywhere. Fix it before the auth router lands and it never becomes live.

---

# CLAUDE REVIEW 5 — RBAC, members, audit APIs + isolation scaffolding

Verified independently. 43 passed · ruff clean · mypy clean (66 files) · app boots.

## Strong work

**`RoleService` escalation guards are correct.** `_validate_permissions` computes
`codes - self.context.permissions` and raises `PRIVILEGE_ESCALATION` — that is
ARCHITECTURE §5.1 rule 2 implemented properly. `get_custom(..., for_update=True)`
locks before mutation, system roles are protected, assigned roles cannot be
deleted, and audit rides the transaction.

`bump_assigned_memberships` on permission change is the detail worth calling
out: without it, ADR-0008's cache would serve stale permissions after a role
edit. You inferred that; it was not spelled out in the handoff.

**P2-6 properly closed.** `RoleRepository` scopes reads to
`tenant_id == ctx OR tenant_id IS NULL`, `is_system` matches only
`tenant_id IS NULL` (so another tenant's custom role yields 404, not 409), and
every mutation is tenant-scoped. Exactly right.

**`test_rls.py` is the best test in the suite.** Behavioural, asserts the app
role is not owner / not superuser / not `BYPASSRLS`, that the audit stream has
no UPDATE/DELETE privilege, and that tenant B sees its own custom role plus the
8 system roles but not tenant A's. That is ADR-0022's replacement for `FORCE`,
done right.

**Both P1-20 follow-ups done:** `types-redis` removed, and structural guard #2
built off `openapi()` — which correctly sidesteps the `_IncludedRouter` trap.

**Enforcement verified empirically.** I swept every documented business
operation anonymously: all 16 return `401`. No gaps.

---

## P2-21 — `test_manual_tenant_scope.py` asserts source text, not behaviour

```python
source = inspect.getsource(RoleRepository)
assert "Role.tenant_id == self.tenant_id" in source
```

This tests the *spelling* of the implementation. A correct refactor to a local
(`.where(Role.tenant_id == tid)`) fails it; a comment containing the string
passes it. It cannot detect a leak and it punishes valid change — the worst
combination for a guard.

`test_rls.py::test_roles_expose_system_and_current_tenant_only` already proves
the property at the database layer. What is missing is the **application** layer:

```
Tenant B: GET    /api/v1/roles/{A_role_id}  → 404
Tenant B: PATCH  /api/v1/roles/{A_role_id}  → 404
Tenant B: DELETE /api/v1/roles/{A_role_id}  → 404
Tenant B: GET    /api/v1/roles/             → excludes A's role
```

Replace the source-string assertions with that. Keep `registry.py` — the
documented exemption is the right idea, and its comment is accurate.

## P2-22 — the unset-GUC test can pass for the wrong reason

`test_unset_tenant_guc_returns_zero_tenant_rows` asserts `count == 0` on
`branches`. On a freshly migrated CI database there are no branches, so it
passes whether or not RLS works.

I confirmed it is genuinely meaningful by running it against a database holding
2 branches — the app role still saw 0, so RLS is working. But the test must not
depend on my choosing the right database. Insert a branch as `nexora_owner`
inside the test, then assert the app role sees 0.

A test that passes on an empty database proves nothing about isolation.

## P2-23 — structural guard #2 proves declaration, not enforcement

`bearer = HTTPBearer(auto_error=False)`, so FastAPI does **not** 401 on its own —
`get_current_identity` must check `credentials is None`, and it does. But a
future route depending on `bearer` directly would still advertise
`security: HTTPBearer` in the schema and pass the guard while enforcing nothing.

Freeze the sweep I ran by hand: call every non-public operation in
`openapi()["paths"]` with no credentials and assert `401`. It is ~10 lines,
needs no database, and closes the gap between declared and actual.

Remember to extend `public_operations` when the auth router lands — `/login`,
`/register`, `/refresh`, `/forgot-password`, `/reset-password`,
`/verify-email`, `/invitations/accept` are legitimately public.

## P3-24 — hardcoded system-role count

`assert ... == 8` breaks whenever the seeded roles change. Assert against the
seed constant, or `> 0` plus "every row has `tenant_id IS NULL`".

---

## Open

| # | Finding | Severity |
|---|---|---|
| P2-21 | source-string tenant-scope guard → behavioural API test | P2 |
| P2-22 | unset-GUC test vacuous on empty DB | P2 |
| P2-23 | auth guard proves declaration, not enforcement | P2 |
| P3-24 | hardcoded role count | P3 |
| — | Node 22 LTS pin | P2 |

No P0 or P1. **Remaining Phase 1 scope:** auth router (still absent — nothing
can log in yet), invitations, `docker-compose.yml`, `Makefile`, CI workflow,
frontend, and the isolation/authz suites for the modules now shipped.

The auth router is the critical path: every endpoint above is currently
unreachable in practice because there is no way to obtain a token.

---

# CLAUDE REVIEW 4 — every prior finding closed; stack verified end to end

Good session. Independently verified, not taken from your report.

## Verified working (live PostgreSQL 16, virgin database, no workarounds)

```
alembic upgrade head            9 revisions on a virgin DB
alembic check                   no drift
downgrade base → upgrade head   clean; 0 residual tables/enums/functions
seed                            currencies=5 permissions=30 roles=8 role_permissions=41
ruff check / ruff format        clean
mypy app                        clean, 58 files
pytest tests                    36 passed
```

Application actually serves traffic:

| Request | Result |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `GET /api/v1/branches` | `401` with the correct error envelope |
| `POST /api/v1/tenants` | `401` |
| OpenAPI | `/api/v1/branches/`, `/api/v1/branches/{branch_id}`, `/api/v1/tenants/`, `/health`, `/metrics`, `/ready` |

Auth is enforced on every business route and the error shape matches `API.md` §4
exactly.

## Closed since Review 3

P1-3 (validation no longer echoes `input`) · P1-4 (catch-all handler present)
· P1-14 (`FORCE` gone — this is what made the virgin-DB migration work)
· P1-15 (`infra/postgres/init/01-roles.sql`) · P1-16 (`NoDecode`; plain
`CORS_ORIGINS=http://localhost:3000` now parses) · **P1-18** (you collapsed
`get_auth_db` into `get_db` — single session per request, GUC now lands where
services query) · **P1-19** (onboarding establishes context after `flush()`,
exactly the pattern handed over) · P2-17 · P3-11 · P3-12.

P1-19 deserves a note: you implemented the mid-transaction context bootstrap
including the `set_config` call, which is the half that RLS depends on and the
easy half to omit.

---

## P1-20 — `Redis[str]` crashed application startup (**fixed by Claude**)

**Files:** `app/core/redis.py`, `app/api/deps.py`, `app/core/ratelimit.py`,
`app/modules/rbac/service.py`, `app/modules/platform/router.py`

```
File "app/api/deps.py", line 66, in __annotate__
    redis: Annotated[Redis[str], Depends(get_redis)],
TypeError: <class 'redis.asyncio.client.Redis'> is not a generic class
```

`redis.asyncio.Redis` is **not subscriptable at runtime** in redis 6.4.0, so
importing any router raised and `create_app()` never returned. The application
could not start at all.

It passed every check because `types-redis` (pinned `>=4.6,<5`, stubs for redis
**4.x**) declares `Redis` generic — mypy validated against stubs that do not
describe the installed runtime.

**Fix applied:** a `TYPE_CHECKING` alias in `app/core/redis.py` — mypy still sees
`Redis[str]`, runtime sees plain `Redis` — and all five modules now use
`RedisClient`.

**Two follow-ups for you:**

1. **Drop `types-redis` from dev dependencies.** redis ≥5 ships `py.typed`
   inline hints; the stub package is stale *and* actively misleading, as this
   proves. A wrong stub is worse than no stub.
2. **Add the startup smoke test.** Nothing in the suite imports `app.main`, so
   36 green tests coexisted with an application that could not boot. This is
   structural guard #2 from the handoff (`introspect app.routes`, assert every
   route carries an auth dependency) — building it would have caught this as a
   side effect. It is the highest-value test still missing.

Note when you write it: `app.routes` now contains `_IncludedRouter` wrappers
rather than flattened `APIRoute`s, so filtering on `hasattr(r, "methods")`
silently yields almost nothing. Walk them recursively, or assert against
`/api/v1/openapi.json`.

---

## Open

| # | Finding | Status |
|---|---|---|
| — | `types-redis` removal + startup smoke test | **new, from P1-20** |
| P2-6 | `Role` outside Layer 2 — needs manual scoping + isolation test | open |
| P2-10 | `X-Request-ID` validation | you added `import re`; confirm it landed |
| — | Node 22 LTS pin for Docker/CI | open |

No P0 or P1 is open. **Phase 1 is not complete** — auth endpoints, members,
invitations, roles, audit API, the frontend, Docker Compose and CI remain — but
the foundation is sound and verified, and Phase 2 is no longer gated on defects.

Scratch DBs on the local server: `nexora_dev` (2 seeded tenants, for
`tests/integration/test_tenant_guard.py`) and `nexora_ci`. Roles `nexora_owner`
/ `nexora_app` are now created properly by your `01-roles.sql`.

---

# CLAUDE REVIEW 3 — P0s fixed by Claude; two new P1s in the new layer

You were writing `deps.py`, `tenancy/repository.py` and `tenancy/router.py`
while both P0s were still open — i.e. building the service layer on a tenant
guard that was switched off and failing open. Rather than send a third review, I
fixed the foundation directly. **Both P0s and P1-5 are closed.**

## Fixed by Claude (keep these)

| File | Change |
|---|---|
| `app/db/tenant_guard.py` | rewritten: fails closed, covers deletes, typed errors |
| `app/db/__init__.py` | imports `tenant_guard` — registration is now structural |
| `tests/structural/test_tenant_guard_registered.py` | **new** — 3 tests |
| `tests/integration/test_tenant_guard.py` | **new** — 4 behavioural tests |
| `pyproject.toml` | `pythonpath = ["."]` |
| `alembic/versions/000{2,3,4}` | `create_type=False` (Review 2, P1-13) |

**P0-1 — registration.** `tenant_guard` is now imported by `app/db/__init__.py`,
so importing *anything* under `app.db` arms the guard. That is deliberate: an
explicit import at one call site is what silently disappeared last time. Three
structural tests assert both listeners are attached.

**P0-2 — fail closed.** `apply_tenant_filter` now gates on
`state.all_mappers`: if the statement touches a `TenantScoped` entity and there
is no context and no `skip_tenant_filter`, it raises `MissingTenantContextError`
with a message naming the remedy. Statements touching no tenant-scoped entity
(login by email, currency lookup) pass untouched and need no escape hatch.

**P1-5 — deletes.** `enforce_tenant_writes` now scans
`session.new | session.dirty | session.deleted`, and raises the typed
`CrossTenantWriteError` instead of a bare `RuntimeError` (closes P2-8).

### Verified against live PostgreSQL 16

```
tests/integration/test_tenant_guard.py
  tenant_scoped_select_without_context_raises      PASSED
  non_tenant_select_without_context_succeeds       PASSED
  escape_hatch_still_works                         PASSED
  two_tenants_in_one_process_see_only_their_own    PASSED
4 passed · unit+structural: 18 passed · ruff clean · mypy clean (58 files)
```

**P2-9 is withdrawn.** That last test was written to catch the
`with_loader_criteria` lambda baking a tenant id into a cached statement. It
does not — SQLAlchemy binds the closure variable correctly, and tenant A and
tenant B see disjoint rows in the same process. The test stays as a regression
pin; the concern was unfounded.

---

## P1-18 — the tenant GUC is set on the wrong session

**File:** `app/api/deps.py:71-89`

`get_tenant_context` depends on `get_auth_db` and runs
`set_config('app.tenant_id', …)` on **that** session. Business work runs on
`get_db` — a *different* session on a *different* connection, where the GUC was
never set.

Once RLS is active, every business query returns **zero rows**. The failure
presents as "the app is empty", not as an error, and the tempting fix is to
disable RLS — which is why this matters more than its blast radius suggests.

**Fix:** one session per request. Set the GUC on the same session the services
use — fold `get_auth_db` into `get_db`, or have `get_tenant_context` take the
business session. This is P2-7 from Review 1 (two session paths) now made
concrete; resolving it resolves both.

---

## P1-19 — onboarding will now raise, because of my own fix

**File:** `app/modules/tenancy/router.py` + `service.py`

`POST /tenants` correctly runs with no tenant context — no tenant exists yet.
But `create_organization` writes `Branch` and `Warehouse`, which are
`TenantScoped`, so the now-armed write guard raises `MissingTenantContextError`.

This is a direct consequence of P0-2 and it is my fix's job to tell you how to
land it, not yours to discover at runtime.

**Fix — establish context mid-transaction, once the tenant row exists:**

```python
async def create_organization(self, user_id: UUID, payload: TenantCreate):
    tenant = Tenant(...)
    self.session.add(tenant)
    await self.session.flush()          # tenant.id now exists

    token = set_tenant_context(bootstrap_context(tenant.id, user_id))
    try:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.id)}
        )
        # Branch, Warehouse, Membership, MembershipRole, audit event
        ...
    finally:
        reset_tenant_context(token)
```

Do **not** reach for `skip_tenant_filter` here. The tenant genuinely exists by
that point, so the correct move is to establish its context — the escape hatch
is for operations that have no tenant at all, and every use of it spends from
the budget in structural guard #5.

The `set_config` call matters as much as the contextvar: without it RLS rejects
the `Branch` insert via `WITH CHECK`, independently of Layer 2.

---

## Still open from earlier reviews

| # | Finding | Status |
|---|---|---|
| P1-3 | validation errors echo submitted passwords | **open** |
| P1-4 | no catch-all handler (`deps.py` handles JWT → 401 well; the generic `Exception` handler is still missing) | **partly done** |
| P1-14 | drop `FORCE` from `0008_rls.py` — still 4 occurrences | **open** |
| P1-15 | `infra/postgres/init/01-roles.sql` — `infra/` still empty | **open** |
| P1-16 | `NoDecode` on `cors_origins` | **open** |
| P1-18 | GUC on wrong session | **new** |
| P1-19 | onboarding needs mid-transaction context | **new** |

Closed since Review 2: P0-1, P0-2, P1-5, P1-13, P2-8, P2-17 (you pinned
`<3.13`), P3-11 (you dropped the deprecated mypy plugin). P2-9 withdrawn.

**P1-14 is the one to do next** — until `FORCE` is gone, `alembic upgrade head`
fails on any clean database, and I am currently working around it by hand.

A migrated scratch database `nexora_dev` is on the local server with two seeded
tenants, so the integration test above runs as-is.

---

# CLAUDE REVIEW 2 — migrations, validated against a live PostgreSQL 16

**Codex's blocker is cleared.** Docker's daemon is down, but a Homebrew
PostgreSQL 16.14 is running on `127.0.0.1:5432`. I created the two roles the
migrations require and ran the full chain against it. Migrations are no longer
unverified — here is what actually happens.

### Reproducing this locally (no Docker needed)

```sql
CREATE ROLE nexora_owner LOGIN PASSWORD 'owner_pw';
CREATE ROLE nexora_app   LOGIN PASSWORD 'app_pw';
CREATE DATABASE nexora_dev OWNER nexora_owner;
\c nexora_dev
GRANT USAGE ON SCHEMA public TO nexora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE nexora_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexora_app;
```

Then point `DATABASE_OWNER_URL` at `nexora_owner` and `DATABASE_URL` at
`nexora_app`. **This belongs in `infra/postgres/init/01-roles.sql`** — see P1-15.

---

### Result: `alembic upgrade head` failed twice on a clean database

Both are now diagnosed. After fixing both, the chain runs end to end and seeds
`currencies=5, permissions=30, roles=8, role_permissions=41`.

---

## P1-13 — ENUM double-create broke `upgrade head` (**already fixed by Claude**)

**Files:** `alembic/versions/0002_core_identity.py:19`,
`0003_membership_rbac.py:19`, `0004_auth_tokens.py:19`

```
asyncpg.exceptions.DuplicateObjectError: type "tenant_status" already exists
[SQL: CREATE TYPE tenant_status AS ENUM ('ACTIVE','SUSPENDED','CANCELLED')]
```

`postgresql.ENUM(...)` defaults to `create_type=True`, so `op.create_table()`
emits `CREATE TYPE` a second time — with no `checkfirst` — after the explicit
`.create(bind, checkfirst=True)` on line 35 already created it.

**I applied the fix** (three one-token edits, `create_type=False` on each of the
three enums), because it was blocking all further validation. Please keep it.
The explicit `.create(..., checkfirst=True)` / `.drop(..., checkfirst=True)` pairs
are correct and should stay — they are what makes the downgrade clean.

---

## P1-14 — `FORCE ROW LEVEL SECURITY` makes seeding impossible — **my spec was wrong**

**File:** `alembic/versions/0008_rls.py:30` (and every `FORCE` line)
**Root cause:** `docs/DATABASE.md` §6, which I wrote. Not a Codex defect.

```
asyncpg.exceptions.InsufficientPrivilegeError:
  new row violates row-level security policy for table "roles"
```

`ENABLE` applies policies to every role *except the table owner*; `FORCE` adds
the owner too. Migrations run as `nexora_owner` (correctly — `env.py` uses
`database_owner_url`), and system roles carry `tenant_id IS NULL`, which no
`app.tenant_id` value can satisfy against `WITH CHECK (tenant_id = <guc>)`.

Proven both directions on the live database:

```
with FORCE:      INSERT system role  →  ERROR: new row violates RLS policy
after NO FORCE:  same INSERT          →  INSERT 0 1
```

**Fix:** drop every `FORCE ROW LEVEL SECURITY` line from `0008_rls.py`. Keep
`ENABLE`, keep both policy clauses, keep `nexora_app` as non-owner. Recorded as
**ADR-0022**; `DATABASE.md` §6 is corrected with a new §6.1.

Add `tests/integration/test_rls.py` asserting what `FORCE` was meant to catch:

```python
# app role must not be owner, must not have BYPASSRLS, and must fail closed
assert rolbypassrls is False
assert tableowner != current_user
# unset app.tenant_id → zero rows
```

**Your policies themselves are correct.** Verified as `nexora_app`:

| Check | Result |
|---|---|
| GUC unset → `SELECT count(*) FROM branches` | `0` — fails closed ✅ |
| GUC = Tenant A | only A's row ✅ |
| INSERT with another tenant's `tenant_id` | rejected by `WITH CHECK` ✅ |
| `UPDATE audit_events` as app | `permission denied` — REVOKE works ✅ |

The `NULLIF(current_setting(...), '')::uuid` idiom is a genuine improvement over
what I specified; I have adopted it into `DATABASE.md` §6.

---

## P1-15 — `infra/` is empty, so no environment can run these migrations

`0007_triggers.py:80` executes
`REVOKE UPDATE, DELETE ON audit_events, security_events FROM nexora_app`.
That role does not exist anywhere: `infra/` contains no files, and no migration
creates it. I had to create both roles by hand to get the chain to run.

Any fresh environment — a teammate's clone, CI, `docker compose up` — fails at
0007. Needs `infra/postgres/init/01-roles.sql` (Postgres runs `/docker-entrypoint-initdb.d/*.sql`
on first start), and the same bootstrap available to CI, which has no init-dir hook.

---

## P1-16 — The app cannot start from its own `.env.example`

**File:** `app/core/config.py:34,49`

```
pydantic_settings.exceptions.SettingsError:
  error parsing value for field "cors_origins" from source "EnvSettingsSource"
```

`.env.example` documents `CORS_ORIGINS=http://localhost:3000`. pydantic-settings
JSON-decodes complex types (`list[str]`) **inside the env source**, which raises
before any `mode="before"` validator runs — so `parse_origins` on line 49 is
dead code for env input. It works only for a JSON array.

**Fix** (keeps the validator working):

```python
from typing import Annotated
from pydantic_settings import NoDecode

cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
```

Test: load `Settings` from `CORS_ORIGINS=http://a.com,http://b.com` and assert
two origins. Acceptance criterion "docker compose up produces a working stack
from a clean clone" fails without this.

---

## P2-17 — The virtualenv is Python 3.14; the project targets 3.12

`.venv/lib/python3.14/…`, while `pyproject.toml` sets `requires-python = ">=3.12"`
and `[tool.mypy] python_version = "3.12"`. mypy is therefore type-checking
against a different Python than the one executing the code, and CI will run a
third. Pin one version across venv, mypy, Docker and CI.

---

## NOT a defect — retracting an in-flight suspicion

My first `alembic downgrade -1` failed on a foreign-key violation against
`currencies`. That was **my** test tenants holding FK references, not a bug. On a
pristine database the downgrade path is clean:

```
downgrade base   → residual tables 0, enums 0, functions 0
upgrade head     → 9 revisions applied
```

Complete downgrades with no leaked types or functions is better than most
projects manage, and `0009`'s `DISABLE TRIGGER` / `ENABLE TRIGGER` wrapper around
the system-role seed correctly anticipated the trigger-ordering trap from
`0007`. Credit where due.

---

## Answer to the architecture conflict you raised — resolved, unblock yourself

Your `# Known Problems` entry is a correct catch: `user.registered` cannot go in
`audit_events` when `tenant_id` is `NOT NULL` and registration precedes any
tenant. **Resolution is ADR-0023.** Summary:

1. `audit_events.tenant_id` **stays NOT NULL** — every RLS policy and the Layer 2
   filter depend on it. Making it nullable would force `tenant_id IS NULL OR …`
   into the policies, exposing platform rows to every tenant.
2. Pre-tenant identity events — `user.registered`, `user.email_verified`,
   `user.password_reset`, `user.password_changed` — go to **`security_events`**,
   which already has a nullable tenant and already writes outside the business
   transaction. **No schema change needed.**
3. Tenant-scoped events (`member.invitation_accepted`, `member.role_changed`)
   keep their tenant and stay in `audit_events`.
4. `outbox_events.tenant_id` → **nullable**, and remove `outbox_events` from RLS
   (`0008_rls.py` `DIRECT_TABLES`). It is an internal queue with no tenant-facing
   read path; the drain worker uses `skip_tenant_filter`.

This is the third option you listed, and it was the right instinct. Proceed.

---

## Updated fix order

The two P0s from Review 1 are still open and still gate everything downstream.

| # | Finding | Status |
|---|---|---|
| P0-1 | `tenant_guard` never imported | **open** |
| P0-2 | read filter fails open | **open** |
| P1-3 | validation errors echo passwords | **open** |
| P1-4 | no catch-all handler; expired JWT → 500 | **open** |
| P1-5 | write guard ignores deletes | **open** |
| P1-13 | ENUM double-create | **fixed by Claude — keep it** |
| P1-14 | drop `FORCE` from `0008_rls.py` | ready, ADR-0022 |
| P1-15 | `infra/postgres/init/01-roles.sql` | ready |
| P1-16 | `NoDecode` on `cors_origins` | ready |
| P2-17 | pin Python version | ready |
| ADR-0023 | audit/outbox conflict | **resolved — unblocked** |

Do P1-14 through P1-16 first; they are small and they make the stack actually
runnable, which lets you verify everything after. Then the P0s, then the rest.

I left two scratch databases (`nexora_verify`, `nexora_verify2`) and the two
roles on the local server. Drop the databases when convenient; **keep the
roles** — they are what you need for local migration runs until
`infra/postgres/init/01-roles.sql` exists.

---

# CLAUDE REVIEW — Phase 1, Slice 1 (foundation + models)

**Verdict: NOT APPROVED. 2 × P0, 3 × P1 open.**
Scope reviewed: `backend/app/core/**`, `backend/app/db/**`, `backend/app/main.py`,
`backend/app/modules/*/models.py`, `backend/tests/**`, `backend/pyproject.toml`.

### What is right

Worth stating, because these were the easy things to get wrong and Codex did not:

- `UnitOfWork` uses `set_config('app.tenant_id', :tid, true)` with a bind
  parameter — correct transaction-local GUC, and it avoids the string
  interpolation that `SET LOCAL` would have forced.
- `Role` is deliberately **not** `TenantScoped` (nullable `tenant_id` for system
  roles), with both partial unique indexes and the
  `CHECK (is_system = (tenant_id IS NULL))` from `DATABASE.md` §3.9. The two-index
  trap was avoided. See P2-6 for the consequence that follows.
- `AuditEvent` correctly omits `updated_at`.
- `cors_origins` validator rejects `*`.
- `mypy strict`, ruff with `S` (bandit) rules, `testcontainers` for real
  PostgreSQL — ADR-0019 honoured rather than quietly swapped for SQLite.
- Dummy-hash timing equalisation is present in `SecurityService`.

---

## P0-1 — The tenant guard is never imported, so Layer 2 does not exist

**File:** `backend/app/db/tenant_guard.py` (whole module) · `backend/app/main.py:9-17`

`@event.listens_for` registers a listener **only when the module is imported.**
Nothing anywhere imports `app.db.tenant_guard`:

```
$ grep -rn "tenant_guard" app tests
(no matches)
```

**Impact.** The automatic tenant filter and the write guard are both inert. Every
query written from here on will be unscoped unless the author remembers the
`WHERE` clause by hand — which is precisely the failure mode Layer 2 exists to
make impossible (`ARCHITECTURE.md` §3). This is latent only because no repository
or route exists yet; it becomes an active cross-tenant leak the moment one does.

This is the most dangerous kind of defect in the codebase right now: the module
looks finished, ruff passes, mypy passes, the tests pass, and the control is
switched off.

**Fix.** Import the module for its side effects where the session factory is
built (`app/db/session.py`, or explicitly in `create_app`), and add a test that
asserts the listener is registered:

```python
from sqlalchemy import event
from sqlalchemy.orm import Session
assert event.contains(Session, "do_orm_execute", apply_tenant_filter)
```

A listener-registration test is required for **both** listeners. Without it the
same defect returns silently after any import refactor.

---

## P0-2 — The read filter fails **open** when tenant context is unset

**File:** `backend/app/db/tenant_guard.py:12-14`

```python
context = tenant_context_var.get()
if context is None:
    return                      # ← unfiltered query proceeds
```

`ARCHITECTURE.md` §3 Layer 2 specifies `current_tenant_context()`, which **raises**.

**Impact.** Any query on a `TenantScoped` entity executed without tenant context
returns **every tenant's rows**. Reachable from a background task that forgot its
context kwargs, a service called before the auth dependency ran, or any future
code path that constructs a session directly. It is silent — no error, no log,
just extra rows.

Note the asymmetry that makes this clearly a bug rather than a choice:
`enforce_tenant_writes` on line 32 calls `current_tenant_context()` and **does**
fail closed. Writes are protected; reads are not.

RLS would catch this in production (`current_setting` → NULL → policy false →
zero rows), but RLS is not implemented yet, and ADR-0003 states explicitly that
it must never be the primary control.

**Fix.** Fail closed, while still allowing genuinely tenant-less queries (login
by email, seeding, migrations) through the sanctioned escape hatch:

```python
@event.listens_for(Session, "do_orm_execute")
def apply_tenant_filter(state: ORMExecuteState) -> None:
    if not state.is_select or state.execution_options.get("skip_tenant_filter"):
        return
    touches_tenant_scoped = any(
        issubclass(m.class_, TenantScoped) for m in state.all_mappers
    )
    if not touches_tenant_scoped:
        return
    context = current_tenant_context()   # raises — fail closed
    ...
```

`ORMExecuteState.all_mappers` gives the entities involved, so non-tenant queries
(`User` at login) are unaffected and do not need the escape hatch.

Required tests: unfiltered `select(AuditEvent)` with no context **raises**;
`select(User)` with no context **succeeds**; `skip_tenant_filter` still works.

---

## P1-3 — Validation errors echo the submitted value, including passwords

**File:** `backend/app/core/errors.py:65`

```python
{"errors": exc.errors()}
```

Pydantic v2 error dicts carry an `input` key holding **the offending value**. A
registration request failing `PASSWORD_MIN_LENGTH` therefore returns the
submitted password in the HTTP response body, and puts it into any log or error
tracker that captures the response.

Directly violates `SECURITY.md` §10 ("never logged: passwords…") and it lands on
the one endpoint where the value is always a credential.

**Fix.** Build a sanitised list; never pass pydantic errors through verbatim:

```python
details = {"errors": [
    {"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]}
    for e in exc.errors()
]}
```

Test: `POST /auth/register` with a 3-character password → assert the password
string appears nowhere in the response body.

---

## P1-4 — No catch-all handler; auth failures will surface as 500s

**File:** `backend/app/core/errors.py:50-67`

Two gaps:

1. **No `Exception` handler.** `ARCHITECTURE.md` §8 requires unhandled exceptions
   to return a generic `500` carrying `request_id`, with no stack trace. Right
   now FastAPI's default applies: no error envelope, no `request_id`, and with
   `debug=true` a traceback in the response.
2. **The `AppError` hierarchy is missing half its members.** Present:
   `NotFoundError`, `PermissionDeniedError`, `ConflictError`. Missing:
   `AuthenticationError` (401), `ValidationError` (422 domain),
   `BusinessRuleViolation` (422), `RateLimited` (429), `ExternalServiceError`
   (502/503).

`AuthenticationError` is the one that bites in this phase: `decode_access_token`
(`core/security.py:62`) lets PyJWT's `ExpiredSignatureError` propagate. With no
mapping to `401`, **an expired access token returns 500** — so the frontend never
sees the `401` that triggers refresh, and every session breaks at the 15-minute
mark. Fix this before `api/deps.py` is written, or the bug gets designed around.

Also add `RuntimeError` from `current_tenant_context()` to the taxonomy (P2-8).

---

## P1-5 — The write guard ignores deletions

**File:** `backend/app/db/tenant_guard.py:27-29`

```python
session.new.union(session.dirty)     # session.deleted is absent
```

INSERT and UPDATE are checked; **DELETE is not.** An object loaded through a
`skip_tenant_filter` query, or through any path once P0-2 is triggered, can be
deleted across tenant boundaries with no guard.

**Fix.** Include `session.deleted` in the scanned set. For deletes the check is
tenant equality only — never the `tenant_id` stamping branch on line 34.

Test: load a Tenant A row with `skip_tenant_filter`, set context to Tenant B,
delete, flush → must raise.

---

## P2-6 — `Role` is outside Layer 2 entirely

**File:** `backend/app/modules/rbac/models.py:18-37`

Not inheriting `TenantScoped` is the **right** call — the mixin declares
`tenant_id` NOT NULL and system roles need NULL. But the consequence is that
custom tenant roles are a tenant-owned table that the automatic filter will never
touch, and structural guard #3 will never check.

**Required:** the `rbac` repository scopes every custom-role query by hand
(`WHERE tenant_id = :ctx OR tenant_id IS NULL` for reads that must include system
roles); `Role` is added to the isolation registry with an explicit exemption
comment in structural guard #3 explaining *why* it is exempt; and
`tests/isolation/` covers Tenant B reading, updating and deleting a Tenant A
custom role.

Same treatment for any future model that legitimately cannot inherit the mixin.
The exemption list must be short, named, and justified — not implicit.

---

## P2-7 — Two session paths, one of which disables RLS

**File:** `backend/app/db/session.py:64-68`

`session_dependency` yields a session with **no transaction** and **no
`app.tenant_id`**. Any route using it runs outside the `UnitOfWork` contract, so
RLS is inert and "one transaction per request" (`ARCHITECTURE.md` §9) does not
hold.

Delete it, or make it delegate to `UnitOfWork`. Two ways to get a session is one
too many, and the wrong one is the one that is easier to type.

---

## P2-8 — Tenant violations raise bare `RuntimeError`

**Files:** `backend/app/db/tenant_guard.py:37` · `backend/app/core/context.py:23`

Fails closed, which is the important part. But it is outside the `AppError`
taxonomy, produces a 500, and — more significantly — emits no
`tenant.cross_access_attempt` security event. `SECURITY.md` §4 treats that event
as a genuine intrusion signal; silently 500-ing throws the signal away.

Add `CrossTenantAccessError(AppError)` and `MissingTenantContextError(AppError)`,
and emit the security event from the handler.

---

## P2-9 — The `with_loader_criteria` lambda needs a proof test

**File:** `backend/app/db/tenant_guard.py:16-22`

Binding `tenant_id` to a local before the lambda is the correct pattern, and
SQLAlchemy's lambda system extracts closure variables as bound parameters. But
the failure mode if that assumption is ever wrong — a cached statement carrying
tenant A's id while serving tenant B — is a silent cross-tenant leak, which is
too severe to leave resting on a reading of the documentation.

**Required test:** in a single process and a single session factory, query the
same `TenantScoped` entity as Tenant A then Tenant B, and assert each sees only
its own rows. Cheap, and it pins the behaviour against SQLAlchemy upgrades.

---

## P2-10 — `X-Request-ID` is accepted unvalidated

**File:** `backend/app/main.py:22-23`

Truncated to 64 chars but not format-checked; `ARCHITECTURE.md` §18 says accept
from an edge proxy *if well-formed*. Validate against `^[A-Za-z0-9._-]{1,64}$`
and generate a fresh id otherwise. Attacker-controlled text should not be flowing
into every log line for this request and back out in a response header.

---

## P3-11 — `sqlalchemy.ext.mypy.plugin` is deprecated

**File:** `backend/pyproject.toml:54`

Deprecated in SQLAlchemy 2.0, removed in 2.1, and redundant with native
`Mapped[]` typing. Almost certainly the source of the warning noted in
`# Commands Verified`. Remove it.

## P3-12 — Swagger path disagrees with the contract

**File:** `backend/app/main.py:62` — `docs_url="/docs"`; `API.md` §10 specifies
`/api/v1/docs`. Correctly disabled outside development.

---

## FIX HANDOFF FOR CODEX

Order matters — the P0s are in the layer everything else will be built on.

1. **P0-1** import `tenant_guard` + registration tests for both listeners
2. **P0-2** fail closed via `state.all_mappers` + 3 tests
3. **P1-5** include `session.deleted` + test
4. **P1-3** sanitise validation errors + password-not-echoed test
5. **P1-4** catch-all handler + complete `AppError` hierarchy + PyJWT → 401 mapping
6. **P2-6 … P2-10**, then **P3-11**, **P3-12**
7. Re-run: `ruff format --check . && ruff check . && mypy app && pytest -v`

Report each finding as **FIXED / NOT FIXED / DEFERRED WITH REASON**.

Do not proceed to repositories, services or routers until P0-1 and P0-2 are
closed. Every one of those layers will be written on top of the tenant guard, and
building on a switched-off control means re-auditing all of it later.

---

---

# IMPLEMENTATION HANDOFF FOR CODEX — PHASE 1

## Goal

A runnable modular monolith where a user can register, create an organization,
invite colleagues, assign roles, manage branches, and have every one of those
actions tenant-scoped, permission-checked and audited — with the isolation
guarantees proven by an adversarial test suite.

**Acceptance is not "the endpoints respond".** Acceptance is that the tests in
§10 pass, including the ones that try to break isolation.

---

## 1. Files to create

### Backend — foundation

```
backend/pyproject.toml           deps + ruff + mypy + pytest config (no setup.py)
backend/alembic.ini
backend/alembic/env.py           async-aware; imports Base.metadata; naming convention
backend/alembic/versions/
backend/Dockerfile               multi-stage, non-root user
backend/app/main.py              app factory, middleware, routers, exception handlers
backend/app/cli.py               `seed` command: currencies, permissions, system roles

backend/app/core/config.py       pydantic-settings; REQUIRED vars have no default
backend/app/core/security.py     Argon2id hash/verify, JWT encode/decode, token generation
backend/app/core/errors.py       AppError hierarchy + FastAPI exception handlers
backend/app/core/logging.py      structlog + redaction processor
backend/app/core/context.py      contextvars: request_id, TenantContext
backend/app/core/pagination.py   Page[T], CursorPage[T], cursor encode/decode + validation
backend/app/core/money.py        Decimal helpers, ROUND_HALF_UP, MoneyStr serializer
backend/app/core/clock.py        injectable UTC clock
backend/app/core/ids.py          uuid7()
backend/app/core/ratelimit.py    Redis sliding window
backend/app/core/redis.py        client factory

backend/app/db/base.py           DeclarativeBase + naming_convention (DATABASE.md §1.2)
backend/app/db/session.py        async engine, sessionmaker, UnitOfWork (SET LOCAL app.tenant_id)
backend/app/db/mixins.py         UUIDPk, Timestamped, TenantScoped
backend/app/db/types.py          Money, UnitCost, Quantity, Rate (asdecimal=True)
backend/app/db/tenant_guard.py   do_orm_execute filter + before_flush write guard

backend/app/api/deps.py          get_current_user, get_tenant_context, RequirePermission, RequireBranch
backend/app/api/v1/router.py     mounts module routers
```

### Backend — modules

Each module gets `models.py`, `schemas.py`, `repository.py`, `service.py`,
`router.py`, `permissions.py`, `events.py`:

```
backend/app/modules/auth/          users, sessions, refresh tokens, verification, reset
backend/app/modules/tenancy/       tenants, memberships, invitations
backend/app/modules/branches/      branches, warehouses
backend/app/modules/rbac/          roles, permissions, authorization service
backend/app/modules/audit/         audit events, security events
backend/app/modules/platform/      health, ready, metrics
backend/app/modules/idempotency/   idempotency key service (table + service; used from Phase 4)
backend/app/modules/outbox/        outbox model + drain task
```

### Backend — workers

```
backend/app/workers/celery_app.py
backend/app/workers/base.py           TenantAwareTask: refuses to run without tenant kwargs
backend/app/workers/tasks/email.py
backend/app/workers/tasks/outbox.py
backend/app/workers/tasks/cleanup.py  expire idempotency keys, tokens, sessions
```

### Backend — tests

```
backend/tests/conftest.py              app, db, redis, factories, tenant fixtures
backend/tests/factories/
backend/tests/unit/                    security, money, pagination, permission resolution
backend/tests/integration/auth/        register, login, refresh, rotation, reuse, logout, reset
backend/tests/integration/tenancy/     creation, membership, invitations
backend/tests/integration/branches/
backend/tests/integration/rbac/
backend/tests/integration/audit/
backend/tests/isolation/               cross-tenant adversarial matrix + registry
backend/tests/authz/                   permission-denial + escalation guards
backend/tests/concurrency/             committed parallel transactions
backend/tests/structural/              architecture guards (§9)
```

### Frontend

```
frontend/package.json  tsconfig.json  next.config.ts  tailwind.config.ts  Dockerfile
frontend/src/app/(auth)/login|register|forgot-password|reset-password|verify-email/page.tsx
frontend/src/app/(auth)/accept-invitation/page.tsx
frontend/src/app/(app)/layout.tsx                  authenticated shell: sidebar, topbar, org switcher
frontend/src/app/(app)/dashboard/page.tsx          placeholder tiles — no fabricated numbers
frontend/src/app/(app)/settings/organization/page.tsx
frontend/src/app/(app)/settings/branches/page.tsx
frontend/src/app/(app)/settings/members/page.tsx
frontend/src/app/(app)/settings/roles/page.tsx
frontend/src/app/(app)/settings/audit/page.tsx
frontend/src/app/onboarding/create-organization/page.tsx
frontend/src/app/api/bff/[...path]/route.ts        proxy + token custody (ADR-0014)
frontend/src/app/api/bff/auth/{login,logout,refresh,session}/route.ts
frontend/src/lib/{api-client,auth,permissions,format}.ts
frontend/src/components/ui/                        shadcn primitives
frontend/src/components/{app-shell,data-table,confirm-dialog,empty-state,error-state,can}.tsx
frontend/src/features/{auth,tenancy,branches,members,roles,audit}/
frontend/e2e/{auth.spec.ts,onboarding.spec.ts,members.spec.ts}
```

### Infrastructure

```
docker-compose.yml                     backend, worker, frontend, postgres, redis, mailhog
                                       (+ minio and qdrant, unused until Phases 9)
infra/postgres/init/01-roles.sql       creates nexora_app as NON-OWNER (critical for RLS)
Makefile                               format lint typecheck test build verify seed migrate
.github/workflows/ci.yml               8 jobs per ARCHITECTURE.md §21
```

---

## 2. Models

Column-level specification is in **`docs/DATABASE.md` §3** and is binding.
Summary and the traps worth restating:

| Model | Notes that are easy to get wrong |
|---|---|
| `User` | `CITEXT` email — case-insensitive uniqueness at the DB. **No `tenant_id`** |
| `Tenant` | `slug` unique + regex CHECK; `base_currency` FK |
| `Currency` | Reference table; `minor_units` drives rounding — do not hardcode 2 |
| `Branch` | `UNIQUE (tenant_id, code)` **and** partial unique `(tenant_id) WHERE is_default` |
| `Warehouse` | Created now; inventory semantics arrive Phase 2 |
| `Membership` | `UNIQUE (tenant_id, user_id)`; `roles_version` drives cache invalidation |
| `MembershipBranch` | **No rows = access to all branches.** Rows = restricted |
| `Permission` | Global catalog, code is PK, seeded by migration |
| `Role` | Two unique indexes needed — see below |
| `RolePermission` | Trigger blocks mutation when `role.is_system` |
| `MembershipRole` | Trigger enforces role tenant == membership tenant |
| `AuthSession` | One per login; the refresh family root |
| `RefreshToken` | `token_hash` SHA-256 UNIQUE; `used_at`; `replaced_by_id` self-FK |
| `EmailVerificationToken`, `PasswordResetToken` | Single-use, hashed, TTL |
| `Invitation` | Partial unique `(tenant_id, email) WHERE status='PENDING'` |
| `AuditEvent` | Append-only; **no `updated_at`** |
| `SecurityEvent` | `tenant_id` nullable — pre-auth failures have no tenant |
| `IdempotencyKey` | `UNIQUE (tenant_id, endpoint, key)` |
| `OutboxEvent` | Partial index `(sent_at, available_at) WHERE sent_at IS NULL` |

**The `Role` two-index trap.** `UNIQUE (tenant_id, code)` does *not* prevent
duplicate system roles, because `NULL` values are distinct in a unique index.
Both are required:

```sql
CREATE UNIQUE INDEX uq_roles_tenant_code   ON roles(tenant_id, code) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX uq_roles_system_code   ON roles(code)            WHERE tenant_id IS NULL;
```

Plus `CHECK (is_system = (tenant_id IS NULL))`.

---

## 3. Migrations

1. `0001_extensions` — `citext`, `pg_trgm`, `btree_gist`
2. `0002_core_identity` — users, currencies, tenants, branches, warehouses
3. `0003_membership_rbac` — memberships, membership_branches, permissions, roles, role_permissions, membership_roles
4. `0004_auth_tokens` — auth_sessions, refresh_tokens, verification/reset tokens, invitations
5. `0005_audit` — audit_events, security_events
6. `0006_platform` — idempotency_keys, outbox_events
7. `0007_triggers` — `updated_at`, append-only blocks, system-role immutability, membership-role tenant check
8. `0008_rls` — enable + FORCE RLS, policies with **both** `USING` and `WITH CHECK`
9. `0009_seed_reference` — currencies, permission catalog, system roles + mappings (data migration, separate revision)

Every migration needs a **real** `downgrade()`. CI runs `downgrade -1` then
`upgrade head`; `pass` fails the build.

Triggers, RLS and partial indexes need `op.execute()` — autogenerate does not
emit them, and `alembic check` will not notice they are missing. Write them by
hand and test them.

---

## 4. Constraints and invariants to enforce

**Database level**
- `UNIQUE (tenant_id, code)` on branches, warehouses, roles(custom)
- Partial unique: one default branch per tenant; one pending invitation per (tenant, email)
- `CHECK (is_system = (tenant_id IS NULL))` on roles
- `CHECK (fiscal_year_start_month BETWEEN 1 AND 12)`
- `CHECK (slug ~ '^[a-z0-9-]+$')`
- Trigger: `audit_events` and `security_events` reject UPDATE/DELETE
- Trigger: `role_permissions` rejects mutation for system roles
- Trigger: `membership_roles` rejects a role whose tenant differs from the membership's
- Trigger: `updated_at` maintained by the database
- RLS with `USING` **and** `WITH CHECK` on every tenant-owned table
- `REVOKE UPDATE, DELETE ON audit_events, security_events FROM nexora_app`

**Service level**
- A tenant always has ≥1 ACTIVE OWNER membership → removing the last → `409 LAST_OWNER_REQUIRED`
- A user cannot modify their own roles → `403 CANNOT_MODIFY_OWN_ROLES`
- A user cannot grant permissions they do not hold → `403 CANNOT_GRANT_UNHELD_PERMISSION`
- Only OWNER may grant OWNER
- A branch cannot be deactivated if it is the tenant's last active branch
- `base_currency` is immutable once any business record exists
- Invitation acceptance is single-use and atomic

---

## 5. Endpoints

Exactly as specified in **`docs/API.md` §5**, with §4 error shape, §3
pagination, §6 permissions, §9 rate limits.

Restating the three that carry the most risk:

**`POST /api/v1/tenants`** — the onboarding transaction. Tenant + OWNER
membership + `OWNER` role assignment + default branch + default warehouse +
audit event, **all in one transaction**. A partially-created organization is a
support incident with no clean recovery.

**`POST /api/v1/auth/refresh`** — the rotation-and-reuse-detection path
(`ARCHITECTURE.md` §4.1). Consuming an already-used token must revoke the whole
family and emit `security.refresh_reuse_detected`. This is the single most
security-sensitive function in Phase 1; write its tests first.

**`POST /api/v1/invitations/accept`** — public, token-bearing, handles both the
existing-user and new-user cases in one transaction. The role comes from the
invitation, never from the request body. A client choosing its own role is a
privilege-escalation hole.

---

## 6. Permissions

Seed the catalog and the system-role map from **`docs/API.md` §6**, including
the reserved codes for later phases. Seeding them now means role definitions
stay stable instead of churning every phase.

Enforcement: `RequirePermission(...)` on the route, object-level checks in the
service. Route permission alone is never sufficient for a resource-addressed
endpoint.

---

## 7. Audit events

Emit for every one of these, in the same transaction as the operation:

```
tenant.created              tenant.settings_changed
branch.created              branch.updated            branch.deactivated
warehouse.created           warehouse.updated
member.invited              member.invitation_revoked member.invitation_accepted
member.role_changed         member.branches_changed   member.status_changed
member.removed
role.created                role.updated              role.deleted
user.registered             user.email_verified       user.password_changed
user.password_reset
```

Security events, written **outside** the business transaction:

```
auth.login_failed           auth.login_succeeded      auth.logout
auth.refresh_reuse_detected auth.account_locked
authz.denied                ratelimit.exceeded        tenant.cross_access_attempt
```

The split matters: business audit rides the transaction so an audit row *proves*
the operation committed; security events record things that failed and must
survive the rollback that caused them.

---

## 8. Edge cases to handle explicitly

1. Register with an existing email → **same** response and comparable timing as a new email
2. Login for a non-existent user → verify against a dummy Argon2 hash so timing does not leak existence
3. Login while `locked_until` is in the future → `423`/`ACCOUNT_LOCKED`, no password check
4. User with **no** membership → authenticates, `active_tenant_id: null`, may only reach `/me` and `POST /tenants`
5. Refresh with a consumed token → revoke the family, `401`
6. Two concurrent refreshes from one client → one wins; document the single-flight requirement for the frontend
7. `switch-tenant` to a tenant the user has no ACTIVE membership in → `403`
8. Membership suspended mid-session → next request fails; `roles_version` bump invalidates the cache
9. Invitation accepted twice → second attempt `409`
10. Invitation for an email that registers independently first → accept links the existing user
11. Invitation to an already-member email → `409 DUPLICATE_RESOURCE`
12. Removing the last OWNER → `409`
13. Assigning Tenant B's custom role to a Tenant A membership → rejected by **trigger**, not only by service
14. Deactivating the last active branch → `409`
15. Cashier restricted to Branch A requests Branch B → `403 BRANCH_ACCESS_DENIED`
16. Password reset → **all** sessions revoked
17. Password change → **other** sessions revoked, current one survives
18. Request body containing `tenant_id` → `422` (`extra="forbid"`)
19. Tampered pagination cursor → `422`, never a widened scope
20. Redis unavailable → auth rate limiting fails **closed**; read endpoints fail **open**
21. Expired verification/reset token → generic failure, no existence disclosure
22. Concurrent identical invitations → partial unique index rejects the second

---

## 9. Structural guard tests (required in Phase 1)

Per ADR-0021. These are the tests that keep the architecture true as the system
grows, so they are built with the foundation rather than retrofitted:

1. **No float money** — walk `Base.metadata`; fail on `Float`/`REAL`/`DOUBLE PRECISION`
2. **Every route authenticated** — introspect `app.routes`; every route outside an explicit public allowlist carries an auth dependency
3. **Every `TenantScoped` model** has `tenant_id`, a leading-`tenant_id` index, and an isolation-registry entry
4. **Module imports acyclic** and respect `ARCHITECTURE.md` §2.1; `tenancy`/`rbac`/`audit`/`core` import no business module
5. **Escape-hatch budget** — count `skip_tenant_filter` uses against a recorded allowlist
6. **Routers import no repository or model module**
7. **No SQL string interpolation** — no f-string/`%`/`.format()` building SQL text
8. **Response models never expose `password_hash` or `token_hash`**

Each guard's failure message must name the rule and the offending symbol. A
guard that fails with a bare assertion error costs more than it saves.

---

## 10. Tests (binding)

### Required by `prompt.md` §43
1. User registration and login
2. Password security behaviour (Argon2id, never stored or returned in plaintext, no plaintext logging)
3. Tenant creation
4. Membership creation
5. **Tenant A cannot access Tenant B**
6. Role permission denial
7. Branch tenant isolation
8. Audit generation
9. Refresh token invalidation/revocation

### Isolation suite (`tests/isolation/`) — for every tenant-owned resource
```
Tenant B: GET    /resource/{A_id}  → 404   (never 403)
Tenant B: PATCH  /resource/{A_id}  → 404
Tenant B: DELETE /resource/{A_id}  → 404
Tenant B: list                     → contains no A id
Tenant B: create referencing an A foreign key → 422/404, never a cross-tenant link
```
Driven by a parametrized registry; guard test #3 fails the build if a model is missing from it.

### Authorization suite (`tests/authz/`)
- Every endpoint × an actor lacking its permission → `403`
- Self-role modification → `403`
- Granting an unheld permission → `403`
- Non-OWNER granting OWNER → `403`
- Removing the last OWNER → `409`
- Branch-restricted actor accessing another branch → `403`

### Auth suite
- Rotation issues a new token and consumes the old
- **Reuse of a consumed token revokes the entire family**
- Logout denylists the session; the access token stops working
- `logout-all` revokes every session
- Password reset revokes all sessions
- Password change revokes other sessions but not the current one
- Login rate limit triggers and `Retry-After` is present
- Enumeration: identical responses for existing vs non-existing emails

### Concurrency suite (`tests/concurrency/`)
- Two concurrent `POST /tenants` with the same slug → one succeeds, one `409`
- Two concurrent refreshes with the same token → one succeeds, the other detects reuse
- Two concurrent invitation accepts → one succeeds, one `409`

### RLS verification
Connecting as `nexora_app` **without** `app.tenant_id` set returns zero rows
from a tenant-owned table. This is the test that catches the classic
misconfiguration where the app connects as the table owner and RLS silently does
nothing (`DATABASE.md` §6).

---

## 11. Acceptance criteria

Phase 1 is complete when **all** hold:

- [ ] `make verify` passes: format, lint, mypy, pytest, vitest, `next build`
- [ ] `docker compose up` produces a working stack from a clean clone
- [ ] `alembic upgrade head` → `alembic check` clean → `downgrade -1` → `upgrade head` all succeed
- [ ] A user can register → verify email → create an organization → invite a colleague → assign a role → manage branches, through the UI
- [ ] Every §10 test suite passes, including isolation, authz and concurrency
- [ ] All 8 structural guards pass
- [ ] The RLS verification test passes
- [ ] Backend line coverage ≥ 80%; auth, tenancy and rbac services ≥ 90%
- [ ] No secret, token, password or PII appears in any log at any level
- [ ] No `TODO` standing in for core behaviour
- [ ] CI is green on all 8 jobs
- [ ] `docs/AGENT_HANDOFF.md` Codex sections updated with **actual** command output

---

## 12. Commands to verify

```bash
# Backend
cd backend
ruff format --check .
ruff check .
mypy app
alembic upgrade head && alembic check
alembic downgrade -1 && alembic upgrade head
pytest -v --cov=app --cov-report=term-missing --cov-fail-under=80
pytest tests/isolation tests/authz tests/structural -v      # must be zero failures
pytest tests/concurrency -v -m concurrency

# Frontend
cd frontend
npm run lint
npx tsc --noEmit
npm run test
npm run build

# Stack
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli seed
curl -fsS localhost:8000/health && curl -fsS localhost:8000/ready
npx playwright test
```

Report **actual output**, including failures. A truthful red build is worth more
than a claimed green one.

---

## 13. Explicitly out of scope for Phase 1

Products · inventory · sales · purchasing · POS · accounting · CRM · VAT ·
reporting · AI · RAG · forecasting · anomaly detection.

The `idempotency` and `outbox` modules ship as **infrastructure only** — the
tables and services exist and are unit-tested; no Phase 1 endpoint requires an
`Idempotency-Key` yet. They are built now because retrofitting idempotency into
POS in Phase 4 would mean reworking transaction boundaries under deadline
pressure.

---

# Instructions For Next Agent

**Codex — start here:**

1. Read `AGENTS.md`, then `docs/ARCHITECTURE.md`, `docs/DATABASE.md`,
   `docs/API.md`, `docs/SECURITY.md`, `docs/DECISIONS.md`.
2. Implement the handoff above in the §1 file order: foundation before modules,
   modules before routers, tests alongside — not after.
3. Build `db/tenant_guard.py` and `api/deps.py` **early**. Every module depends
   on them, and retrofitting tenant scoping is how leaks get shipped.
4. Write the refresh-rotation tests before the refresh implementation. It is the
   highest-risk function in the phase.
5. Pin Node **22 LTS** in Docker and CI (see `# Known Problems`).
6. Do not weaken a check to get green. If something is genuinely wrong in this
   handoff, record it under `# Known Problems` and continue with the rest.
7. Update the Codex sections of this file with real command output, then hand
   back for review.

**Claude will then run the Phase 1 review** (`prompt.md` §44): cross-tenant
access, IDOR/BOLA, role escalation, tenant context derivation, authorization
placement, JWT/refresh design, password handling, secrets, error leakage, audit,
transaction boundaries, constraints, indexes, migration quality, frontend auth
assumptions, and test quality — with findings classified P0/P1/P2/P3.

**Phase 2 will not start while any P0 or P1 finding is open.**
