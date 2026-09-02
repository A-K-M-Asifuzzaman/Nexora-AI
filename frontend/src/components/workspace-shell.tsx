"use client";

import gsap from "gsap";
import { BookOpen, Bot, Boxes, Building2, FileText, LayoutDashboard, LogOut, Mail, Menu, Plus, ReceiptText, Settings2, Trash2, TrendingUp, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { Brand } from "@/components/brand";
import type { WorkspaceSection } from "@/lib/workspace-sections";

type Membership = { tenant_id: string; tenant_name: string; roles: string[] };
type CurrentUser = { email: string; full_name: string; active_tenant_id: string | null; memberships: Membership[] };
type Branch = { id: string; code: string; name: string; is_default: boolean; is_active: boolean };
type Role = { id: string; code: string; name: string; is_system: boolean };
type Invitation = { id: string; email: string; role_id: string; status: string; expires_at: string };
type ApiError = { error?: { message?: string } };

function RouteLoading() {
  return <section className="route-loading" aria-live="polite" aria-label="Loading workspace section"><span className="route-loader-mark"><i /><i /><i /></span><div><strong>Preparing your workspace</strong><small lang="bn">আপনার তথ্য প্রস্তুত হচ্ছে…</small></div><span className="route-loader-line" /></section>;
}

const DashboardOverview = dynamic(() => import("@/components/dashboard-overview").then((module) => module.DashboardOverview), { loading: RouteLoading });
const CatalogInventoryPanel = dynamic(() => import("@/components/catalog-inventory-panel").then((module) => module.CatalogInventoryPanel), { loading: RouteLoading });
const TradingPanel = dynamic(() => import("@/components/trading-panel").then((module) => module.TradingPanel), { loading: RouteLoading });
const DocumentsPanel = dynamic(() => import("@/components/documents-panel").then((module) => module.DocumentsPanel), { loading: RouteLoading });
const InsightsPanel = dynamic(() => import("@/components/insights-panel").then((module) => module.InsightsPanel), { loading: RouteLoading });
const CopilotPanel = dynamic(() => import("@/components/copilot-panel").then((module) => module.CopilotPanel), { loading: RouteLoading });
const UserGuidePanel = dynamic(() => import("@/components/user-guide-panel").then((module) => module.UserGuidePanel), { loading: RouteLoading });

const navigation = [
  { section: "overview", label: "Overview", bnLabel: "সারসংক্ষেপ", eyebrow: "COMMAND CENTER", description: "Live commercial, cash and stock signals.", bnDescription: "বিক্রয়, নগদ অর্থ ও মজুতের বর্তমান অবস্থা এক নজরে দেখুন।", icon: LayoutDashboard },
  { section: "inventory", label: "Catalog & inventory", bnLabel: "পণ্য ও মজুত", eyebrow: "OPERATIONS", description: "Products, stock balances, movements and point of sale.", bnDescription: "পণ্য, বর্তমান মজুত, স্টক চলাচল ও কাউন্টার বিক্রয় পরিচালনা করুন।", icon: Boxes },
  { section: "sales", label: "Sales & finance", bnLabel: "বিক্রয় ও অর্থ", eyebrow: "TRADE", description: "Receivables, customers, suppliers, orders and invoices.", bnDescription: "পাওনা, ক্রেতা, সরবরাহকারী, অর্ডার ও চালান দেখুন।", icon: ReceiptText },
  { section: "documents", label: "Documents", bnLabel: "নথিপত্র", eyebrow: "KNOWLEDGE", description: "Secure uploads, indexing status and access controls.", bnDescription: "নিরাপদ নথি আপলোড, প্রক্রিয়াকরণ ও প্রবেশাধিকার নিয়ন্ত্রণ করুন।", icon: FileText },
  { section: "insights", label: "Forecast & alerts", bnLabel: "পূর্বাভাস ও সতর্কতা", eyebrow: "INTELLIGENCE", description: "Explainable forecasts and operational anomaly triage.", bnDescription: "ব্যাখ্যাসহ পূর্বাভাস দেখুন এবং অস্বাভাবিক ঘটনা যাচাই করুন।", icon: TrendingUp },
  { section: "copilot", label: "AI copilot", bnLabel: "এআই সহকারী", eyebrow: "ASSISTANT", description: "Ask permission-aware questions about your business.", bnDescription: "আপনার অনুমোদিত ব্যবসায়িক তথ্য সম্পর্কে সহজ ভাষায় প্রশ্ন করুন।", icon: Bot },
  { section: "administration", label: "Organization", bnLabel: "প্রতিষ্ঠান", eyebrow: "ADMINISTRATION", description: "Branches, roles and team invitations.", bnDescription: "শাখা, ব্যবহারকারীর দায়িত্ব ও দলের আমন্ত্রণ পরিচালনা করুন।", icon: Settings2 },
  { section: "guide", label: "User guide", bnLabel: "ব্যবহার নির্দেশিকা", eyebrow: "GETTING STARTED", description: "Understand each end-to-end business journey.", bnDescription: "প্রতিটি ব্যবসায়িক কাজ শুরু থেকে শেষ পর্যন্ত বুঝে নিন।", icon: BookOpen },
] satisfies Array<{ section: WorkspaceSection; label: string; bnLabel: string; eyebrow: string; description: string; bnDescription: string; icon: typeof LayoutDashboard }>;

function csrfToken(): string {
  const value = document.cookie.split("; ").find((part) => part.startsWith("nexora_csrf="));
  return value ? decodeURIComponent(value.split("=").slice(1).join("=")) : "";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/bff/${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(!["GET", "HEAD"].includes(init?.method ?? "GET") ? { "X-CSRF-Token": csrfToken() } : {}),
      ...init?.headers,
    },
  });
  const body = (response.status === 204 ? {} : await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(body.error?.message ?? "The request could not be completed.");
  return body;
}

