// @vitest-environment node
/**
 * SECURITY.md §11 requires four browser security controls. The backend sets
 * three of them, but only on `/api/v1` JSON that no browser renders — framing,
 * sniffing and referrer leakage are properties of the document, and every
 * document here is served by Next.
 *
 * This is a declaration test, which is the weaker kind (cf. P2-23). Enforcement
 * was verified separately against a running production server:
 *
 *   $ curl -si http://127.0.0.1:3987/invite/accept
 *   X-Content-Type-Options: nosniff
 *   X-Frame-Options: DENY
 *   Referrer-Policy: strict-origin-when-cross-origin
 *
 * What this guards is the regression — someone editing next.config.ts and
 * dropping a header, or narrowing `source` so it stops covering every route.
 */

import { describe, expect, it } from "vitest";

import nextConfig, { securityHeaders } from "../../next.config";
import { createContentSecurityPolicy } from "./content-security-policy";

describe("SECURITY.md §11 headers", () => {
  it("declares every required header", () => {
    const declared = Object.fromEntries(securityHeaders.map((h) => [h.key, h.value]));
    expect(declared).toMatchObject({
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "strict-origin-when-cross-origin",
    });
  });

  it("applies them to every route, not just pages", async () => {
    // A `source` of "/" or "/((?!api).*)" would leave the BFF proxy uncovered
    // while still passing a shape check.
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/:path*");
    expect(rules[0].headers).toEqual(securityHeaders);
  });

  it("builds a nonce-based production CSP without unsafe script execution", () => {
    const policy = createContentSecurityPolicy("test-nonce", false);

    expect(policy).toContain("script-src 'self' 'nonce-test-nonce' 'strict-dynamic'");
    expect(policy).toContain("style-src 'self' 'nonce-test-nonce'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).not.toContain("'unsafe-inline'");
    expect(policy).not.toContain("'unsafe-eval'");
  });

  it("permits eval only for the React development toolchain", () => {
    expect(createContentSecurityPolicy("test-nonce", true)).toContain("'unsafe-eval'");
  });
});
