import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthForm } from "./auth-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("AuthForm demo access", () => {
  it("shows published demo credentials and opens the workspace with one click", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthForm mode="login" demoCredentials={{ email: "demo@example.com", password: "public-demo-password" }} />);

    expect(screen.getByText("demo@example.com")).toBeVisible();
    expect(screen.getByText("public-demo-password")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Open demo workspace/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/auth/login",
      expect.objectContaining({ body: JSON.stringify({ email: "demo@example.com", password: "public-demo-password" }) }),
    ));
    expect(push).toHaveBeenCalledWith("/workspace");
  });
});
