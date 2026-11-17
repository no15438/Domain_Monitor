import type { NextConfig } from "next";

const backendOrigin =
  process.env.INTERNAL_API_BASE?.replace(/\/$/, "") ||
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/event-memory/:path*",
        destination: `${process.env.EVENT_MEMORY_API_BASE?.replace(/\/$/, "") || backendOrigin}/api/event-memory/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
