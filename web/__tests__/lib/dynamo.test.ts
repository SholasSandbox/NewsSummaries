/**
 * __tests__/lib/dynamo.test.ts
 *
 * Unit tests for lib/dynamo.ts — specifically the listEpisodes,
 * fetchExistingHashes, and writeUnifiedSummaryToDynamo functions
 * that back the /api/podcast and /api/ingest routes.
 *
 * The AWS SDK is mocked at the module level using vi.mock so no real
 * DynamoDB calls are ever made.
 *
 * Important: lib/dynamo.ts captures `process.env.DYNAMODB_TABLE_NAME`
 * into the module-level `TABLE` constant at load time. vitest.setup.ts
 * sets DYNAMODB_TABLE_NAME="test-episodes" before modules are loaded so
 * this constant is populated for the happy-path tests. For the "throws
 * when TABLE is not set" tests we use vi.resetModules() + dynamic import
 * to force a fresh module load with the env var absent.
 */

import { describe, it, expect, vi, beforeEach, afterAll } from "vitest"

// ── Hoist mock helpers so they are available inside vi.mock factories ────────
const { mockSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
}))

// ── Mock the entire AWS SDK before importing lib/dynamo ──────────────────────
vi.mock("@aws-sdk/client-dynamodb", () => ({
  // Must be a regular function (not arrow) so it can be used with `new`
  DynamoDBClient: vi.fn().mockImplementation(function () { return {} }),
}))

vi.mock("@aws-sdk/lib-dynamodb", () => ({
  DynamoDBDocumentClient: {
    from: vi.fn().mockReturnValue({ send: mockSend }),
  },
  // All three command classes are constructed with `new`, so they need
  // regular function implementations (arrow functions cannot be constructors).
  BatchGetCommand: vi.fn().mockImplementation(function (input: unknown) { return { input } }),
  PutCommand: vi.fn().mockImplementation(function (input: unknown) { return { input } }),
  ScanCommand: vi.fn().mockImplementation(function (input: unknown) { return { input } }),
}))

import { listEpisodes, fetchExistingHashes, writeUnifiedSummaryToDynamo } from "@/lib/dynamo"
import type { EpisodeRecord } from "@/lib/dynamo"

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeEpisode(overrides: Partial<EpisodeRecord> = {}): EpisodeRecord {
  return {
    episode_id: "ep-001",
    title: "Test Episode",
    date: "2026-04-01",
    source: "BBC",
    category: "technology",
    status: "processed",
    created_at: "2026-04-01T06:00:00Z",
    ...overrides,
  }
}

// ── listEpisodes ─────────────────────────────────────────────────────────────

describe("listEpisodes", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("returns empty array when table has no items", async () => {
    mockSend.mockResolvedValue({ Items: [] })

    const result = await listEpisodes()

    expect(result).toEqual([])
  })

  it("returns empty array when Items is undefined", async () => {
    mockSend.mockResolvedValue({})

    const result = await listEpisodes()

    expect(result).toEqual([])
  })

  it("returns episodes sorted newest-first by created_at", async () => {
    const older = makeEpisode({ episode_id: "old", created_at: "2026-03-01T06:00:00Z" })
    const newer = makeEpisode({ episode_id: "new", created_at: "2026-04-01T06:00:00Z" })
    mockSend.mockResolvedValue({ Items: [older, newer] })

    const result = await listEpisodes()

    expect(result[0].episode_id).toBe("new")
    expect(result[1].episode_id).toBe("old")
  })

  it("falls back to episode_id sort when created_at is missing", async () => {
    const a = makeEpisode({ episode_id: "ep-zzz", created_at: undefined })
    const b = makeEpisode({ episode_id: "ep-aaa", created_at: undefined })
    mockSend.mockResolvedValue({ Items: [a, b] })

    const result = await listEpisodes()

    // "ep-zzz" > "ep-aaa" lexicographically → zzz comes first (descending)
    expect(result[0].episode_id).toBe("ep-zzz")
    expect(result[1].episode_id).toBe("ep-aaa")
  })

  it("passes Limit capped at 100 regardless of input", async () => {
    mockSend.mockResolvedValue({ Items: [] })

    await listEpisodes(200)

    const callArg = mockSend.mock.calls[0][0]
    // ScanCommand was constructed with Limit: 100 (Math.min(200, 100))
    expect(callArg.input.Limit).toBe(100)
  })

  it("uses the provided limit when it is below 100", async () => {
    mockSend.mockResolvedValue({ Items: [] })

    await listEpisodes(10)

    const callArg = mockSend.mock.calls[0][0]
    expect(callArg.input.Limit).toBe(10)
  })

  it("returns all fields present on the raw DynamoDB item", async () => {
    const item: EpisodeRecord = makeEpisode({
      importance: "high",
      summary: "A summary.",
      audio_url: "https://cdn.example.com/audio/ep-001.mp3",
      summary_s3_key: "summaries/2026-04-01/ep-001.json",
      article_count: 5,
    })
    mockSend.mockResolvedValue({ Items: [item] })

    const [result] = await listEpisodes(1)

    expect(result.importance).toBe("high")
    expect(result.summary).toBe("A summary.")
    expect(result.audio_url).toBe("https://cdn.example.com/audio/ep-001.mp3")
    expect(result.article_count).toBe(5)
  })

  it("throws when DYNAMODB_TABLE_NAME is not set", async () => {
    // Requires a fresh module load with TABLE="" — use resetModules + dynamic import
    vi.resetModules()
    const saved = process.env.DYNAMODB_TABLE_NAME
    delete process.env.DYNAMODB_TABLE_NAME
    try {
      const { listEpisodes: freshFn } = await import("@/lib/dynamo")
      await expect(freshFn()).rejects.toThrow("DYNAMODB_TABLE_NAME env var is not set")
    } finally {
      process.env.DYNAMODB_TABLE_NAME = saved
      vi.resetModules()
    }
  })
})

