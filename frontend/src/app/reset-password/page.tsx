import { Brand } from "@/components/brand";
import { ResetPasswordForm } from "@/components/password-recovery-form";

export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const token = (await searchParams).token ?? "";
  return <main className="auth-page"><aside className="auth-side"><Brand /><div className="auth-quote"><h1>Choose a fresh password.</h1><p>Resetting your password signs out every existing session.</p></div><small>© 2026 Nexora AI</small></aside><section className="auth-panel"><div className="auth-card"><h2>Reset password</h2><p>Enter your reset code and a new password.</p><ResetPasswordForm token={token} /></div></section></main>;
}
