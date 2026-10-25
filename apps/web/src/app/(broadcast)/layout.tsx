import type { Metadata } from "next";
import type { ReactNode } from "react";

import { fontVariables } from "@/lib/fonts";

import "../globals.css";

export const metadata: Metadata = {
  title: "PitchMind overlay",
  description: "Transparent broadcast graphics for a browser source (OBS, vMix).",
};

/** Its own root layout: the page must stay transparent over the video. */
export default function BroadcastLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={fontVariables} style={{ background: "transparent" }}>
      <body className="overflow-hidden font-sans antialiased" style={{ background: "transparent" }}>
        {children}
      </body>
    </html>
  );
}
