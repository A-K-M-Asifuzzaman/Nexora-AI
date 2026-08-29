"use client";

import { ArrowDownToLine, ArrowUpFromLine, Boxes, PackagePlus, Plus } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { PosPanel } from "@/components/pos-panel";

type Product = { id: string; sku: string; name: string; cost_price: string; selling_price: string; is_active: boolean };
type Unit = { id: string; code: string; name: string; precision: number };
type Warehouse = { id: string; code: string; name: string };
type Balance = { id: string; warehouse_id: string; product_id: string; quantity_on_hand: string; reserved_quantity: string; available: string };
type Movement = { id: string; movement_type: string; product_id: string; warehouse_id: string; quantity: string; occurred_at: string };
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

export function CatalogInventoryPanel() {
  const [products, setProducts] = useState<Product[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [balances, setBalances] = useState<Balance[]>([]);
  const [movements, setMovements] = useState<Movement[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [productPage, unitPage, warehousePage, balancePage, movementPage] = await Promise.all([
        api<{ items: Product[] }>("products/"),
        api<{ items: Unit[] }>("units/"),
        api<{ items: Warehouse[] }>("warehouses/"),
        api<{ items: Balance[] }>("inventory/balances/"),
        api<{ items: Movement[] }>("inventory/movements/?limit=20"),
      ]);
      setProducts(productPage.items ?? []); setUnits(unitPage.items ?? []); setWarehouses(warehousePage.items ?? []);
      setBalances(balancePage.items ?? []); setMovements(movementPage.items ?? []); setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Catalog and inventory could not be loaded.");
    }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  async function createUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); const form = event.currentTarget; const data = new FormData(form);
    try {
      await api("units/", { method: "POST", body: JSON.stringify({ code: data.get("code"), name: data.get("name"), precision: Number(data.get("precision")) }) });
      form.reset(); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unit creation failed."); } finally { setBusy(false); }
  }

  async function createProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); const form = event.currentTarget; const data = new FormData(form);
    try {
      await api("products/", { method: "POST", body: JSON.stringify({ sku: data.get("sku"), name: data.get("name"), uom_id: data.get("uom_id"), selling_price: data.get("selling_price"), is_stock_tracked: true }) });
      form.reset(); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Product creation failed."); } finally { setBusy(false); }
  }

  async function postMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); const form = event.currentTarget; const data = new FormData(form);
    const operation = String(data.get("operation"));
    const payload: Record<string, FormDataEntryValue | null> = { warehouse_id: data.get("warehouse_id"), product_id: data.get("product_id"), quantity: data.get("quantity") };
    if (operation === "receipts") payload.unit_cost = data.get("unit_cost");
    try {
      await api(`inventory/${operation}/`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
      form.reset(); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Inventory movement failed."); } finally { setBusy(false); }
  }

  const productName = (id: string) => products.find((item) => item.id === id)?.name ?? "Unknown product";
  const warehouseName = (id: string) => warehouses.find((item) => item.id === id)?.name ?? "Unknown warehouse";

  return <>
    {error && <p role="alert" className="workspace-error">{error}</p>}
    <section id="catalog" className="management-card"><div className="section-title"><div><small>CATALOG</small><h2>Products</h2></div><span>{products.length} total</span></div>
      <div className="inventory-table"><div className="inventory-head"><span>Product</span><span>SKU</span><span>Cost</span><span>Price</span></div>{products.map((product) => <div key={product.id}><strong>{product.name}</strong><span>{product.sku}</span><span>{product.cost_price}</span><span>{product.selling_price}</span></div>)}{products.length === 0 && <p className="empty-state">No products yet.</p>}</div>
      <form className="catalog-form" onSubmit={createUnit}><input name="code" aria-label="Unit code" placeholder="Unit code" pattern="[A-Z0-9_\-]+" maxLength={16} required /><input name="name" aria-label="Unit name" placeholder="Unit name" maxLength={100} required /><input name="precision" aria-label="Unit precision" type="number" min={0} max={6} defaultValue={0} required /><button disabled={busy}><Plus />Add unit</button></form>
      <form className="catalog-form product-form" onSubmit={createProduct}><input name="sku" aria-label="Product SKU" placeholder="SKU" maxLength={64} required /><input name="name" aria-label="Product name" placeholder="Product name" maxLength={300} required /><select name="uom_id" aria-label="Unit" required defaultValue=""><option value="" disabled>Select unit</option>{units.map((unit) => <option key={unit.id} value={unit.id}>{unit.code} — {unit.name}</option>)}</select><input name="selling_price" aria-label="Selling price" inputMode="decimal" placeholder="0.0000" pattern="[0-9]+(\.[0-9]{1,4})?" required /><button disabled={busy || units.length === 0}><PackagePlus />Add product</button></form>
    </section>
    <section id="inventory" className="management-card"><div className="section-title"><div><small>INVENTORY</small><h2>Stock balances</h2></div><span>{balances.length} stocked items</span></div>
      <div className="inventory-table"><div className="inventory-head"><span>Product</span><span>Warehouse</span><span>On hand</span><span>Available</span></div>{balances.map((balance) => <div key={balance.id}><strong>{productName(balance.product_id)}</strong><span>{warehouseName(balance.warehouse_id)}</span><span>{balance.quantity_on_hand}</span><span>{balance.available}</span></div>)}{balances.length === 0 && <p className="empty-state">No stock has been posted.</p>}</div>
      <form className="catalog-form movement-form" onSubmit={postMovement}><select name="operation" aria-label="Movement type" defaultValue="receipts"><option value="receipts">Receive stock</option><option value="issues">Issue stock</option></select><select name="warehouse_id" aria-label="Warehouse" required defaultValue=""><option value="" disabled>Select warehouse</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select><select name="product_id" aria-label="Product" required defaultValue=""><option value="" disabled>Select product</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select><input name="quantity" aria-label="Quantity" inputMode="decimal" placeholder="Quantity" required /><input name="unit_cost" aria-label="Unit cost for receipts" inputMode="decimal" placeholder="Unit cost (receipts)" /><button disabled={busy || products.length === 0 || warehouses.length === 0}><Boxes />Post movement</button></form>
      <div className="movement-list"><h3>Recent movements</h3>{movements.map((movement) => <article key={movement.id}>{movement.movement_type === "RECEIPT" ? <ArrowDownToLine /> : <ArrowUpFromLine />}<div><strong>{productName(movement.product_id)}</strong><small>{warehouseName(movement.warehouse_id)} · {new Date(movement.occurred_at).toLocaleString()}</small></div><span>{movement.quantity}</span></article>)}</div>
    </section>
    <PosPanel />
  </>;
}
