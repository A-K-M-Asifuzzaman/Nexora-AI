"use client";

import { Bot, Boxes, ChevronRight, FileSearch, HandCoins, HelpCircle, ShoppingCart, Sparkles } from "lucide-react";
import { useState } from "react";

const journeys = [
  {
    title: "Sell and collect",
    summary: "From a customer request to recognized revenue and settled cash.",
    icon: HandCoins,
    steps: ["Create customer", "Create & confirm order", "Fulfil from stock", "Create & issue invoice", "Record payment"],
    destination: "#orders",
  },
  {
    title: "Buy and replenish",
    summary: "Receive stock with traceable cost, liability and payment records.",
    icon: Boxes,
    steps: ["Create supplier", "Confirm purchase order", "Receive goods", "Issue supplier bill", "Pay supplier"],
    destination: "#trading",
  },
  {
    title: "Run the counter",
    summary: "Open a controlled shift, sell, hold carts, refund and close cash.",
    icon: ShoppingCart,
    steps: ["Choose terminal", "Open session", "Build cart", "Take exact tender", "Close & reconcile"],
    destination: "#pos",
  },
  {
    title: "Turn documents into answers",
    summary: "Upload safely, index asynchronously, then ask permission-aware questions.",
    icon: FileSearch,
    steps: ["Upload document", "Virus scan", "Extract & index", "Apply document ACL", "Ask Copilot"],
    destination: "#documents",
  },
];

export function UserGuidePanel() {
  const [open, setOpen] = useState(0);
  return (
    <section id="guide" className="management-card guide-panel" aria-labelledby="guide-title">
      <div className="guide-intro">
        <div><small>IN-APP USER GUIDE</small><h2 id="guide-title">Know the next step</h2><p>Every workflow below uses the same production rules as the live system. Follow a journey, then inspect its impact in the overview.</p></div>
        <span><HelpCircle /><b>Demo tip</b><small>Start with Overview, then follow one complete journey.</small></span>
      </div>
      <div className="journey-tabs" role="tablist" aria-label="Business workflow guides">
        {journeys.map((journey, index) => {
          const Icon = journey.icon;
          return <button key={journey.title} role="tab" aria-selected={open === index} aria-controls={`journey-${index}`} onClick={() => setOpen(index)}><Icon /><span><b>{journey.title}</b><small>{journey.summary}</small></span><ChevronRight /></button>;
        })}
      </div>
      {journeys.map((journey, index) => open === index && (
        <div key={journey.title} id={`journey-${index}`} role="tabpanel" className="journey-detail">
          <div className="journey-flow" role="list" aria-label={`${journey.title} workflow`}>
            {journey.steps.map((step, stepIndex) => <div role="listitem" key={step}><span>{stepIndex + 1}</span><b>{step}</b>{stepIndex < journey.steps.length - 1 && <ChevronRight aria-hidden="true" />}</div>)}
          </div>
          <div className="journey-notes">
            <p><Sparkles /> Every money value remains exact; inventory changes only through its ledger; accounting and VAT post from the business event.</p>
            <a href={journey.destination}>Open this workspace <ChevronRight /></a>
          </div>
        </div>
      ))}
      <div className="guide-footer"><Bot /><span><b>Need an explanation?</b><small>Use Nexora Copilot at the bottom of the workspace. It reads only authorized data and never generates SQL.</small></span></div>
    </section>
  );
}
