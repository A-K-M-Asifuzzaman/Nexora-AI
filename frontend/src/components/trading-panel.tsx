"use client";

import { FileText, HandCoins, Receipt, Truck, Users2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { PaginatedList } from "@/components/paginated-list";

type Party = { id: string; code: string; name: string; is_active: boolean };
type Product = { id: string; sku: string; name: string; selling_price: string };
type Warehouse = { id: string; code: string; name: string };
type Branch = { id: string; code: string; name: string };
type SalesOrder = {
  id: string; order_number: string; customer_id: string; status: string;
  order_date: string; total_amount: string;
};
type Invoice = {
  id: string; invoice_number: string | null; customer_id: string; branch_id: string; status: string;
  issue_date: string; total_amount: string; paid_amount: string;
  sales_order_id: string | null;
};
type Receivable = {
  customer_id: string; customer_name: string; invoiced: string; paid: string; outstanding: string;
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
  const body = (await response.json()) as T & ApiError;
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

export function TradingPanel() {
  const [customers, setCustomers] = useState<Party[]>([]);
  const [suppliers, setSuppliers] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [payableTotal, setPayableTotal] = useState("0");
  const [receivableTotal, setReceivableTotal] = useState("0");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    // allSettled, not all: a member without sales permissions should see the
    // panel hidden rather than the whole workspace failing to load.
    const results = await Promise.allSettled([
      api<{ items: Party[] }>("customers/"),
      api<{ items: Party[] }>("suppliers/"),
      api<{ items: Product[] }>("products/"),
      api<{ items: Branch[] }>("branches/"),
      api<{ items: Warehouse[] }>("warehouses/"),
      api<{ items: SalesOrder[] }>("sales/orders/"),
      api<{ items: Invoice[] }>("sales/invoices/"),
      api<{ items: Receivable[]; total_outstanding: string }>("sales/receivables"),
      api<{ total_outstanding: string }>("purchases/payables"),
    ]);
    setVisible(results.every((result) => result.status === "fulfilled"));
    if (results[0].status === "fulfilled") setCustomers(results[0].value.items ?? []);
    if (results[1].status === "fulfilled") setSuppliers(results[1].value.items ?? []);
    if (results[2].status === "fulfilled") setProducts(results[2].value.items ?? []);
    if (results[3].status === "fulfilled") setBranches(results[3].value.items ?? []);
    if (results[4].status === "fulfilled") setWarehouses(results[4].value.items ?? []);
    if (results[5].status === "fulfilled") setOrders(results[5].value.items ?? []);
    if (results[6].status === "fulfilled") setInvoices(results[6].value.items ?? []);
    if (results[7].status === "fulfilled") {
      setReceivables(results[7].value.items ?? []);
      setReceivableTotal(results[7].value.total_outstanding ?? "0");
    }
    if (results[8].status === "fulfilled") setPayableTotal(results[8].value.total_outstanding ?? "0");
  }, []);

  // Deferred a tick so the initial fetch is not treated as setState during
  // the effect itself — same shape as CatalogInventoryPanel.
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await action(); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Something went wrong."); }
    finally { setBusy(false); }
  }

  async function createCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    await run(async () => {
      await api("customers/", { method: "POST", body: JSON.stringify({ code: data.get("code"), name: data.get("name") }) });
      form.reset();
    });
  }

  async function createSupplier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    await run(async () => {
      await api("suppliers/", { method: "POST", body: JSON.stringify({ code: data.get("code"), name: data.get("name") }) });
      form.reset();
    });
  }

  async function createOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    await run(async () => {
      await api("sales/orders/", {
        method: "POST",
        body: JSON.stringify({
          customer_id: data.get("customer_id"),
          branch_id: branches[0]?.id,
          warehouse_id: warehouses[0]?.id,
          order_date: new Date().toISOString().slice(0, 10),
          // Quantity and price stay strings all the way to the API — parsing
          // them into numbers here is how precision gets lost (ADR-0015).
          lines: [{
            product_id: data.get("product_id"),
            quantity: String(data.get("quantity") ?? "1"),
            unit_price: String(data.get("unit_price") ?? "0"),
          }],
        }),
      });
      form.reset();
    });
  }

  const advance = (order: SalesOrder) => run(async () => {
    if (order.status === "DRAFT") { await api(`sales/orders/${order.id}/confirm`, { method: "POST" }); return; }
    if (order.status === "CONFIRMED" || order.status === "PARTIALLY_FULFILLED") {
      await api(`sales/orders/${order.id}/fulfillments`, { method: "POST", body: JSON.stringify({}) });
      return;
    }
    await api("sales/invoices/", {
      method: "POST",
      body: JSON.stringify({ sales_order_id: order.id, issue_date: new Date().toISOString().slice(0, 10) }),
    });
  });

  // An order stays FULFILLED after it is invoiced — there is no INVOICED
  // status — so status alone cannot tell whether anything is left to bill.
  // The invoices already loaded here answer it without another round trip.
  const isInvoiced = (order: SalesOrder) =>
    invoices.some((invoice) => invoice.sales_order_id === order.id);

  const nextAction = (order: SalesOrder): string | null => {
    if (order.status === "CANCELLED") return null;
    if (order.status === "DRAFT") return "Confirm";
    if (order.status === "FULFILLED") return isInvoiced(order) ? null : "Invoice";
    return "Fulfil";
  };

  const issue = (invoice: Invoice) => run(() =>
    api(`sales/invoices/${invoice.id}/issue`, {
      method: "POST",
      // API.md §8 requires the header: issuing allocates a gapless number, and
      // a retry that allocated twice would burn one.
      headers: { "Idempotency-Key": idempotencyKey() },
    }));

  const outstanding = (invoice: Invoice) =>
    (Number(invoice.total_amount) - Number(invoice.paid_amount)).toFixed(4);

  async function recordPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const data = new FormData(form);
    const invoice = invoices.find((item) => item.id === data.get("invoice_id"));
    if (!invoice) return;
    await run(async () => {
      await api("sales/payments", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey() },
        body: JSON.stringify({
          customer_id: invoice.customer_id,
          branch_id: invoice.branch_id,
          method: data.get("method"),
          amount: data.get("amount"),
          payment_date: new Date().toISOString().slice(0, 10),
          allocations: [{ invoice_id: invoice.id, amount: data.get("amount") }],
        }),
      });
      form.reset();
    });
  }

  const customerName = (id: string) => customers.find((c) => c.id === id)?.name ?? "—";

  if (!visible) return null;

  return <>
    <section id="trading" className="management-card">
      <div className="section-title">
        <div><small>MONEY</small><h2>Receivables &amp; payables</h2></div>
      </div>
      <div className="ledger-totals">
        <article><small>Owed to you</small><strong>{money(receivableTotal)}</strong></article>
        <article><small>You owe</small><strong>{money(payableTotal)}</strong></article>
      </div>
      {error && <p role="alert" className="workspace-error">{error}</p>}
      <PaginatedList items={receivables} pageSize={5} label="Receivables" className="branch-list" keyFor={(row) => row.customer_id} empty={<p className="empty-state">Nothing outstanding.</p>} renderItem={(row) => <article>
          <span className="branch-icon"><HandCoins /></span>
          <div><strong>{row.customer_name}</strong><small>Invoiced {money(row.invoiced)} · Paid {money(row.paid)}</small></div>
          <em className="active">{money(row.outstanding)}</em>
        </article>} />
    </section>

    <section id="parties" className="management-card">
      <div className="section-title">
        <div><small>RELATIONSHIPS</small><h2>Customers &amp; suppliers</h2></div>
        <span>{customers.length} / {suppliers.length}</span>
      </div>
      <PaginatedList items={[...customers.map((party) => ({ party, kind: "Customer" as const })), ...suppliers.map((party) => ({ party, kind: "Supplier" as const }))]} pageSize={6} label="Customers and suppliers" className="branch-list" keyFor={(item) => `${item.kind}-${item.party.id}`} renderItem={(item) => <article>
        <span className="branch-icon">{item.kind === "Customer" ? <Users2 /> : <Truck />}</span>
        <div><strong>{item.party.name}</strong><small>{item.party.code} · {item.kind}</small></div>
      </article>} />
      <form className="inline-form" onSubmit={createCustomer}>
        <input name="code" aria-label="Customer code" placeholder="CODE" maxLength={32} required />
        <input name="name" aria-label="Customer name" placeholder="Customer name" maxLength={300} required />
        <button disabled={busy}><Users2 />Add customer</button>
      </form>
      <form className="inline-form" onSubmit={createSupplier}>
        <input name="code" aria-label="Supplier code" placeholder="CODE" maxLength={32} required />
        <input name="name" aria-label="Supplier name" placeholder="Supplier name" maxLength={300} required />
        <button disabled={busy}><Truck />Add supplier</button>
      </form>
    </section>

    <section id="orders" className="management-card">
      <div className="section-title">
        <div><small>SELLING</small><h2>Sales orders</h2></div>
        <span>{orders.length} total</span>
      </div>
      <PaginatedList items={orders} pageSize={6} label="Sales orders" className="branch-list" keyFor={(order) => order.id} empty={<p className="empty-state">No sales orders yet.</p>} renderItem={(order) => <article>
          <span className="branch-icon"><FileText /></span>
          <div><strong>{order.order_number}</strong><small>{customerName(order.customer_id)} · {order.order_date}</small></div>
          <em className={order.status === "CANCELLED" ? "inactive" : "active"}>{order.status.replace(/_/g, " ").toLowerCase()}</em>
          <b className="amount">{money(order.total_amount)}</b>
          {nextAction(order) && <button className="row-action" disabled={busy} onClick={() => void advance(order)}>{nextAction(order)}</button>}
        </article>} />
      <form className="inline-form order-form" onSubmit={createOrder}>
        <select name="customer_id" aria-label="Customer" required defaultValue="">
          <option value="" disabled>Customer</option>
          {customers.map((party) => <option key={party.id} value={party.id}>{party.name}</option>)}
        </select>
        <select name="product_id" aria-label="Product" required defaultValue="">
          <option value="" disabled>Product</option>
          {products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
        </select>
        <input name="quantity" aria-label="Quantity" placeholder="Qty" defaultValue="1" required />
        <input name="unit_price" aria-label="Unit price" placeholder="Unit price" defaultValue="0.0000" required />
        <button disabled={busy || customers.length === 0 || products.length === 0}>Create order</button>
      </form>
    </section>

    <section id="invoices" className="management-card">
      <div className="section-title">
        <div><small>BILLING</small><h2>Invoices</h2></div>
        <span>{invoices.length} total</span>
      </div>
      <PaginatedList items={invoices} pageSize={6} label="Invoices" className="branch-list" keyFor={(invoice) => invoice.id} empty={<p className="empty-state">No invoices yet.</p>} renderItem={(invoice) => <article>
          <span className="branch-icon"><Receipt /></span>
          <div>
            {/* A draft holds no number until issued, so the series stays gapless. */}
            <strong>{invoice.invoice_number ?? "Draft"}</strong>
            <small>{customerName(invoice.customer_id)} · paid {money(invoice.paid_amount)} of {money(invoice.total_amount)}</small>
          </div>
          <em className={invoice.status === "PAID" ? "active" : "inactive"}>{invoice.status.replace(/_/g, " ").toLowerCase()}</em>
          {invoice.status === "DRAFT" && <button className="row-action" disabled={busy} onClick={() => void issue(invoice)}>Issue</button>}
        </article>} />
      <form className="inline-form" onSubmit={recordPayment}>
        <select name="invoice_id" aria-label="Invoice" required defaultValue="">
          <option value="" disabled>Invoice to pay</option>
          {invoices.filter((invoice) => invoice.status === "ISSUED" || invoice.status === "PARTIALLY_PAID").map((invoice) =>
            <option key={invoice.id} value={invoice.id}>{invoice.invoice_number} · {customerName(invoice.customer_id)} · {money(outstanding(invoice))} due</option>)}
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
