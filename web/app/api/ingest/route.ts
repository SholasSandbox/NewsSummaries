/**
 * POST /api/ingest
 *
 * Scraping and distillation pipeline for 5–10 news article URLs.
 * Leverages the existing Python Lambda functions for per-article summarization.
 *
 * Pipeline (Logic Path):
 *   1. parse_urls    – validate input (1–10 URLs accepted)
 *   2. scrape        – Firecrawl extracts clean markdown from each URL in parallel
 *                      (concurrent Promise.allSettled; cookie walls bypassed)
 *   3. deduplicate   – check Supabase news_vectors; skip already-ingested stories
 *   4. store_raw     – upload new articles to S3 (raw/{date}/{hash}.json) in the
 *                      format expected by Lambda 2 (generate_summaries)
 *   5. summarize     – invoke Lambda 2 (generate_summaries) synchronously per article;
 *                      Lambda 2 calls OpenAI o3-mini, writes structured summary to S3
 *                      (summaries/{date}/{hash}.json) and DynamoDB
 *   6. read_summaries – read Lambda 2's output from S3 to get clean per-article summaries
 *   7. distill       – single Claude Sonnet call synthesises all per-article summaries
 *                      into a "Unified Market Intelligence" briefing (new capability –
 *                      Lambda 2 does one-by-one; this cross-article synthesis is new)
 *   8. embed         – OpenAI text-embedding-3-small for the unified summary
 *   9. store         – save unified summary + article tracking to Supabase
 *
 * Runtime: Node.js (not Edge) – required for AWS SDK v3 (Lambda + S3 clients).
 * The scraping loop in step 2 remains fully concurrent via Promise.allSettled.
 *
 * Response envelope: LogicPathResponse (see lib/types.ts)
 */

import { type NextRequest, NextResponse } from "next/server"
import { scrapeUrls } from "@/lib/scraper"
import {
  fetchExistingHashes,
  insertArticles,
  insertUnifiedSummary,
} from "@/lib/supabase"
import { distillArticles } from "@/lib/distiller"
import { generateEmbedding } from "@/lib/embeddings"
import {
  uploadRawArticle,
  invokeSummarizeLambda,
  readSummaryFromS3,
  type LambdaSummaryDoc,
} from "@/lib/aws-lambda"
import type {
  IngestRequest,
  LogicPathResponse,
  ScrapedArticle,
  StepResult,
  UnifiedSummary,
} from "@/lib/types"

// ── Validation ─────────────────────────────────────────────────────────────

