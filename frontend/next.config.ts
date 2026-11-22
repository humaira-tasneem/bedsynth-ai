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
  async rewrites() {
    const isProduction = process.env.NODE_ENV === "production";
    const backendApiUrl = process.env.BACKEND_API_URL?.replace(/\/$/, "")
      || (isProduction ? "" : "http://127.0.0.1:8000");

    if (!backendApiUrl) {
      throw new Error("BACKEND_API_URL must be set for production builds and deployments.");
    }

    let backendOrigin: URL;
    try {
      backendOrigin = new URL(backendApiUrl);
    } catch {
      throw new Error("BACKEND_API_URL must be a valid backend origin.");
    }
    if (!backendOrigin.hostname || backendOrigin.username || backendOrigin.password
      || backendOrigin.pathname !== "/" || backendOrigin.search || backendOrigin.hash
      || (isProduction && backendOrigin.protocol !== "https:")) {
      throw new Error("BACKEND_API_URL must be an origin only; production origins must use HTTPS.");
    }

    return [
      { source: "/api/:path*", destination: `${backendApiUrl}/api/:path*` },
      { source: "/health", destination: `${backendApiUrl}/health` },
    ];
  },
};
nextConfig.outputFileTracingRoot = process.cwd();

export default nextConfig;
