const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  return origin !== null && origin === new URL(request.url).origin;
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
