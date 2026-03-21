import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // The web/ sub-directory runs as a self-contained Next.js 16 application.
  // AWS SDK v3 requires the Node.js runtime (not Edge) for Lambda + S3 + DynamoDB calls.
  experimental: {},
}

export default nextConfig
