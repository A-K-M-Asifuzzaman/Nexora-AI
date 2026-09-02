"use client";

import { Bot, Boxes, ChevronRight, FileSearch, HandCoins, HelpCircle, ShoppingCart, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

const journeys = [
  {
    title: "Sell and collect",
    titleBn: "বিক্রি ও টাকা আদায়",
    summary: "From a customer request to recognized revenue and settled cash.",
    summaryBn: "ক্রেতার চাহিদা থেকে পণ্য সরবরাহ, আয় স্বীকৃতি এবং টাকা আদায় পর্যন্ত।",
    icon: HandCoins,
    steps: ["Create customer", "Create & confirm order", "Fulfil from stock", "Create & issue invoice", "Record payment"],
    stepsBn: ["ক্রেতা তৈরি", "অর্ডার তৈরি ও নিশ্চিত", "স্টক থেকে সরবরাহ", "ইনভয়েস ইস্যু", "পেমেন্ট রেকর্ড"],
    destination: "/workspace/sales",
  },
  {
    title: "Buy and replenish",
    titleBn: "ক্রয় ও মজুত পূরণ",
    summary: "Receive stock with traceable cost, liability and payment records.",
    summaryBn: "যাচাইযোগ্য খরচ, দায় এবং পেমেন্ট রেকর্ডসহ পণ্য গ্রহণ করুন।",
    icon: Boxes,
    steps: ["Create supplier", "Confirm purchase order", "Receive goods", "Issue supplier bill", "Pay supplier"],
    stepsBn: ["সরবরাহকারী তৈরি", "ক্রয়াদেশ নিশ্চিত", "পণ্য গ্রহণ", "সরবরাহকারী বিল", "পেমেন্ট করুন"],
    destination: "/workspace/inventory",
  },
  {
    title: "Run the counter",
    titleBn: "বিক্রয় কাউন্টার চালান",
    summary: "Open a controlled shift, sell, hold carts, refund and close cash.",
    summaryBn: "নিয়ন্ত্রিত শিফট খুলে বিক্রি, কার্ট হোল্ড, রিফান্ড ও ক্যাশ মিল করুন।",
    icon: ShoppingCart,
    steps: ["Choose terminal", "Open session", "Build cart", "Take exact tender", "Close & reconcile"],
    stepsBn: ["টার্মিনাল বাছাই", "সেশন খুলুন", "কার্ট তৈরি", "সঠিক পেমেন্ট নিন", "বন্ধ ও মিল করুন"],
    destination: "/workspace/inventory",
  },
  {
    title: "Turn documents into answers",
    titleBn: "ডকুমেন্ট থেকে উত্তর",
    summary: "Upload safely, index asynchronously, then ask permission-aware questions.",
    summaryBn: "নিরাপদে আপলোড ও ইনডেক্স করে অনুমতিভিত্তিক প্রশ্নের উত্তর পান।",
    icon: FileSearch,
    steps: ["Upload document", "Virus scan", "Extract & index", "Apply document ACL", "Ask Copilot"],
    stepsBn: ["ডকুমেন্ট আপলোড", "ভাইরাস স্ক্যান", "এক্সট্র্যাক্ট ও ইনডেক্স", "অ্যাক্সেস নিয়ন্ত্রণ", "কোপাইলটকে জিজ্ঞাসা"],
    destination: "/workspace/documents",
  },
] as const;

export function UserGuidePanel() {
  const [open, setOpen] = useState(0);
  return (
    <section id="guide" className="management-card guide-panel" aria-labelledby="guide-title">
      <div className="guide-intro">
        <div><small>IN-APP USER GUIDE · ব্যবহার সহায়িকা</small><h2 id="guide-title">Know the next step <span>· পরবর্তী ধাপ জানুন</span></h2><p>Every workflow below uses the same production rules as the live system. Follow a journey, then inspect its impact in the overview.<br /><span lang="bn">প্রতিটি ধাপে প্রোডাকশনের একই নিয়ম কাজ করে। একটি পূর্ণ প্রক্রিয়া শেষ করে Overview-তে তার প্রভাব দেখুন।</span></p></div>
        <span><HelpCircle /><b>Demo tip · ডেমো পরামর্শ</b><small>Start with Overview, then follow one complete journey.<br /><span lang="bn">Overview থেকে শুরু করে একটি সম্পূর্ণ প্রক্রিয়া অনুসরণ করুন।</span></small></span>
      </div>
      <div className="journey-tabs" role="tablist" aria-label="Business workflow guides">
        {journeys.map((journey, index) => {
          const Icon = journey.icon;
          return <button key={journey.title} role="tab" aria-selected={open === index} aria-controls={`journey-${index}`} onClick={() => setOpen(index)}><Icon /><span><b>{journey.title}<em lang="bn">{journey.titleBn}</em></b><small>{journey.summary}<span lang="bn">{journey.summaryBn}</span></small></span><ChevronRight /></button>;
        })}
      </div>
      {journeys.map((journey, index) => open === index && (
        <div key={journey.title} id={`journey-${index}`} role="tabpanel" className="journey-detail">
          <div className="journey-flow" role="list" aria-label={`${journey.title} workflow`}>
            {journey.steps.map((step, stepIndex) => <div role="listitem" key={step}><span>{stepIndex + 1}</span><b>{step}<small lang="bn">{journey.stepsBn[stepIndex]}</small></b>{stepIndex < journey.steps.length - 1 && <ChevronRight aria-hidden="true" />}</div>)}
          </div>
          <div className="journey-notes">
            <p><Sparkles /> Every money value remains exact; inventory changes only through its ledger; accounting and VAT post from the business event.<span lang="bn">প্রতিটি টাকার হিসাব নির্ভুল; মজুত শুধু লেজারের মাধ্যমে বদলায়; ব্যবসায়িক ঘটনা থেকেই হিসাব ও ভ্যাট পোস্ট হয়।</span></p>
            <Link href={journey.destination}>Open this workspace · এই অংশ খুলুন <ChevronRight /></Link>
          </div>
        </div>
      ))}
      <div className="guide-footer"><Bot /><span><b>Need an explanation? · ব্যাখ্যা প্রয়োজন?</b><small>Open the dedicated AI Copilot workspace. It reads only authorized data and never generates SQL.<span lang="bn">AI Copilot খুলুন—এটি শুধু অনুমোদিত তথ্য পড়ে এবং কখনো SQL তৈরি করে না।</span></small></span></div>
    </section>
  );
}
