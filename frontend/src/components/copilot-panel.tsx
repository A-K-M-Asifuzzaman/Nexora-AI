"use client";

import { AlertTriangle, Bot, Send, ShieldCheck, Wrench } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type ToolInvocation = { tool: string; arguments: Record<string, unknown>; error: boolean; rows: number };
type AskResponse = {
  answer: string | null;
  grounded: boolean;
  regenerated: boolean;
  note?: string | null;
  tool_calls: ToolInvocation[];
  data: unknown[];
};
type ToolDescription = { name: string; description: string; permissions: string[] };
type ApiError = { error?: { message?: string } };

type Turn =
  | { role: "user"; text: string }
  | { role: "assistant"; result: AskResponse };

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
  if (!response.ok) throw new Error(body.error?.message ?? "The copilot could not answer.");
  return body;
}

export function CopilotPanel() {
  const [tools, setTools] = useState<ToolDescription[]>([]);
  const [visible, setVisible] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setTools(await api<ToolDescription[]>("ai/tools"));
      setVisible(true);
    } catch {
      // No ai.use permission, or the copilot is disabled for this deployment.
      setVisible(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight });
  }, [turns]);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const question = String(new FormData(form).get("question") ?? "").trim();
    if (!question) return;

    setBusy(true);
    setError(null);
    setTurns((prev) => [...prev, { role: "user", text: question }]);
    form.reset();
    try {
      const result = await api<AskResponse>("ai/ask", {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      setTurns((prev) => [...prev, { role: "assistant", result }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The copilot could not answer.");
    } finally {
      setBusy(false);
    }
  }

  if (!visible) return null;

  return (
    <section id="copilot" className="management-card">
      <div className="section-title">
        <div>
          <small>ASSISTANT</small>
          <h2>Business copilot</h2>
        </div>
        <span>{tools.length} tools</span>
      </div>

      <p className="copilot-note">
        <ShieldCheck />
        Answers come only from your own data, through {tools.length} read-only tools that each
        check your permissions. Figures are verified against the tool results before they are
        shown.
      </p>

      <div className="copilot-transcript" ref={transcript}>
        {turns.length === 0 && (
          <p className="empty-state">
            Ask about revenue, margin, stock, receivables or payables — for example
            &ldquo;what were my top products last month?&rdquo;
          </p>
        )}
        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <article key={index} className="copilot-turn user">
              <p>{turn.text}</p>
            </article>
          ) : (
            <article key={index} className="copilot-turn assistant">
              <span className="branch-icon"><Bot /></span>
              <div>
                {turn.result.answer ? (
                  <p>{turn.result.answer}</p>
                ) : (
                  /* Degraded: the provider failed or the answer could not be
                     grounded. The figures are shown instead of a guess. */
                  <p className="copilot-degraded">
                    <AlertTriangle />
                    {turn.result.note}
                  </p>
                )}
                {turn.result.tool_calls.length > 0 && (
                  <ul className="copilot-tools">
                    {turn.result.tool_calls.map((call, i) => (
                      <li key={i} className={call.error ? "failed" : undefined}>
                        <Wrench />
                        {call.tool}
                        {call.error ? " · refused" : ""}
                      </li>
                    ))}
                  </ul>
                )}
                {!turn.result.answer && turn.result.data.length > 0 && (
                  <pre className="copilot-data">
                    {JSON.stringify(turn.result.data, null, 2)}
                  </pre>
                )}
              </div>
            </article>
          ),
        )}
      </div>

      {error && <p role="alert" className="workspace-error">{error}</p>}

      <form className="inline-form copilot-form" onSubmit={ask}>
        <input
          name="question"
          aria-label="Ask the copilot"
          placeholder="Ask about your business…"
          maxLength={2000}
          autoComplete="off"
          required
        />
        <button disabled={busy}>
          <Send />
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}
