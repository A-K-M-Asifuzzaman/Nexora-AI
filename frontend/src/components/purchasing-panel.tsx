"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { HandCoins, PackageCheck, Receipt, Truck } from "lucide-react";

import { PaginatedList } from "@/components/paginated-list";

type Party = { id: string; code: string; name: string; is_active: boolean };
type Product = { id: string; sku: string; name: string; cost_price: string };
type Branch = { id: string; code: string; name: string };
type Warehouse = { id: string; code: string; name: string };
type PurchaseOrder = {
  id: string; order_number: string; supplier_id: string; status: string;
  order_date: string; total_amount: string;
};
type SupplierBill = {
  id: string; bill_number: string | null; supplier_id: string; branch_id: string; status: string;
  purchase_order_id: string | null; total_amount: string; paid_amount: string;
};
type ApiError = { error?: { message?: string } };

const PAYMENT_METHODS = ["CASH", "CARD", "BANK_TRANSFER", "MOBILE"] as const;

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

/** Money arrives as a string (ADR-0015) and must never be parsed into a float. */
function money(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${grouped}.${fraction.slice(0, 2).padEnd(2, "0")}`;
}

const idempotencyKey = () => crypto.randomUUID();

export function PurchasingPanel() {
  const [suppliers, setSuppliers] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [bills, setBills] = useState<SupplierBill[]>([]);
  const [payableTotal, setPayableTotal] = useState("0");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    // allSettled, not all: a member without purchasing permissions should see
    // the panel hidden rather than the whole workspace failing to load.
    const results = await Promise.allSettled([
      api<{ items: Party[] }>("suppliers/"),
      api<{ items: Product[] }>("products/"),
      api<{ items: Branch[] }>("branches/"),
      api<{ items: Warehouse[] }>("warehouses/"),
      api<{ items: PurchaseOrder[] }>("purchases/orders/"),
      api<{ items: SupplierBill[] }>("purchases/bills/"),
      api<{ total_outstanding: string }>("purchases/payables"),
    ]);
    setVisible(results.every((result) => result.status === "fulfilled"));
    if (results[0].status === "fulfilled") setSuppliers(results[0].value.items ?? []);
    if (results[1].status === "fulfilled") setProducts(results[1].value.items ?? []);
    if (results[2].status === "fulfilled") setBranches(results[2].value.items ?? []);
    if (results[3].status === "fulfilled") setWarehouses(results[3].value.items ?? []);
    if (results[4].status === "fulfilled") setOrders(results[4].value.items ?? []);
    if (results[5].status === "fulfilled") setBills(results[5].value.items ?? []);
    if (results[6].status === "fulfilled") setPayableTotal(results[6].value.total_outstanding ?? "0");
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await action(); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Something went wrong."); }
    finally { setBusy(false); }
  }

  async function createOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    await run(async () => {
      await api("purchases/orders/", {
        method: "POST",
        body: JSON.stringify({
          supplier_id: data.get("supplier_id"),
          branch_id: branches[0]?.id,
          warehouse_id: warehouses[0]?.id,
          order_date: new Date().toISOString().slice(0, 10),
          lines: [{
            product_id: data.get("product_id"),
            quantity: String(data.get("quantity") ?? "1"),
            unit_cost: String(data.get("unit_cost") ?? "0"),
          }],
        }),
      });
      form.reset();
    });
  }

  // A purchase order stays RECEIVED after billing — there is no BILLED
  // status — so status alone cannot tell whether anything is left to bill.
  const isBilled = (order: PurchaseOrder) =>
    bills.some((bill) => bill.purchase_order_id === order.id);

  const advance = (order: PurchaseOrder) => run(async () => {
    if (order.status === "DRAFT") { await api(`purchases/orders/${order.id}/confirm`, { method: "POST" }); return; }
    if (order.status === "CONFIRMED" || order.status === "PARTIALLY_RECEIVED") {
      await api(`purchases/orders/${order.id}/receipts`, { method: "POST", body: JSON.stringify({}) });
      return;
    }
    await api("purchases/bills/", {
      method: "POST",
      body: JSON.stringify({ purchase_order_id: order.id, issue_date: new Date().toISOString().slice(0, 10) }),
    });
  });

  const nextAction = (order: PurchaseOrder): string | null => {
    if (order.status === "CANCELLED") return null;
    if (order.status === "DRAFT") return "Confirm";
    if (order.status === "RECEIVED") return isBilled(order) ? null : "Bill";
    return "Receive";
  };

  const issueBill = (bill: SupplierBill) => run(() =>
    api(`purchases/bills/${bill.id}/issue`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey() },
    }));

  const outstanding = (bill: SupplierBill) =>
    (Number(bill.total_amount) - Number(bill.paid_amount)).toFixed(4);

  async function recordPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    const bill = bills.find((item) => item.id === data.get("bill_id"));
    if (!bill) return;
    await run(async () => {
      await api("purchases/payments", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey() },
        body: JSON.stringify({
          supplier_id: bill.supplier_id,
          branch_id: bill.branch_id,
          method: data.get("method"),
          amount: data.get("amount"),
          payment_date: new Date().toISOString().slice(0, 10),
          allocations: [{ supplier_bill_id: bill.id, amount: data.get("amount") }],
        }),
      });
      form.reset();
    });
  }

  const supplierName = (id: string) => suppliers.find((s) => s.id === id)?.name ?? "—";

  if (!visible) return null;

  return <>
    <section id="purchasing-payables" className="management-card">
      <div className="section-title"><div><small>PROCUREMENT</small><h2>Payables</h2></div></div>
      <div className="ledger-totals"><article><small>You owe</small><strong>{money(payableTotal)}</strong></article></div>
      {error && <p role="alert" className="workspace-error">{error}</p>}
    </section>

    <section id="purchase-orders" className="management-card">
      <div className="section-title">
        <div><small>BUYING</small><h2>Purchase orders</h2></div>
        <span>{orders.length} total</span>
      </div>
      <PaginatedList items={orders} pageSize={6} label="Purchase orders" className="branch-list" keyFor={(order) => order.id} empty={<p className="empty-state">No purchase orders yet.</p>} renderItem={(order) => <article>
          <span className="branch-icon"><Truck /></span>
          <div><strong>{order.order_number}</strong><small>{supplierName(order.supplier_id)} · {order.order_date}</small></div>
          <em className={order.status === "CANCELLED" ? "inactive" : "active"}>{order.status.replace(/_/g, " ").toLowerCase()}</em>
          <b className="amount">{money(order.total_amount)}</b>
          {nextAction(order) && <button className="row-action" disabled={busy} onClick={() => void advance(order)}>{nextAction(order)}</button>}
        </article>} />
      <form className="inline-form order-form" onSubmit={createOrder}>
        <select name="supplier_id" aria-label="Supplier" required defaultValue="">
          <option value="" disabled>Supplier</option>
          {suppliers.map((party) => <option key={party.id} value={party.id}>{party.name}</option>)}
        </select>
        <select name="product_id" aria-label="Purchase order product" required defaultValue="">
          <option value="" disabled>Product</option>
          {products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
        </select>
        <input name="quantity" aria-label="Purchase order quantity" placeholder="Qty" defaultValue="1" required />
        <input name="unit_cost" aria-label="Purchase unit cost" placeholder="Unit cost" defaultValue="0.0000" required />
        <button disabled={busy || suppliers.length === 0 || products.length === 0}><PackageCheck />Create order</button>
      </form>
    </section>

    <section id="supplier-bills" className="management-card">
      <div className="section-title">
        <div><small>BILLING</small><h2>Supplier bills</h2></div>
        <span>{bills.length} total</span>
      </div>
      <PaginatedList items={bills} pageSize={6} label="Supplier bills" className="branch-list" keyFor={(bill) => bill.id} empty={<p className="empty-state">No supplier bills yet.</p>} renderItem={(bill) => <article>
          <span className="branch-icon"><Receipt /></span>
          <div>
            {/* A draft holds no number until issued, so the series stays gapless. */}
            <strong>{bill.bill_number ?? "Draft"}</strong>
            <small>{supplierName(bill.supplier_id)} · paid {money(bill.paid_amount)} of {money(bill.total_amount)}</small>
          </div>
          <em className={bill.status === "PAID" ? "active" : "inactive"}>{bill.status.replace(/_/g, " ").toLowerCase()}</em>
          {bill.status === "DRAFT" && <button className="row-action" disabled={busy} onClick={() => void issueBill(bill)}>Issue</button>}
        </article>} />
      <form className="inline-form" onSubmit={recordPayment}>
        <select name="bill_id" aria-label="Bill" required defaultValue="">
          <option value="" disabled>Bill to pay</option>
          {bills.filter((bill) => bill.status === "ISSUED" || bill.status === "PARTIALLY_PAID").map((bill) =>
            <option key={bill.id} value={bill.id}>{bill.bill_number} · {supplierName(bill.supplier_id)} · {money(outstanding(bill))} due</option>)}
        </select>
        <select name="method" aria-label="Payment method" required defaultValue="CASH">
          {PAYMENT_METHODS.map((method) => <option key={method} value={method}>{method.replace("_", " ")}</option>)}
        </select>
        <input name="amount" aria-label="Payment amount" inputMode="decimal" placeholder="Amount" pattern="[0-9]+(\.[0-9]{1,4})?" required />
        <button disabled={busy}><HandCoins />Record payment</button>
      </form>
    </section>
  </>;
}
