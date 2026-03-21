/**
 * lib/types.ts
 *
 * Shared TypeScript interfaces for the ingest pipeline.
 * These types cross the boundary between the Next.js API route and
 * the AWS services (Lambda, S3, DynamoDB).
 */

// ── Inbound request ────────────────────────────────────────────────────────

export interface IngestRequest {
  urls: string[]
}

// ── Pipeline types ─────────────────────────────────────────────────────────

/** A single article scraped by Firecrawl. */
export interface ScrapedArticle {
  url: string
  /** SHA-256("{url}|{title}".toLowerCase())[:16] — matches Lambda 1 schema. */
  url_hash: string
  title: string
  /** Clean markdown produced by Firecrawl v4. */
  markdown: string
  source_type: string
  scraped_at: string
}

/** One step of the 9-step pipeline execution trace. */
export interface StepResult {
  step: string
  status: "success" | "skipped" | "error"
  count?: number
  detail?: string
}

/** Final unified summary stored in S3 + DynamoDB. */
export interface UnifiedSummary {
  id: string
  content: string
  sources: string[]
  article_count: number
  s3_key: string
  created_at: string
}

// ── API response ───────────────────────────────────────────────────────────

export interface LogicPathResponse {
  success: boolean
  steps: StepResult[]
  output: {
    ingested_count: number
    duplicate_count: number
    failed_scrape_count: number
    summary: UnifiedSummary | null
  }
  meta: {
    duration_ms: number
    processed_at: string
  }
}
