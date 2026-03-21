/**
 * lib/dynamo.ts
 *
 * DynamoDB helpers for the ingest pipeline.
 *
 * Logic Path: All state lives in DynamoDB (no Supabase). The episodes table
 * is keyed on episode_id (= article_hash for Lambda-generated episodes, or
 * "unified-{date}-{uuid}" for web-generated unified summaries). BatchGetItem
 * is used for deduplication to keep read costs low across batches of 10 URLs.
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb"
import { DynamoDBDocumentClient, BatchGetCommand, PutCommand, ScanCommand } from "@aws-sdk/lib-dynamodb"

const region = process.env.AWS_REGION ?? "us-east-1"
const TABLE  = process.env.DYNAMODB_TABLE_NAME ?? ""

const raw = new DynamoDBClient({ region })
const ddb  = DynamoDBDocumentClient.from(raw)

/**
 * Given a list of article hashes, return the subset that already exist
 * in DynamoDB so the pipeline can skip re-processing duplicates.
 *
 * @param hashes   Article hash values to check. Only the first 100 are
 *                 evaluated (DynamoDB BatchGetItem hard limit); callers
 *                 should keep batch sizes ≤ 100 to avoid silent truncation.
 * @param _date    Reserved for future date-scoped queries (unused now).
 */
export async function fetchExistingHashes(
  hashes: string[],
  _date: string,
): Promise<Set<string>> {
  if (!TABLE || hashes.length === 0) return new Set()

  // BatchGetItem accepts at most 100 keys per call
  const keys = hashes.slice(0, 100).map((h) => ({ episode_id: h }))

  const res = await ddb.send(
    new BatchGetCommand({
      RequestItems: { [TABLE]: { Keys: keys, ProjectionExpression: "episode_id" } },
    }),
  )

  const existing = new Set<string>()
  for (const item of res.Responses?.[TABLE] ?? []) {
    if (typeof item.episode_id === "string") existing.add(item.episode_id)
  }
  return existing
}

export interface UnifiedSummaryRecord {
  episode_id: string
  date: string
  title: string
  source: string
  category: string
  status: string
  article_count: number
  source_urls: string[]
  s3_key: string
  created_at: string
  ttl: number
}

/**
 * Write a unified summary metadata record to DynamoDB.
 */
export async function writeUnifiedSummaryToDynamo(
  item: UnifiedSummaryRecord,
): Promise<void> {
  if (!TABLE) throw new Error("DYNAMODB_TABLE_NAME env var is not set")

  await ddb.send(
    new PutCommand({
      TableName: TABLE,
      Item: item,
    }),
  )
}

// ── Admin / Observability ──────────────────────────────────────────────────

export interface EpisodeRecord {
  episode_id: string
  date?: string
  title?: string
  source?: string
  category?: string
  status?: string
  importance?: string
  summary?: string
  audio_url?: string
  summary_s3_key?: string
  raw_s3_key?: string
  article_count?: number
  created_at?: string
}

/**
 * Scan the episodes table and return the most-recent records.
 * Uses a DynamoDB Scan (acceptable for the small scale of this project;
 * switch to a GSI-based Query if the table grows large).
 *
 * @param limit  Max items to return (default 50).
 */
export async function listEpisodes(limit = 50): Promise<EpisodeRecord[]> {
  if (!TABLE) throw new Error("DYNAMODB_TABLE_NAME env var is not set")

  const res = await ddb.send(
    new ScanCommand({
      TableName: TABLE,
      Limit: Math.min(limit, 100),
    }),
  )

  const items = (res.Items ?? []) as EpisodeRecord[]
  // Sort newest-first by created_at (falls back to episode_id sort)
  return items.sort((a, b) =>
    (b.created_at ?? b.episode_id ?? "").localeCompare(a.created_at ?? a.episode_id ?? ""),
  )
}
