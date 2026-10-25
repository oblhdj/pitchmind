import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { fontVariables } from "@/lib/fonts";

import "../globals.css";

export const metadata: Metadata = {
  title: { default: "PitchMind", template: "%s · PitchMind" },
  description: "Live match intelligence: why it matters, explained for every fan, with the evidence.",
};

export const viewport: Viewport = {
  themeColor: "#04070d",
  colorScheme: "dark",
};

export default function FanLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={fontVariables}>
      <body className="fan-backdrop min-h-dvh font-sans text-slate-100 antialiased">{children}</body>
    </html>
  );
}
