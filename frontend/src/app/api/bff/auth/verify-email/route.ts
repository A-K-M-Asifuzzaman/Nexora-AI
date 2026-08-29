import { proxyPublic } from "@/lib/bff-public";

export async function POST(request: Request): Promise<Response> {
  return proxyPublic(request, "auth/verify-email");
}
