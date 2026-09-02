/**
 * Content Security Policy (SECURITY.md §11).
 *
 * `script-src` is the directive that stops XSS, and it stays strict: a
 * per-request nonce plus `strict-dynamic`, with no `unsafe-inline` and no
 * `unsafe-eval` outside development. That is the half worth defending.
 *
 * `style-src` deliberately uses `'unsafe-inline'` and carries **no nonce**.
 * Two reasons, and the first is not a preference:
 *
 * 1. A nonce and `'unsafe-inline'` cannot coexist. Per CSP Level 2+, when a
 *    nonce is present in a directive the browser **ignores** `'unsafe-inline'`
 *    entirely. So "nonce plus a fallback" is not an option; it is nonce-only.
 *
 * 2. Several inline styles are injected at runtime by code we do not control
 *    and cannot nonce: `next/font` (`font-styles.tsx`), React's own stylesheet
 *    insertion in `react-dom-client`, and in development the devtools overlay
 *    via webpack's style-loader. With a nonce on `style-src` the browser blocks
 *    all of them and the application renders unstyled.
 *
 * The cost, stated plainly: inline CSS injection is not blocked. That permits
 * CSS-based data exfiltration (attribute selectors plus background-url) and
 * visual spoofing — but not script execution, which `script-src` still stops.
 * SECURITY.md §11 requires a CSP "without `unsafe-eval`", which this satisfies;
 * it does not require `style-src` to be nonce-based.
 *
 * This was found in a browser console, not by inspecting server HTML: the
 * blocked styles are injected after hydration, so checking the rendered
 * document showed nothing wrong.
 */
export function requestUsesHttps(protocol: string, forwardedProtocol: string | null): boolean {
  const externalProtocol = forwardedProtocol?.split(",", 1)[0]?.trim().toLowerCase();
  return externalProtocol ? externalProtocol === "https" : protocol.toLowerCase() === "https:";
}

export function createContentSecurityPolicy(
  nonce: string,
  isDevelopment: boolean,
  isSecureRequest: boolean,
): string {
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    // Development needs the HMR websocket; production must not widen this.
    `connect-src 'self'${isDevelopment ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    // Secure production requests only. A standalone production-mode Docker
    // image can still be served over plain HTTP for local evaluation. Applying
    // this directive there rewrites same-origin BFF calls to https:// and makes
    // them fail with ERR_SSL_PROTOCOL_ERROR. Behind the production reverse
    // proxy the external request is HTTPS, so the directive remains enabled.
    ...(!isDevelopment && isSecureRequest ? ["upgrade-insecure-requests"] : []),
  ];

  return `${directives.join("; ")};`;
}
