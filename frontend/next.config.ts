import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  typedRoutes: true,
  turbopack: { root: process.cwd() },
};

export default nextConfig;
