export default function Home() {
  return (
    <main style={{ fontFamily: "monospace", maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>News Summaries — Ingest API</h1>
      <p>
        POST to <code>/api/ingest</code> with a JSON body:
      </p>
      <pre
        style={{
          background: "#f4f4f4",
          padding: "1rem",
          borderRadius: 4,
          overflowX: "auto",
        }}
      >{`{
  "urls": [
    "https://www.reuters.com/...",
    "https://techcrunch.com/...",
    "https://edition.cnn.com/..."
  ]
}`}</pre>
      <p>
        The pipeline scrapes each URL (Firecrawl), deduplicates against the
        Supabase <code>news_vectors</code> table, distils all new articles into
        a single Unified Market Intelligence summary via Claude Sonnet, and
        stores the result with embeddings.
      </p>
    </main>
  )
}
