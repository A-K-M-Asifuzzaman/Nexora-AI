"use client";

import { CreditCard, Pause, Play, Square, ShoppingCart } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Product = { id: string; sku: string; name: string; selling_price: string; is_active: boolean };
type Terminal = { id: string; code: string; name: string };
type Session = { id: string; session_number: string; status: string };
type ClosedSession = { session_number: string; expected_cash: string | null; counted_cash: string | null; cash_variance: string | null };
type Held = { id: string; label: string | null };
type Sale = { id: string; sale_number: string; total_amount: string };
type ApiError = { error?: { message?: string } };

function csrfToken(): string {
  const value = document.cookie.split("; ").find((part) => part.startsWith("nexora_csrf="));
  return value ? decodeURIComponent(value.split("=").slice(1).join("=")) : "";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/bff/${path}`, { ...init, headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(!["GET", "HEAD"].includes(init?.method ?? "GET") ? { "X-CSRF-Token": csrfToken() } : {}), ...init?.headers } });
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(body.error?.message ?? "The POS request could not be completed.");
  return body;
}

export function PosPanel() {
  const [products, setProducts] = useState<Product[]>([]); const [terminals, setTerminals] = useState<Terminal[]>([]);
  const [terminalId, setTerminalId] = useState(""); const [session, setSession] = useState<Session | null>(null);
  const [cart, setCart] = useState<Record<string, number>>({}); const [cash, setCash] = useState(""); const [card, setCard] = useState("");
  const [holds, setHolds] = useState<Held[]>([]); const [lastSale, setLastSale] = useState<Sale | null>(null);
  const [countedCash, setCountedCash] = useState(""); const [lastClose, setLastClose] = useState<ClosedSession | null>(null);
  const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { try { const [productPage, terminalResponse] = await Promise.all([api<{ items: Product[] }>("products/"), api<Terminal[]>("pos/terminals/")]); const terminalRows = Array.isArray(terminalResponse) ? terminalResponse : []; setProducts((productPage.items ?? []).filter((item) => item.is_active)); setTerminals(terminalRows); setTerminalId((current) => current || terminalRows[0]?.id || ""); } catch (reason) { setError(reason instanceof Error ? reason.message : "POS could not be loaded."); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  // A terminal can already have an open shift — left by another staff
  // member, a previous browser session, or seeded demo data — that this
  // tab has no local state for. Without this, "Open shift" 409s with no way
  // to reach the close button, since that only renders once `session` is set.
  useEffect(() => {
    if (!terminalId || session) return;
    let cancelled = false;
    void api<Session | null>(`pos/terminals/${terminalId}/session`).then((existing) => {
      if (!cancelled && existing) setSession(existing);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [terminalId, session]);
  const total = useMemo(() => products.reduce((sum, product) => sum + (cart[product.id] ?? 0) * Number(product.selling_price), 0), [cart, products]);
  const add = useCallback((productId: string) => setCart((current) => ({ ...current, [productId]: (current[productId] ?? 0) + 1 })), []);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "F2" && products[0]) { event.preventDefault(); add(products[0].id); } if (event.key === "Escape") setCart({}); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [add, products]);
  async function openSession() { setBusy(true); setError(null); setLastClose(null); try { setSession(await api<Session>("pos/sessions/open", { method: "POST", body: JSON.stringify({ terminal_id: terminalId, opening_float: "0.0000" }) })); } catch (reason) { setError(reason instanceof Error ? reason.message : "Session could not be opened."); } finally { setBusy(false); } }
  async function closeSession() { if (!session) return; setBusy(true); setError(null); try { const closed = await api<Session & ClosedSession>(`pos/sessions/${session.id}/close`, { method: "POST", body: JSON.stringify({ counted_cash: countedCash || "0" }) }); setLastClose({ session_number: closed.session_number, expected_cash: closed.expected_cash, counted_cash: closed.counted_cash, cash_variance: closed.cash_variance }); setSession(null); setCart({}); setHolds([]); setCountedCash(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Shift could not be closed."); } finally { setBusy(false); } }
  async function refreshHolds(sessionId: string) { setHolds(await api<Held[]>(`pos/sessions/${sessionId}/holds`)); }
  async function holdCart() { if (!session) return; setBusy(true); setError(null); try { await api("pos/holds/", { method: "POST", body: JSON.stringify({ session_id: session.id, label: "Parked cart", lines: Object.entries(cart).map(([product_id, quantity]) => ({ product_id, quantity: String(quantity), discount_rate: "0" })) }) }); setCart({}); await refreshHolds(session.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "Cart could not be held."); } finally { setBusy(false); } }
  async function resume(heldId: string) { if (!session) return; setBusy(true); try { const result = await api<{ lines: { product_id: string; quantity: string }[] }>(`pos/holds/${heldId}/resume`, { method: "POST" }); setCart(Object.fromEntries(result.lines.map((line) => [line.product_id, Number(line.quantity)]))); await refreshHolds(session.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "Cart could not be resumed."); } finally { setBusy(false); } }
  async function checkout() { if (!session) return; setBusy(true); setError(null); const payments = [cash && { tender: "CASH", amount: cash, change_given: "0" }, card && { tender: "CARD", amount: card, change_given: "0" }].filter(Boolean); try { const sale = await api<Sale>("pos/checkout", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ session_id: session.id, lines: Object.entries(cart).map(([product_id, quantity]) => ({ product_id, quantity: String(quantity), discount_rate: "0" })), payments }) }); setLastSale(sale); setCart({}); setCash(""); setCard(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Checkout failed."); } finally { setBusy(false); } }
  return <section id="pos" className="management-card pos-panel"><div className="section-title"><div><small>POINT OF SALE</small><h2>Checkout</h2></div><span>F2 add first item · Esc clear</span></div>{error && <p role="alert" className="workspace-error">{error}</p>}{!session ? <div className="pos-start"><select aria-label="POS terminal" value={terminalId} onChange={(event) => setTerminalId(event.target.value)}><option value="">Select terminal</option>{terminals.map((terminal) => <option key={terminal.id} value={terminal.id}>{terminal.name}</option>)}</select><button disabled={busy || !terminalId} onClick={() => void openSession()}><Play />Open shift</button></div> : <><div className="pos-session-bar"><p className="pos-session">Shift {session.session_number} is open</p><label>Counted cash<input aria-label="Counted cash" inputMode="decimal" placeholder="0.0000" value={countedCash} onChange={(event) => setCountedCash(event.target.value)} /></label><button disabled={busy} onClick={() => void closeSession()}><Square />Close shift</button></div><div className="pos-layout"><div className="pos-products">{products.map((product) => <button key={product.id} onClick={() => add(product.id)}><strong>{product.name}</strong><small>{product.sku}</small><span>{product.selling_price}</span></button>)}</div><aside className="pos-cart"><h3><ShoppingCart />Cart</h3>{Object.entries(cart).map(([id, quantity]) => <div key={id}><span>{products.find((item) => item.id === id)?.name}</span><b>× {quantity}</b></div>)}<strong className="pos-total">Total <span>{total.toFixed(4)}</span></strong><label>Cash<input aria-label="Cash tender" inputMode="decimal" value={cash} onChange={(event) => setCash(event.target.value)} /></label><label>Card<input aria-label="Card tender" inputMode="decimal" value={card} onChange={(event) => setCard(event.target.value)} /></label><div className="pos-actions"><button disabled={busy || total === 0} onClick={() => void holdCart()}><Pause />Hold</button><button disabled={busy || total === 0 || (!cash && !card)} onClick={() => void checkout()}><CreditCard />Pay</button></div></aside></div>{holds.length > 0 && <div className="pos-holds"><b>Held carts</b>{holds.map((held) => <button key={held.id} onClick={() => void resume(held.id)}>{held.label ?? "Held cart"}</button>)}</div>}</>}{lastSale && <p role="status" className="pos-success">Receipt {lastSale.sale_number} · {lastSale.total_amount}</p>}{lastClose && <p role="status" className="pos-success">Shift {lastClose.session_number} closed · counted {lastClose.counted_cash} vs expected {lastClose.expected_cash} · variance {lastClose.cash_variance}</p>}</section>;
}
