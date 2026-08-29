import type { NextConfig } from "next";

/**
 * Security headers required by SECURITY.md §11.
 *
 * The backend sets three of these already (`app/main.py`), but those responses
 * are JSON consumed by the BFF. A browser never renders them, so none of the
 * protections reach the surface they exist to protect: framing, sniffing and
 * referrer leakage are all properties of the *document*, and every document in
 * this app is served by Next.
 *
 * `X-Frame-Options` matters most. The workspace holds state-changing forms —
 * create branch, invite member, switch tenant — behind an ambient session
 * cookie, which is exactly the shape clickjacking targets.
 *
 * `Referrer-Policy` matters more since the invitation accept page: it carries a
 * one-time token in its query string, and the default policy would send that
 * whole URL to any cross-origin resource the page touches. It reduces the
 * exposure but does not remove it — see P2-38 in the handoff.
 */
export const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  typedRoutes: true,
  turbopack: { root: process.cwd() },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
