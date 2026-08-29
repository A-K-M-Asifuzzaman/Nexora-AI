# Nexora AI — Database Design

> PostgreSQL 16. Authoritative schema contract.
> Phase 1 tables are specified to column level and are binding.
> Later-phase tables are specified at model level and will be detailed in their
> own design phase.

---

## 1. Conventions

| Rule | Value |
|---|---|
| Primary keys | `UUID`, generated **application-side** (`uuid7` preferred, `uuid4` acceptable) |
| Table names | `snake_case`, plural (`journal_entries`) |
| Timestamps | `TIMESTAMPTZ`, always UTC, never naive |
| Every table | `created_at`, `updated_at` |
| Tenant-owned tables | `tenant_id UUID NOT NULL REFERENCES tenants(id)` |
| Booleans | `NOT NULL DEFAULT false`, never nullable |
| Enums | PostgreSQL native `ENUM` for closed sets; `VARCHAR` + `CHECK` for sets expected to grow |
| Soft delete | Only where the domain needs history; otherwise hard delete. Never a `deleted` flag that queries forget |

### 1.1 UUIDv7 rationale

UUIDv4 primary keys on high-insert tables (`inventory_movements`,
`audit_events`, `sale_lines`) cause B-tree index fragmentation because inserts
land at random leaf pages. UUIDv7 is time-ordered, so inserts append and index
locality matches access patterns (recent rows are hot). Keys stay opaque and
non-enumerable — the timestamp prefix reveals creation time only, which is
already exposed as `created_at`.

### 1.2 Constraint naming (Alembic-stable)

```python
naming_convention = {
  "ix": "ix_%(table_name)s_%(column_0_N_name)s",
  "uq": "uq_%(table_name)s_%(column_0_N_name)s",
  "ck": "ck_%(table_name)s_%(constraint_name)s",
  "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  "pk": "pk_%(table_name)s",
}
```

Without this, Alembic emits unnamed constraints that cannot be dropped in a
downgrade. This is set once in `db/base.py` before any model is written.

---

## 2. Numeric Types — Money and Quantity

**Never `FLOAT`, `REAL`, or `DOUBLE PRECISION` for anything financial.** A
structural test walks the metadata and fails the build on violation
(`ARCHITECTURE.md` §13.4).

| Concept | SQL type | Python | Notes |
|---|---|---|---|
| Monetary amount | `NUMERIC(18,4)` | `Decimal` | 4 dp internally; rounded to currency minor units for presentation and posting |
| Unit price / cost | `NUMERIC(18,6)` | `Decimal` | Unit costs need more precision than totals (weighted-average cost drifts otherwise) |
| Quantity | `NUMERIC(20,6)` | `Decimal` | Fractional units: kg, litres, metres |
| Tax / discount rate | `NUMERIC(9,6)` | `Decimal` | `0.150000` = 15% |
| FX rate | `NUMERIC(20,10)` | `Decimal` | Reserved; single-currency in v1 |

SQLAlchemy types are declared once in `db/types.py`:

```python
Money    = Numeric(18, 4, asdecimal=True)
UnitCost = Numeric(18, 6, asdecimal=True)
Quantity = Numeric(20, 6, asdecimal=True)
Rate     = Numeric(9, 6, asdecimal=True)
```

`asdecimal=True` is mandatory — the driver otherwise hands back floats and the
whole guarantee evaporates silently.

### 2.1 Rounding policy