const MIN_URLS = 1   // relaxed for testing; tighten to 5 for production
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
  const startedAt = Date.now()
  const processedAt = new Date().toISOString()
  const steps: StepResult[] = []

  const bucket = process.env.S3_BUCKET_NAME
  if (!bucket) {
    return errorResponse("Missing S3_BUCKET_NAME env var", 500, steps, startedAt, processedAt)
  }
  const runDate = new Date().toISOString().slice(0, 10) // YYYY-MM-DD

  // ── 1. Parse & validate URLs ─────────────────────────────────────────────
  let body: IngestRequest
  try {
    body = (await req.json()) as IngestRequest
  } catch {
    return errorResponse("Request body must be valid JSON", 400, steps, startedAt, processedAt)
  }

  const rawUrls: string[] = body?.urls ?? []
  const validUrls = rawUrls.filter(isValidUrl)

  if (validUrls.length < MIN_URLS) {
    return errorResponse(
      `At least ${MIN_URLS} valid URL(s) required; received ${validUrls.length}`,
      400, steps, startedAt, processedAt,
    )
  }

  const urls = validUrls.slice(0, MAX_URLS)
  steps.push({ step: "parse_urls", status: "success", count: urls.length })

  // ── 2. Scrape with Firecrawl (concurrent) ────────────────────────────────
  // Promise.allSettled ensures a failing URL doesn't block the rest.
  let scrapeResult: Awaited<ReturnType<typeof scrapeUrls>>
  try {
    scrapeResult = await scrapeUrls(urls)
    steps.push({
      step: "scrape",
      status: scrapeResult.articles.length > 0 ? "success" : "error",
      count: scrapeResult.articles.length,
      detail: scrapeResult.failedCount > 0
        ? `${scrapeResult.failedCount} URL(s) failed to scrape`
        : undefined,
    })
  } catch (err) {
    steps.push({ step: "scrape", status: "error", detail: String(err) })
    return errorResponse("Scraping failed", 502, steps, startedAt, processedAt)
  }

  if (scrapeResult.articles.length === 0) {
    return errorResponse("No articles could be scraped", 422, steps, startedAt, processedAt)
  }

  // ── 3. Deduplicate against Supabase news_vectors ─────────────────────────
  // URL hashes are checked first so we avoid uploading and re-summarising
  // stories that have already passed through this pipeline.
  let newArticles = scrapeResult.articles
  let duplicateCount = 0

  try {
    const allHashes = scrapeResult.articles.map((a) => a.url_hash)
    const existingHashes = await fetchExistingHashes(allHashes)
    newArticles = scrapeResult.articles.filter((a) => !existingHashes.has(a.url_hash))
    duplicateCount = scrapeResult.articles.length - newArticles.length

    steps.push({
      step: "deduplicate",
      status: "success",
      count: newArticles.length,
      detail: duplicateCount > 0 ? `${duplicateCount} duplicate(s) skipped` : undefined,
    })
  } catch (err) {
    // Non-fatal: log and continue with all scraped articles
    steps.push({
      step: "deduplicate",
      status: "error",
      detail: `Dedup check failed (${String(err)}); processing all ${scrapeResult.articles.length} article(s)`,
    })
  }

  if (newArticles.length === 0) {
    return buildResponse(true, [
      ...steps,
      { step: "store_raw",      status: "skipped", detail: "All articles already processed" },
      { step: "summarize",      status: "skipped" },
      { step: "read_summaries", status: "skipped" },
      { step: "distill",        status: "skipped" },
      { step: "embed",          status: "skipped" },
      { step: "store",          status: "skipped" },
    ], {
      ingested_count: 0,
      duplicate_count: duplicateCount,
      failed_scrape_count: scrapeResult.failedCount,
      summary: null,
    }, startedAt, processedAt)
  }

  // ── 4. Upload raw articles to S3 (Lambda 2-compatible format) ────────────
  // Key: raw/{YYYY-MM-DD}/{article_hash}.json
  // Lambda 2 reads from this exact location when invoked in step 5.
  const rawS3Keys: Array<{ article: ScrapedArticle; s3Key: string }> = []
  let storeRawFailed = 0

  await Promise.allSettled(
    newArticles.map(async (article) => {
      try {
        const s3Key = await uploadRawArticle(article, bucket, runDate)
        rawS3Keys.push({ article, s3Key })
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
    return errorResponse("All S3 uploads failed", 502, steps, startedAt, processedAt)
  }

  // ── 5. Invoke Lambda 2 (generate_summaries) synchronously ────────────────
  // Lambda 2 calls OpenAI o3-mini, writes the structured summary JSON to S3
  // (summaries/{date}/{hash}.json) and a DynamoDB episode record with
  // status="summarized" (which triggers Lambda 3 via DynamoDB Streams).
  let lambdaProcessed = 0
  let lambdaFailed = 0
  let lambdaSkipped = 0

  await Promise.allSettled(
    rawS3Keys.map(async ({ s3Key }) => {
      try {
        const result = await invokeSummarizeLambda(bucket, s3Key)
        lambdaProcessed += result.processed
        lambdaFailed    += result.failed
        lambdaSkipped   += result.skipped
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
      lambdaSkipped > 0 ? `${lambdaSkipped} skipped (already summarised)` : null,
      lambdaFailed  > 0 ? `${lambdaFailed} failed` : null,
    ]
      .filter(Boolean)
      .join("; ") || undefined,
  })

  // ── 6. Read Lambda 2's structured summaries from S3 ──────────────────────
  // Lambda 2 writes clean 2–3 sentence summaries with category/importance/keywords.
  // Feeding these into Claude (step 7) produces a tighter unified briefing than
  // feeding raw markdown.
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
    return errorResponse(
      "No summaries available for distillation",
      422, steps, startedAt, processedAt,
    )
  }

  // ── 7. Distil with Claude (single call across all article summaries) ──────
  // Lambda 2 summarises articles one-by-one. Claude's single cross-article call
  // is the NEW capability: it synthesises all summaries into a unified briefing
  // that surfaces patterns, contradictions, and actionable signals across sources.
  let summaryText: string
  try {
    summaryText = await distillArticles(
      lambdaSummaries.map<ScrapedArticle>((doc) => ({
        url: doc.url,
        url_hash: doc.article_hash,
        title: doc.title,
        // Feed the structured Lambda 2 summary rather than raw markdown
        markdown: `**Summary (${doc.importance} importance, ${doc.category})**: ${doc.summary}\n\nKeywords: ${doc.keywords.join(", ")}`,
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
    return errorResponse("Distillation failed", 502, steps, startedAt, processedAt)
  }

  // ── 8. Embed unified summary ──────────────────────────────────────────────
  let summaryEmbedding: number[] | null = null
  try {
    summaryEmbedding = await generateEmbedding(summaryText)
    steps.push({ step: "embed", status: "success", count: 1 })
  } catch (err) {
    steps.push({
      step: "embed",
      status: "error",
      detail: `Embedding failed (${String(err)}); storing without vector`,
    })
  }

  // ── 9. Store to Supabase ──────────────────────────────────────────────────
  // news_vectors: track ingested URLs for future deduplication (minimal fields)
  // unified_summaries: full distilled output + embedding
  let savedSummary: UnifiedSummary | null = null

  try {
    const [_, summaryRow] = await Promise.all([
      insertArticles(newArticles, new Map()),   // track URLs; no per-article embeddings
      insertUnifiedSummary(
        summaryText,
        lambdaSummaries.map((d) => d.url),
        summaryEmbedding,
      ),
    ])

    savedSummary = {
      id: summaryRow.id,
      content: summaryRow.summary,
      sources: summaryRow.source_urls,
      article_count: summaryRow.article_count,
      created_at: summaryRow.created_at,
    }

    steps.push({
      step: "store",
      status: "success",
      count: newArticles.length,
      detail: `Summary ID: ${summaryRow.id}`,
    })
  } catch (err) {
    steps.push({ step: "store", status: "error", detail: String(err) })
    return errorResponse("Storage failed", 502, steps, startedAt, processedAt)
  }

  // ── Return Logic Path response ───────────────────────────────────────────
  return buildResponse(true, steps, {
    ingested_count: newArticles.length,
    duplicate_count: duplicateCount,
    failed_scrape_count: scrapeResult.failedCount,
    summary: savedSummary,
  }, startedAt, processedAt)
}

// ── Response builders ──────────────────────────────────────────────────────

function buildResponse(
  success: boolean,
  steps: StepResult[],
  output: LogicPathResponse["output"],
  startedAt: number,
  processedAt: string,
  status = 200,
): NextResponse {
  const body: LogicPathResponse = {
    success,
    steps,
    output,
    meta: { duration_ms: Date.now() - startedAt, processed_at: processedAt },
  }
  return NextResponse.json(body, { status })
}

function errorResponse(
  detail: string,
  status: number,
  steps: StepResult[],
  startedAt: number,
  processedAt: string,
): NextResponse {
  return buildResponse(
    false,
    [...steps, { step: "error", status: "error", detail }],
    { ingested_count: 0, duplicate_count: 0, failed_scrape_count: 0, summary: null },
    startedAt,
    processedAt,
    status,
  )
}

