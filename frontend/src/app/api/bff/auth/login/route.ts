import { loginUpstream } from "@/lib/bff-upstream";

export async function POST(request: Request): Promise<Response> {
  return loginUpstream(await request.text());
}
