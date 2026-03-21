/**
 * POST /api/ingest
 *
 * Scraping and distillation pipeline for 5–10 news article URLs.
 * Strictly AWS-native — no Supabase. All state in DynamoDB and S3.
 *
 * Logic Path: Firecrawl scrapes clean markdown → DynamoDB deduplication
 * against the existing episodes table (episode_id = article_hash, matching
 * Lambda 1's schema) → Lambda 2 (generate_summaries) invoked synchronously
 * per article → single Claude Sonnet 4.5 call distils all per-article
 * summaries into one Unified Market Intelligence briefing → stored in S3
 * (unified/{date}/{id}.json) with metadata written back to DynamoDB.
 *
 * Pipeline steps (Logic Path format):
 *   1. parse_urls     – validate 1–10 URLs
 *   2. scrape         – Firecrawl v4, concurrent Promise.allSettled
 *   3. deduplicate    – DynamoDB BatchGetItem on episode_id = article_hash
 *   4. store_raw      – S3 raw/{date}/{hash}.json (Lambda 2-compatible)
 *   5. summarize      – Lambda 2 synchronous invocation (OpenAI o3-mini)
 *   6. read_summaries – S3 summaries/{date}/{hash}.json (Lambda 2 output)
 *   7. distill        – Claude Sonnet 4.5 cross-article unified briefing
 *   8. embed          – OpenAI text-embedding-3-small on unified summary
 *   9. store          – S3 unified/{date}/{id}.json + DynamoDB metadata
 *
 * Runtime: Node.js (AWS SDK v3 requires Node.js built-ins).
 */

import { type NextRequest, NextResponse } from "next/server"
import { scrapeUrls } from "@/lib/scraper"
import { fetchExistingHashes, writeUnifiedSummaryToDynamo } from "@/lib/dynamo"
import { distillArticles } from "@/lib/distiller"
import { generateEmbedding } from "@/lib/embeddings"
import {
  uploadRawArticle,
  invokeSummarizeLambda,
  readSummaryFromS3,
  writeUnifiedSummaryToS3,
  type LambdaSummaryDoc,
} from "@/lib/aws-lambda"
import type {
  IngestRequest,
  LogicPathResponse,
  ScrapedArticle,
  StepResult,
  UnifiedSummary,
} from "@/lib/types"
import { randomUUID } from "crypto"

// ── Validation ─────────────────────────────────────────────────────────────

const MIN_URLS = 1   // relax to 5 for production
const MAX_URLS = 10

function isValidUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url)
    return protocol === "https:" || protocol === "http:"
  } catch {
    return false
  }
}

// ── Handler ────────────────────────────────────────────────────────────────

