import { loginUpstream } from "@/lib/bff-upstream";
import { isSameOrigin, originRejected } from "@/lib/bff-public";

export async function POST(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return originRejected();
  return loginUpstream(await request.text());
}
