"use client";

import { AlertTriangle, CheckCircle2, Clock, FileText, Lock, RefreshCw, ShieldCheck, Trash2, Upload } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { PaginatedList } from "@/components/paginated-list";

type DocumentStatus = "PENDING" | "EXTRACTING" | "INDEXED" | "FAILED";
type DocumentVisibility = "TENANT" | "ROLE_RESTRICTED";
type DocumentItem = {
  id: string;
  filename: string;
  title: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  visibility: DocumentVisibility;
  failure_reason: string | null;
  chunk_count: number;
  indexed_at: string | null;
  created_at: string;
};
type Role = { id: string; code: string; name: string };
type ApiError = { error?: { message?: string } };

const SUPPORTED_TYPES = "application/pdf,text/plain,text/markdown,text/csv,.pdf,.txt,.md,.csv";

function csrfToken(): string {
  const value = document.cookie.split("; ").find((part) => part.startsWith("nexora_csrf="));
  return value ? decodeURIComponent(value.split("=").slice(1).join("=")) : "";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/bff/${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(!["GET", "HEAD"].includes(init?.method ?? "GET") ? { "X-CSRF-Token": csrfToken() } : {}),
      ...init?.headers,
    },
  });
  if (response.status === 204) return undefined as T;
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(body.error?.message ?? "The request could not be completed.");
  return body;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function StatusPill({ status, failureReason }: { status: DocumentStatus; failureReason: string | null }) {
  if (status === "INDEXED") {
    return (
      <em className="active">
        <CheckCircle2 />
        Indexed
      </em>
    );
  }
  if (status === "FAILED") {
    return (
      <em className="inactive" title={failureReason ?? undefined}>
        <AlertTriangle />
        Failed
      </em>
    );
  }
  return (
    <em className="pending">
      <Clock />
      {status === "EXTRACTING" ? "Processing" : "Pending"}
    </em>
  );
}

export function DocumentsPanel() {
  const [visible, setVisible] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [restricted, setRestricted] = useState(false);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const items = await api<DocumentItem[]>("documents");
      setDocuments(items);
      setVisible(true);
      const roleList = await api<Role[]>("roles/").catch(() => []);
      setRoles(roleList);
    } catch {
      // No documents.read permission, or the deployment has AI disabled.
      setVisible(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // A document that just finished uploading is PENDING/EXTRACTING; poll
  // gently until nothing is still in flight, so status/chunk counts update
  // without the user having to refresh the page themselves.
  useEffect(() => {
    const inFlight = documents.some((d) => d.status === "PENDING" || d.status === "EXTRACTING");
    if (!inFlight) return;
    poll.current = window.setTimeout(() => void load(), 4000);
    return () => {
      if (poll.current) window.clearTimeout(poll.current);
    };
  }, [documents, load]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!data.get("file") || !(data.get("file") as File).size) {
      setError("Choose a file to upload.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await api("documents", { method: "POST", body: data });
      form.reset();
      setRestricted(false);
      setSelectedRoles([]);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function reindex(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`documents/${id}/reindex`, { method: "POST" });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Reindex failed.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`documents/${id}`, { method: "DELETE" });
      setDocuments((prev) => prev.filter((d) => d.id !== id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Delete failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!visible) return null;

  return (
    <section id="documents" className="management-card">
      <div className="section-title">
        <div>
          <small>KNOWLEDGE BASE</small>
          <h2>Documents</h2>
        </div>
        <span>{documents.length} total</span>
      </div>

      <p className="copilot-note">
        <ShieldCheck />
        Uploaded files are indexed for search and for the business copilot. A document is visible
        to your whole organization unless you restrict it to specific roles.
      </p>

      <form ref={formRef} className="document-upload" onSubmit={upload}>
        <div className="document-upload-row">
          <label className="document-file-field">
            <Upload />
            <span>Choose a file</span>
            <small>PDF, text, Markdown or CSV</small>
            <input name="file" type="file" accept={SUPPORTED_TYPES} required />
          </label>
          <div className="document-upload-fields">
            <input name="title" aria-label="Title" placeholder="Title (optional)" maxLength={255} />
            <label className="document-visibility-toggle">
              <input
                type="checkbox"
                checked={restricted}
                onChange={(event) => {
                  setRestricted(event.target.checked);
                  if (!event.target.checked) setSelectedRoles([]);
                }}
              />
              <Lock />
              Restrict to specific roles
            </label>
            {restricted && (
              <div className="document-role-picker">
                {roles.map((role) => (
                  <label key={role.id}>
                    <input
                      type="checkbox"
                      name="role_ids"
                      value={role.id}
                      checked={selectedRoles.includes(role.id)}
                      onChange={(event) =>
                        setSelectedRoles((prev) =>
                          event.target.checked
                            ? [...prev, role.id]
                            : prev.filter((id) => id !== role.id),
                        )
                      }
                    />
                    {role.name}
                  </label>
                ))}
              </div>
            )}
            <input type="hidden" name="visibility" value={restricted ? "ROLE_RESTRICTED" : "TENANT"} />
            <button disabled={uploading || (restricted && selectedRoles.length === 0)}>
              <Upload />
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
      </form>

      {error && <p role="alert" className="workspace-error">{error}</p>}

      <PaginatedList
        items={documents}
        pageSize={6}
        label="Knowledge-base documents"
        className="branch-list document-list"
        keyFor={(doc) => doc.id}
        empty={(
          <p className="empty-state">
            No documents yet. Upload a policy, contract or manual to make it searchable.
          </p>
        )}
        renderItem={(doc) => (
          <article>
            <span className="branch-icon">
              <FileText />
            </span>
            <div>
              <strong>{doc.title}</strong>
              <small>
                {doc.filename} · {formatSize(doc.size_bytes)}
                {doc.status === "INDEXED" ? ` · ${doc.chunk_count} passages` : ""}
                {doc.visibility === "ROLE_RESTRICTED" ? " · Restricted" : ""}
              </small>
            </div>
            <StatusPill status={doc.status} failureReason={doc.failure_reason} />
            <button
              className="row-action"
              disabled={busy || doc.status === "PENDING" || doc.status === "EXTRACTING"}
              onClick={() => void reindex(doc.id)}
              aria-label={`Reindex ${doc.title}`}
              title="Reindex"
            >
              <RefreshCw />
            </button>
            <button
              className="row-action"
              disabled={busy}
              onClick={() => void remove(doc.id)}
              aria-label={`Delete ${doc.title}`}
              title="Delete"
            >
              <Trash2 />
            </button>
          </article>
        )}
      />
    </section>
  );
}
