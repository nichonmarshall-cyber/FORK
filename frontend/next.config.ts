import type { NextConfig } from "next";

// Account and notebook requests go to /api/fork/* on the frontend's own
// origin and are proxied to the backend. That keeps the sign-in cookie
// first-party: the browser only ever sees this site, so Safari's tracking
// prevention and third-party-cookie blocking never drop it.
//
// Uses the same backend URL the rest of the app already calls directly
// (NEXT_PUBLIC_API_BASE), so a deployment that works today needs no new
// setting. FORK_API_ORIGIN overrides it when the server should reach the
// backend at a different address than browsers do.
const backend = (
  process.env.FORK_API_ORIGIN ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000"
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/fork/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
