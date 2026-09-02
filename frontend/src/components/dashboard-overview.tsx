"use client";

import gsap from "gsap";
import { AlertTriangle, ArrowUpRight, Boxes, CircleDollarSign, RefreshCw, Scale, WalletCards } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

type Dashboard = {
  from_date: string;
  to_date: string;
  pos_revenue: string;
  refunds: string;
  transactions: number;
  cost_of_goods_sold: string;
  gross_profit: string;
  invoiced: string;
  accounts_receivable: string;
  accounts_payable: string;
  inventory_value: string;
};
type TrendPoint = { date: string; revenue: string; transactions: number };
type ProductRank = { product_id: string; sku: string; name: string; quantity: string; revenue: string; margin: string };
type PipelineStage = { stage: string; count: number; amount: string; weighted_amount: string };
type LowStock = { product_id: string; sku: string; name: string; warehouse: string; on_hand: string; reserved: string; reorder_point: string };
type ApiError = { error?: { message?: string } };
type Range = "30" | "90" | "YTD";

// `Intl`'s own currency symbol for BDT only resolves to "৳" under a bn-*
// locale, which also switches digits to Bengali numerals and lakh/crore
// grouping — a bigger visual change than intended here. Formatting as plain
// decimals and prefixing the taka mark ourselves keeps Western digits and
// thousands grouping consistent with the rest of the interface.
const regularMoney = new Intl.NumberFormat("en-US", {
  style: "decimal",
  maximumFractionDigits: 0,
});
const compactMoney = new Intl.NumberFormat("en-US", {
  style: "decimal",
  notation: "compact",
  maximumFractionDigits: 1,
});

function api<T>(path: string): Promise<T> {
  return fetch(`/api/bff/${path}`).then(async (response) => {
    const body = (await response.json()) as T & ApiError;
    if (!response.ok) throw new Error(body.error?.message ?? "This report could not be loaded.");
    return body;
  });
}

export function formatMoney(value: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const magnitude = Math.abs(amount);
  const formatted = (magnitude >= 100_000 ? compactMoney : regularMoney).format(magnitude);
  return `${amount < 0 ? "-" : ""}৳${formatted}`;
}

export function weeklyTrend(items: TrendPoint[]): TrendPoint[] {
  const buckets = new Map<string, { revenue: number; transactions: number }>();
  for (const item of items) {
    const day = new Date(`${item.date}T00:00:00Z`);
    const monday = new Date(day);
    const offset = (day.getUTCDay() + 6) % 7;
    monday.setUTCDate(day.getUTCDate() - offset);
    const key = monday.toISOString().slice(0, 10);
    const current = buckets.get(key) ?? { revenue: 0, transactions: 0 };
    current.revenue += Number(item.revenue);
    current.transactions += item.transactions;
    buckets.set(key, current);
  }
  return [...buckets].map(([date, value]) => ({
    date,
    revenue: value.revenue.toFixed(4),
    transactions: value.transactions,
  }));
}

function rangeDates(range: Range): { from: string; to: string } {
  const now = new Date();
  const to = now.toISOString().slice(0, 10);
  const from = new Date(now);
  if (range === "YTD") from.setUTCMonth(0, 1);
  else from.setUTCDate(from.getUTCDate() - Number(range) + 1);
  return { from: from.toISOString().slice(0, 10), to };
}

