import { Brand } from "@/components/brand";
import { EmailVerificationForm, ResendVerificationForm } from "@/components/email-verification-form";

export default async function VerifyEmailPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const token = (await searchParams).token ?? "";
  return <main className="auth-page"><aside className="auth-side"><Brand /><div className="auth-quote"><h1>One quick security check.</h1><p>Verify your email before continuing to your business workspace.</p></div><small>© 2026 Nexora AI</small></aside><section className="auth-panel"><div className="auth-card"><h2>Verify your email</h2><p>Enter the single-use code from your email.</p><EmailVerificationForm token={token} /><div className="auth-divider" /><ResendVerificationForm /></div></section></main>;
}
