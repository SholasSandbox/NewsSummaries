/**
 * Homepage — News Summaries Market Intelligence Dashboard
 *
 * Logic Path: This page is the entry point for the pipeline. It explains
 * the 9-step ingest flow and provides a live-demo UI backed by POST /api/ingest.
 * Tailwind CSS 4.0 (CSS-first config, no tailwind.config.js required).
 */
"use client"

import Link from "next/link"
import { useState } from "react"

const EXAMPLE_URLS = [
  "https://www.reuters.com/technology/",
  "https://techcrunch.com/",
  "https://edition.cnn.com/business",
]

const PIPELINE_STEPS = [
  { icon: "🔗", label: "Parse URLs",      detail: "Validate & cap at 10 URLs"                          },
  { icon: "🕷️", label: "Scrape",          detail: "Firecrawl v4 — cookie bypass, clean markdown"      },
  { icon: "🔍", label: "Deduplicate",     detail: "DynamoDB BatchGetItem — episode_id = article_hash" },
  { icon: "📦", label: "Store Raw",       detail: "S3 raw/{date}/{hash}.json — Lambda-compatible"     },
  { icon: "⚡", label: "Lambda Summarise",detail: "Lambda 2 → OpenAI o3-mini per article"             },
  { icon: "📖", label: "Read Summaries",  detail: "S3 summaries/{date}/{hash}.json"                    },
  { icon: "🧠", label: "Distil",          detail: "Claude Sonnet 4.5 — Unified Market Intelligence"   },
  { icon: "🔢", label: "Embed",           detail: "OpenAI text-embedding-3-small (1536 dims)"        },
  { icon: "💾", label: "Store",           detail: "S3 unified/{date}/{id}.json + DynamoDB metadata"   },
]

interface StepResult {
  step: string
  status: "success" | "skipped" | "error"
  count?: number
  detail?: string
}

interface IngestResponse {
  success: boolean
  steps: StepResult[]
  output: {
    ingested_count: number
    duplicate_count: number
    failed_scrape_count: number
    summary: {
      id: string
      content: string
      sources: string[]
      article_count: number
      s3_key: string
      created_at: string
    } | null
  }
  meta: { duration_ms: number; processed_at: string }
}

