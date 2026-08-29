# Nexora AI — API Contract

> Versioned REST under `/api/v1`. Binding for backend and frontend.
> A breaking change requires `/api/v2`, not an edit here.

---

## 1. Principles

1. **Tenant comes from the token, never the URL.** There is no
   `/tenants/{id}/products`. The active tenant is a signed claim; the path is
   simply `/products`. This removes an entire class of IDOR by construction —
   there is no tenant identifier for an attacker to tamper with.
2. **Money is a JSON string.** `"1234.5600"`, never `1234.56`. JSON numbers
   become IEEE-754 doubles in every mainstream client (ADR-0015).
3. **Timestamps are RFC 3339 UTC** with `Z`.
4. Resource identifiers are UUIDs.
5. `Content-Type: application/json` throughout; uploads use `multipart/form-data`.
6. Unknown request-body fields are **rejected** (`extra="forbid"`), which blocks
   mass-assignment.

---

## 2. Standard Headers

| Header | Direction | Purpose |
|---|---|---|
| `Authorization: Bearer <jwt>` | → | Access token |
| `X-Request-ID` | ↔ | Correlation; generated if absent, always echoed |
| `Idempotency-Key` | → | Required on POS checkout, payments, refunds |
| `X-CSRF-Token` | → | BFF state-changing routes only |
| `Retry-After` | ← | On `429` and `503` |

---

## 3. Pagination

Two schemes, chosen deliberately:

**Offset** for admin/browse views needing page numbers:
```
GET /products?page=1&page_size=50   # page_size ≤ 100, default 25
```
```json
{ "items": [...], "page": 1, "page_size": 50, "total": 1284, "total_pages": 26 }
```

**Cursor** for large append-only feeds (`audit_events`, `inventory_movements`),
where `OFFSET 50000` forces the planner to walk 50 000 rows:
```
GET /inventory/movements?cursor=<opaque>&limit=50
```
```json
{ "items": [...], "next_cursor": "eyJ...", "has_more": true }
```

The cursor is an opaque base64 of `(sort_key, id)` and is **validated**, not
trusted — a tampered cursor yields `422`, never a scope change.

**No endpoint returns an unbounded list.** A missing `limit` means the default,
never "all". Enforced by a structural test over response models.

---

## 4. Error Envelope

```json
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Insufficient inventory for 2 item(s).",
    "details": { "items": [{ "product_id": "…", "requested": "5.000000", "available": "3.000000" }] }
  },
  "request_id": "01JB2Z…"
}
```

`code` is a stable machine identifier — clients branch on it, never on
`message`. `message` is human-readable and safe to display. `details` is
structured and may be empty.

### 4.1 Error code registry

**Auth** `INVALID_CREDENTIALS` · `TOKEN_EXPIRED` · `TOKEN_INVALID` ·
`SESSION_REVOKED` · `EMAIL_NOT_VERIFIED` · `ACCOUNT_LOCKED` ·
`REFRESH_REUSE_DETECTED`

**Authorization** `PERMISSION_DENIED` · `BRANCH_ACCESS_DENIED` ·
`NO_ACTIVE_TENANT` · `CANNOT_MODIFY_OWN_ROLES` ·
`CANNOT_MODIFY_OWN_BRANCHES` · `CANNOT_GRANT_UNHELD_PERMISSION` ·
`CANNOT_GRANT_UNHELD_BRANCH` · `PRIVILEGE_ESCALATION` ·
`LAST_OWNER_REQUIRED` · `SYSTEM_ROLE_IMMUTABLE` · `ROLE_ASSIGNED`

### 4.1.1 The two containment rules

Authorization has two dimensions (`ARCHITECTURE.md` §3.1, §5.1), and each has a
containment rule that prevents an actor from granting more than it holds:

| Dimension | Rule | Violation code |
|---|---|---|
| Permissions | granted set ⊆ actor's effective permissions | `CANNOT_GRANT_UNHELD_PERMISSION` |
| Branch scope | granted set ⊆ actor's branch scope, when the actor is restricted | `CANNOT_GRANT_UNHELD_BRANCH` |

For branch scope the **empty set means unrestricted**, so a restricted actor may
never send `branch_ids: []` — that would widen the target to every branch. An
unrestricted actor (no `membership_branches` rows) may grant anything.

Both dimensions additionally forbid self-modification
(`CANNOT_MODIFY_OWN_ROLES`, `CANNOT_MODIFY_OWN_BRANCHES`): holding a management
permission must never be a route to promoting yourself.

**Validation** `VALIDATION_ERROR` · `INVALID_STATE_TRANSITION` ·
`DUPLICATE_RESOURCE`

**Resource** `RESOURCE_NOT_FOUND` (also returned for cross-tenant access)

**Idempotency** `IDEMPOTENCY_KEY_REUSE` · `REQUEST_IN_PROGRESS`

