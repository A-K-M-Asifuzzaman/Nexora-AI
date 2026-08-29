import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));

describe("WorkspaceShell", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        email: "owner@example.com",
        full_name: "Workspace Owner",
        active_tenant_id: null,
        memberships: [],
      }),
    }));
  });

  it("guides a user without memberships through organization creation", async () => {
    render(<WorkspaceShell />);

    expect(await screen.findByRole("heading", { name: "Create your organization" })).toBeVisible();
    expect(screen.getByLabelText("Organization name")).toBeRequired();
    expect(screen.getByRole("button", { name: "Create workspace" })).toBeEnabled();
  });
});
