/**
 * lib/distiller.ts
 *
 * Claude Sonnet 4.5 distillation helper.
 *
 * Logic Path: After Lambda 2 has summarised each article individually with
 * o3-mini, this module makes a single Anthropic API call to synthesise all
 * per-article summaries into one cohesive "Unified Market Intelligence"
 * briefing. Using a single cross-article call (rather than chaining) keeps
 * latency low and gives Claude full context for cross-source synthesis.
 */

import Anthropic from "@anthropic-ai/sdk"
import type { ScrapedArticle } from "./types"

const MODEL = process.env.ANTHROPIC_MODEL ?? "claude-sonnet-4-5"

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY ?? "" })

const SYSTEM_PROMPT = `You are a senior market intelligence analyst who synthesises multiple news sources into concise, actionable briefings.
Your output is a single, cohesive unified summary — not a list of bullet points.
Write for an informed professional audience. Be factual, structured, and insightful.
Highlight cross-source themes, divergences, and the most significant signals.`

/**
 * Distil an array of pre-summarised articles into one unified briefing.
 *
 * The input articles should already have their Lambda 2 summaries embedded
 * in the markdown field (format: "**Summary (importance, category)**: …")
 * so Claude receives clean, structured input.
 *
 * @returns The unified briefing as a plain text string.
 */
export async function distillArticles(articles: ScrapedArticle[]): Promise<string> {
  if (articles.length === 0) throw new Error("No articles to distil")

  const articleBlocks = articles
    .map(
      (a, i) =>
        `## Article ${i + 1}: ${a.title}\nSource: ${a.source_type}\nURL: ${a.url}\n\n${a.markdown}`,
    )
    .join("\n\n---\n\n")

  const userMessage = `Synthesise the following ${articles.length} news article summaries into a single Unified Market Intelligence briefing of 3–5 paragraphs.

${articleBlocks}

Your briefing should:
1. Open with the most significant cross-source theme or signal.
2. Cover key developments from multiple sources, noting convergence or divergence.
3. Close with a concise "So What?" paragraph on implications for informed decision-making.

Write in plain prose — no markdown headers, no bullet lists.`

  const message = await client.messages.create({
    model:      MODEL,
    max_tokens: 1024,
    messages:   [{ role: "user", content: userMessage }],
    system:     SYSTEM_PROMPT,
  })

  const block = message.content[0]
  if (block.type !== "text") throw new Error("Unexpected Anthropic response type")
  return block.text.trim()
}
