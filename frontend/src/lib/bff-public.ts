const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

/**
 * Same-origin check for CSRF, compared against `Host` rather than `request.url`.
 *
 * `new URL(request.url).origin` is the address the *server* is bound to, not the
 * one the browser addressed. Both `next dev` and `next start` run with
 * `--hostname 0.0.0.0`, so `request.url` is `http://0.0.0.0:3000/…` while a
 * browser sends `Origin: http://localhost:3000`. Those can never be equal, so
 * the check rejected every legitimate request — login, register, password
 * reset, invitation accept, and via `requireCsrf` every state-changing proxy
 * call. Measured, not theorised:
 *
 *   requestUrl "http://0.0.0.0:3000/api/bff/probe"
 *   originHeader "http://localhost:3000"
 *
 * `Host` is what the browser actually connected to, so comparing the origin's
 * host against it is the check that was intended. Origin stays unforgeable from
 * another site, which is the property CSRF protection rests on.
 *
 * Behind a reverse proxy this depends on `Host` being passed through
 * faithfully — the same trusted-hop assumption tracked as P2-32.
 */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  const host = request.headers.get("Host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function originRejected(): Response {
  return Response.json(
    { error: { code: "CSRF_INVALID", message: "Request origin is not allowed.", details: {} } },
    { status: 403 },
  );
}

/** Proxy one explicitly named public mutation; callers cannot supply a path. */
export async function proxyPublic(request: Request, path: string): Promise<Response> {
  if (!isSameOrigin(request)) return originRejected();
  const response = await fetch(`${backend}/api/v1/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const body = await response.text();
  return new Response(body || null, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
  });
}