export default function Home() {
  const [urlInput, setUrlInput]     = useState(EXAMPLE_URLS.join("\n"))
  const [loading, setLoading]       = useState(false)
  const [result, setResult]         = useState<IngestResponse | null>(null)
  const [error, setError]           = useState<string | null>(null)

  async function runPipeline() {
    setLoading(true)
    setResult(null)
    setError(null)

    const urls = urlInput
      .split(/[\n,]+/)
      .map((u) => u.trim())
      .filter(Boolean)

    try {
      const res  = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls }),
      })
      const data = (await res.json()) as IngestResponse
      setResult(data)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="relative z-10 min-h-screen">

      {/* ── Header ── */}
      <header className="border-b border-white/8 px-6 py-5">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/20 text-lg ring-1 ring-indigo-500/30">
              📡
            </div>
            <div>
              <p className="text-xs font-medium tracking-widest text-indigo-400 uppercase">AWS Serverless</p>
              <h1 className="text-lg font-semibold text-white leading-tight">News Summaries</h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/podcast"
              className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:border-indigo-500/30 hover:text-indigo-300 transition"
            >
              🎙️ Podcast
            </Link>
            <Link
              href="/admin"
              className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:border-indigo-500/30 hover:text-indigo-300 transition"
            >
              Admin
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-12">

        {/* ── Hero ── */}
        <div className="mb-14 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-500/20 bg-indigo-500/5 px-4 py-1.5 text-xs text-indigo-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400"></span>
            Next.js 16 · AWS Lambda · Claude Sonnet 4.5 · Firecrawl v4
          </div>
          <h2 className="mb-4 text-4xl font-bold tracking-tight text-white sm:text-5xl">
            Unified Market
            <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent"> Intelligence</span>
          </h2>
          <p className="mx-auto max-w-2xl text-base text-gray-400">
            Scrape 5–10 news URLs → Lambda 2 summarises each with o3-mini →
            Claude synthesises all into one cross-source briefing → stored in S3 + DynamoDB.
          </p>
        </div>

        {/* ── Pipeline steps ── */}
        <div className="mb-14">
          <h3 className="mb-5 text-xs font-semibold uppercase tracking-widest text-gray-500">
            9-Step Logic Path
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {PIPELINE_STEPS.map((s, i) => (
              <div
                key={s.label}
                className="flex items-start gap-3 rounded-xl border border-white/6 bg-white/2 p-4 transition-colors hover:border-indigo-500/20 hover:bg-indigo-500/5"
              >
                <span className="mt-0.5 text-lg leading-none">{s.icon}</span>
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium text-white">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-indigo-500/20 text-[10px] font-bold text-indigo-400">
                      {i + 1}
                    </span>
                    {s.label}
                  </p>
                  <p className="mt-0.5 text-xs leading-snug text-gray-500">{s.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Input form ── */}
        <div className="mb-8 rounded-2xl border border-white/8 bg-white/2 p-6">
          <label className="mb-3 block text-sm font-medium text-gray-300">
            Article URLs
            <span className="ml-2 text-xs font-normal text-gray-500">
              one per line · 5–10 recommended · 10 max
            </span>
          </label>
          <textarea
            className="w-full rounded-xl border border-white/8 bg-black/20 px-4 py-3 font-mono text-sm text-gray-200 placeholder-gray-600 outline-none transition focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30"
            rows={5}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder={"https://www.reuters.com/technology/\nhttps://techcrunch.com/\nhttps://edition.cnn.com/business"}
            spellCheck={false}
          />
          <div className="mt-4 flex items-center justify-between">
            <p className="text-xs text-gray-600">
              Pipeline writes to <code className="text-indigo-400">S3</code> and{" "}
              <code className="text-indigo-400">DynamoDB</code> — no third-party databases.
            </p>
            <button
              onClick={runPipeline}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Running pipeline…
                </>
              ) : (
                <>⚡ Run Pipeline</>
              )}
            </button>
          </div>
        </div>

        {/* ── Error ── */}
        {error && (
          <div className="mb-8 rounded-xl border border-red-500/20 bg-red-500/5 px-5 py-4 text-sm text-red-400">
            ⚠️ {error}
          </div>
        )}

        {/* ── Results ── */}
        {result && (
          <div className="space-y-6">

            {/* Step trace */}
            <div className="rounded-2xl border border-white/8 bg-white/2 p-6">
              <h3 className="mb-4 text-sm font-semibold text-gray-300">
                Execution Trace
                <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-medium ${
                  result.success ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
                }`}>
                  {result.success ? "✓ Success" : "✗ Failed"} · {result.meta.duration_ms}ms
                </span>
              </h3>
              <div className="space-y-1.5">
                {result.steps.map((step) => (
                  <div
                    key={step.step}
                    className="flex items-start gap-3 rounded-lg px-3 py-2 text-sm"
                  >
                    <span className={
                      step.status === "success" ? "text-emerald-400"
                      : step.status === "skipped" ? "text-gray-500"
                      : "text-red-400"
                    }>
                      {step.status === "success" ? "✓" : step.status === "skipped" ? "–" : "✗"}
                    </span>
                    <div className="flex flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <code className="font-mono text-indigo-300">{step.step}</code>
                      {step.count !== undefined && (
                        <span className="text-xs text-gray-500">({step.count})</span>
                      )}
                      {step.detail && (
                        <span className="text-xs text-gray-500">{step.detail}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Unified summary */}
            {result.output.summary && (
              <div className="rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-indigo-300">
                    🧠 Unified Market Intelligence
                  </h3>
                  <div className="flex gap-3 text-xs text-gray-500">
                    <span>{result.output.summary.article_count} articles</span>
                    <span>·</span>
                    <code className="text-indigo-400/60">{result.output.summary.s3_key}</code>
                  </div>
                </div>
                <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-gray-300">
                  {result.output.summary.content}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {result.output.summary.sources.map((url) => (
                    <a
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="truncate rounded-md bg-white/5 px-2 py-1 text-xs text-gray-500 hover:text-gray-300 max-w-xs"
                    >
                      {new URL(url).hostname}
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "Ingested",   value: result.output.ingested_count,     color: "text-emerald-400" },
                { label: "Duplicates", value: result.output.duplicate_count,    color: "text-amber-400"   },
                { label: "Scrape Errors", value: result.output.failed_scrape_count, color: "text-red-400" },
              ].map((s) => (
                <div key={s.label} className="rounded-xl border border-white/8 bg-white/2 px-4 py-4 text-center">
                  <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                  <p className="mt-1 text-xs text-gray-500">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Footer ── */}
      <footer className="mt-16 border-t border-white/6 px-6 py-6 text-center text-xs text-gray-600">
        AWS-native · Lambda + S3 + DynamoDB · No third-party databases
      </footer>
    </main>
  )
}
