// @vitest-environment node
/**
 * Holder/waiter interaction of the single-flight refresh (findings P1-34, P1-35).
 *
 * `bff-session.test.ts` pins the lock primitive. These pin the thing the lock
 * exists for: what a queued request does while another is refreshing, and which
 * of those outcomes is allowed to end the session.
 *
 * The bounds are shrunk through the same env vars production reads, so the real
 * ordering invariant (refresh < lock TTL < wait) still holds here — the timings
 * are smaller, the relationship between them is not weakened.
 */

import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

process.env.BFF_SESSION_SECRET = "test-secret-of-at-least-32-characters";
process.env.BFF_REFRESH_TIMEOUT_MS = "300";
process.env.BFF_REFRESH_LOCK_TTL_MS = "600";
process.env.BFF_REFRESH_WAIT_MS = "1200";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (jar.has(name) ? { value: jar.get(name) } : undefined),
    set: (name: string, value: string) => { jar.set(name, value); },
    delete: (name: string) => { jar.delete(name); },
  }),
}));

const {
  acquireRefreshLock,
  awaitRotatedToken,
  closeSessionStore,
  readSession,
  releaseRefreshLock,
  writeSession,
  REFRESH_TIMEOUT_MS,
  REFRESH_LOCK_TTL_MS,
  REFRESH_WAIT_MS,
} = await import("./bff-session");
const { proxyUpstream } = await import("./bff-upstream");

const REFRESH_URL = "/api/v1/auth/refresh";
const get = () => new Request("http://bff.test/api/bff/branches", { method: "GET" });

/** A backend that 401s the stale token and accepts anything newer. */
function backend(onRefresh: (init: RequestInit) => Promise<Response>, stale: string) {
  return vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes(REFRESH_URL)) return onRefresh(init ?? {});
    const auth = new Headers(init?.headers).get("Authorization");
    return auth === `Bearer ${stale}`
      ? Response.json({ error: { code: "TOKEN_EXPIRED" } }, { status: 401 })
      : Response.json({ items: [] }, { status: 200 });
  });
}

async function seed(access: string, refresh: string): Promise<string> {
  await writeSession(access, refresh);
  const session = await readSession();
  if (!session) throw new Error("seed failed");
  return session.id;
}

describe("single-flight refresh: holder and waiter", () => {
  beforeEach(() => { jar.clear(); });
  afterEach(() => { vi.unstubAllGlobals(); });
  afterAll(async () => { await closeSessionStore(); });

  it("keeps the bounds ordered refresh < lock TTL < wait", () => {
    // The guarantee is this ordering. Asserted so a future tune of one value
    // cannot silently reintroduce P1-34 or P1-35.
    expect(REFRESH_TIMEOUT_MS).toBeLessThan(REFRESH_LOCK_TTL_MS);
    expect(REFRESH_LOCK_TTL_MS).toBeLessThan(REFRESH_WAIT_MS);
  });

  it("hands a waiter the token published by a holder slower than the lock TTL", async () => {
    const id = await seed("stale", "refresh-1");
    const owner = await acquireRefreshLock(id);
    expect(owner).not.toBeNull();
    vi.stubGlobal("fetch", backend(async () => Response.json({}, { status: 200 }), "stale"));

    // The holder publishes after the lock has already lapsed. The waiter must
    // still be waiting: its budget outlasts the lock by construction.
    const holder = setTimeout(() => { void writeSession("fresh", "refresh-2"); }, REFRESH_LOCK_TTL_MS + 200);

    const response = await proxyUpstream(get(), ["branches"]);
    clearTimeout(holder);
    await releaseRefreshLock(id, owner!);

    expect(response.status).toBe(200);
    expect(await readSession()).not.toBeNull();
  }, 10_000);

  it("leaves the session intact when the wait times out", async () => {
    // Regression for P1-34: this returned 401 and destroyed a live session.
    const id = await seed("stale", "refresh-1");
    const owner = await acquireRefreshLock(id);
    vi.stubGlobal("fetch", backend(async () => Response.json({}, { status: 200 }), "stale"));

    const response = await proxyUpstream(get(), ["branches"]);
    await releaseRefreshLock(id, owner!);

    expect(response.status).toBe(503);
    expect(response.headers.get("Retry-After")).toBe("1");
    expect(await response.json()).toMatchObject({ error: { code: "REFRESH_IN_PROGRESS" } });
    // The point of the finding: a refresh that has not answered yet is not a
    // dead session.
    expect(await readSession()).not.toBeNull();
  }, 10_000);

  it("clears the session when the backend rejects the refresh", async () => {
    await seed("stale", "refresh-1");
    vi.stubGlobal("fetch", backend(
      async () => Response.json({ error: { code: "REFRESH_REUSE_DETECTED" } }, { status: 401 }),
      "stale",
    ));

    const response = await proxyUpstream(get(), ["branches"]);

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ error: { code: "SESSION_REVOKED" } });
    expect(await readSession()).toBeNull();
  }, 10_000);

  it("aborts a refresh that outruns its timeout, before the lock can lapse", async () => {
    // Regression for P1-35: unbounded, this ran past the lock TTL and left a
    // window for a second request to replay the same rotating token.
    await seed("stale", "refresh-1");
    vi.stubGlobal("fetch", backend(
      (init) => new Promise<Response>((_, reject) => {
        init.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      }),
      "stale",
    ));

    const started = Date.now();
    const response = await proxyUpstream(get(), ["branches"]);
    const elapsed = Date.now() - started;

    expect(elapsed).toBeLessThan(REFRESH_LOCK_TTL_MS);
    // An abandoned refresh may or may not have rotated upstream, so the stored
    // token is no longer trustworthy: fail closed rather than retry it.
    expect(response.status).toBe(401);
    expect(await readSession()).toBeNull();
  }, 10_000);

  it("reports a vanished session as failed rather than waiting out the budget", async () => {
    const id = await seed("stale", "refresh-1");
    jar.clear();
    const started = Date.now();
    const outcome = await awaitRotatedToken(id, "stale");
    expect(outcome).toEqual({ status: "failed" });
    expect(Date.now() - started).toBeLessThan(REFRESH_WAIT_MS);
  }, 10_000);
});
