"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { error?: { message?: string } };
    return body.error?.message ?? "The request could not be completed.";
  } catch { return "The request could not be completed."; }
}

export function ForgotPasswordForm() {
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const response = await fetch("/api/bff/auth/forgot-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: data.get("email") }),
    });
    setPending(false);
    if (!response.ok) { setError(await responseError(response)); return; }
    setAccepted(true);
  }

  if (accepted) return <div className="auth-result" role="status"><strong>Check your email</strong><p>If an account exists for that address, a reset code has been sent.</p><Link href="/reset-password">Enter reset code</Link></div>;
  return <form onSubmit={submit}><div className="field"><label htmlFor="recovery_email">Work email</label><input id="recovery_email" name="email" type="email" autoComplete="email" required /></div>{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" disabled={pending}>{pending ? "Sending…" : "Send reset code"}</button></form>;
}

export function ResetPasswordForm({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const response = await fetch("/api/bff/auth/reset-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token || data.get("token"), new_password: data.get("new_password") }),
    });
    setPending(false);
    if (!response.ok) { setError(await responseError(response)); return; }
    setDone(true);
  }

  if (done) return <div className="auth-result" role="status"><strong>Password updated</strong><p>All existing sessions have been signed out.</p><Link className="button button-dark" href="/login">Sign in</Link></div>;
  return <form onSubmit={submit}>{!token && <div className="field"><label htmlFor="reset_token">Reset code</label><input id="reset_token" name="token" autoComplete="one-time-code" minLength={16} maxLength={256} required /></div>}<div className="field"><label htmlFor="new_password">New password</label><input id="new_password" name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></div>{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" disabled={pending}>{pending ? "Updating…" : "Reset password"}</button></form>;
}
