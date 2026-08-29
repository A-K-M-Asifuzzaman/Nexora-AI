import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InvitationAcceptForm } from "./invitation-accept-form";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

describe("InvitationAcceptForm", () => {
  beforeEach(() => { replace.mockReset(); window.location.hash = ""; });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("redeems the link token without allowing a role choice", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ created_account: "true" }) });
    vi.stubGlobal("fetch", fetchMock);
    window.location.hash = "token=invitation-token-value";
    render(<InvitationAcceptForm />);

    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("Invitation code")).not.toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Invited Person" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-secure-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/invitations/accept",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ token: "invitation-token-value", full_name: "Invited Person", password: "a-secure-password" }) }),
    ));
    expect(replace).toHaveBeenCalledWith("/login?invitation=accepted");
  });

  it("accepts a pasted code when the link has no token", () => {
    render(<InvitationAcceptForm />);
    expect(screen.getByLabelText("Invitation code")).toBeRequired();
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeEnabled();
  });

  it("removes a fragment credential from browser history after capture", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    window.location.hash = "token=invitation-token-value";

    render(<InvitationAcceptForm />);

    await waitFor(() => expect(replaceState).toHaveBeenCalledWith(null, "", "/"));
    expect(screen.queryByLabelText("Invitation code")).not.toBeInTheDocument();
  });
});
