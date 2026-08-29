import { Brand } from "@/components/brand";
import { InvitationAcceptForm } from "@/components/invitation-accept-form";

export default async function InvitationAcceptPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const token = (await searchParams).token ?? "";
  return <main className="auth-page"><aside className="auth-side"><Brand /><div className="auth-quote"><h1>Your team is ready for you.</h1><p>Accept your secure invitation to join the organization workspace.</p></div><small>© 2026 Nexora AI</small></aside><section className="auth-panel"><div className="auth-card"><h2>Accept invitation</h2><p>Set your account details to continue.</p><InvitationAcceptForm token={token} /></div></section></main>;
}
