/**
 * lib/scraper.ts
 *
 * Firecrawl v4 scraping helper.
 *
 * Logic Path: Firecrawl's scrapeUrl() returns clean markdown, bypassing
 * paywalls and cookie banners. article_hash uses the same SHA-256 formula
 * as Lambda 1 (src/ingest_news/handler.py:_article_hash) so that DynamoDB
 * dedup keys are identical across both ingestion paths.
 */

import FirecrawlApp from "firecrawl"
import { createHash } from "crypto"
import type { ScrapedArticle } from "./types"

const firecrawl = new FirecrawlApp({ apiKey: process.env.FIRECRAWL_API_KEY ?? "" })

/**
 * Compute a stable 16-char hex hash for an article.
 * Matches Lambda 1: SHA-256("{url}|{title}".lower())[:16]
 */
export function computeArticleHash(url: string, title: string): string {
  return createHash("sha256")
    .update(`${url}|${title}`.toLowerCase())
    .digest("hex")
    .slice(0, 16)
}

export interface ScrapeResult {
  articles: ScrapedArticle[]
  failedCount: number
}

/**
 * Scrape an array of URLs concurrently via Firecrawl v4.
 * Failed URLs are counted but do not abort the batch.
 */
export async function scrapeUrls(urls: string[]): Promise<ScrapeResult> {
  const scraped = await Promise.allSettled(
    urls.map(async (url) => {
      const res = await firecrawl.scrape(url, { formats: ["markdown"] })

      const markdown  = res.markdown ?? ""
      const title     = (res.metadata?.title ?? new URL(url).hostname).trim()
      const scrapedAt = new Date().toISOString()

      const article: ScrapedArticle = {
        url,
        url_hash:    computeArticleHash(url, title),
        title,
        markdown,
        source_type: res.metadata?.sourceURL ?? url,
        scraped_at:  scrapedAt,
      }
      return article
    }),
  )

  const articles: ScrapedArticle[] = []
  let failedCount = 0

  for (const result of scraped) {
    if (result.status === "fulfilled") {
      articles.push(result.value)
    } else {
      failedCount++
    }
  }

  return { articles, failedCount }
}
