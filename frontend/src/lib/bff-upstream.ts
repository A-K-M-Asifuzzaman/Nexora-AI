import { clearSession, readSession, writeSession } from "./bff-session";

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

async function rotate(refreshToken: string): Promise<string | null> {
  const response = await fetch(`${backend}/api/v1/auth/refresh`, {
    method: "POST", headers: { Cookie: `nexora_rt=${refreshToken}` }, cache: "no-store",
  });
  if (!response.ok) return null;
  const payload = await response.json() as { access_token?: string };
  const refresh = refreshFrom(response);
  if (!payload.access_token || !refresh) return null;
  await writeSession(payload.access_token, refresh);
  return payload.access_token;
}

export async function proxyUpstream(request: Request, path: string[]): Promise<Response> {
  const auth = await readSession();
  if (!auth) return Response.json({ error: { code: "TOKEN_INVALID", message: "Authentication is required.", details: {} } }, { status: 401 });
  const url = new URL(`${backend}/api/v1/${path.join("/")}`);
  url.search = new URL(request.url).search;
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
  const call = (token: string) => fetch(url, {
    method: request.method,
    headers: { "Content-Type": request.headers.get("content-type") ?? "application/json", Authorization: `Bearer ${token}`, "X-Request-ID": request.headers.get("X-Request-ID") ?? crypto.randomUUID() },
    body,
    cache: "no-store",
  });
  let response = await call(auth.session.accessToken);
  if (response.status === 401) {
    const token = await rotate(auth.session.refreshToken);
    if (!token) { await clearSession(); return Response.json({ error: { code: "SESSION_REVOKED", message: "Session expired.", details: {} } }, { status: 401 }); }
    response = await call(token);
  }
  const payload = await response.text();
  if (response.headers.get("content-type")?.includes("application/json")) {
    const json = JSON.parse(payload) as Record<string, unknown>;
    if (typeof json.access_token === "string") {
      const latest = await readSession();
      if (latest) await writeSession(json.access_token, latest.session.refreshToken);
      delete json.access_token;
    }
    return Response.json(json, { status: response.status });
  }
  return new Response(payload || null, { status: response.status, headers: { "Content-Type": response.headers.get("content-type") ?? "text/plain" } });
}
