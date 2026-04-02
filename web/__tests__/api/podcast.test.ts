/**
 * __tests__/api/podcast.test.ts
 *
 * Unit tests for GET /api/podcast
 *
 * The route does three things:
 *   1. Reads CLOUDFRONT_DOMAIN from env to build a feed_url
 *   2. Calls listEpisodes(50) from lib/dynamo
 *   3. Returns a JSON response — 200 on success, 500 on error
 *
 * listEpisodes is mocked at the module level so no real DynamoDB
 * connection is required.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { NextRequest } from "next/server"

// ── Mock lib/dynamo before importing the route ──────────────────────────────
vi.mock("@/lib/dynamo", () => ({
  listEpisodes: vi.fn(),
}))

import { GET } from "@/app/api/podcast/route"
import { listEpisodes } from "@/lib/dynamo"

const mockListEpisodes = vi.mocked(listEpisodes)

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeRequest(): NextRequest {
  return new NextRequest("http://localhost/api/podcast")
}

const SAMPLE_EPISODES = [
  {
    episode_id: "ep-001",
    title: "Markets Rally",
    date: "2026-04-01",
    source: "Reuters",
    category: "finance",
    status: "processed",
    audio_url: "https://cdn.example.com/audio/ep-001.mp3",
    created_at: "2026-04-01T06:00:00Z",
  },
  {
    episode_id: "ep-002",
    title: "Tech Layoffs",
    date: "2026-04-01",
    source: "BBC",
    category: "technology",
    status: "distilled",
    audio_url: "https://cdn.example.com/audio/ep-002.mp3",
    created_at: "2026-04-01T18:00:00Z",
  },
]

// ── Tests ────────────────────────────────────────────────────────────────────

describe("GET /api/podcast", () => {
  const originalEnv = process.env

  beforeEach(() => {
    // Reset env and mock state before each test
    process.env = { ...originalEnv }
    vi.clearAllMocks()
  })

  afterEach(() => {
    process.env = originalEnv
  })

  // ── Success path ────────────────────────────────────────────────────────

  it("returns 200 with episodes and feed_url when CLOUDFRONT_DOMAIN is set", async () => {
    process.env.CLOUDFRONT_DOMAIN = "d1234.cloudfront.net"
    mockListEpisodes.mockResolvedValue(SAMPLE_EPISODES)

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(body.success).toBe(true)
    expect(body.feed_url).toBe("https://d1234.cloudfront.net/rss/feed.xml")
    expect(body.episodes).toEqual(SAMPLE_EPISODES)
  })

  it("calls listEpisodes with limit 50", async () => {
    process.env.CLOUDFRONT_DOMAIN = "d1234.cloudfront.net"
    mockListEpisodes.mockResolvedValue([])

    await GET(makeRequest())

    expect(mockListEpisodes).toHaveBeenCalledOnce()
    expect(mockListEpisodes).toHaveBeenCalledWith(50)
  })

  it("returns feed_url as null when CLOUDFRONT_DOMAIN is not set", async () => {
    delete process.env.CLOUDFRONT_DOMAIN
    mockListEpisodes.mockResolvedValue([])

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(body.feed_url).toBeNull()
    expect(body.success).toBe(true)
  })

  it("returns feed_url as null when CLOUDFRONT_DOMAIN is empty string", async () => {
    process.env.CLOUDFRONT_DOMAIN = ""
    mockListEpisodes.mockResolvedValue([])

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(body.feed_url).toBeNull()
  })

  it("returns empty episodes array when table is empty", async () => {
    process.env.CLOUDFRONT_DOMAIN = "d1234.cloudfront.net"
    mockListEpisodes.mockResolvedValue([])

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(body.episodes).toEqual([])
  })

  // ── feed_url construction ────────────────────────────────────────────────

  it("builds the feed_url by appending /rss/feed.xml to the domain", async () => {
    process.env.CLOUDFRONT_DOMAIN = "abc123xyz.cloudfront.net"
    mockListEpisodes.mockResolvedValue([])

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(body.feed_url).toBe("https://abc123xyz.cloudfront.net/rss/feed.xml")
  })

  // ── Error handling ───────────────────────────────────────────────────────

  it("returns 500 with success:false when listEpisodes throws", async () => {
    process.env.CLOUDFRONT_DOMAIN = "d1234.cloudfront.net"
    mockListEpisodes.mockRejectedValue(new Error("DynamoDB connection timeout"))

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(500)
    expect(body.success).toBe(false)
    expect(body.episodes).toEqual([])
    expect(body.error).toContain("DynamoDB connection timeout")
  })

  it("still includes feed_url in 500 error response", async () => {
    process.env.CLOUDFRONT_DOMAIN = "d1234.cloudfront.net"
    mockListEpisodes.mockRejectedValue(new Error("network error"))

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(500)
    expect(body.feed_url).toBe("https://d1234.cloudfront.net/rss/feed.xml")
  })

  it("returns feed_url:null in 500 response when CLOUDFRONT_DOMAIN is not set", async () => {
    delete process.env.CLOUDFRONT_DOMAIN
    mockListEpisodes.mockRejectedValue(new Error("DYNAMODB_TABLE_NAME env var is not set"))

    const res = await GET(makeRequest())
    const body = await res.json()

    expect(res.status).toBe(500)
    expect(body.feed_url).toBeNull()
    expect(body.success).toBe(false)
  })
})
