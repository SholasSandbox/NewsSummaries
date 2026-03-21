/**
 * lib/aws-lambda.ts
 *
 * AWS SDK v3 helpers: S3 raw upload, Lambda 2 (generate_summaries) invocation,
 * S3 summary read-back, and unified S3 write.
 *
 * Logic Path: The web app mirrors what Lambda 1 does when uploading raw
 * articles (same key pattern: raw/{date}/{hash}.json). It then invokes
 * Lambda 2 synchronously (RequestResponse) exactly as if Lambda 1 had
 * triggered it, keeping the AI processing logic in Python/Lambda where it
 * belongs.
 */

import { S3Client, PutObjectCommand, GetObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3"
import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda"
import type { ScrapedArticle } from "./types"

const region = process.env.AWS_REGION ?? "us-east-1"

const s3     = new S3Client({ region })
const lambda = new LambdaClient({ region })

// ── Types ──────────────────────────────────────────────────────────────────

/** Structured summary document produced by Lambda 2 and stored in S3. */
export interface LambdaSummaryDoc {
  episode_id: string
  date: string
  created_at: string
  title: string
  source: string
  url: string
  article_hash: string
  raw_s3_key: string
  summary_s3_key: string
  summary: string
  category: string
  importance: string
  keywords: string[]
}

interface UnifiedS3Payload {
  id: string
  date: string
  summary: string
  source_urls: string[]
  article_count: number
  embedding: number[] | null
  created_at: string
}

// ── S3 helpers ─────────────────────────────────────────────────────────────

/**
 * Upload a scraped article to S3 in Lambda 2-compatible format.
 * Key: raw/{date}/{url_hash}.json
 */
export async function uploadRawArticle(
  article: ScrapedArticle,
  bucket: string,
  runDate: string,
): Promise<string> {
  const s3Key = `raw/${runDate}/${article.url_hash}.json`

  const body = JSON.stringify({
    url:          article.url,
    title:        article.title,
    source:       article.source_type,
    article_hash: article.url_hash,
    raw_summary:  article.markdown,
    ingested_at:  article.scraped_at,
    run_date:     runDate,
  })

  await s3.send(
    new PutObjectCommand({
      Bucket:      bucket,
      Key:         s3Key,
      Body:        body,
      ContentType: "application/json",
    }),
  )

  return s3Key
}

/**
 * Read the Lambda 2 summary JSON from S3.
 * Key: summaries/{date}/{hash}.json  (Lambda 2 derives this from the raw key)
 * Returns null if the object does not yet exist.
 */
export async function readSummaryFromS3(
  bucket: string,
  rawS3Key: string,
): Promise<LambdaSummaryDoc | null> {
  const summaryKey = rawS3Key.replace("raw/", "summaries/")

  // Check existence before reading to avoid an exception
  try {
    await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: summaryKey }))
  } catch {
    return null
  }

  try {
    const res  = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: summaryKey }))
    const body = await res.Body?.transformToString("utf-8")
    if (!body) return null
    return JSON.parse(body) as LambdaSummaryDoc
  } catch {
    return null
  }
}

/**
 * Write the unified (cross-article) summary to S3.
 * Key: unified/{date}/{id}.json
 */
export async function writeUnifiedSummaryToS3(
  bucket: string,
  payload: UnifiedS3Payload,
): Promise<string> {
  const s3Key = `unified/${payload.date}/${payload.id}.json`

  await s3.send(
    new PutObjectCommand({
      Bucket:      bucket,
      Key:         s3Key,
      Body:        JSON.stringify(payload),
      ContentType: "application/json",
    }),
  )

  return s3Key
}

// ── Lambda 2 invocation ────────────────────────────────────────────────────

interface LambdaResult {
  processed: number
  failed: number
  skipped: number
}

/**
 * Synchronously invoke Lambda 2 (generate_summaries) for one raw S3 object.
 * Lambda 2 expects: { source: "ingest_news", s3_key: "raw/...", bucket: "..." }
 */
export async function invokeSummarizeLambda(
  bucket: string,
  s3Key: string,
): Promise<LambdaResult> {
  const functionName = process.env.GENERATE_SUMMARIES_FUNCTION
  if (!functionName) {
    throw new Error("GENERATE_SUMMARIES_FUNCTION env var is not set")
  }

  const payload = JSON.stringify({ source: "ingest_news", s3_key: s3Key, bucket })

  const res = await lambda.send(
    new InvokeCommand({
      FunctionName:   functionName,
      InvocationType: "RequestResponse",
      Payload:        Buffer.from(payload),
    }),
  )

  if (res.FunctionError) {
    const errBody = res.Payload ? Buffer.from(res.Payload).toString("utf-8") : "unknown"
    throw new Error(`Lambda 2 error: ${res.FunctionError} — ${errBody}`)
  }

  if (res.Payload) {
    try {
      const body   = Buffer.from(res.Payload).toString("utf-8")
      const parsed = JSON.parse(body) as { statusCode?: number; body?: string }
      if (parsed.body) {
        const inner = JSON.parse(parsed.body) as Partial<LambdaResult>
        return {
          processed: inner.processed ?? 0,
          failed:    inner.failed    ?? 0,
          skipped:   inner.skipped   ?? 0,
        }
      }
    } catch {
      // If the response doesn't parse, treat as success
    }
  }

  return { processed: 1, failed: 0, skipped: 0 }
}
