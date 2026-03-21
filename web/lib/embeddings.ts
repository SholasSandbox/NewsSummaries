/**
 * lib/embeddings.ts
 *
 * OpenAI text-embedding-3-small helper.
 *
 * Logic Path: A 1536-dimension vector is generated for each unified summary
 * and stored alongside the text in S3. This enables future semantic search
 * across the data lake (e.g., via Bedrock Knowledge Bases or a vector index)
 * without requiring an external vector database.
 */

import OpenAI from "openai"

const MODEL      = "text-embedding-3-small"
const DIMENSIONS = 1536

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY ?? "" })

/**
 * Generate a 1536-dimension embedding for the given text.
 *
 * @param text  The unified summary text to embed (truncated to ~8k tokens by OpenAI if needed).
 * @returns     Array of 1536 floats.
 */
export async function generateEmbedding(text: string): Promise<number[]> {
  const res = await openai.embeddings.create({
    model:      MODEL,
    input:      text,
    dimensions: DIMENSIONS,
  })
  return res.data[0].embedding
}
