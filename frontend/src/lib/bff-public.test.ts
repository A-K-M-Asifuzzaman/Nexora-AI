// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { isSameOrigin, proxyPublic } from "./bff-public";

describe("public BFF mutation guard", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("requires an exact same-origin header", () => {
    expect(isSameOrigin(new Request("https://app.test/api", { method: "POST" }))).toBe(false);
    expect(isSameOrigin(new Request("https://app.test/api", { method: "POST", headers: { Origin: "https://evil.test" } }))).toBe(false);
    expect(isSameOrigin(new Request("https://app.test/api", { method: "POST", headers: { Origin: "https://app.test" } }))).toBe(true);
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
