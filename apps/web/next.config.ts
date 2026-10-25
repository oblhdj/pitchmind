import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false, // keep demo recordings from the dev server clean
};

export default nextConfig;
