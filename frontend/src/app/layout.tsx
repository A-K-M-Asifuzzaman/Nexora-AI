import type { Metadata } from "next";
import { Instrument_Sans, Manrope } from "next/font/google";

import "./styles.css";
import "./auth-extras.css";
import "./chart-bars.css";

const body = Instrument_Sans({ subsets: ["latin"], variable: "--font-body" });
const display = Manrope({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Nexora AI — Business clarity",
  description: "A focused operating system for growing businesses.",
};

// A nonce is generated per request by proxy.ts, so pages must render in the
// presence of a request rather than being emitted once with a stale nonce.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${body.variable} ${display.variable}`}>{children}</body>
    </html>
  );
}
