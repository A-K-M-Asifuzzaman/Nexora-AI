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
 *   $ curl -si http://127.0.0.1:3987/invite/accept?token=abc
 *   X-Content-Type-Options: nosniff
 *   X-Frame-Options: DENY
 *   Referrer-Policy: strict-origin-when-cross-origin
 *
 * What this guards is the regression — someone editing next.config.ts and
 * dropping a header, or narrowing `source` so it stops covering every route.
 */

import { describe, expect, it } from "vitest";

import nextConfig, { securityHeaders } from "../../next.config";

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

  it("does not yet claim a CSP", () => {
    // §11 also requires a CSP without `unsafe-eval`. It is not implemented:
    // doing it properly needs a per-request nonce through middleware, and a CSP
    // shipped without browser verification is likelier to break the app than to
    // protect it. Tracked as P1-37. This assertion is here so that when a CSP
    // does land, this test fails and forces the finding to be closed rather
    // than silently left open.
    expect(securityHeaders.some((h) => h.key === "Content-Security-Policy")).toBe(false);
  });
});
