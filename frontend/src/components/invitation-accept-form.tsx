"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

type ErrorEnvelope = { error?: { message?: string } };

export function InvitationAcceptForm({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const invitationToken = token || String(data.get("token") ?? "");
    const response = await fetch("/api/bff/invitations/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: invitationToken, full_name: data.get("full_name"), password: data.get("password") }),
    });
    const body = await response.json() as ErrorEnvelope;
    setPending(false);
    if (!response.ok) {
      setError(body.error?.message ?? "This invitation could not be accepted.");
      return;
    }
    router.replace("/login?invitation=accepted");
  }

  return <form onSubmit={submit}>{!token && <div className="field"><label htmlFor="token">Invitation code</label><input id="token" name="token" autoComplete="off" minLength={16} maxLength={256} required /></div>}<div className="field"><label htmlFor="full_name">Full name</label><input id="full_name" name="full_name" autoComplete="name" maxLength={200} required /></div><div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></div><p className="form-hint">Already have an account? Your existing name and password will remain unchanged.</p>{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" type="submit" disabled={pending}>{pending ? "Accepting…" : "Accept invitation"}</button></form>;
}
