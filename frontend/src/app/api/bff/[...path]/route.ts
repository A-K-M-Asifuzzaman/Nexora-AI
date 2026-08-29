import { requireCsrf } from "@/lib/bff-session";
import { proxyUpstream } from "@/lib/bff-upstream";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, context: Context): Promise<Response> {
  if (request.method !== "GET" && !(await requireCsrf(request))) {
    return Response.json({ error: { code: "CSRF_INVALID", message: "Invalid CSRF token.", details: {} } }, { status: 403 });
  }
  return proxyUpstream(request, (await context.params).path);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
