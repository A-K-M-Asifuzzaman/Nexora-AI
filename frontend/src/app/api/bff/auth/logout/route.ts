import { clearSession, requireCsrf } from "@/lib/bff-session";
import { proxyUpstream } from "@/lib/bff-upstream";

export async function POST(request: Request): Promise<Response> {
  if (!(await requireCsrf(request))) {
    return Response.json(
      { error: { code: "CSRF_INVALID", message: "Invalid CSRF token.", details: {} } },
      { status: 403 },
    );
  }
  const response = await proxyUpstream(request, ["auth", "logout"]);
  await clearSession();
  return response;
}
