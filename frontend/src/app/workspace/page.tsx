import { ArrowUpRight, Bell, Boxes, CircleDollarSign, LayoutDashboard, ReceiptText, Search, Users } from "lucide-react";
import { redirect } from "next/navigation";

import { Brand } from "@/components/brand";
import { readSession } from "@/lib/bff-session";

import "./workspace.css";

export default async function WorkspacePage() {
  if (!(await readSession())) redirect("/login");
  return <main className="workspace"><aside className="workspace-sidebar"><Brand/><nav><a className="selected"><LayoutDashboard/>Overview</a><a><ReceiptText/>Sales</a><a><Boxes/>Inventory</a><a><CircleDollarSign/>Accounting</a><a><Users/>Team</a></nav><div className="workspace-user"><span>AZ</span><div><b>Asif Zaman</b><small>Workspace owner</small></div></div></aside><section className="workspace-content"><header><div><small>YOUR WORKSPACE</small><h1>Good morning, Asif.</h1></div><div className="workspace-actions"><button aria-label="Search"><Search/></button><button aria-label="Notifications"><Bell/></button></div></header><div className="workspace-metrics"><article><small>Revenue this month</small><strong>$84,290</strong><span>↗ 12.4% from last month</span></article><article><small>Net profit</small><strong>$21,840</strong><span>↗ 8.1% from last month</span></article><article><small>Open invoices</small><strong>18</strong><span className="neutral">$12,460 outstanding</span></article></div><div className="workspace-grid"><article className="activity-card"><div className="section-title"><div><small>PERFORMANCE</small><h2>Revenue movement</h2></div><button>Last 6 months</button></div><div className="large-chart"><i style={{height:"32%"}}/><i style={{height:"47%"}}/><i style={{height:"41%"}}/><i style={{height:"66%"}}/><i style={{height:"58%"}}/><i className="active" style={{height:"86%"}}/></div><div className="months"><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span></div></article><article className="ai-card"><span>✦</span><small>NEXORA INSIGHT</small><h2>Your margin is improving</h2><p>Gross margin rose 3.2% this month, led by stronger wholesale performance.</p><button>Explore insight <ArrowUpRight/></button></article></div></section></main>;
}
