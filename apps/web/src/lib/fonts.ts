import { Barlow_Condensed, IBM_Plex_Sans_Arabic, Inter } from "next/font/google";

const inter = Inter({ subsets: ["latin"], variable: "--nf-inter", display: "swap" });
const barlow = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  variable: "--nf-barlow",
  display: "swap",
});
const arabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--nf-arabic",
  display: "swap",
});

export const fontVariables = `${inter.variable} ${barlow.variable} ${arabic.variable}`;
