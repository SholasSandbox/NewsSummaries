/**
 * POST /api/ingest
 *
 * Scraping and distillation pipeline for 5–10 news article URLs.
 *
 * Pipeline (Logic Path):
 *   1. parse_urls    – validate input (5–10 URLs required)
 *   2. scrape        – Firecrawl extracts clean markdown from each URL in parallel
 *   3. deduplicate   – check news_vectors table; skip already-seen stories
 *   4. distill       – single Claude Sonnet call → Unified Market Intelligence summary
 *   5. embed         – OpenAI text-embedding-3-small for articles + summary
 *   6. store         – save articles and summary to Supabase
 *
 * Response envelope: LogicPathResponse (see lib/types.ts)
 *   Each step appends a StepResult so the caller can trace execution end-to-end.
 *
 * @see docs/ARCHITECTURE.md for the full system diagram
 */

import { type NextRequest, NextResponse } from "next/server"
import { scrapeUrls, hashUrl } from "@/lib/scraper"
import { fetchExistingHashes, insertArticles, insertUnifiedSummary } from "@/lib/supabase"
import { distillArticles } from "@/lib/distiller"
import { generateEmbedding, generateEmbeddingsBatch } from "@/lib/embeddings"
import type {
  IngestRequest,
  LogicPathResponse,
  StepResult,
  UnifiedSummary,
} from "@/lib/types"

// ── Edge Runtime ───────────────────────────────────────────────────────────
// Runs on V8 isolates at CDN edge – no Node.js APIs, sub-30 s timeout.
export const runtime = "edge"

// ── Validation ─────────────────────────────────────────────────────────────

const MIN_URLS = 1   // relaxed minimum for testing; set to 5 for production
const MAX_URLS = 10

function isValidUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === "https:" || parsed.protocol === "http:"
  } catch {
    return false
  }
}

// ── Handler ────────────────────────────────────────────────────────────────

export async function POST(req: NextRequest): Promise<NextResponse> {
  const startedAt = Date.now()
  const processedAt = new Date().toISOString()
  const steps: StepResult[] = []

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

  // ── 2. Scrape with Firecrawl ─────────────────────────────────────────────
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

  // ── 3. Deduplicate against news_vectors ──────────────────────────────────
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
    return buildResponse(
      true,
      [
        ...steps,
        { step: "distill", status: "skipped", detail: "All articles already processed" },
        { step: "embed", status: "skipped" },
        { step: "store", status: "skipped" },
      ],
      {
        ingested_count: 0,
        duplicate_count: duplicateCount,
        failed_scrape_count: scrapeResult.failedCount,
        summary: null,
      },
      startedAt,
      processedAt,
    )
  }

  // ── 4. Distill with Claude (single call for all articles) ────────────────
  let summaryText: string
  try {
    summaryText = await distillArticles(newArticles)
    steps.push({
      step: "distill",
      status: "success",
      count: newArticles.length,
      detail: `${summaryText.length} chars generated`,
    })
  } catch (err) {
    steps.push({ step: "distill", status: "error", detail: String(err) })
    return errorResponse("Distillation failed", 502, steps, startedAt, processedAt)
  }

  // ── 5. Generate embeddings (articles + summary) ──────────────────────────
  let articleEmbeddings = new Map<string, number[]>()
  let summaryEmbedding: number[] | null = null

  try {
    const [articleEmbMap, summEmb] = await Promise.all([
      generateEmbeddingsBatch(
        newArticles.map((a) => ({
          key: a.url_hash,
          text: `${a.title}\n\n${a.markdown}`,
        }))
      ),
      generateEmbedding(summaryText),
    ])
    articleEmbeddings = articleEmbMap
    summaryEmbedding = summEmb
    steps.push({
      step: "embed",
      status: "success",
      count: articleEmbeddings.size + 1,
      detail: `${articleEmbeddings.size} article embedding(s) + 1 summary embedding`,
    })
  } catch (err) {
    // Non-fatal: store without embeddings
    steps.push({
      step: "embed",
      status: "error",
      detail: `Embedding generation failed (${String(err)}); storing without vectors`,
    })
  }

  // ── 6. Store to Supabase ─────────────────────────────────────────────────
  let savedSummary: UnifiedSummary | null = null

  try {
    const [_, summaryRow] = await Promise.all([
      insertArticles(newArticles, articleEmbeddings),
      insertUnifiedSummary(
        summaryText,
        newArticles.map((a) => a.url),
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
  return buildResponse(
    true,
    steps,
    {
      ingested_count: newArticles.length,
      duplicate_count: duplicateCount,
      failed_scrape_count: scrapeResult.failedCount,
      summary: savedSummary,
    },
    startedAt,
    processedAt,
  )
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
    meta: {
      duration_ms: Date.now() - startedAt,
      processed_at: processedAt,
    },
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
    steps,
    { ingested_count: 0, duplicate_count: 0, failed_scrape_count: 0, summary: null },
    startedAt,
    processedAt,
    status,
  )
}
