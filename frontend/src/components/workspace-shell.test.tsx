import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("invites a colleague using a server-provided role", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      const body = path.endsWith("auth/me")
        ? { email: "owner@example.com", full_name: "Workspace Owner", active_tenant_id: "tenant-1", memberships: [{ tenant_id: "tenant-1", tenant_name: "Acme", roles: ["OWNER"] }] }
        : path.endsWith("branches/")
          ? { items: [] }
          : path.endsWith("roles/")
            ? [{ id: "role-1", code: "EMPLOYEE", name: "Employee", is_system: true }]
            : path.endsWith("invitations/") && init?.method === "POST"
              ? { id: "invite-1" }
              : [];
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkspaceShell section="administration" />);

    expect(await screen.findByRole("heading", { name: /Organization/, level: 1 })).toBeVisible();
    expect(screen.getAllByRole("link", { name: /Catalog & inventory/ })[0]).toHaveAttribute("href", "/workspace/inventory");
    for (const link of screen.getAllByRole("link", { name: /Organization/ })) {
      expect(link).toHaveAttribute("aria-current", "page");
    }

    fireEvent.change(screen.getByLabelText("Colleague email"), { target: { value: "colleague@example.com" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "role-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/invitations/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ email: "colleague@example.com", role_id: "role-1" }) }),
    ));
  });

  it("opens an accessible mobile navigation drawer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ email: "owner@example.com", full_name: "Workspace Owner", active_tenant_id: "tenant-1", memberships: [{ tenant_id: "tenant-1", tenant_name: "Acme", roles: ["OWNER"] }] }) }));
    render(<WorkspaceShell section="overview" />);

    const trigger = await screen.findByRole("button", { name: "Open workspace navigation" });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("complementary", { name: "Mobile workspace navigation" })).toBeVisible();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "Mobile workspace navigation" })).not.toBeInTheDocument();
  });
});
