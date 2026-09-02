import {
  acquireRefreshLock,
  awaitRotatedToken,
  clearSession,
  readSession,
  releaseRefreshLock,
  REFRESH_TIMEOUT_MS,
  type RefreshOutcome,
  writeSession,
} from "./bff-session";

const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

function refreshFrom(response: Response): string | null {
  const header = response.headers.get("set-cookie");
  return header?.match(/nexora_rt=([^;]+)/)?.[1] ?? null;
}

export async function loginUpstream(body: string): Promise<Response> {
  const response = await fetch(`${backend}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body, cache: "no-store",
  });
  const payload = await response.json() as Record<string, unknown>;
  const token = typeof payload.access_token === "string" ? payload.access_token : null;
  const refresh = refreshFrom(response);
  if (response.ok && token && refresh) {
    await writeSession(token, refresh);
    delete payload.access_token;
  }
  return Response.json(payload, { status: response.status });
}

/**
 * Refresh under a single-flight lock.
 *
 * Only the lock holder calls upstream; everyone else waits and picks up the
 * token it published. Without this, parallel requests replay the same refresh
 * token, reuse detection fires, and the session family is revoked — the user is
 * silently logged out by their own dashboard (ADR-0006).
 */
async function rotate(sessionId: string, staleToken: string): Promise<RefreshOutcome> {
  const lockOwner = await acquireRefreshLock(sessionId);
  if (!lockOwner) {
    return awaitRotatedToken(sessionId, staleToken);
  }
  try {
    // The previous holder may have completed between this request's initial
    // session read and its lock acquisition. Re-check under the lock so a
    // queued request never replays the refresh token it read earlier.
    const latest = await readSession();
    if (!latest || latest.id !== sessionId) return { status: "failed" };
    if (latest.session.accessToken !== staleToken) {
      return { status: "refreshed", accessToken: latest.session.accessToken };
    }

    let response: Response;
    try {
      response = await fetch(`${backend}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { Cookie: `nexora_rt=${latest.session.refreshToken}` },
        cache: "no-store",
        // Keeps the critical section inside the lock's lifetime. Unbounded, a
        // stalled refresh outlives the lock, and the next request re-reads a
        // session the holder has not published to yet and replays the same
        // rotating token (P1-35).
        signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
      });
    } catch {
      // Aborted, or the backend was unreachable. It may or may not have rotated
      // the token before we gave up, so what we hold can no longer be trusted:
      // presenting it again is indistinguishable from replay. Fail closed.
      return { status: "failed" };
    }

    if (!response.ok) return { status: "failed" };
    const payload = await response.json() as { access_token?: string };
    const refresh = refreshFrom(response);
    if (!payload.access_token || !refresh) return { status: "failed" };

    // The refreshed token is tenant-agnostic by design (ARCHITECTURE.md §4.3),
    // so on its own it makes every tenant-scoped call return
    // 403 NO_ACTIVE_TENANT. Re-bind to the organization this session had
    // selected. Without this the user silently loses their organization every
    // time the 15-minute access token expires.
    let access = payload.access_token;
    const tenantId = latest.session.activeTenantId;
    if (tenantId) {
      const rebound = await fetch(`${backend}/api/v1/auth/switch-tenant`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${access}` },
        body: JSON.stringify({ tenant_id: tenantId }),
        cache: "no-store",
        signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
      });
      if (rebound.ok) {
        const body = await rebound.json() as { access_token?: string };
        if (body.access_token) access = body.access_token;
      }
      // A failure here is not fatal: membership may have been revoked while the
      // token was expiring, which is exactly when the user *should* drop back to
      // choosing an organization rather than being logged out entirely.
    }

    await writeSession(access, refresh, tenantId ?? null);
    return { status: "refreshed", accessToken: access };
  } finally {
    await releaseRefreshLock(sessionId, lockOwner);
  }
}

export async function proxyUpstream(request: Request, path: string[]): Promise<Response> {
  const auth = await readSession();
  if (!auth) return Response.json({ error: { code: "TOKEN_INVALID", message: "Authentication is required.", details: {} } }, { status: 401 });
  const url = new URL(`${backend}/api/v1/${path.join("/")}`);
  url.search = new URL(request.url).search;
  // `.text()` would UTF-8-decode-and-re-encode the body, which is fine for
  // JSON but corrupts anything binary — a multipart file upload's bytes are
  // not valid UTF-8 in general. `arrayBuffer()` forwards them unmodified.
  const contentType = request.headers.get("content-type") ?? "";
  const body = ["GET", "HEAD"].includes(request.method)
    ? undefined
    : contentType.includes("multipart/form-data")
      ? await request.arrayBuffer()
      : await request.text();
  // Idempotency-Key is forwarded, not just Content-Type/Authorization/
  // X-Request-ID: several backend writes require it (checkout, invoice/bill
  // issue, payments) and reject a request without one — dropping it here
  // silently broke every one of those end-to-end through this proxy.
  const idempotencyKey = request.headers.get("Idempotency-Key");
  const call = (token: string) => fetch(url, {
    method: request.method,
    headers: {
      "Content-Type": request.headers.get("content-type") ?? "application/json",
      Authorization: `Bearer ${token}`,
      "X-Request-ID": request.headers.get("X-Request-ID") ?? crypto.randomUUID(),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    body,
    cache: "no-store",
  });
  let response = await call(auth.session.accessToken);
  if (response.status === 401) {
    const outcome = await rotate(auth.id, auth.session.accessToken);
    // A refresh is still in flight and may yet succeed. Clearing here would end
    // a live session over a slow backend, which is the logout P1-34 described.
    // The request fails and is retryable; the session stands.
    if (outcome.status === "timeout") {
      return Response.json(
        { error: { code: "REFRESH_IN_PROGRESS", message: "Session refresh is still in progress. Retry.", details: {} } },
        { status: 503, headers: { "Retry-After": "1" } },
      );
    }
    if (outcome.status === "failed") {
      await clearSession();
      return Response.json({ error: { code: "SESSION_REVOKED", message: "Session expired.", details: {} } }, { status: 401 });
    }
    response = await call(outcome.accessToken);
  }
  const payload = await response.text();
  // `payload` is the string "null" for an endpoint whose response_model is
  // Optional and has nothing to return (e.g. "does this terminal have an
  // open session?") — truthy as a string, but `JSON.parse` yields the value
  // `null`, not an object, and `json.access_token` below would throw.
  if (payload && payload !== "null" && response.headers.get("content-type")?.includes("application/json")) {
    const json = JSON.parse(payload) as Record<string, unknown>;
    if (typeof json.access_token === "string") {
      const latest = await readSession();
      if (latest) {
        // `switch-tenant` returns the newly selected organization; remembering
        // it here is what lets a later refresh re-bind to the same one.
        const selected =
          typeof json.active_tenant_id === "string"
            ? json.active_tenant_id
            : latest.session.activeTenantId ?? null;
        await writeSession(json.access_token, latest.session.refreshToken, selected);
      }
      delete json.access_token;
    }
    return Response.json(json, { status: response.status });
  }
  return new Response(payload || null, { status: response.status, headers: { "Content-Type": response.headers.get("content-type") ?? "text/plain" } });
}
