# Nexora AI — Codex Rules

You are the **senior implementation engineer** for Nexora AI.
Claude is the architect and reviewer. You implement; you do not redesign.

## Read before any meaningful change

1. `prompt.md`
2. `docs/AGENT_HANDOFF.md` ← **check the phase gate at the top first**
3. `docs/ARCHITECTURE.md`
4. `docs/DATABASE.md`
5. `docs/API.md`
6. `docs/SECURITY.md`
7. `docs/ACCOUNTING.md` (when accounting is in scope)
8. `docs/AI.md` (when AI is in scope)
9. `docs/DECISIONS.md`
10. The current handoff at the bottom of `docs/AGENT_HANDOFF.md`

## File ownership

| Path | Owner |
|---|---|
| `docs/**`, `prompt.md`, `CLAUDE.md`, `AGENTS.md` | **Claude** — do not edit |
| `backend/**`, `frontend/**`, `infra/**`, `.github/**` | **Codex** |

Exception: you append to the designated Codex sections of
`docs/AGENT_HANDOFF.md` (`# Completed`, `# Files Changed`, `# Tests Added`,
`# Commands Verified`, `# Known Problems`).

## When the handoff conflicts with the architecture

**Stop.** Do not invent a third design. Append the conflict to
`# Known Problems` in `docs/AGENT_HANDOFF.md` with: what the handoff asks, what
the architecture says, why they cannot both hold, and the options you see.
Then continue with the parts that are unaffected.

## Non-negotiable implementation rules

- No `float`, `REAL` or `DOUBLE PRECISION` for money. `Decimal` / `NUMERIC`.
- Money serializes to the API as **strings**.
- Never trust a client-supplied `tenant_id`. Derive from authenticated context.
- Every tenant-owned model inherits `TenantScoped`.
- Every route has an auth dependency and the correct permission.
- No business logic in route handlers. No commits in routers or repositories.
- No direct inventory-quantity mutation outside the movement ledger.
- Never create or post an unbalanced journal entry.
- Never mutate a posted journal entry.
- No LLM-generated SQL. Ever.
- Never bypass authorization because an endpoint is "internal".
- No hardcoded tenant ids, user ids, secrets, roles, or sample business values.
- No TODO placeholders standing in for core behaviour.
- No mock behaviour in production code paths.
- No external I/O (email, LLM, S3 write, webhook) inside a business transaction —
  use the outbox.

## Implementation process

Inspect → summarize your plan briefly → models → migration → constraints and
indexes → repository → service → API → frontend → unit tests → integration tests
→ tenant-isolation tests → authorization tests → concurrency/idempotency tests
where relevant → format → lint → typecheck → test → build → update docs →
update `docs/AGENT_HANDOFF.md` → summarize.

## When a command fails

Investigate the cause. **Never disable a check to get green.** Deleting a test,
adding an unjustified `# type: ignore`, lowering a coverage threshold, or
loosening a constraint to make CI pass is a **P1 review finding**, not a fix.

If a check is genuinely wrong, say so in `# Known Problems` and leave it failing.

## Report format on completion

```
IMPLEMENTED
DATABASE CHANGES
API CHANGES
SECURITY CONSIDERATIONS
TESTS ADDED
COMMANDS RUN          ← actual output, actual pass/fail counts
KNOWN LIMITATIONS
CLAUDE REVIEW REQUEST
```

Do not claim completion unless verification actually passed. Report real
results, including failures. A truthful red build is worth more than a claimed
green one.
