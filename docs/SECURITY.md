# Nexora AI — Security Architecture

> Phase 0 baseline. Revisited and audited in Phase 11.
> Every control below is either implemented with a test, or listed in §12 as
> not-yet-implemented. Nothing here is aspirational without being marked so.

---

## 1. Threat Model

| # | Actor | Primary goal | Principal controls |
|---|---|---|---|
| 1 | Unauthenticated attacker | Break in, enumerate | Argon2id, rate limits, uniform responses, short token TTL |
| 2 | Malicious tenant | Read another tenant's data | 3-layer isolation, uniform `404`, adversarial tests |
| 3 | Malicious employee | Exceed own role | Permission model, escalation guards, immutable audit |
| 4 | Compromised cashier | Fraudulent refunds/discounts | Branch scope, refund permission split, anomaly detection |
| 5 | Compromised manager | Alter financials | Posted-entry immutability, reversal-only correction, audit |
| 6 | Malicious upload | RCE, stored XSS, storage abuse | MIME sniffing, size caps, random names, no inline serving |
| 7 | Malicious RAG document | Prompt injection → data exfiltration | Untrusted-content framing, tool allowlist, tenant-filtered retrieval |
| 8 | Prompt injection (any source) | Make the LLM exceed the user's rights | Authorization at the **tool**, not in the prompt |
| 9 | Replay attacker | Duplicate a checkout/payment | Idempotency keys, atomic key+business commit |
| 10 | IDOR / BOLA prober | Access objects by guessing ids | UUIDv7 ids, tenant filter, object-level authz, `404` |
| 11 | Enumerator | Map users/tenants | Uniform responses, constant-time-ish auth, rate limits |
| 12 | Race exploiter | Oversell, double-spend | `FOR UPDATE` with deterministic lock order |

---

## 2. Authentication Controls

**Password storage.** Argon2id via `argon2-cffi`: `m=65536 KiB, t=3, p=4`,
16-byte salt, 32-byte hash. Parameters live in config and are re-tunable; hashes
are self-describing so raising cost later rehashes transparently on next login.

Rejected: bcrypt (72-byte silent truncation — a 100-character passphrase is
weaker than expected, and the failure is invisible), PBKDF2 (not memory-hard,
cheap to attack on GPUs), any fast hash.

**Password policy.** Minimum 12 characters. No composition rules — they push
users toward `Password1!` — but the password is checked against a common-password
list and rejected if it contains the user's email local-part. NIST SP 800-63B
alignment.

**Login throttling.** Two mechanisms:
- Redis rate limit per `(IP, email)` and per IP (`API.md` §9).
- Per-account `failed_login_count` with **exponential backoff** (`locked_until`),
  not a hard lock. A hard lock lets an attacker who knows an email deny that
  user service indefinitely — the DoS becomes the attack. Backoff resets on
  success.

**Enumeration resistance.** `/register`, `/login`, `/forgot-password` and
`/resend-verification` return the same response and comparable timing whether or
not the account exists. When the user is absent, login verifies the supplied
password against a **dummy Argon2 hash** so the timing signal does not leak
existence.

**Token design.** See `ARCHITECTURE.md` §4. Key properties:
- Access token 15 min → bounded revocation lag.
- Refresh token opaque, hashed at rest → a database read cannot forge one.
- Rotation with reuse detection → theft is detected and self-limits.
- `httpOnly` cookie with `Path=/api/v1/auth` → not sent on ordinary API calls,
  and unreadable by JavaScript.
- Session denylist in Redis → logout is effective within the access TTL.

**Secret management.** `JWT_SECRET_KEY` has no default. `Settings` raises at
startup if it is absent or shorter than 32 bytes, so the application cannot boot
with a placeholder. `.env` is gitignored; `.env.example` carries **only**
placeholders. `gitleaks` runs in CI.

---

## 3. Authorization Controls

**Route level** — `RequirePermission(...)` dependency. A structural test asserts
every route outside a small public allowlist has an auth dependency, so the
"forgot to add `Depends`" vulnerability cannot ship.

**Object level (BOLA)** — route permission alone is never sufficient for a
resource-addressed endpoint. After loading a resource the service verifies:
tenant match (already guaranteed by the query filter, verified again as
defense-in-depth), branch scope, and any ownership rule (e.g. a cashier may void
only their own open POS session).

**Escalation guards** (`ARCHITECTURE.md` §5.1) — no self-role-edit; no granting
permissions you do not hold; OWNER-only-grants-OWNER; last-owner protection.
Each has a dedicated test in `tests/authz/`.

**No role-string checks in business logic.** `if role == "ADMIN"` is a review
defect. Roles are a packaging of permissions; business code asks about
permissions.

---

## 4. Tenant Isolation

Three layers, described in `ARCHITECTURE.md` §3. Security-relevant properties:

- Client-supplied `tenant_id` is **ignored everywhere**; schemas forbid the
  field outright.