**Inventory** `INSUFFICIENT_STOCK` · `NEGATIVE_INVENTORY_NOT_ALLOWED` ·
`RESERVATION_EXPIRED`

**Accounting** `UNBALANCED_JOURNAL` · `PERIOD_CLOSED` · `ENTRY_ALREADY_POSTED` ·
`ENTRY_ALREADY_REVERSED` · `ENTRY_IMMUTABLE` · `ACCOUNT_INACTIVE` ·
`ACCOUNT_NOT_POSTABLE`

**AI** `AI_TOOL_NOT_PERMITTED` · `AI_DATE_RANGE_TOO_LARGE` ·
`AI_PROVIDER_UNAVAILABLE` · `AI_UNGROUNDED_RESPONSE` · `INSUFFICIENT_HISTORY`

**Platform** `RATE_LIMITED` · `INTERNAL_ERROR` · `SERVICE_UNAVAILABLE`

### 4.2 Status code discipline

| Code | Meaning here |
|---|---|
| `400` | Malformed request (not schema-level) |
| `401` | Missing/invalid/expired credentials |
| `403` | Authenticated, in-tenant, insufficient permission |
| `404` | Not found **or not yours** — deliberately indistinguishable |
| `409` | State conflict, concurrent modification, in-progress idempotent request |
| `422` | Schema or business-rule violation |
| `429` | Rate limited |

The `403`/`404` distinction is the one to get right: `403` for a resource the
user's tenant owns but their role forbids; `404` when the resource belongs to
another tenant. Returning `403` in the second case confirms existence
(`SECURITY.md` §4).

---

## 5. Phase 1 Endpoints (binding)

### 5.1 Authentication — `/api/v1/auth`

| Method | Path | Auth | Permission | Notes |
|---|---|---|---|---|
| `POST` | `/register` | public | — | Rate limited. Uniform response regardless of email existence |
| `POST` | `/login` | public | — | Returns access token; sets refresh cookie |
| `POST` | `/refresh` | cookie | — | Rotates; reuse revokes family |
| `POST` | `/logout` | bearer | — | Revokes session; denylists `sid` |
| `POST` | `/logout-all` | bearer | — | Revokes every session for the user |
| `GET` | `/me` | bearer | — | User + memberships + active tenant + **effective permissions** |
| `POST` | `/switch-tenant` | bearer | — | New access token bound to another membership |
| `POST` | `/verify-email` | public | — | Single-use token |
| `POST` | `/resend-verification` | public | — | Rate limited, uniform response |
| `POST` | `/forgot-password` | public | — | **Always `202`**, even for unknown email |
| `POST` | `/reset-password` | public | — | Single-use token; revokes all sessions |
| `POST` | `/change-password` | bearer | — | Requires current password; revokes other sessions |

`POST /login` response:

```json
{
  "access_token": "eyJhbGciOi…",
  "token_type": "bearer",
  "expires_in": 900,
  "active_tenant_id": "01JB…",
  "memberships": [
    { "tenant_id": "01JB…", "tenant_name": "Acme Traders", "roles": ["OWNER"] }
  ]
}
```

The refresh token is **not** in the body — it is set as
`Set-Cookie: nexora_rt=…; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth`.
The narrow `Path` means it is not attached to ordinary API calls, shrinking its
exposure surface.

A user with **no** membership authenticates successfully and receives
`active_tenant_id: null` — they can only reach `/me` and
`POST /tenants` (create an organization). Every tenant-scoped route returns
`403 NO_ACTIVE_TENANT`.

### 5.2 Tenants — `/api/v1/tenants`

| Method | Path | Permission | Notes |
|---|---|---|---|
| `POST` | `/` | authenticated | Creates tenant + OWNER membership + default branch + default warehouse, **atomically** |
| `GET` | `/current` | authenticated | Active tenant profile |
| `PATCH` | `/current` | `tenant.manage_settings` | Audited |
| `GET` | `/current/settings` | `tenant.manage_settings` | |

`POST /tenants` is the onboarding transaction. All of it commits or none:
tenant, owner membership, `OWNER` role assignment, default branch, default
warehouse, audit event.

### 5.3 Branches — `/api/v1/branches`

`GET /` (`branches.read`) · `POST /` (`branches.create`) ·
`GET /{id}` (`branches.read`) · `PATCH /{id}` (`branches.update`) ·
`DELETE /{id}` (`branches.delete` — soft, refuses if the last active branch)

### 5.4 Members — `/api/v1/members`

| Method | Path | Permission |
|---|---|---|
| `GET` | `/` | `users.read` |
| `GET` | `/{membership_id}` | `users.read` |
| `PATCH` | `/{membership_id}/roles` | `users.manage_roles` |
| `PATCH` | `/{membership_id}/branches` | `users.manage_roles` |
| `PATCH` | `/{membership_id}/status` | `users.manage` |
| `DELETE` | `/{membership_id}` | `users.manage` |

