"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function submit(formData: FormData) {
    setPending(true); setError(null);
    const payload = Object.fromEntries(formData);
    const response = await fetch(`/api/bff/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json() as { error?: { message?: string } };
    setPending(false);
    if (!response.ok) { setError(body.error?.message ?? "Something went wrong."); return; }
    if (mode === "login") router.push("/workspace");
    else router.push("/verify-email");
  }
  return <form action={submit}>{mode === "register" && <div className="field"><label htmlFor="full_name">Full name</label><input id="full_name" name="full_name" autoComplete="name" required /></div>}<div className="field"><label htmlFor="email">Work email</label><input id="email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required /></div><div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="At least 12 characters" minLength={mode === "login" ? 1 : 12} required /></div>{mode === "login" && <Link className="field-link" href="/forgot-password">Forgot password?</Link>}{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" type="submit" disabled={pending}>{pending ? "Please wait…" : mode === "login" ? "Sign in" : "Continue"}</button></form>;
}
