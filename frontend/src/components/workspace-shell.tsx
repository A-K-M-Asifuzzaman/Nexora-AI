"use client";

import { Building2, LayoutDashboard, LogOut, MapPin, Plus, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { Brand } from "@/components/brand";

type Membership = { tenant_id: string; tenant_name: string; roles: string[] };
type CurrentUser = { email: string; full_name: string; active_tenant_id: string | null; memberships: Membership[] };
type Branch = { id: string; code: string; name: string; is_default: boolean; is_active: boolean };
type ApiError = { error?: { message?: string } };

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
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(body.error?.message ?? "The request could not be completed.");
  return body;
}

export function WorkspaceShell() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const current = await api<CurrentUser>("auth/me");
      setUser(current);
      setBranches(current.active_tenant_id ? (await api<{ items: Branch[] }>("branches/")).items : []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load your workspace.");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

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

  async function logout() {
    await fetch("/api/bff/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } });
    router.replace("/login"); router.refresh();
  }

  if (!user) return <main className="workspace-loading">{error ?? "Loading your workspace…"}</main>;
  if (!user.active_tenant_id) return <main className="onboarding-shell"><Brand /><section className="onboarding-card"><small>SET UP YOUR WORKSPACE</small><h1>Create your organization</h1><p>We’ll also create your first branch and warehouse.</p><form onSubmit={createOrganization}><label>Organization name<input name="name" required maxLength={200} /></label><label>Workspace slug<input name="slug" required pattern="[a-z0-9-]+" placeholder="acme-traders" /></label><div className="form-row"><label>Currency<input name="base_currency" defaultValue="USD" required maxLength={3} /></label><label>Timezone<input name="timezone" defaultValue="UTC" required /></label></div>{error && <p role="alert" className="form-error">{error}</p>}<button disabled={busy}>{busy ? "Creating…" : "Create workspace"}</button></form></section></main>;

  const active = user.memberships.find((item) => item.tenant_id === user.active_tenant_id);
  return <main className="workspace"><aside className="workspace-sidebar"><Brand /><label className="tenant-picker"><span>Organization</span><select value={user.active_tenant_id} disabled={busy} onChange={(event) => void switchTenant(event.target.value)}>{user.memberships.map((membership) => <option key={membership.tenant_id} value={membership.tenant_id}>{membership.tenant_name}</option>)}</select></label><nav><a className="selected"><LayoutDashboard />Overview</a><a href="#branches"><MapPin />Branches</a><a href="#team"><Users />Team</a></nav><button className="logout-button" onClick={() => void logout()}><LogOut />Sign out</button><div className="workspace-user"><span>{user.full_name.slice(0, 2).toUpperCase()}</span><div><b>{user.full_name}</b><small>{active?.roles.join(", ") || user.email}</small></div></div></aside><section className="workspace-content"><header><div><small>YOUR WORKSPACE</small><h1>{active?.tenant_name}</h1></div></header>{error && <p role="alert" className="workspace-error">{error}</p>}<section id="branches" className="management-card"><div className="section-title"><div><small>ORGANIZATION</small><h2>Branches</h2></div><span>{branches.length} total</span></div><div className="branch-list">{branches.map((branch) => <article key={branch.id}><span className="branch-icon"><Building2 /></span><div><strong>{branch.name}</strong><small>{branch.code}{branch.is_default ? " · Default" : ""}</small></div><em className={branch.is_active ? "active" : "inactive"}>{branch.is_active ? "Active" : "Inactive"}</em></article>)}</div><form className="inline-form" onSubmit={createBranch}><input name="code" aria-label="Branch code" placeholder="CODE" pattern="[A-Z0-9-]+" maxLength={32} required /><input name="name" aria-label="Branch name" placeholder="Branch name" maxLength={200} required /><button disabled={busy}><Plus />Add branch</button></form></section></section></main>;
}
