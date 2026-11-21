import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep production builds from replacing chunks used by an active dev server.
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",
  // This is Next.js development chrome (the floating N/Dev Tools button), not app UI.
  devIndicators: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};
nextConfig.outputFileTracingRoot = process.cwd();

export default nextConfig;
