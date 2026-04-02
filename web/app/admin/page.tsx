/**
 * /admin — Episodes Admin Dashboard
 *
 * Internal observability page matching the diagram's "Admin/Observability"
 * layer (Lambda 4 – Episodes API). Lists DynamoDB episode metadata with
 * colour-coded status badges, category chips, and links to audio + transcript.
 *
 * Tailwind CSS 4.0 (CSS-first config).
 */
"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

interface Episode {
  episode_id: string
  date?: string
  title?: string
  source?: string
  category?: string
  status?: string
  importance?: string
  summary?: string
  audio_url?: string
  summary_s3_key?: string
  raw_s3_key?: string
  article_count?: number
  created_at?: string
}

interface EpisodesResponse {
  success: boolean
  episodes: Episode[]
  error?: string
}

const STATUS_COLOURS: Record<string, string> = {
  processed: "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20",
  distilled: "bg-indigo-500/15 text-indigo-400 ring-1 ring-indigo-500/20",
  skipped:   "bg-gray-500/15 text-gray-400 ring-1 ring-gray-500/20",
  failed:    "bg-red-500/15 text-red-400 ring-1 ring-red-500/20",
}

const IMPORTANCE_COLOURS: Record<string, string> = {
  high:   "text-red-400",
  medium: "text-amber-400",
  low:    "text-gray-500",
}

function StatusBadge({ status }: { status?: string }) {
  const s = (status ?? "unknown").toLowerCase()
  const cls = STATUS_COLOURS[s] ?? "bg-gray-500/10 text-gray-400 ring-1 ring-gray-500/20"
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {s}
    </span>
  )
}

function CategoryChip({ category }: { category?: string }) {
  if (!category) return null
  return (
    <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-2 py-0.5 text-[11px] font-medium text-indigo-400 ring-1 ring-indigo-500/15">
      {category}
    </span>
  )
}

export default function AdminPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [search, setSearch]     = useState("")

  async function fetchEpisodes() {
    setLoading(true)
    setError(null)
    try {
      const res  = await fetch("/api/episodes")
      const data = (await res.json()) as EpisodesResponse
      if (!data.success) throw new Error(data.error ?? "Unknown error")
      setEpisodes(data.episodes)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void fetchEpisodes() }, [])

  const filtered = episodes.filter((ep) => {
    const q = search.toLowerCase()
    return (
      !q ||
      ep.title?.toLowerCase().includes(q) ||
      ep.episode_id.toLowerCase().includes(q) ||
      ep.category?.toLowerCase().includes(q) ||
      ep.source?.toLowerCase().includes(q)
    )
  })

  return (
    <main className="min-h-screen">
      {/* ── Header ── */}
      <header className="border-b border-white/8 px-6 py-5">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/20 text-lg ring-1 ring-indigo-500/30">
              🎛️
            </div>
            <div>
              <p className="text-xs font-medium tracking-widest text-indigo-400 uppercase">Admin / Observability</p>
              <h1 className="text-lg font-semibold text-white leading-tight">Episodes Dashboard</h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:border-indigo-500/30 hover:text-indigo-300 transition"
            >
              ← Ingest Pipeline
            </Link>
            <Link
              href="/podcast"
              className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:border-indigo-500/30 hover:text-indigo-300 transition"
            >
              🎙️ Podcast
            </Link>
            <button
              onClick={() => void fetchEpisodes()}
              disabled={loading}
              className="rounded-xl bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 transition"
            >
              {loading ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-10">

        {/* ── Stats row ── */}
        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Total Episodes",  value: episodes.length,                                                         color: "text-white"        },
            { label: "Processed",       value: episodes.filter((e) => e.status === "processed").length,                 color: "text-emerald-400"  },
            { label: "Distilled",       value: episodes.filter((e) => e.status === "distilled").length,                 color: "text-indigo-400"   },
            { label: "With Audio",      value: episodes.filter((e) => e.audio_url).length,                              color: "text-violet-400"   },
          ].map((s) => (
            <div key={s.label} className="rounded-xl border border-white/8 bg-white/2 px-4 py-4 text-center">
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              <p className="mt-1 text-xs text-gray-500">{s.label}</p>
            </div>
          ))}
        </div>

        {/* ── Search ── */}
        <div className="mb-4">
          <input
            type="search"
            placeholder="Search by title, source, category, or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl border border-white/8 bg-black/20 px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30"
          />
        </div>

        {/* ── Error ── */}
        {error && (
          <div className="mb-6 rounded-xl border border-red-500/20 bg-red-500/5 px-5 py-4 text-sm text-red-400">
            ⚠️ {error}
          </div>
        )}

        {/* ── Loading skeleton ── */}
        {loading && (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded-xl bg-white/4" />
            ))}
          </div>
        )}

        {/* ── Episodes table ── */}
        {!loading && (
          <>
            <div className="overflow-hidden rounded-2xl border border-white/8">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/6 bg-white/2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    <th className="px-4 py-3">Title / ID</th>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Category</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Importance</th>
                    <th className="px-4 py-3">Links</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/4">
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-10 text-center text-gray-600">
                        {search ? "No episodes match your search." : "No episodes found in DynamoDB."}
                      </td>
                    </tr>
                  )}
                  {filtered.map((ep) => (
                    <tr key={ep.episode_id} className="hover:bg-white/2 transition-colors">
                      <td className="max-w-xs px-4 py-3">
                        <p className="truncate font-medium text-white" title={ep.title}>
                          {ep.title ?? "(no title)"}
                        </p>
                        <p className="mt-0.5 truncate font-mono text-[10px] text-gray-600" title={ep.episode_id}>
                          {ep.episode_id}
                        </p>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-gray-400">
                        {ep.date ?? ep.created_at?.slice(0, 10) ?? "—"}
                      </td>
                      <td className="max-w-[120px] truncate px-4 py-3 text-gray-400" title={ep.source}>
                        {ep.source ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <CategoryChip category={ep.category} />
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={ep.status} />
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-medium ${IMPORTANCE_COLOURS[ep.importance?.toLowerCase() ?? ""] ?? "text-gray-600"}`}>
                          {ep.importance ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          {ep.audio_url && (
                            <a
                              href={ep.audio_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-md bg-violet-500/10 px-2 py-1 text-[11px] text-violet-400 hover:bg-violet-500/20 transition ring-1 ring-violet-500/20"
                              title="Play audio"
                            >
                              🎧 Audio
                            </a>
                          )}
                          {ep.summary_s3_key && (
                            <span
                              className="rounded-md bg-indigo-500/10 px-2 py-1 text-[11px] text-indigo-400 ring-1 ring-indigo-500/20"
                              title={ep.summary_s3_key}
                            >
                              📄 S3
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-right text-xs text-gray-600">
              {filtered.length} / {episodes.length} episodes shown
            </p>
          </>
        )}
      </div>

      <footer className="mt-12 border-t border-white/6 px-6 py-6 text-center text-xs text-gray-600">
        Admin / Observability · Lambda 4 (Episodes API) · DynamoDB direct read · Internal use only
      </footer>
    </main>
  )
}