export async function POST(req: NextRequest): Promise<NextResponse> {
  const startedAt   = Date.now()
  const processedAt = new Date().toISOString()
  const runDate     = processedAt.slice(0, 10)   // YYYY-MM-DD
  const steps: StepResult[] = []

  const bucket = process.env.S3_BUCKET_NAME
  if (!bucket) {
    return errResp("Missing S3_BUCKET_NAME env var", 500, steps, startedAt, processedAt)
  }

  // ── 1. Parse & validate URLs ─────────────────────────────────────────────
  let body: IngestRequest
  try {
    body = (await req.json()) as IngestRequest
  } catch {
    return errResp("Request body must be valid JSON", 400, steps, startedAt, processedAt)
  }

  const urls = (body?.urls ?? []).filter(isValidUrl).slice(0, MAX_URLS)
  if (urls.length < MIN_URLS) {
    return errResp(
      `At least ${MIN_URLS} valid URL(s) required; received ${urls.length}`,
      400, steps, startedAt, processedAt,
    )
  }
  steps.push({ step: "parse_urls", status: "success", count: urls.length })

  // ── 2. Scrape with Firecrawl (concurrent) ────────────────────────────────
  let scrapeResult: Awaited<ReturnType<typeof scrapeUrls>>
  try {
    scrapeResult = await scrapeUrls(urls)
    steps.push({
      step: "scrape",
      status: scrapeResult.articles.length > 0 ? "success" : "error",
      count: scrapeResult.articles.length,
      detail: scrapeResult.failedCount > 0
        ? `${scrapeResult.failedCount} URL(s) failed to scrape` : undefined,
    })
  } catch (err) {
    steps.push({ step: "scrape", status: "error", detail: String(err) })
    return errResp("Scraping failed", 502, steps, startedAt, processedAt)
  }

  if (scrapeResult.articles.length === 0) {
    return errResp("No articles could be scraped", 422, steps, startedAt, processedAt)
  }

  // ── 3. Deduplicate via DynamoDB (episodes table, episode_id = article_hash)
  let newArticles = scrapeResult.articles
  let duplicateCount = 0

  try {
    const allHashes     = scrapeResult.articles.map((a) => a.url_hash)
    const existingHashes = await fetchExistingHashes(allHashes, runDate)
    newArticles    = scrapeResult.articles.filter((a) => !existingHashes.has(a.url_hash))
    duplicateCount = scrapeResult.articles.length - newArticles.length

    steps.push({
      step: "deduplicate",
      status: "success",
      count: newArticles.length,
      detail: duplicateCount > 0 ? `${duplicateCount} duplicate(s) skipped` : undefined,
    })
  } catch (err) {
    // Non-fatal: continue with all articles
    steps.push({
      step: "deduplicate",
      status: "error",
      detail: `DynamoDB dedup failed (${String(err)}); processing all ${scrapeResult.articles.length}`,
    })
  }

  if (newArticles.length === 0) {
    return buildResp(true, [
      ...steps,
      { step: "store_raw",      status: "skipped", detail: "All articles already processed" },
      { step: "summarize",      status: "skipped" },
      { step: "read_summaries", status: "skipped" },
      { step: "distill",        status: "skipped" },
      { step: "embed",          status: "skipped" },
      { step: "store",          status: "skipped" },
    ], { ingested_count: 0, duplicate_count: duplicateCount, failed_scrape_count: scrapeResult.failedCount, summary: null },
    startedAt, processedAt)
  }

  // ── 4. Upload raw articles to S3 (Lambda 2-compatible format) ────────────
  const rawS3Keys: Array<{ article: ScrapedArticle; s3Key: string }> = []
  let storeRawFailed = 0

  await Promise.allSettled(
    newArticles.map(async (article) => {
      try {
        rawS3Keys.push({ article, s3Key: await uploadRawArticle(article, bucket, runDate) })
      } catch {
        storeRawFailed++
      }
    }),
  )

  steps.push({
    step: "store_raw",
    status: rawS3Keys.length > 0 ? "success" : "error",
    count: rawS3Keys.length,
    detail: storeRawFailed > 0 ? `${storeRawFailed} upload(s) failed` : undefined,
  })

  if (rawS3Keys.length === 0) {
    return errResp("All S3 uploads failed", 502, steps, startedAt, processedAt)
  }

  // ── 5. Invoke Lambda 2 per article (synchronous) ──────────────────────────
  let lambdaProcessed = 0, lambdaFailed = 0, lambdaSkipped = 0

  await Promise.allSettled(
    rawS3Keys.map(async ({ s3Key }) => {
      try {
        const r = await invokeSummarizeLambda(bucket, s3Key)
        lambdaProcessed += r.processed
        lambdaFailed    += r.failed
        lambdaSkipped   += r.skipped
      } catch {
        lambdaFailed++
      }
    }),
  )

  steps.push({
    step: "summarize",
    status: lambdaProcessed > 0 || lambdaSkipped > 0 ? "success" : "error",
    count: lambdaProcessed,
    detail: [
      lambdaSkipped > 0 ? `${lambdaSkipped} already summarised` : null,
      lambdaFailed  > 0 ? `${lambdaFailed} failed` : null,
    ].filter(Boolean).join("; ") || undefined,
  })

  // ── 6. Read Lambda 2 structured output from S3 ────────────────────────────
  const lambdaSummaries: LambdaSummaryDoc[] = []

  await Promise.allSettled(
    rawS3Keys.map(async ({ s3Key }) => {
      const doc = await readSummaryFromS3(bucket, s3Key)
      if (doc) lambdaSummaries.push(doc)
    }),
  )

  steps.push({
    step: "read_summaries",
    status: lambdaSummaries.length > 0 ? "success" : "error",
    count: lambdaSummaries.length,
  })

  if (lambdaSummaries.length === 0) {
    return errResp("No summaries available for distillation", 422, steps, startedAt, processedAt)
  }

  // ── 7. Distil with Claude Sonnet 4.5 (single cross-article call) ──────────
  // Feed Lambda 2's structured per-article summaries (not raw markdown) so
  // Claude gets clean, categorised input and produces a tighter unified briefing.
  let summaryText: string
  try {
    summaryText = await distillArticles(
      lambdaSummaries.map<ScrapedArticle>((doc) => ({
        url: doc.url,
        url_hash: doc.article_hash,
        title: doc.title,
        markdown: `**Summary (${doc.importance}, ${doc.category})**: ${doc.summary}\n\nKeywords: ${doc.keywords.join(", ")}`,
        source_type: doc.source,
        scraped_at: doc.created_at,
      })),
    )
    steps.push({
      step: "distill",
      status: "success",
      count: lambdaSummaries.length,
      detail: `${summaryText.length} chars generated`,
    })
  } catch (err) {
    steps.push({ step: "distill", status: "error", detail: String(err) })
    return errResp("Distillation failed", 502, steps, startedAt, processedAt)
  }

  // ── 8. Generate embedding for unified summary ─────────────────────────────
  let embedding: number[] | null = null
  try {
    embedding = await generateEmbedding(summaryText)
    steps.push({ step: "embed", status: "success", count: 1 })
  } catch (err) {
    steps.push({
      step: "embed",
      status: "error",
      detail: `Embedding failed (${String(err)}); storing without vector`,
    })
  }

  // ── 9. Store to S3 (data lake) + DynamoDB (app state) ────────────────────
  let savedSummary: UnifiedSummary | null = null

  try {
    const summaryId  = randomUUID()
    const createdAt  = new Date().toISOString()
    const sourceUrls = lambdaSummaries.map((d) => d.url)

    const s3Key = await writeUnifiedSummaryToS3(bucket, {
      id: summaryId,
      date: runDate,
      summary: summaryText,
      source_urls: sourceUrls,
      article_count: lambdaSummaries.length,
      embedding,
      created_at: createdAt,
    })

    const ttl = Math.floor(Date.now() / 1000) + 90 * 24 * 3600  // 90-day TTL

    await writeUnifiedSummaryToDynamo({
      episode_id: `unified-${runDate}-${summaryId}`,
      date: runDate,
      title: `Unified Market Intelligence — ${runDate}`,
      source: "unified-distillation",
      category: "unified",
      status: "distilled",
      article_count: lambdaSummaries.length,
      source_urls: sourceUrls,
      s3_key: s3Key,
      created_at: createdAt,
      ttl,
    })

    savedSummary = {
      id: summaryId,
      content: summaryText,
      sources: sourceUrls,
      article_count: lambdaSummaries.length,
      s3_key: s3Key,
      created_at: createdAt,
    }

    steps.push({
      step: "store",
      status: "success",
      count: newArticles.length,
      detail: `S3: ${s3Key}`,
    })
  } catch (err) {
    steps.push({ step: "store", status: "error", detail: String(err) })
    return errResp("Storage failed", 502, steps, startedAt, processedAt)
  }

  return buildResp(true, steps, {
    ingested_count: newArticles.length,
    duplicate_count: duplicateCount,
    failed_scrape_count: scrapeResult.failedCount,
    summary: savedSummary,
  }, startedAt, processedAt)
}

// ── Response builders ──────────────────────────────────────────────────────

function buildResp(
  success: boolean,
  steps: StepResult[],
  output: LogicPathResponse["output"],
  startedAt: number,
  processedAt: string,
  status = 200,
): NextResponse {
  return NextResponse.json({
    success, steps, output,
    meta: { duration_ms: Date.now() - startedAt, processed_at: processedAt },
  } satisfies LogicPathResponse, { status })
}

function errResp(
  detail: string,
  status: number,
  steps: StepResult[],
  startedAt: number,
  processedAt: string,
): NextResponse {
  return buildResp(
    false,
    [...steps, { step: "error", status: "error", detail }],
    { ingested_count: 0, duplicate_count: 0, failed_scrape_count: 0, summary: null },
    startedAt, processedAt, status,
  )
}


