import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "News Summaries — Market Intelligence",
  description: "AI-powered news distillation pipeline. Scrape → Summarise → Distil into Unified Market Intelligence.",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">{children}</body>
    </html>
  )
}