export function WorkspaceShell({ section = "overview" }: { section?: WorkspaceSection }) {
  const router = useRouter();
  const shellRef = useRef<HTMLElement>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [teamVisible, setTeamVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const current = await api<CurrentUser>("auth/me");
      setUser(current);
      if (!current.active_tenant_id) {
        setBranches([]); setRoles([]); setInvitations([]); setTeamVisible(false);
        return;
      }
      if (section !== "administration") {
        setBranches([]); setRoles([]); setInvitations([]); setTeamVisible(false);
        return;
      }
      setBranches((await api<{ items: Branch[] }>("branches/")).items.filter((branch) => branch.is_active));
      const team = await Promise.allSettled([api<Role[]>("roles/"), api<Invitation[]>("invitations/")]);
      setTeamVisible(team.every((result) => result.status === "fulfilled"));
      setRoles(team[0].status === "fulfilled" ? team[0].value : []);
      setInvitations(team[1].status === "fulfilled" ? team[1].value : []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load your workspace.");
    }
  }, [section]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [mobileMenuOpen]);

  useLayoutEffect(() => {
    if (!shellRef.current || (typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
    const context = gsap.context(() => {
      gsap.fromTo(".workspace-page-heading > div", { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.45, ease: "power2.out" });
      gsap.fromTo(".workspace-route", { autoAlpha: 0, y: 18, scale: 0.995 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.55, ease: "power3.out", delay: 0.06 });
      gsap.fromTo(".workspace-sidebar nav a", { autoAlpha: 0, x: -8 }, { autoAlpha: 1, x: 0, duration: 0.3, stagger: 0.035, ease: "power2.out" });
    }, shellRef);
    return () => context.revert();
  }, [section]);

  useLayoutEffect(() => {
    if (!mobileMenuOpen || (typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
    const context = gsap.context(() => {
      gsap.fromTo(".mobile-menu-backdrop", { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.2 });
      gsap.fromTo(".workspace-mobile-drawer", { xPercent: -100 }, { xPercent: 0, duration: 0.36, ease: "power3.out" });
      gsap.fromTo(".workspace-mobile-drawer nav a", { autoAlpha: 0, x: -12 }, { autoAlpha: 1, x: 0, duration: 0.28, stagger: 0.035, delay: 0.12 });
    }, shellRef);
    return () => context.revert();
  }, [mobileMenuOpen]);

  async function switchTenant(tenantId: string) {
    setBusy(true); setError(null);
    try {
      await api("auth/switch-tenant", { method: "POST", body: JSON.stringify({ tenant_id: tenantId }) });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Organization switch failed.");
    } finally { setBusy(false); }
  }

  async function createOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    const data = new FormData(event.currentTarget);
    try {
      const created = await api<{ tenant: { id: string } }>("tenants/", { method: "POST", body: JSON.stringify({ name: data.get("name"), slug: data.get("slug"), base_currency: data.get("base_currency"), timezone: data.get("timezone"), default_branch_code: "MAIN", default_branch_name: "Head Office", default_warehouse_code: "WH1", default_warehouse_name: "Main Store" }) });
      await switchTenant(created.tenant.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Organization creation failed.");
    } finally { setBusy(false); }
  }

  async function createBranch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    const form = event.currentTarget; const data = new FormData(form);
    try {
      await api("branches/", { method: "POST", body: JSON.stringify({ code: data.get("code"), name: data.get("name") }) });
      form.reset(); await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Branch creation failed.");
    } finally { setBusy(false); }
  }

  async function inviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    const form = event.currentTarget; const data = new FormData(form);
    try {
      await api("invitations/", { method: "POST", body: JSON.stringify({ email: data.get("email"), role_id: data.get("role_id") }) });
      form.reset(); await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invitation could not be sent.");
    } finally { setBusy(false); }
  }

  async function deleteBranch(branch: Branch) {
    if (!window.confirm(`Delete branch ${branch.name}?`)) return;
    setBusy(true); setError(null);
    try {
      await api(`branches/${branch.id}`, { method: "DELETE" });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Branch deletion failed."); } finally { setBusy(false); }
  }

  async function revokeInvitation(invitation: Invitation) {
    if (!window.confirm(`Revoke the invitation for ${invitation.email}?`)) return;
    setBusy(true); setError(null);
    try {
      await api(`invitations/${invitation.id}`, { method: "DELETE" });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Invitation revocation failed."); } finally { setBusy(false); }
  }

  async function logout() {
    await fetch("/api/bff/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } });
    router.replace("/login"); router.refresh();
  }

  if (!user) return <main className="workspace-loading">{error ?? "Loading your workspace…"}</main>;
  if (!user.active_tenant_id && user.memberships.length > 0) return <main className="onboarding-shell"><Brand /><section className="onboarding-card"><small>SELECT YOUR WORKSPACE</small><h1>Welcome back</h1><p>Your organizations already exist. Choose one to continue.</p><div className="workspace-choice-list">{user.memberships.map((membership) => <button key={membership.tenant_id} disabled={busy} onClick={() => void switchTenant(membership.tenant_id)}><strong>{membership.tenant_name}</strong><small>{membership.roles.join(", ")}</small></button>)}</div>{error && <p role="alert" className="form-error">{error}</p>}</section></main>;
  if (!user.active_tenant_id) return <main className="onboarding-shell"><Brand /><section className="onboarding-card"><small>SET UP YOUR WORKSPACE</small><h1>Create your organization</h1><p>We’ll also create your first branch and warehouse.</p><form onSubmit={createOrganization}><label>Organization name<input name="name" required maxLength={200} /></label><label>Workspace slug<input name="slug" required pattern="[a-z0-9\-]+" placeholder="acme-traders" /></label><div className="form-row"><label>Currency<input name="base_currency" defaultValue="BDT" required maxLength={3} /></label><label>Timezone<input name="timezone" defaultValue="Asia/Dhaka" required /></label></div>{error && <p role="alert" className="form-error">{error}</p>}<button disabled={busy}>{busy ? "Creating…" : "Create workspace"}</button></form></section></main>;

  const active = user.memberships.find((item) => item.tenant_id === user.active_tenant_id);
  const current = navigation.find((item) => item.section === section) ?? navigation[0];
  const routeContent = section === "overview" ? <DashboardOverview />
    : section === "inventory" ? <CatalogInventoryPanel />
      : section === "sales" ? <TradingPanel />
        : section === "documents" ? <DocumentsPanel />
          : section === "insights" ? <InsightsPanel />
            : section === "copilot" ? <CopilotPanel />
              : section === "guide" ? <UserGuidePanel />
                : <>
                  <section className="management-card">
                    <div className="section-title"><div><small>ORGANIZATION</small><h2>Branches</h2></div><span>{branches.length} total</span></div>
                    <div className="branch-list">
                      {branches.map((branch) => <article key={branch.id}><span className="branch-icon"><Building2 /></span><div><strong>{branch.name}</strong><small>{branch.code}{branch.is_default ? " · Default" : ""}</small></div><em className={branch.is_active ? "active" : "inactive"}>{branch.is_active ? "Active" : "Inactive"}</em>{!branch.is_default && <button type="button" className="icon-action danger" disabled={busy} aria-label={`Delete branch ${branch.name}`} onClick={() => void deleteBranch(branch)}><Trash2 /></button>}</article>)}
                    </div>
                    <form className="inline-form" onSubmit={createBranch}><input name="code" aria-label="Branch code" placeholder="CODE" pattern="[A-Z0-9\-]+" maxLength={32} required /><input name="name" aria-label="Branch name" placeholder="Branch name" maxLength={200} required /><button disabled={busy}><Plus />Add branch</button></form>
                  </section>
                  {teamVisible && <section className="management-card">
                    <div className="section-title"><div><small>ACCESS</small><h2>Team invitations</h2></div><span>{invitations.length} total</span></div>
                    <div className="branch-list">{invitations.length === 0 && <p className="empty-state">No invitations are pending.</p>}{invitations.map((invitation) => <article key={invitation.id}><span className="branch-icon"><Mail /></span><div><strong>{invitation.email}</strong><small>{roles.find((role) => role.id === invitation.role_id)?.name ?? "Assigned role"} · Expires {new Date(invitation.expires_at).toLocaleDateString()}</small></div><em className={invitation.status === "PENDING" ? "active" : "inactive"}>{invitation.status.toLowerCase()}</em>{invitation.status === "PENDING" && <button type="button" className="icon-action danger" disabled={busy} aria-label={`Revoke invitation for ${invitation.email}`} onClick={() => void revokeInvitation(invitation)}><Trash2 /></button>}</article>)}</div>
                    <form className="inline-form team-form" onSubmit={inviteMember}><input name="email" type="email" aria-label="Colleague email" placeholder="colleague@example.com" maxLength={320} required /><select name="role_id" aria-label="Role" required defaultValue=""><option value="" disabled>Select role</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select><button disabled={busy || roles.length === 0}><Plus />Send invite</button></form>
                  </section>}
                </>;

  return <main className="workspace" ref={shellRef}>
    <aside className="workspace-sidebar">
      <Brand />
      <label className="tenant-picker"><span>Organization</span><select value={user.active_tenant_id} disabled={busy} onChange={(event) => void switchTenant(event.target.value)}>{user.memberships.map((membership) => <option key={membership.tenant_id} value={membership.tenant_id}>{membership.tenant_name}</option>)}</select></label>
      <nav aria-label="Workspace sections">{navigation.map((item) => <Link key={item.section} className={item.section === section ? "selected" : undefined} aria-current={item.section === section ? "page" : undefined} href={`/workspace/${item.section}`}><item.icon /><span><b>{item.label}</b><small lang="bn">{item.bnLabel}</small></span></Link>)}</nav>
      <button className="logout-button" onClick={() => void logout()}><LogOut />Sign out</button>
      <div className="workspace-user"><span>{user.full_name.slice(0, 2).toUpperCase()}</span><div><b>{user.full_name}</b><small>{active?.roles.join(", ") || user.email}</small></div></div>
    </aside>
    <section className="workspace-content">
      <header className="workspace-page-heading">
        <button type="button" className="mobile-menu-trigger" aria-expanded={mobileMenuOpen} aria-controls="mobile-workspace-menu" aria-label="Open workspace navigation" onClick={() => setMobileMenuOpen(true)}><Menu /></button>
        <div><small>{active?.tenant_name} · {current.eyebrow}</small><h1>{current.label} <span lang="bn">{current.bnLabel}</span></h1><p>{current.description}<span lang="bn">{current.bnDescription}</span></p></div>
      </header>
      {mobileMenuOpen && <>
        <button type="button" className="mobile-menu-backdrop" aria-label="Close workspace navigation" onClick={() => setMobileMenuOpen(false)} />
        <aside className="workspace-mobile-drawer" id="mobile-workspace-menu" aria-label="Mobile workspace navigation">
          <div className="mobile-drawer-header"><Brand /><button type="button" aria-label="Close workspace navigation" onClick={() => setMobileMenuOpen(false)}><X /></button></div>
          <label className="tenant-picker"><span>Organization</span><select value={user.active_tenant_id} disabled={busy} onChange={(event) => void switchTenant(event.target.value)}>{user.memberships.map((membership) => <option key={membership.tenant_id} value={membership.tenant_id}>{membership.tenant_name}</option>)}</select></label>
          <nav aria-label="Workspace sections">{navigation.map((item) => <Link key={item.section} className={item.section === section ? "selected" : undefined} aria-current={item.section === section ? "page" : undefined} href={`/workspace/${item.section}`} onClick={() => setMobileMenuOpen(false)}><item.icon /><span><b>{item.label}</b><small lang="bn">{item.bnLabel}</small></span></Link>)}</nav>
          <button className="logout-button" onClick={() => void logout()}><LogOut />Sign out</button>
          <div className="workspace-user"><span>{user.full_name.slice(0, 2).toUpperCase()}</span><div><b>{user.full_name}</b><small>{active?.roles.join(", ") || user.email}</small></div></div>
        </aside>
      </>}
      {error && <p role="alert" className="workspace-error">{error}</p>}
      <div className="workspace-route" key={section}>{routeContent}</div>
    </section>
  </main>;
}
