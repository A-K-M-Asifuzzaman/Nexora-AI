import { Brand } from "@/components/brand";
import { ForgotPasswordForm } from "@/components/password-recovery-form";

export default function ForgotPasswordPage() {
  return <main className="auth-page"><aside className="auth-side"><Brand /><div className="auth-quote"><h1>Recover access securely.</h1><p>We use a short-lived, single-use code to reset your password.</p></div><small>© 2026 Nexora AI</small></aside><section className="auth-panel"><div className="auth-card"><h2>Forgot password?</h2><p>Enter your account email to request a reset code.</p><ForgotPasswordForm /></div></section></main>;
}
