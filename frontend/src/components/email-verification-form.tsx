"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json() as { error?: { message?: string } };
    return body.error?.message ?? fallback;
  } catch { return fallback; }
}

export function EmailVerificationForm({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const response = await fetch("/api/bff/auth/verify-email", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token || data.get("token") }),
    });
    setPending(false);
    if (!response.ok) { setError(await errorMessage(response, "This verification code is invalid or expired.")); return; }
    setDone(true);
  }

  if (done) return <div className="auth-result" role="status"><strong>Email verified</strong><p>You can now sign in to your account.</p><Link className="button button-dark" href="/login">Continue to sign in</Link></div>;
  return <form onSubmit={verify}>{!token && <div className="field"><label htmlFor="token">Verification code</label><input id="token" name="token" autoComplete="one-time-code" minLength={16} maxLength={256} required /></div>}{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" disabled={pending}>{pending ? "Verifying…" : "Verify email"}</button></form>;
}

export function ResendVerificationForm() {
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const response = await fetch("/api/bff/auth/resend-verification", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: data.get("email") }),
    });
    setPending(false);
    if (!response.ok) { setError(await errorMessage(response, "A new code could not be requested.")); return; }
    setAccepted(true);
  }

  return <form onSubmit={resend}><div className="field"><label htmlFor="verification_email">Need a new code?</label><input id="verification_email" name="email" type="email" autoComplete="email" required /></div>{accepted && <p role="status">If the address is eligible, a new code has been sent.</p>}{error && <p role="alert">{error}</p>}<button className="button auth-submit" disabled={pending}>{pending ? "Sending…" : "Resend code"}</button></form>;
}
