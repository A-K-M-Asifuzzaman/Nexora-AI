import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { cookies } from "next/headers";
import { Redis as UpstashRedis } from "@upstash/redis";
import { createClient } from "redis";

import { isSameOrigin } from "./bff-public";

const SESSION_COOKIE = "nexora_bff";
const REFRESH_COOKIE = "nexora_rt";
export const CSRF_COOKIE = "nexora_csrf";
const SESSION_SECONDS = 60 * 60 * 24 * 30;
const REFRESH_POLL_MS = 100;

/**
 * `activeTenantId` is the BFF's memory of which organization the user selected.
 *
 * `ARCHITECTURE.md` §4.3 makes the refresh session deliberately tenant-agnostic:
 * the tenant lives in the signed `tid` claim, never "re-derived from a mutable
 * header". So a refresh legitimately returns a token with no tenant, and
 * something has to re-bind it. That something is the BFF, which is the only
 * party holding session state the browser cannot forge.
 */
type Session = { accessToken: string; refreshToken: string; activeTenantId?: string | null };

/**
 * The result of trying to refresh a session.
 *
 * `failed` and `timeout` must stay distinct. `failed` is an answer — the backend
 * rejected the refresh token, so the session is dead and must be cleared.
 * `timeout` is the absence of an answer — a refresh may still be in flight and
 * may still succeed. Collapsing the two (as a bare `null` does) means every slow
 * refresh is read as a dead session and logs the user out (P1-34).
 */
export type RefreshOutcome =
  | { status: "refreshed"; accessToken: string }
  | { status: "failed" }
  | { status: "timeout" };

function positiveInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`);
  return value;
}

/** Upstream refresh is aborted at this bound, so the holder always outlives it. */
export const REFRESH_TIMEOUT_MS = positiveInt("BFF_REFRESH_TIMEOUT_MS", 10_000);
/** How long the single-flight lock survives a holder that dies mid-refresh. */
export const REFRESH_LOCK_TTL_MS = positiveInt("BFF_REFRESH_LOCK_TTL_MS", 15_000);
/** How long a queued request waits for the holder to publish a rotated token. */
export const REFRESH_WAIT_MS = positiveInt("BFF_REFRESH_WAIT_MS", 20_000);

// The single-flight guarantee rests entirely on this ordering, and both halves
// of it were wrong before Review 13.
//
//   refresh < lock TTL  — otherwise the lock lapses under a still-running
//                         refresh and a second request replays the same
//                         rotating token, which reuse detection treats as theft
//                         and answers by revoking the family (P1-35).
//   lock TTL < wait     — otherwise a waiter gives up while the holder is still
//                         legitimately working, and its "no token" is read as a
//                         dead session (P1-34).
//
// Asserted at load rather than documented, so an env override cannot quietly
// reintroduce either defect.
if (!(REFRESH_TIMEOUT_MS < REFRESH_LOCK_TTL_MS && REFRESH_LOCK_TTL_MS < REFRESH_WAIT_MS)) {
  throw new Error(
    `BFF refresh bounds must satisfy timeout < lock TTL < wait; got ${REFRESH_TIMEOUT_MS} / ${REFRESH_LOCK_TTL_MS} / ${REFRESH_WAIT_MS}`,
  );
}

type SetOpts = { ex?: number; nx?: boolean; px?: number };

type Store = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: SetOpts): Promise<string | null>;
  del(key: string): Promise<number>;
  eval(script: string, keys: string[], args: string[]): Promise<unknown>;
};

class UpstashStore implements Store {
  private readonly client: UpstashRedis;
  constructor(url: string, token: string) {
    // The session value is our own encrypted, non-JSON payload — never let
    // the SDK try to JSON-parse it back out.
    this.client = new UpstashRedis({ url, token, automaticDeserialization: false });
  }
  get(key: string) { return this.client.get<string>(key); }
  set(key: string, value: string, opts?: SetOpts) {
    // Upstash's SetCommandOptions is a discriminated union (ex XOR px, nx
    // XOR xx, ...) that can't structurally accept a plain `{ex?, nx?, px?}`
    // bag. Every call site here only ever passes one of {ex} or {nx, px},
    // never a conflicting mix, so this cast is safe in practice.
    return this.client.set(key, value, (opts ?? {}) as Parameters<UpstashRedis["set"]>[2]);
  }
  del(key: string) { return this.client.del(key); }
  eval(script: string, keys: string[], args: string[]) { return this.client.eval(script, keys, args); }
}

// Fallback for when Upstash isn't configured: plain node-redis over TCP.
// Deliberately never cached across calls. A client cached per warm
// serverless instance (the previous approach) has no lifecycle hook that
// ever closes it, and Vercel creates far more instances under concurrent
// load than any pool would reclaim — that leak pegged Render's free-tier
// Redis at its connection cap and made login hang indefinitely (P1, found
// live on the deployed demo). A fresh connect-per-call costs a TLS/TCP
// handshake on every Redis operation, but nothing can outlive the single
// call that opened it, so the leak is structurally impossible here too.
class TcpFallbackStore implements Store {
  constructor(private readonly url: string) {}

  async get(key: string) {
    const client = createClient({ url: this.url, socket: { connectTimeout: 5_000 } });
    try {
      await client.connect();
      return await client.get(key);
    } finally {
      await client.destroy();
    }
  }

  async set(key: string, value: string, opts?: SetOpts) {
    const client = createClient({ url: this.url, socket: { connectTimeout: 5_000 } });
    try {
      await client.connect();
      return await client.set(key, value, {
        ...(opts?.ex !== undefined ? { EX: opts.ex } : {}),
        ...(opts?.nx ? { NX: true } : {}),
        ...(opts?.px !== undefined ? { PX: opts.px } : {}),
      });
    } finally {
      await client.destroy();
    }
  }

  async del(key: string) {
    const client = createClient({ url: this.url, socket: { connectTimeout: 5_000 } });
    try {
      await client.connect();
      return await client.del(key);
    } finally {
      await client.destroy();
    }
  }

  async eval(script: string, keys: string[], args: string[]) {
    const client = createClient({ url: this.url, socket: { connectTimeout: 5_000 } });
    try {
      await client.connect();
      return await client.eval(script, { keys, arguments: args });
    } finally {
      await client.destroy();
    }
  }
}

let redis: Store | undefined;

function secret(): string {
  const value = process.env.BFF_SESSION_SECRET;
  if (!value || value.length < 32) throw new Error("BFF_SESSION_SECRET must contain 32 characters");
  return value;
}

function sign(id: string): string {
  return createHmac("sha256", secret()).update(id).digest("base64url");
}

function encryptionKey(): Buffer {
  return createHash("sha256").update(secret()).digest();
}

function encrypt(session: Session): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(session), "utf8"), cipher.final()]);
  return [iv, cipher.getAuthTag(), ciphertext].map((value) => value.toString("base64url")).join(".");
}

function decrypt(value: string): Session | null {
  try {
    const [iv, tag, ciphertext] = value.split(".").map((part) => Buffer.from(part, "base64url"));
    if (!iv || !tag || !ciphertext) return null;
    const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), iv);
    decipher.setAuthTag(tag);
    return JSON.parse(Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8")) as Session;
  } catch {
    return null;
  }
}

// Upstash is preferred — its client talks REST per call, so there is no
// persistent connection for a horizontally-scaled platform like Vercel to
// leak (see UpstashStore/TcpFallbackStore above for the full story). Falls
// back to the existing TCP Redis when Upstash credentials aren't set up
// yet, so this upgrades automatically the moment they are, with no further
// code change.
function client(): Store {
  if (!redis) {
    const url = process.env.KV_REST_API_URL ?? process.env.UPSTASH_REDIS_REST_URL;
    const token = process.env.KV_REST_API_TOKEN ?? process.env.UPSTASH_REDIS_REST_TOKEN;
    if (url && token) {
      redis = new UpstashStore(url, token);
    } else {
      const tcpUrl = process.env.BFF_REDIS_URL;
      if (!tcpUrl) throw new Error("Neither Upstash REST credentials nor BFF_REDIS_URL are configured");
      redis = new TcpFallbackStore(tcpUrl);
    }
  }
  return redis;
}

function validSignedId(value: string | undefined): string | null {
  if (!value) return null;
  const [id, signature] = value.split(".");
  if (!id || !signature) return null;
  const expected = Buffer.from(sign(id));
  const supplied = Buffer.from(signature);
  return expected.length === supplied.length && timingSafeEqual(expected, supplied) ? id : null;
}

export async function readSession(): Promise<{ id: string; session: Session } | null> {
  const jar = await cookies();
  const id = validSignedId(jar.get(SESSION_COOKIE)?.value);
  if (!id) return null;
  const raw = await client().get(`bff:session:${id}`);
  const session = raw ? decrypt(raw) : null;
  return session ? { id, session } : null;
}

export async function writeSession(
  accessToken: string,
  refreshToken: string,
  activeTenantId?: string | null,
): Promise<void> {
  const jar = await cookies();
  const current = validSignedId(jar.get(SESSION_COOKIE)?.value);
  const id = current ?? randomBytes(32).toString("base64url");
  await client().set(`bff:session:${id}`, encrypt({ accessToken, refreshToken, activeTenantId: activeTenantId ?? null }), {
    ex: SESSION_SECONDS,
  });
  const secure = process.env.NODE_ENV === "production";
  jar.set(SESSION_COOKIE, `${id}.${sign(id)}`, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: SESSION_SECONDS });
  if (!jar.get(CSRF_COOKIE)) jar.set(CSRF_COOKIE, randomBytes(24).toString("base64url"), { httpOnly: false, sameSite: "lax", secure, path: "/" });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  const id = validSignedId(jar.get(SESSION_COOKIE)?.value);
  if (id) await client().del(`bff:session:${id}`);
  jar.delete(SESSION_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(CSRF_COOKIE);
}

/**
 * Try to become the one request that refreshes this session.
 *
 * Refresh tokens rotate with reuse detection (ADR-0006): presenting a consumed
 * token revokes the whole session family. So two parallel requests that both
 * find an expired access token and both refresh will log the user out — one
 * rotates successfully, the other looks exactly like a stolen token being
 * replayed. A dashboard firing three requests after fifteen minutes idle does
 * this reliably.
 *
 * The lock is in Redis rather than in-process because there may be several Next
 * instances behind the load balancer. It expires on its own so a crashed holder
 * cannot wedge the session.
 */
export async function acquireRefreshLock(id: string): Promise<string | null> {
  const owner = randomBytes(32).toString("base64url");
  const result = await client().set(`bff:refresh-lock:${id}`, owner, {
    nx: true,
    px: REFRESH_LOCK_TTL_MS,
  });
  return result === "OK" ? owner : null;
}

export async function releaseRefreshLock(id: string, owner: string): Promise<void> {
  await client().eval(
    "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
    [`bff:refresh-lock:${id}`],
    [owner],
  );
}

export async function closeSessionStore(): Promise<void> {
  // Both Store implementations either hold no persistent connection
  // (Upstash) or close it on every call (TcpFallbackStore) — nothing to
  // disconnect here. This only resets the singleton so tests can rebuild it
  // against a fresh mocked URL/token between runs.
  redis = undefined;
}

/**
 * Wait for whoever holds the lock to publish a new access token.
 *
 * The budget exceeds the lock TTL by construction, so this never gives up while
 * a holder could still be working — the case that used to end in a spurious
 * logout (P1-34).
 */
export async function awaitRotatedToken(id: string, previous: string): Promise<RefreshOutcome> {
  const deadline = Date.now() + REFRESH_WAIT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, REFRESH_POLL_MS));
    const latest = await readSession();
    // A holder that is definitively rejected clears the session, so a session
    // that has gone is that answer arriving — not a reason to keep waiting.
    if (!latest || latest.id !== id) return { status: "failed" };
    if (latest.session.accessToken !== previous) {
      return { status: "refreshed", accessToken: latest.session.accessToken };
    }
  }
  // No answer yet. The request fails; the session does not.
  return { status: "timeout" };
}

export async function requireCsrf(request: Request): Promise<boolean> {
  if (!isSameOrigin(request)) return false;
  const value = (await cookies()).get(CSRF_COOKIE)?.value;
  return Boolean(value && request.headers.get("X-CSRF-Token") === value);
}
