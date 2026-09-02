"use client";

import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

type DemoCredentials = { email: string; password: string };

export function AuthForm({ mode, demoCredentials }: { mode: "login" | "register"; demoCredentials?: DemoCredentials }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function authenticate(payload: Record<string, FormDataEntryValue | string>) {
    setPending(true); setError(null);
    const response = await fetch(`/api/bff/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json() as { error?: { message?: string } };
    setPending(false);
    if (!response.ok) { setError(body.error?.message ?? "Something went wrong."); return; }
    if (mode === "login") router.push("/workspace");
    else router.push("/verify-email");
  }

  async function submit(formData: FormData) {
    await authenticate(Object.fromEntries(formData));
  }

  return <>
    {mode === "login" && demoCredentials && <section className="demo-access-card" aria-labelledby="demo-access-title"><span><Sparkles /></span><div><strong id="demo-access-title">Explore the live demo <b lang="bn">ডেমো দেখুন</b></strong><p><code>{demoCredentials.email}</code><code>{demoCredentials.password}</code></p></div><button type="button" disabled={pending} onClick={() => void authenticate(demoCredentials)}>{pending ? "Opening…" : "Open demo workspace"}<small lang="bn">এক ক্লিকে প্রবেশ করুন</small></button></section>}
    <form action={submit}>{mode === "register" && <div className="field"><label htmlFor="full_name">Full name</label><input id="full_name" name="full_name" autoComplete="name" required /></div>}<div className="field"><label htmlFor="email">Work email</label><input id="email" name="email" type="email" autoComplete="email" placeholder="you@company.com" defaultValue={demoCredentials?.email} required /></div><div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="At least 12 characters" minLength={mode === "login" ? 1 : 12} defaultValue={demoCredentials?.password} required /></div>{mode === "login" && <Link className="field-link" href="/forgot-password">Forgot password?</Link>}{error && <p role="alert">{error}</p>}<button className="button button-dark auth-submit" type="submit" disabled={pending}>{pending ? "Please wait…" : mode === "login" ? "Sign in" : "Continue"}</button></form>
  </>;
}
