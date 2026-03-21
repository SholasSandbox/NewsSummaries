/**
 * GET /api/episodes
 *
 * Internal endpoint for the Admin UI. Reads episode metadata directly from
 * DynamoDB (the same table used by Lambda 4 – Episodes API) and returns up
 * to 50 recent records sorted newest-first.
 *
 * Logic Path: Scans the DynamoDB episodes table using the AWS SDK v3
 * DynamoDBDocumentClient. Restricted to server-side only (no CORS needed)
 * because it is called only from the Next.js admin page.
 */

import { type NextRequest, NextResponse } from "next/server"
import { listEpisodes } from "@/lib/dynamo"

export async function GET(_req: NextRequest): Promise<NextResponse> {
  try {
    const episodes = await listEpisodes(50)
    return NextResponse.json({ success: true, episodes })
  } catch (err) {
    return NextResponse.json(
      { success: false, error: String(err) },
      { status: 500 },
    )
  }
}
