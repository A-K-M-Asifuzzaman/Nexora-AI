const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

/** Public token-bearing invitation redemption; no ambient session is required. */
export async function POST(request: Request): Promise<Response> {
  const response = await fetch(`${backend}/api/v1/invitations/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  return new Response(await response.text(), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