`ROUND_HALF_UP`, applied **per line**, then summed. Rationale: `ROUND_HALF_EVEN`
(banker's) is statistically nicer but diverges from what invoice recipients and
tax authorities expect; per-line rounding makes each printed line self-consistent
with the total, which is what a human checking an invoice verifies. Documented
in `docs/ACCOUNTING.md` §6 with worked examples.

Currency minor units are stored on the currency record (`BDT`→2, `USD`→2,
`JPY`→0) rather than hardcoded as 2.

---

## 3. Phase 1 Schema (binding)

### 3.1 `users` — global identity, **not** tenant-scoped

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `email` | CITEXT | NOT NULL, UNIQUE |
| `password_hash` | TEXT | NOT NULL |
| `full_name` | VARCHAR(200) | NOT NULL |
| `is_active` | BOOL | NOT NULL DEFAULT true |
| `is_superuser` | BOOL | NOT NULL DEFAULT false |
| `email_verified_at` | TIMESTAMPTZ | NULL |
| `last_login_at` | TIMESTAMPTZ | NULL |
| `failed_login_count` | INT | NOT NULL DEFAULT 0 |
| `locked_until` | TIMESTAMPTZ | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL |

- `CITEXT` (extension `citext`) so `Alice@x.com` and `alice@x.com` cannot both
  register. Case-insensitive uniqueness at the database, not in application code
  that a future endpoint forgets to call.
- `password_hash` is **never** selected into any response schema. Enforced by
  Pydantic response models that omit it, plus a structural test.
- No `tenant_id`: identity is global, tenant access comes from `memberships`.

### 3.2 `tenants`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `name` | VARCHAR(200) | NOT NULL |
| `slug` | VARCHAR(80) | NOT NULL, UNIQUE, `CHECK (slug ~ '^[a-z0-9-]+$')` |
| `legal_name` | VARCHAR(255) | NULL |
| `tax_identifier` | VARCHAR(64) | NULL |
| `base_currency` | CHAR(3) | NOT NULL, FK `currencies(code)` |
| `timezone` | VARCHAR(64) | NOT NULL DEFAULT `'UTC'` |
| `country_code` | CHAR(2) | NULL |
| `status` | ENUM(`ACTIVE`,`SUSPENDED`,`CANCELLED`) | NOT NULL DEFAULT `ACTIVE` |
| `allow_negative_inventory` | BOOL | NOT NULL DEFAULT false |
| `fiscal_year_start_month` | SMALLINT | NOT NULL DEFAULT 1, `CHECK BETWEEN 1 AND 12` |
| `settings` | JSONB | NOT NULL DEFAULT `'{}'` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL |

`base_currency` is immutable after the first posted transaction (service-level
guard + test). Changing it retroactively would silently reinterpret every
historical amount.

### 3.3 `currencies`

`code CHAR(3) PK`, `name`, `minor_units SMALLINT NOT NULL`, `symbol`.
Seeded reference data.

### 3.4 `branches`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | NOT NULL, FK `tenants(id)` ON DELETE RESTRICT |
| `code` | VARCHAR(32) | NOT NULL |
| `name` | VARCHAR(200) | NOT NULL |
| `address` / `phone` / `email` | — | NULL |
| `is_active` | BOOL | NOT NULL DEFAULT true |
| `is_default` | BOOL | NOT NULL DEFAULT false |

- `UNIQUE (tenant_id, code)` — tenant-scoped uniqueness, the pattern for every
  human-facing identifier in this system.
- `UNIQUE (tenant_id) WHERE is_default` — partial unique index: at most one
  default branch per tenant, enforced by the database rather than by hope.
- Index: `ix_branches_tenant_id_is_active`.

### 3.5 `warehouses`

`id`, `tenant_id`, `branch_id` (FK, NULL = tenant-level), `code`, `name`,
`is_active`. `UNIQUE (tenant_id, code)`.

Created in Phase 1 because branch setup needs a default warehouse; inventory
semantics arrive in Phase 2.

### 3.6 `memberships`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | NOT NULL, FK |
| `user_id` | UUID | NOT NULL, FK `users(id)` |
| `status` | ENUM(`INVITED`,`ACTIVE`,`SUSPENDED`,`REVOKED`) | NOT NULL |
| `roles_version` | INT | NOT NULL DEFAULT 0 |
| `invited_by_user_id` | UUID | NULL, FK `users(id)` |
| `joined_at` | TIMESTAMPTZ | NULL |

- `UNIQUE (tenant_id, user_id)` — one membership per user per tenant.
- Index `ix_memberships_user_id_status` — drives the "my organizations" list.
- `roles_version` increments on any role change and is the cache-invalidation
  key (`ARCHITECTURE.md` §5.2).

### 3.7 `membership_branches`

`membership_id` FK, `branch_id` FK, PK `(membership_id, branch_id)`.
**Absence of rows = access to all branches.** Presence = restricted to listed
branches only.

### 3.8 `permissions` — global catalog

`code VARCHAR(64) PK` (e.g. `sales.create`), `description`, `module VARCHAR(32)`.
Seeded by migration; never tenant-owned. Codes are immutable — renaming one
breaks every custom role referencing it.

### 3.9 `roles`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | **NULL** for system roles, set for custom roles |
| `code` | VARCHAR(64) | NOT NULL |
| `name` | VARCHAR(120) | NOT NULL |
| `is_system` | BOOL | NOT NULL DEFAULT false |

- `UNIQUE (tenant_id, code)` — with `NULL` tenant_id for system roles.
  Because `NULL` values are distinct in a unique index, add
  `CREATE UNIQUE INDEX uq_roles_system_code ON roles(code) WHERE tenant_id IS NULL;`
  Two indexes are required; this is a classic and easily-missed bug.
- `CHECK (is_system = (tenant_id IS NULL))` — system roles are exactly the
  global ones. Makes the two concepts impossible to desynchronize.

Seeded system roles: `OWNER`, `ADMIN`, `MANAGER`, `ACCOUNTANT`, `CASHIER`,
`SALES`, `INVENTORY_MANAGER`, `EMPLOYEE`.

### 3.10 `role_permissions`

`role_id` FK ON DELETE CASCADE, `permission_code` FK, PK `(role_id, permission_code)`.
A trigger blocks INSERT/UPDATE/DELETE where the role `is_system` — system role
definitions may only change via migration.

### 3.11 `membership_roles`

`membership_id` FK ON DELETE CASCADE, `role_id` FK, PK `(membership_id, role_id)`.
Effective permissions = union across assigned roles.

`CHECK` cannot express "role.tenant_id matches membership.tenant_id" across
tables, so a trigger enforces it: assigning Tenant B's custom role to a Tenant A
membership must fail at the database. This is a genuine cross-tenant escalation
vector and deserves more than a service check.

### 3.12 `auth_sessions`

`id` UUID PK, `user_id` FK, `created_at`, `last_used_at`, `revoked_at` NULL,
`revoked_reason` VARCHAR(64) NULL, `user_agent` TEXT, `ip` INET.
One row per login; the refresh-token family root.

### 3.13 `refresh_tokens`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `session_id` | UUID FK → `auth_sessions` ON DELETE CASCADE | |
| `token_hash` | CHAR(64) | SHA-256 hex, **UNIQUE** |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `used_at` | TIMESTAMPTZ | NULL — non-null means consumed |
| `replaced_by_id` | UUID | NULL, self-FK — the rotation chain |

Index `ix_refresh_tokens_session_id`. The raw token is **never** stored; only
its SHA-256. (Argon2 is unnecessary here: the token is 256 bits of CSPRNG
entropy, not a low-entropy human secret, so a fast hash is not brute-forceable
and keeps the refresh path cheap.)

### 3.14 `email_verification_tokens` / `password_reset_tokens`

`id`, `user_id` FK, `token_hash` CHAR(64) UNIQUE, `expires_at`, `used_at` NULL.
Single-use, short TTL (verification 24h, reset 1h). Issuing a new reset token
invalidates outstanding ones for that user.

### 3.15 `invitations`

`id`, `tenant_id`, `email` CITEXT, `role_id` FK, `token_hash` CHAR(64) UNIQUE,
`invited_by_user_id`, `expires_at`, `accepted_at` NULL, `status`.
Partial unique index: `UNIQUE (tenant_id, email) WHERE accepted_at IS NULL AND status='PENDING'`
— one live invitation per email per tenant.

### 3.16 `audit_events` — append-only

| Column | Type |
|---|---|
| `id` | UUID PK |
| `tenant_id` | UUID NOT NULL |
| `actor_user_id` | UUID NULL (NULL = system) |
| `actor_membership_id` | UUID NULL |
| `action` | VARCHAR(80) NOT NULL |
| `resource_type` | VARCHAR(64) NOT NULL |
| `resource_id` | UUID NULL |
| `request_id` | VARCHAR(64) NULL |
| `ip` | INET NULL |
| `user_agent` | TEXT NULL |
| `metadata` | JSONB NOT NULL DEFAULT `'{}'` |
| `occurred_at` | TIMESTAMPTZ NOT NULL DEFAULT `now()` |

Indexes: `(tenant_id, occurred_at DESC)`, `(tenant_id, resource_type, resource_id)`,
`(tenant_id, actor_user_id, occurred_at DESC)`.

No `updated_at` — the row is immutable by definition, and offering the column
would imply otherwise.

### 3.17 `security_events`

Same shape, written **outside** the business transaction, `tenant_id` nullable
(pre-authentication failures have no tenant). Records: `auth.login_failed`,
`auth.refresh_reuse_detected`, `authz.denied`, `ratelimit.exceeded`,
`tenant.cross_access_attempt`.

### 3.18 `idempotency_keys`

Per `ARCHITECTURE.md` §11. `UNIQUE (tenant_id, endpoint, key)`,
index on `expires_at` for the cleanup job.

### 3.19 `outbox_events`

`id`, `tenant_id`, `topic`, `payload` JSONB, `created_at`, `available_at`,
`sent_at` NULL, `attempts` INT, `last_error` TEXT.
Index `(sent_at, available_at) WHERE sent_at IS NULL` — a partial index so the
drain query stays cheap as the sent-history grows.

---

## 4. Forward Schema (later phases, model-level)

**Phase 2 — Catalog + Inventory**
`categories` (self-FK tree), `brands`, `units_of_measure`, `tax_categories`,
`products`, `product_variants`, `product_barcodes`, `inventory_movements`,
`inventory_balances`, `stock_reservations`, `stock_transfers`,
`stock_transfer_lines`, `stock_adjustments`.

Binding now: `UNIQUE (tenant_id, sku)` on products;
`UNIQUE (tenant_id, barcode)` on barcodes; `inventory_movements` is
append-only with an UPDATE/DELETE-blocking trigger;
`inventory_balances` unique on `(tenant_id, warehouse_id, product_id)` with
`CHECK (reserved_quantity >= 0)`.

**Phase 3 — Sales + Purchasing**
`customers`, `suppliers`, `quotations`, `sales_orders`, `sales_order_lines`,
`fulfillments`, `invoices`, `invoice_lines`, `payments`, `payment_allocations`,
`purchase_orders`, `goods_receipts`, `supplier_bills`, `credit_notes`.
`UNIQUE (tenant_id, invoice_number)`.

**Phase 4 — POS** `pos_terminals`, `pos_sessions`, `sales`, `sale_lines`,
`held_sales`, `receipts`, `sale_returns`.

**Phase 5 — Accounting** `accounts`, `journals`, `journal_entries`,
`journal_entry_lines`, `fiscal_periods`, `product_cost_layers`.

**Phase 7 — VAT** `vat_rates`, `vat_transactions`, `vat_returns`.

**Phase 9 — RAG** `documents`, `document_chunks`, `document_acl`,
`document_jobs`.

---

## 5. Indexing Strategy

Every tenant-owned table gets a **leading-`tenant_id` composite index** matching
its dominant access path. A bare `tenant_id` index is usually useless — with one
tenant per query and thousands of rows, the planner needs the second column to
avoid a heap scan.

```sql
(tenant_id, created_at DESC)      list views, newest-first
(tenant_id, status)               work queues
(tenant_id, <natural_key>)        UNIQUE, doubles as a lookup index
(tenant_id, customer_id, created_at DESC)
(tenant_id, warehouse_id, product_id)   UNIQUE on balances
```

Text search (product name/SKU/barcode) uses a `pg_trgm` GIN index rather than
`ILIKE '%x%'`, which cannot use a B-tree and degrades linearly — POS search
must stay sub-100ms with 100k products.

**No index is added without a query that needs it.** Every index costs write
throughput, and `inventory_movements` is the hottest write path in the system.

---

## 6. Row-Level Security

For every tenant-owned table:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <t>
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

`NULLIF(..., '')` matters: `current_setting(..., true)` yields NULL when unset,
but an empty-string GUC would otherwise fail the `::uuid` cast with an error
instead of filtering. With it, an unset tenant yields NULL, the predicate is
NULL, and **zero rows** match — RLS fails closed.

Roles:

- `nexora_owner` — owns the schema, runs migrations and seeds. Not used by the app.
- `nexora_app` — the application role. **Not** the table owner, so the policies
  genuinely apply. This detail is the whole point: policies do not apply to a
  table's owner, so an app connecting as owner has RLS that silently does nothing.

`WITH CHECK` matters as much as `USING`: without it, RLS filters reads but
permits *writing* a row belonging to another tenant.

### 6.1 Do **not** use `FORCE ROW LEVEL SECURITY` — corrected 2026-08-29

An earlier revision of this document specified `FORCE ROW LEVEL SECURITY`
alongside `ENABLE`. **That was wrong** (ADR-0022) and is corrected here.

`ENABLE` applies policies to every role *except the table owner*. `FORCE`
additionally applies them to the owner. Since `nexora_app` is already a
non-owner, `ENABLE` alone fully polices the application; `FORCE` adds nothing
there and instead subjects `nexora_owner` — which runs migrations, seeding and
maintenance — to tenant policies it can never satisfy.

Verified empirically: with `FORCE`, seeding the system roles fails with
`new row violates row-level security policy for table "roles"`, because system
roles carry `tenant_id IS NULL` and no GUC value can satisfy the `WITH CHECK`.
Removing `FORCE` makes the identical insert succeed.

`FORCE` also buys no security: an attacker holding the owner connection can
`DROP POLICY`, `ALTER TABLE … NO FORCE`, or `DROP TABLE` outright.

The misconfiguration `FORCE` was meant to catch — the app accidentally
connecting as the owner, silently disabling RLS — is caught properly by an
explicit test instead:

```sql
-- must all hold in tests/integration/test_rls.py
SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user;      -- false
SELECT tableowner <> current_user FROM pg_tables WHERE tablename='branches';  -- true
SET app.tenant_id = '';  SELECT count(*) FROM branches;              -- 0
```

An assertion is a better guard than a mechanism that breaks every legitimate
owner-run operation.

---

## 7. Triggers and Database-Level Invariants

| Trigger | Table | Guarantees |
|---|---|---|
| `trg_block_mutation` | `audit_events`, `inventory_movements` | `BEFORE UPDATE OR DELETE` → `RAISE EXCEPTION`. Append-only is structural |
| `trg_posted_journal_immutable` | `journal_entries`, `journal_entry_lines` | Blocks mutation once `status='POSTED'` (except the reversal linkage columns) |
| `trg_journal_balanced` | `journal_entries` | `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED` — at COMMIT, `SUM(debit) = SUM(credit)` and equals header totals |
| `trg_system_role_immutable` | `roles`, `role_permissions` | System role definitions change only by migration |
| `trg_membership_role_same_tenant` | `membership_roles` | Role's tenant matches membership's tenant |
| `trg_set_updated_at` | all | Maintains `updated_at` at the database, so a raw SQL fix cannot leave it stale |

The deferred constraint trigger for journal balance is the important one: it
must fire at COMMIT, not per statement, because lines are inserted one at a time
and the entry is legitimately unbalanced mid-transaction.

---

## 8. Migrations

- Alembic, one head, linear history. Merge commits producing two heads are
  rejected in review.
- Every migration implements a **real** `downgrade()`. `pass` is not acceptable
  — CI runs `downgrade -1` then `upgrade head`.
- `alembic check` in CI fails on model/migration drift.
- Raw SQL (`op.execute`) is required for triggers, RLS, partial indexes and
  extensions; autogenerate does not emit them.
- Data migrations are separate revisions from schema migrations.
- Extensions enabled in the first migration: `citext`, `pg_trgm`, `btree_gist`.
- Destructive operations (drop column, drop table, narrow a type) require an
  explicit note in the migration docstring stating why data loss is acceptable.

### 8.1 Concurrent index creation

Index creation on a populated production table uses
`CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction — such
migrations set `transactional_ddl = False` for that revision and are flagged in
the docstring. Not relevant pre-launch, but the pattern is established now so it
is not improvised later under pressure.
