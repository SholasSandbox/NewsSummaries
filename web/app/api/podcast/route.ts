/**
 * GET /api/podcast
 *
 * Returns the CloudFront RSS feed URL and the most recent 50 episodes from
 * DynamoDB in a single response for the public podcast listener page.
 *
 * Logic Path: The CLOUDFRONT_DOMAIN env var is only available server-side.
 * Exposing it through this route avoids the need for a NEXT_PUBLIC_ variable
 * while keeping the podcast page a lightweight "use client" component.
 */

import { type NextRequest, NextResponse } from "next/server"
import { listEpisodes } from "@/lib/dynamo"

export async function GET(_req: NextRequest): Promise<NextResponse> {
  const domain = process.env.CLOUDFRONT_DOMAIN ?? ""
  const feed_url = domain ? `https://${domain}/rss/feed.xml` : null

  try {
    const episodes = await listEpisodes(50)
    return NextResponse.json({ success: true, feed_url, episodes })
  } catch (err) {
    return NextResponse.json(
      { success: false, feed_url, episodes: [], error: String(err) },
      { status: 500 },
    )
  }
}
