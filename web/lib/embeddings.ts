/**
 * lib/embeddings.ts
 *
 * OpenAI text-embedding helper.
 *
 * Logic Path: A vector is generated for each unified summary and stored
 * alongside the text in S3. Both the model and its dimension are read from
 * environment variables so they can be changed atomically without a code
 * redeploy (OPENAI_EMBEDDING_MODEL + OPENAI_EMBEDDING_DIMENSIONS).
 * This enables future semantic search across the data lake (e.g., via Bedrock
 * Knowledge Bases or a vector index) without requiring an external vector
 * database.
 */

import OpenAI from "openai"

const MODEL      = process.env.OPENAI_EMBEDDING_MODEL      ?? "text-embedding-3-small"
const parsed = parseInt(process.env.OPENAI_EMBEDDING_DIMENSIONS ?? "1536", 10)
if (isNaN(parsed) || parsed <= 0) {
  throw new Error(
    `Invalid OPENAI_EMBEDDING_DIMENSIONS: "${process.env.OPENAI_EMBEDDING_DIMENSIONS}". Must be a positive integer.`
  )
}
const DIMENSIONS = parsed

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY ?? "" })

/**
 * Generate an embedding vector for the given text.
 *
 * Dimension count is controlled by the OPENAI_EMBEDDING_DIMENSIONS env var
 * (default 1536, tied to text-embedding-3-small). If the model is changed,
 * set both env vars atomically to keep the stored vectors consistent.
 *
 * @param text  The unified summary text to embed (truncated to ~8k tokens by OpenAI if needed).
 * @returns     Float array whose length equals DIMENSIONS.
 */
export async function generateEmbedding(text: string): Promise<number[]> {
  const res = await openai.embeddings.create({
    model:      MODEL,
    input:      text,
    dimensions: DIMENSIONS,
  })
  return res.data[0].embedding
}