// ── fetchExistingHashes ──────────────────────────────────────────────────────

describe("fetchExistingHashes", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterAll(() => {
    // Ensure module cache is clean after the reset-modules tests
    vi.resetModules()
  })

  it("returns empty Set when hashes array is empty (skips DynamoDB call)", async () => {
    const result = await fetchExistingHashes([], "2026-04-01")

    expect(result.size).toBe(0)
    expect(mockSend).not.toHaveBeenCalled()
  })

  it("returns hashes that exist in DynamoDB", async () => {
    mockSend.mockResolvedValue({
      Responses: {
        "test-episodes": [{ episode_id: "abc123" }, { episode_id: "def456" }],
      },
    })

    const result = await fetchExistingHashes(["abc123", "def456", "new999"], "2026-04-01")

    expect(result.has("abc123")).toBe(true)
    expect(result.has("def456")).toBe(true)
    expect(result.has("new999")).toBe(false)
  })

  it("returns empty Set when DynamoDB returns no Responses", async () => {
    mockSend.mockResolvedValue({})

    const result = await fetchExistingHashes(["abc123"], "2026-04-01")

    expect(result.size).toBe(0)
  })

  it("only sends first 100 hashes to DynamoDB (BatchGetItem hard limit)", async () => {
    mockSend.mockResolvedValue({ Responses: { "test-episodes": [] } })
    const hashes = Array.from({ length: 150 }, (_, i) => `hash-${i}`)

    await fetchExistingHashes(hashes, "2026-04-01")

    expect(mockSend).toHaveBeenCalledOnce()
    const callArg = mockSend.mock.calls[0][0]
    expect(callArg.input.RequestItems["test-episodes"].Keys).toHaveLength(100)
  })

  it("returns empty Set when DYNAMODB_TABLE_NAME is not set", async () => {
    vi.resetModules()
    const saved = process.env.DYNAMODB_TABLE_NAME
    delete process.env.DYNAMODB_TABLE_NAME
    try {
      const { fetchExistingHashes: freshFn } = await import("@/lib/dynamo")
      const result = await freshFn(["abc123"], "2026-04-01")
      expect(result.size).toBe(0)
    } finally {
      process.env.DYNAMODB_TABLE_NAME = saved
      vi.resetModules()
    }
  })
})

// ── writeUnifiedSummaryToDynamo ──────────────────────────────────────────────

describe("writeUnifiedSummaryToDynamo", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("calls DynamoDB PutCommand with the correct item", async () => {
    mockSend.mockResolvedValue({})
    const item = {
      episode_id: "unified-2026-04-01-abc",
      date: "2026-04-01",
      title: "Daily Briefing",
      source: "unified",
      category: "general",
      status: "ready",
      article_count: 10,
      source_urls: ["https://example.com/a"],
      s3_key: "summaries/2026-04-01/unified.json",
      created_at: "2026-04-01T06:00:00Z",
      ttl: 1745280000,
    }

    await writeUnifiedSummaryToDynamo(item)

    expect(mockSend).toHaveBeenCalledOnce()
    const callArg = mockSend.mock.calls[0][0]
    expect(callArg.input.TableName).toBe("test-episodes")
    expect(callArg.input.Item).toEqual(item)
  })

  it("throws when DYNAMODB_TABLE_NAME is not set", async () => {
    vi.resetModules()
    const saved = process.env.DYNAMODB_TABLE_NAME
    delete process.env.DYNAMODB_TABLE_NAME
    try {
      const { writeUnifiedSummaryToDynamo: freshFn } = await import("@/lib/dynamo")
      await expect(
        freshFn({
          episode_id: "x",
          date: "2026-04-01",
          title: "t",
          source: "s",
          category: "c",
          status: "ok",
          article_count: 1,
          source_urls: [],
          s3_key: "k",
          created_at: "2026-04-01T00:00:00Z",
          ttl: 0,
        }),
      ).rejects.toThrow("DYNAMODB_TABLE_NAME env var is not set")
    } finally {
      process.env.DYNAMODB_TABLE_NAME = saved
      vi.resetModules()
    }
  })
})