Every one of these enforces the §5.1 escalation guards of `ARCHITECTURE.md`
(no self-role-edit, subset rule, OWNER-only-grants-OWNER, last-owner
protection).

### 5.5 Invitations — `/api/v1/invitations`

`POST /` (`users.invite`) · `GET /` (`users.read`) ·
`POST /{id}/resend` (`users.invite`) · `DELETE /{id}` (`users.invite`) ·
`POST /accept` (**public**, token-bearing)

`POST /accept` handles both an existing user (creates membership) and a new user
(creates user + membership) in one transaction. The invitation token is
single-use and carries the role — the accepting client cannot choose its own
role.

### 5.6 Roles & Permissions — `/api/v1/roles`

`GET /` (`users.read`) · `GET /permissions` (`users.read`) ·
`POST /` (`roles.manage`) · `PATCH /{id}` (`roles.manage`, custom only) ·
`DELETE /{id}` (`roles.manage`, custom only, refuses if assigned)

### 5.7 Audit — `/api/v1/audit`

`GET /events` (`audit.read`) — cursor paginated; filters `action`,
`resource_type`, `resource_id`, `actor_user_id`, `from`, `to`.
**No write endpoints exist.** The API surface offers no way to modify audit
history.

### 5.8 Platform

`GET /health` · `GET /ready` · `GET /metrics` — unversioned, outside `/api/v1`.

---

## 6. Permission Catalog (Phase 1 seed)

```
tenant.manage_settings

branches.read      branches.create    branches.update    branches.delete
warehouses.read    warehouses.create  warehouses.update  warehouses.delete

users.read         users.invite       users.manage       users.manage_roles
roles.manage

audit.read
```

Reserved now, enforced from their phase (so role seeds are stable rather than
churning every phase):

```
products.*  inventory.*  sales.*  purchases.*  pos.*  accounting.*
customers.* suppliers.*  crm.*    vat.*        reports.read
ai.use      documents.upload      documents.read       documents.delete
```

### 6.1 System role → permission map (Phase 1)

| Role | Phase 1 permissions |
|---|---|
| `OWNER` | all |
| `ADMIN` | all except `tenant.manage_settings` |
| `MANAGER` | `branches.read`, `warehouses.read`, `users.read`, `audit.read` |
| `ACCOUNTANT` | `branches.read`, `users.read`, `audit.read` |
| `CASHIER` | `branches.read` |
| `SALES` | `branches.read` |
| `INVENTORY_MANAGER` | `branches.read`, `warehouses.read` |
| `EMPLOYEE` | `branches.read` |

---

## 7. Validation Rules

- Request models: `ConfigDict(extra="forbid")`. A stray field is `422`, not
  silently ignored — this is the mass-assignment defense.
- Money fields accept a **string** and parse to `Decimal`; a JSON float is
  rejected with `VALIDATION_ERROR`. Accepting floats would reintroduce the
  precision bug at the boundary.
- Dates are validated as ranges: `from <= to`, and span-capped per endpoint
  (reports 366 days, AI tools 366 days).
- Free-text fields have explicit `max_length`. Unbounded text is a storage and
  log-flooding vector.
- Enum inputs are Python enums, so an invalid value is `422` before reaching a
  service.

---

## 8. Idempotency Contract

Endpoints requiring `Idempotency-Key` (missing → `400`):

```
POST /api/v1/pos/checkout
POST /api/v1/pos/refunds
POST /api/v1/sales/payments
POST /api/v1/purchases/payments
POST /api/v1/invoices/{id}/issue
```

Key: client-generated UUIDv4, scoped to `(tenant, endpoint)`, retained 24h.
Behaviour per `ARCHITECTURE.md` §11. Replayed responses carry
`Idempotency-Replayed: true` so clients can distinguish a fresh result from a
replay when it matters (receipt printing).

---

## 9. Rate Limits (Phase 1)

| Scope | Limit |
|---|---|
| `POST /auth/login` | 5 / 15 min per (IP, email); 20 / 15 min per IP |
| `POST /auth/register` | 3 / hour per IP |
| `POST /auth/forgot-password` | 3 / hour per email; 10 / hour per IP |
| `POST /auth/refresh` | 60 / hour per session |
| Authenticated default | 300 / min per membership |
| `POST /ai/chat` | 20 / min per membership (Phase 8) |

`429` responses carry `Retry-After`. Limits are per-membership rather than per
user so one tenant cannot exhaust another's budget.

---

## 10. OpenAPI

FastAPI generates `/api/v1/openapi.json`; Swagger UI is enabled in dev and
**disabled in production**. Every route declares `response_model`,
`status_code`, and its error responses, so the schema is a genuine contract
rather than decoration. The frontend generates types from it — a backend
contract change surfaces as a frontend type error in CI, which is the point.
