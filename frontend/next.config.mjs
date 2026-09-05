/** @type {import('next').NextConfig} */
const apiInternalBaseUrl = process.env.RECLAIM_API_INTERNAL_BASE_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/tenants/:path*",
        destination: `${apiInternalBaseUrl}/tenants/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${apiInternalBaseUrl}/health/:path*`,
      },
      {
        source: "/help/:path*",
        destination: `${apiInternalBaseUrl}/help/:path*`,
      },
    ];
  },
};

export default nextConfig;
