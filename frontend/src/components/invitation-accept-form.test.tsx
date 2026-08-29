import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InvitationAcceptForm } from "./invitation-accept-form";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

describe("InvitationAcceptForm", () => {
  beforeEach(() => { replace.mockReset(); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("redeems the link token without allowing a role choice", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ created_account: "true" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<InvitationAcceptForm token="invitation-token-value" />);

    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
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
    render(<InvitationAcceptForm token="" />);
    expect(screen.getByLabelText("Invitation code")).toBeRequired();
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeEnabled();
  });
});
