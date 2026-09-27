import type { NextConfig } from "next";

// Where the Next.js server forwards API calls. In the single-container deployment (deploy/Dockerfile)
// FastAPI runs next to Next.js on 127.0.0.1:8000, so the browser only ever talks to one origin.
const apiOrigin = process.env.INTERNAL_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/healthz", destination: `${apiOrigin}/healthz` },
    ];
  },
};

export default nextConfig;
