import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Container images build a self-contained server (apps/web/Dockerfile sets NEXT_OUTPUT);
  // local dev and Windows builds keep the default output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false, // keep demo recordings from the dev server clean
};

export default nextConfig;
