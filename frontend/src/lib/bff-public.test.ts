// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { isSameOrigin, proxyPublic } from "./bff-public";

describe("public BFF mutation guard", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  const req = (url: string, headers: Record<string, string>) =>
    new Request(url, { method: "POST", headers });

  it("requires an exact same-origin header", () => {
    expect(isSameOrigin(req("https://app.test/api", { Host: "app.test" }))).toBe(false);
    expect(isSameOrigin(req("https://app.test/api", { Origin: "https://evil.test", Host: "app.test" }))).toBe(false);
    expect(isSameOrigin(req("https://app.test/api", { Origin: "https://app.test", Host: "app.test" }))).toBe(true);
  });

  it("accepts a browser request when the server is bound to a different address", () => {
    // The regression. Both `next dev` and `next start` run with
    // --hostname 0.0.0.0, so request.url carries the bind address while the
    // browser sends the address it dialled. Comparing Origin to
    // new URL(request.url).origin made these unequal and rejected every real
    // login, register, reset and CSRF-guarded call with 403.
    expect(
      isSameOrigin(req("http://0.0.0.0:3000/api/bff/auth/login", {
        Origin: "http://localhost:3000",
        Host: "localhost:3000",
      })),
    ).toBe(true);
  });

  it("still rejects a cross-origin request that reaches the same server", () => {
    expect(
      isSameOrigin(req("http://0.0.0.0:3000/api/bff/auth/login", {
        Origin: "https://evil.test",
        Host: "localhost:3000",
      })),
    ).toBe(false);
  });

  it("rejects a malformed Origin rather than throwing", () => {
    expect(isSameOrigin(req("http://0.0.0.0:3000/api", { Origin: "not-a-url", Host: "localhost:3000" }))).toBe(false);
  });

  it("does not contact upstream for a cross-origin request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await proxyPublic(
      new Request("https://app.test/api/bff/auth/register", { method: "POST", headers: { Origin: "https://evil.test" }, body: "{}" }),
      "auth/register",
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
