import Link from "next/link";

import { Brand } from "@/components/brand";
import { AuthForm } from "@/components/auth-form";

export default function LoginPage() {
  return <AuthFrame mode="login" title="Welcome back" subtitle="Sign in to your business workspace." switchText="New to Nexora?" switchHref="/register" switchLabel="Create an account" />;
}

export function AuthFrame({mode,title,subtitle,switchText,switchHref,switchLabel}:{mode:"login"|"register";title:string;subtitle:string;switchText:string;switchHref:"/login"|"/register";switchLabel:string}) {
  return <main className="auth-page"><aside className="auth-side"><Brand/><div className="auth-quote"><h1>Know what matters. Act with confidence.</h1><p>One secure workspace for your operations, your people, and the decisions that move the business forward.</p></div><small>© 2026 Nexora AI</small></aside><section className="auth-panel"><div className="auth-card"><h2>{title}</h2><p>{subtitle}</p><AuthForm mode={mode}/><div className="auth-switch">{switchText} <Link href={switchHref}>{switchLabel}</Link></div></div></section></main>;
}
