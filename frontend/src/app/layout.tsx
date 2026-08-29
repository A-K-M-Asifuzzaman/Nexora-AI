import type { Metadata } from "next";
import { Instrument_Sans, Manrope } from "next/font/google";

import "./styles.css";
import "./auth-extras.css";

const body = Instrument_Sans({ subsets: ["latin"], variable: "--font-body" });
const display = Manrope({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Nexora AI — Business clarity",
  description: "A focused operating system for growing businesses.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${body.variable} ${display.variable}`}>{children}</body>
    </html>
  );
}