- Cross-tenant object access returns **`404`, never `403`**. A `403` confirms
  existence and converts an id-guessing probe into an oracle. Uniform `404`
  gives the attacker nothing.
- A cross-tenant attempt is recorded as `tenant.cross_access_attempt` in
  `security_events`, which is a genuine intrusion signal and should alert.
- `tests/isolation/` runs the full GET/PATCH/DELETE/list matrix for every
  tenant-owned resource, and a structural test fails the build if a
  `TenantScoped` model is missing from that registry — so coverage cannot rot as
  modules are added.

---

## 5. Injection

**SQL** — SQLAlchemy parameter binding throughout. Raw SQL is permitted only in
migrations and hand-tuned report aggregates, always with bound parameters. A
structural test greps for f-string/`%`/`.format()` construction of SQL text and
fails on a hit. The LLM never produces SQL (`docs/AI.md` §2).

**XSS** — React escapes by default. `dangerouslySetInnerHTML` is banned by ESLint
rule; the only exception path would be sanitized document previews, which must
go through DOMPurify and be justified in review. User-supplied filenames are
escaped on display — a filename is attacker-controlled text, not a label.

**CSRF** — the API itself is bearer-authenticated and therefore not
CSRF-exposed. The **BFF** is cookie-authenticated and is: `SameSite=Lax`,
plus a double-submit CSRF token on state-changing routes, plus a strict `Origin`
check.

**Mass assignment** — `extra="forbid"` on every request model, and response
models are explicit allowlists rather than `from_attributes` dumps of the ORM
object. A field added to a model does not automatically become public.

**Header injection / log forging** — user input is never concatenated into log
lines; structured logging passes values as fields, so a newline in a name cannot
fabricate a log entry.

---

## 6. Rate Limiting

Redis sliding window (`app/core/ratelimit.py`), two independent call sites
built on it:

- **Unauthenticated surface** — `app/modules/auth/ratelimit.py`, keyed by
  `(IP, email)` and by IP alone (`API.md` §9: login, register, forgot-password,
  refresh, the MFA challenge). **Fails closed**: a Redis outage must not open
  a brute-force window.
- **Authenticated, expensive endpoints** — `app/api/ratelimit.py`, keyed on
  **membership**, not user or IP, so one tenant cannot exhaust another's
  budget and a NAT'd office is not collectively throttled. Applied to the AI
  copilot (`/ai/ask`), document upload, document search, and every report
  endpoint. **Fails open**: a Redis outage must not take down reporting or
  the copilot for every authenticated user over one dependency's blip — the
  cost these limits bound (LLM spend, storage) is real but not the kind of
  risk that justifies an outage of its own.

---

## 7. Idempotency and Replay

Full design in `ARCHITECTURE.md` §11. The security-relevant property is that the
idempotency row and the business rows commit in the **same transaction** —
therefore a replayed checkout cannot produce a second sale, a second stock
deduction, or a second payment, even under a network partition where the client
never saw the first response.

Same key + different payload → `422`, never "process it anyway". Treating a
reused key as a new request is exactly the double-charge bug.

---

## 8. File Upload

Every upload:

1. **Size cap** enforced while streaming, not after buffering (a 5 GB upload
   must not first become 5 GB of memory). Default 25 MB, configurable.
2. **Extension allowlist** — `pdf, docx, xlsx, csv, txt, md, png, jpg`.
3. **Content sniffing** (`python-magic`) — the *actual* bytes must match the
   claimed type. Extension alone is attacker-controlled.
4. **Random stored name** — `{uuid}{ext}`. The original name is metadata only.
   This defeats path traversal (`../../etc/passwd`), null-byte tricks, and
   collision-based overwrite in one move.
5. **Private bucket, no inline serving.** Downloads go through short-TTL
   presigned URLs minted only after an authorization check.
   `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` so a
   crafted SVG/HTML cannot execute in the app's origin.
6. **Virus scanning integration point** — `AntivirusScanner` interface with a
   no-op default and a ClamAV implementation. Documents stay `PENDING_SCAN` and
   are not retrievable until scanned when scanning is enabled.
7. Archives (`zip`) are **not** accepted in v1 — zip bombs and nested-path
   extraction are a category of risk with no current business need.

---

## 9. AI and RAG Security

Detailed in `docs/AI.md`. The three load-bearing decisions:

1. **The LLM has no SQL access, ever.** It selects from a registry of
   hand-written, parameterized, tenant-scoped tools. Text-to-SQL against a
   financial database is an unbounded-blast-radius design and is rejected
   outright.
