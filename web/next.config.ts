import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Treat the web/ sub-directory as the project root.
  // The app runs as a self-contained Next.js application.
  experimental: {
    // Edge Runtime functions may call external APIs (Firecrawl, Anthropic, Supabase, OpenAI).
    // Allow all origins; tighten per-route if needed.
  },
}

export default nextConfig
