import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "News Summaries",
  description: "AI-powered news distillation pipeline",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
