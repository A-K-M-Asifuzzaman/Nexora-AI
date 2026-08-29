import { proxyPublic } from "@/lib/bff-public";

/** Public token-bearing invitation redemption; no ambient session is required. */
export async function POST(request: Request): Promise<Response> {
  return proxyPublic(request, "invitations/accept");
}