function TrendChart({ items }: { items: TrendPoint[] }) {
  const weeks = weeklyTrend(items);
  const values = weeks.map((item) => Number(item.revenue));
  const ceiling = Math.max(1, ...values);
  const width = 720;
  const height = 210;
  const points = weeks.map((item, index) => {
    const x = weeks.length <= 1 ? width / 2 : (index / (weeks.length - 1)) * width;
    const y = height - (Number(item.revenue) / ceiling) * (height - 30) - 10;
    return { ...item, x, y };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = points.length ? `0,${height} ${line} ${width},${height}` : "";
  const peak = points.reduce<(typeof points)[number] | null>(
    (best, point) => (!best || Number(point.revenue) > Number(best.revenue) ? point : best),
    null,
  );

  return (
    <div className="trend-visual">
      {points.length === 0 ? <p className="empty-state">No sales in this range.</p> : (
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="sales-trend-title sales-trend-desc">
          <title id="sales-trend-title">Weekly point-of-sale revenue</title>
          <desc id="sales-trend-desc">Revenue aggregated by week for the selected reporting range.</desc>
          <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#36c997" stopOpacity="0.52" /><stop offset="58%" stopColor="#596fd8" stopOpacity="0.18" /><stop offset="100%" stopColor="#7359e8" stopOpacity="0.02" /></linearGradient></defs>
          <line x1="0" y1={height - 1} x2={width} y2={height - 1} className="chart-axis" />
          <polygon points={area} className="trend-area" />
          <polyline points={line} className="trend-line" />
          {points.map((point) => <circle key={point.date} cx={point.x} cy={point.y} r="4" className="trend-point" />)}
          {peak && <text x={Math.min(peak.x + 8, width - 105)} y={Math.max(peak.y - 10, 16)}>{formatMoney(peak.revenue)} peak</text>}
        </svg>
      )}
      {points.length > 0 && <div className="trend-labels"><span>{points[0].date}</span><span>{points.at(-1)?.date}</span></div>}
      <details className="chart-data-table">
        <summary>View weekly values</summary>
        <table><thead><tr><th>Week</th><th>Revenue</th><th>Transactions</th></tr></thead><tbody>{weeks.map((week) => <tr key={week.date}><td>{week.date}</td><td>{formatMoney(week.revenue)}</td><td>{week.transactions}</td></tr>)}</tbody></table>
      </details>
    </div>
  );
}

export function DashboardOverview() {
  const overviewRef = useRef<HTMLElement>(null);
  const [range, setRange] = useState<Range>("90");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [products, setProducts] = useState<ProductRank[]>([]);
  const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
  const [lowStock, setLowStock] = useState<LowStock[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string>("");

  const load = useCallback(async () => {
    setBusy(true); setError(null);
    const { from, to } = rangeDates(range);
    const query = `from_date=${from}&to_date=${to}`;
    const results = await Promise.allSettled([
      api<Dashboard>(`reports/dashboard?${query}`),
      api<{ items: TrendPoint[] }>(`reports/sales-trend?${query}`),
      api<{ items: ProductRank[] }>(`reports/top-products?${query}&limit=6`),
      api<{ items: PipelineStage[] }>("reports/pipeline"),
      api<{ items: LowStock[] }>("reports/low-stock"),
    ]);
    const [summary, salesTrend, topProducts, stages, stock] = results;
    if (summary.status === "fulfilled") setDashboard(summary.value);
    if (salesTrend.status === "fulfilled") setTrend(salesTrend.value.items ?? []);
    if (topProducts.status === "fulfilled") setProducts(topProducts.value.items ?? []);
    if (stages.status === "fulfilled") setPipeline(stages.value.items ?? []);
    if (stock.status === "fulfilled") setLowStock(stock.value.items ?? []);
    const failures = results.filter((result) => result.status === "rejected");
    setError(failures.length === results.length ? "Overview reports are unavailable for this role." : failures.length ? "Some overview data could not be refreshed." : null);
    setUpdatedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    setBusy(false);
  }, [range]);

  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  useLayoutEffect(() => {
    if (!dashboard || !overviewRef.current || (typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
    const context = gsap.context(() => {
      gsap.fromTo(".decision-brief article,.kpi-band article", { y: 13 }, { y: 0, duration: 0.42, stagger: 0.045, ease: "power2.out" });
      gsap.fromTo(".visual-panel", { y: 16 }, { y: 0, duration: 0.5, stagger: 0.07, ease: "power2.out", delay: 0.12 });
      gsap.fromTo(".trend-line", { strokeDasharray: 1200, strokeDashoffset: 1200 }, { strokeDashoffset: 0, duration: 1.05, ease: "power2.inOut", delay: 0.18 });
      gsap.fromTo(".ranking-panel li i,.pipeline-stack i span", { scaleX: 0, transformOrigin: "left center" }, { scaleX: 1, duration: 0.65, stagger: 0.055, ease: "power2.out", delay: 0.3 });
    }, overviewRef);
    return () => context.revert();
  }, [dashboard, range]);

  const maxProduct = Math.max(1, ...products.map((product) => Number(product.revenue)));
  const pipelineTotal = pipeline.reduce((sum, stage) => sum + Number(stage.amount), 0);
  const revenue = Number(dashboard?.pos_revenue ?? "0");
  const grossProfit = Number(dashboard?.gross_profit ?? "0");
  const cashExposure = Number(dashboard?.accounts_receivable ?? "0") - Number(dashboard?.accounts_payable ?? "0");
  const grossMargin = revenue > 0 ? (grossProfit / revenue) * 100 : 0;

  if (!dashboard && !busy && error) return null;
  return (
    <section id="overview" className="overview-surface" aria-labelledby="overview-title" ref={overviewRef}>
      <header className="overview-header">
        <div><small>LIVE BUSINESS PULSE</small><h2 id="overview-title">Clarity at a glance <span lang="bn">· এক নজরে ব্যবসা</span></h2><p>Sales, cash exposure, stock and pipeline—connected to the same records below.<span lang="bn">বিক্রয়, নগদ, মজুত ও সম্ভাব্য ব্যবসার সহজ সারাংশ।</span></p></div>
        <div className="overview-tools" role="group" aria-label="Report range">
          {(["30", "90", "YTD"] as Range[]).map((value) => <button key={value} className={range === value ? "active" : ""} onClick={() => setRange(value)}>{value === "YTD" ? "Year to date" : `${value} days`}</button>)}
          <button aria-label="Refresh overview" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? "spin" : ""} /></button>
        </div>
      </header>
      {error && <p className="overview-warning" role="status">{error}</p>}
      <div className="pulse-status"><span><i />Operational data</span><span>{updatedAt ? `Updated ${updatedAt}` : "Loading…"}</span></div>

      <div className="decision-brief" role="region" aria-label="Business decision summary">
        <article><small>Sales efficiency <span lang="bn">বিক্রয় দক্ষতা</span></small><strong>{grossMargin.toFixed(1)}% gross margin</strong><p lang="bn">প্রতি ১০০ টাকার বিক্রয়ে প্রায় {grossMargin.toFixed(0)} টাকা স্থূল লাভ।</p></article>
        <article><small>Cash position <span lang="bn">নগদ অবস্থান</span></small><strong>{formatMoney(String(Math.abs(cashExposure)))}</strong><p lang="bn">{cashExposure >= 0 ? "সরবরাহকারীর পাওনার চেয়ে ক্রেতার কাছে বেশি অর্থ বাকি।" : "ক্রেতার পাওনার চেয়ে সরবরাহকারীকে বেশি অর্থ দিতে হবে।"}</p></article>
        <article className={lowStock.length ? "attention" : "healthy"}><small>Action needed <span lang="bn">করণীয়</span></small><strong>{lowStock.length ? `${lowStock.length} stock items` : "Stock is healthy"}</strong><p lang="bn">{lowStock.length ? "পুনরায় অর্ডারের সীমায় পৌঁছানো পণ্য আগে যাচাই করুন।" : "বর্তমানে কোনো পণ্য পুনরায় অর্ডারের সীমায় নেই।"}</p></article>
      </div>

      <div className="kpi-band" role="group" aria-label="Key business indicators">
        <article className="primary"><span><CircleDollarSign /></span><small>POS revenue · <b lang="bn">বিক্রয়</b></small><strong>{formatMoney(dashboard?.pos_revenue ?? "0")}</strong><p>{dashboard?.transactions ?? 0} completed transactions</p></article>
        <article><span><ArrowUpRight /></span><small>Gross profit · <b lang="bn">স্থূল লাভ</b></small><strong>{formatMoney(dashboard?.gross_profit ?? "0")}</strong><p>After point-of-sale product cost</p></article>
        <article><span><WalletCards /></span><small>Receivables · <b lang="bn">পাওনা</b></small><strong>{formatMoney(dashboard?.accounts_receivable ?? "0")}</strong><p>Customer cash still to collect</p></article>
        <article><span><Scale /></span><small>Payables · <b lang="bn">দেনা</b></small><strong>{formatMoney(dashboard?.accounts_payable ?? "0")}</strong><p>Supplier obligations outstanding</p></article>
        <article><span><Boxes /></span><small>Inventory value · <b lang="bn">মজুত মূল্য</b></small><strong>{formatMoney(dashboard?.inventory_value ?? "0")}</strong><p>{lowStock.length} products at reorder level</p></article>
      </div>

      <div className="overview-grid">
        <article className="visual-panel trend-panel">
          <div className="visual-heading"><div><small>TIME CHANGE</small><h3>Weekly sales momentum</h3></div><b>{formatMoney(dashboard?.pos_revenue ?? "0")}</b></div>
          <TrendChart items={trend} />
        </article>
        <article className="visual-panel ranking-panel">
          <div className="visual-heading"><div><small>RANKING</small><h3>Top products</h3></div><span>by revenue</span></div>
          <ol>{products.map((product, index) => <li key={product.product_id}><b>{index + 1}</b><div><span>{product.name}</span><i style={{ width: `${Math.max(4, Number(product.revenue) / maxProduct * 100)}%` }} /></div><strong>{formatMoney(product.revenue)}</strong></li>)}</ol>
          {products.length === 0 && <p className="empty-state">No ranked sales in this range.</p>}
        </article>
        <article className="visual-panel pipeline-panel">
          <div className="visual-heading"><div><small>COMPOSITION</small><h3>Opportunity pipeline</h3></div><b>{formatMoney(String(pipelineTotal))}</b></div>
          <div className="pipeline-stack">{pipeline.map((stage) => <div key={stage.stage}><header><span>{stage.stage.replaceAll("_", " ").toLowerCase()}</span><b>{stage.count} · {formatMoney(stage.amount)}</b></header><i><span style={{ width: `${pipelineTotal ? Math.max(3, Number(stage.amount) / pipelineTotal * 100) : 0}%` }} /></i></div>)}</div>
        </article>
        <article className="visual-panel attention-panel">
          <div className="visual-heading"><div><small>ATTENTION</small><h3>Stock watch</h3></div><span><AlertTriangle /> {lowStock.length}</span></div>
          <div className="stock-watch">{lowStock.slice(0, 5).map((item) => <div key={`${item.product_id}-${item.warehouse}`}><span><b>{item.name}</b><small>{item.sku} · {item.warehouse}</small></span><strong>{item.on_hand} on hand</strong></div>)}</div>
          {lowStock.length === 0 && <p className="healthy-state">All configured reorder levels are healthy.</p>}
        </article>
      </div>
    </section>
  );
}
