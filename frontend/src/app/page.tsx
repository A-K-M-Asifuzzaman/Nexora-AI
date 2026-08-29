import { ArrowRight, Check, CirclePlay, MoveUpRight } from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/brand";

const proof = ["Real-time financial visibility", "Built-in access controls", "AI answers with evidence"];

export default function HomePage() {
  return (
    <main className="landing">
      <nav className="topbar">
        <Brand />
        <div className="nav-links" aria-label="Primary navigation">
          <a href="#platform">Platform</a><a href="#security">Security</a><a href="#company">Company</a>
        </div>
        <div className="nav-actions">
          <Link className="text-button" href="/login">Sign in</Link>
          <Link className="button button-dark" href="/register">Start free <ArrowRight size={16} /></Link>
        </div>
      </nav>

      <section className="hero" id="platform">
        <div className="hero-copy">
          <div className="eyebrow"><span /> The intelligent business workspace</div>
          <h1>Run your business with <i>clarity.</i></h1>
          <p className="hero-lede">Bring operations, finance, and your team into one calm workspace—then ask AI what deserves your attention.</p>
          <div className="hero-actions">
            <Link className="button button-accent" href="/register">Build your workspace <MoveUpRight size={17} /></Link>
            <button className="watch" type="button"><CirclePlay size={21} /> See how it works</button>
          </div>
          <ul className="proof-list">{proof.map((item) => <li key={item}><Check size={15} />{item}</li>)}</ul>
        </div>

        <div className="product-frame" aria-label="Nexora dashboard preview">
          <div className="window-bar"><span /><span /><span /><small>app.nexora.ai</small></div>
          <div className="preview-layout">
            <aside><Brand /><div className="mini-nav active">Overview</div><div className="mini-nav">Sales</div><div className="mini-nav">Inventory</div><div className="mini-nav">Accounting</div></aside>
            <div className="preview-main">
              <header><div><small>MONDAY, AUGUST 29</small><h2>Good morning, Asif.</h2></div><div className="avatar">AZ</div></header>
              <div className="metric-row"><Metric label="Revenue" value="$84,290" trend="+12.4%" /><Metric label="Net profit" value="$21,840" trend="+8.1%" /><Metric label="Cash position" value="$128,460" trend="Healthy" /></div>
              <div className="preview-grid">
                <div className="chart-card"><div className="card-head"><span>Revenue movement</span><small>Last 6 months</small></div><div className="chart"><i className="bar-28"/><i className="bar-43"/><i className="bar-37"/><i className="bar-62"/><i className="bar-54"/><i className="bar-82"/><i className="bar-72 current"/></div></div>
                <div className="insight-card"><span className="insight-icon">✦</span><small>NEXORA INSIGHT</small><h3>Your margin is improving</h3><p>Gross margin rose 3.2% this month, led by your wholesale channel.</p><button type="button">Explore insight <ArrowRight size={14}/></button></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="trust" id="security"><span>Designed for decisions. Engineered for trust.</span><div><b>Tenant-isolated</b><b>Audit-ready</b><b>Permission-aware</b><b>Human-first AI</b></div></section>
    </main>
  );
}

function Metric({ label, value, trend }: { label: string; value: string; trend: string }) {
  return <div className="metric"><small>{label}</small><strong>{value}</strong><span>{trend}</span></div>;
}
