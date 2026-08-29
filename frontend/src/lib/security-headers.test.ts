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
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("frame-ancestors 'none'");
    // The directive that stops XSS must never admit inline script or eval.
    const scriptSrc = policy.split("; ").find((d) => d.startsWith("script-src"))!;
    expect(scriptSrc).not.toContain("'unsafe-inline'");
    expect(scriptSrc).not.toContain("'unsafe-eval'");
    expect(policy).not.toContain("'unsafe-eval'");
  });

  it("allows inline styles, and carries no nonce on style-src", () => {
    // A nonce in a directive makes the browser IGNORE 'unsafe-inline' there, so
    // these are mutually exclusive rather than belt-and-braces. next/font,
    // React's stylesheet insertion and the dev overlay all inject styles we
    // cannot nonce; with a nonce here the app renders unstyled. Regression for
    // the console errors reported after the CSP first shipped.
    const policy = createContentSecurityPolicy("test-nonce", false);
    const styleSrc = policy.split("; ").find((d) => d.startsWith("style-src"))!;

    expect(styleSrc).toBe("style-src 'self' 'unsafe-inline'");
    expect(styleSrc).not.toContain("nonce-");
  });

  it("upgrades insecure requests in production only", () => {
    // Regression: with this on in development the browser rewrote every
    // http://localhost fetch to https:// and failed with
    // ERR_SSL_PROTOCOL_ERROR, blanking the workspace.
    expect(createContentSecurityPolicy("n", false)).toContain("upgrade-insecure-requests");
    expect(createContentSecurityPolicy("n", true)).not.toContain("upgrade-insecure-requests");
  });

  it("opens the HMR websocket in development only", () => {
    expect(createContentSecurityPolicy("n", true)).toContain("connect-src 'self' ws: wss:");
    expect(createContentSecurityPolicy("n", false)).toContain("connect-src 'self';");
  });

  it("permits eval only for the React development toolchain", () => {
    expect(createContentSecurityPolicy("test-nonce", true)).toContain("'unsafe-eval'");
  });
});