2. **Authorization lives in the tool, not the prompt.** Every tool independently
   re-checks tenant and permission using the *authenticated* context. A prompt
   injection can at most make the model *call* a tool; it cannot make the tool
   return data the user is not entitled to. Prompt-level instructions ("do not
   reveal other tenants' data") are not a security control and are not treated
   as one.
3. **Retrieved content is data, not instructions.** Tool results and document
   chunks are wrapped in explicit untrusted-content delimiters, and the system
   prompt states that content inside them is never to be followed as
   instruction. This mitigates but does not eliminate injection — hence control 2
   carries the actual weight.

Additional: bounded date ranges (max 366 days) prevent full-history exfiltration
via one call; a **numeric grounding check** verifies that figures in the model's
answer appear in the tool results, and flags `AI_UNGROUNDED_RESPONSE` otherwise;
every tool invocation is logged with its arguments for forensic review.

---

## 10. Logging and Data Handling

**Never logged:** passwords, access tokens, refresh tokens, API keys, reset or
verification tokens, session cookies, payment secrets, full card data.

Enforcement is structural: a structlog processor redacts by **key name**
(`password`, `token`, `secret`, `authorization`, `refresh`, `api_key`, `card`,
`cvv`, `pin`) at serialization time. A new call site cannot forget it, because
redaction happens after the call site. The same processor filters
`audit_events.metadata`.

Errors returned to clients never include stack traces, SQL, or internal paths —
only a code, a safe message, and `request_id`.

PII (`email`, `phone`, `address`) is logged only where operationally necessary
and never at `INFO` in bulk.

---

## 11. Infrastructure

- Containers run as a **non-root** user; images are slim, multi-stage, with no
  build toolchain in the final layer.
- No secret is baked into an image or a compose file; everything is env-injected.
- Postgres, Redis, Qdrant and MinIO are **not** published to the host in the
  production compose file — only the reverse proxy is.
- The app connects as `nexora_app`, a non-superuser, non-owner role, so RLS
  genuinely applies (`DATABASE.md` §6).
- Redis requires a password and is not internet-reachable.
- TLS terminates at the reverse proxy; HSTS, and secure cookies require HTTPS in
  any non-local environment.
- Security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, and a CSP without
  `unsafe-eval`.
- CORS is an explicit origin allowlist. `allow_origins=["*"]` with
  `allow_credentials=True` is invalid and is a P0 if it appears.
- Dependency scanning (`pip-audit`, `npm audit`) and `gitleaks` run in CI.

---

## 12. Known Gaps (honest register)

Tracked, not hidden. Each has a phase.

| Gap | Risk | Status |
|---|---|---|
| No MFA/TOTP | Account takeover on password compromise | **Closed, Phase 11** — TOTP + recovery codes, `app/modules/auth/mfa*.py` |
| Audit trail not hash-chained | A DB-level attacker could alter history | **Closed, Phase 11** (ADR-0016) — `app/modules/audit/chain.py`, migration 0024 |
| No field-level encryption at rest | DB compromise exposes PII | **Evaluated and applied narrowly, Phase 11** — `app/core/field_encryption.py` (Fernet), applied to the MFA TOTP secret; not a blanket policy — see that module's docstring for why |
| Virus scanning is an interface, not wired | Malware could be stored and re-downloaded | **Closed, Phase 11** — `ClamdScanner` wired into indexing behind `ANTIVIRUS_ENABLED`; off by default, same posture as every optional integration here |
| Rate limiting narrower than documented | Unbounded AI/upload/report cost per tenant | **Closed, Phase 11** — `app/api/ratelimit.py`, membership-keyed, fails open (unlike auth's fail-closed) |
| Single-currency assumption | Multi-currency tenants unsupported | Post-v1 |
| No WAF / bot management | Automated abuse | Deployment-layer — `docs/DEPLOYMENT.md` §8 names it explicitly as an operator choice (e.g. Cloudflare in front of the host), not something the compose file provides |
| Access-token revocation lags ≤15 min | Narrow window after logout/role change | Accepted (ADR-0007) |
| No penetration test | Unknown unknowns | Pre-production — needs an external service, not something a coding pass can close |

**Nexora AI does not claim NBR or Bangladesh regulatory compliance**, nor PCI-DSS
compliance. Card payments are recorded as *references to* externally-processed
transactions; no PAN, CVV or track data is ever stored or transmitted by this
system. Any such claim in code, docs or UI is a defect.

---

## 13. Review Checklist (used every phase)

- [ ] Every new route has an auth dependency and the correct permission
- [ ] Every new tenant-owned model inherits `TenantScoped` and is in the isolation registry
- [ ] Every new resource-addressed endpoint has an object-level authz check
- [ ] No new `skip_tenant_filter` without an ADR
- [ ] No money stored or transported as float
- [ ] Money fields serialize as strings
- [ ] New destructive/financial actions emit audit events
- [ ] New external I/O sits outside business transactions
- [ ] New retry-vulnerable endpoints require `Idempotency-Key`
- [ ] No secrets, tokens or PII in new log statements
- [ ] Cross-tenant tests added for new resources
- [ ] Permission-denial tests added for new endpoints
- [ ] Error responses leak no internals
