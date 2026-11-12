import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep production builds from replacing chunks used by an active dev server.
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",
};
nextConfig.outputFileTracingRoot = process.cwd();

export default nextConfig;
