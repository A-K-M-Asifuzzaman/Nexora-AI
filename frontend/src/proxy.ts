import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { createContentSecurityPolicy, requestUsesHttps } from "@/lib/content-security-policy";

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDevelopment = process.env.NODE_ENV === "development";
  const isSecureRequest = requestUsesHttps(request.nextUrl.protocol, request.headers.get("x-forwarded-proto"));
  const policy = createContentSecurityPolicy(nonce, isDevelopment, isSecureRequest);
  const requestHeaders = new Headers(request.headers);

  // Next uses the request CSP to apply this nonce to its framework and inline
  // bootstrap scripts. The response header is the policy enforced by browsers.
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
