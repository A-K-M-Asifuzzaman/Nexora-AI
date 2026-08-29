import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmailVerificationForm } from "./email-verification-form";
import { ForgotPasswordForm, ResetPasswordForm } from "./password-recovery-form";

describe("authentication recovery forms", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("verifies a token supplied by the link", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "verified" }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<EmailVerificationForm token="verification-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Verify email" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/auth/verify-email",
      expect.objectContaining({ body: JSON.stringify({ token: "verification-token" }) }),
    ));
    expect(await screen.findByText("Email verified")).toBeVisible();
  });

  it("uses an enumeration-resistant recovery confirmation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "person@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset code" }));
    expect(await screen.findByText(/If an account exists/)).toBeVisible();
  });

  it("submits reset codes with the new password field required by the API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    render(<ResetPasswordForm token="reset-token-value" />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-secure-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/auth/reset-password",
      expect.objectContaining({ body: JSON.stringify({ token: "reset-token-value", new_password: "new-secure-password" }) }),
    ));
    expect(await screen.findByText("Password updated")).toBeVisible();
  });
});
