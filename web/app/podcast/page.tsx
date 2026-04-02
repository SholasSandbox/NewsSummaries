/**
 * /podcast — Public Listener Page
 *
 * Delivery Layer: the public-facing end of the pipeline diagram.
 * Listeners can subscribe to the RSS feed (copy URL + app deep-links)
 * and browse every episode with an in-browser HTML5 audio player.
 *
 * Logic Path: Fetches /api/podcast (server-side route that reads
 * CLOUDFRONT_DOMAIN + DynamoDB) so no NEXT_PUBLIC_ env vars are needed.
 * Tailwind CSS 4.0 — CSS-first config, matches existing page aesthetic.
 */
"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import type { EpisodeRecord } from "@/lib/dynamo"

interface PodcastResponse {
  success: boolean
  feed_url: string | null
  episodes: EpisodeRecord[]
  error?: string
}

const APP_LINKS = [
  {
    label: "Apple Podcasts",
    icon: "🎵",
    href: (feedUrl: string) =>
      `https://podcasts.apple.com/podcast?feedUrl=${encodeURIComponent(feedUrl)}`,
  },
  {
    label: "Spotify",
    icon: "🎧",
    href: (feedUrl: string) =>
      `https://open.spotify.com/search/${encodeURIComponent(feedUrl)}`,
  },
  {
    label: "Overcast",
    icon: "📻",
    href: (feedUrl: string) =>
      `https://overcast.fm/itunes?url=${encodeURIComponent(feedUrl)}`,
  },
  {
    label: "Pocket Casts",
    icon: "▶️",
    href: (feedUrl: string) =>
      `https://pocketcasts.com/add/?url=${encodeURIComponent(feedUrl)}`,
  },
]

function AudioPlayer({ url, title }: { url: string; title?: string }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)

  function toggle() {
    const el = audioRef.current
    if (!el) return
    if (playing) {
      el.pause()
    } else {
      el.play().catch(() => {})
    }
  }

  function fmt(secs: number) {
    if (!isFinite(secs)) return "—"
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${String(s).padStart(2, "0")}`
  }

  function seek(e: React.ChangeEvent<HTMLInputElement>) {
    const el = audioRef.current
    if (!el) return
    const t = (parseFloat(e.target.value) / 100) * (el.duration || 0)
    el.currentTime = t
  }

  return (
    <div className="mt-3 rounded-xl border border-white/6 bg-black/20 px-4 py-3">
      <audio
        ref={audioRef}
        src={url}
        title={title}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={() => {
          const el = audioRef.current
          if (!el || !el.duration) return
          setProgress((el.currentTime / el.duration) * 100)
        }}
        onLoadedMetadata={() => {
          const el = audioRef.current
          if (el) setDuration(el.duration)
        }}
        preload="metadata"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={toggle}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white transition hover:bg-indigo-500"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "⏸" : "▶"}
        </button>
        <div className="flex flex-1 flex-col gap-1">
          <input
            type="range"
            min={0}
            max={100}
            value={progress}
            onChange={seek}
            className="h-1.5 w-full cursor-pointer accent-indigo-500"
          />
          <div className="flex justify-between text-[10px] text-gray-600">
            <span>{fmt((progress / 100) * duration)}</span>
            <span>{fmt(duration)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard not available (non-https / permissions)
    }
  }

  return (
    <button
      onClick={copy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-gray-300 transition hover:border-indigo-500/30 hover:bg-indigo-500/10 hover:text-indigo-300"
    >
      {copied ? "✓ Copied" : "📋 Copy URL"}
    </button>
  )
}

export default function PodcastPage() {
  const [data, setData] = useState<PodcastResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/podcast")
      .then((r) => r.json())
      .then((d: PodcastResponse) => setData(d))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const episodes = data?.episodes ?? []
  const withAudio = episodes.filter((e) => e.audio_url)
  const feedUrl = data?.feed_url ?? null

  return (
    <main className="relative z-10 min-h-screen">

      {/* ── Header ── */}
      <header className="border-b border-white/8 px-6 py-5">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/20 text-lg ring-1 ring-indigo-500/30">
              🎙️
            </div>
            <div>
              <p className="text-xs font-medium tracking-widest text-indigo-400 uppercase">AWS Serverless</p>
              <h1 className="text-lg font-semibold text-white leading-tight">News Summaries Podcast</h1>
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <Link href="/" className="hover:text-gray-300 transition-colors">Pipeline</Link>
            <span>·</span>
            <Link href="/admin" className="hover:text-gray-300 transition-colors">Admin</Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-12">

        {/* ── Hero ── */}
        <div className="mb-14 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-500/20 bg-indigo-500/5 px-4 py-1.5 text-xs text-indigo-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400"></span>
            AI-generated · Twice daily · CloudFront CDN
          </div>
          <h2 className="mb-4 text-4xl font-bold tracking-tight text-white sm:text-5xl">
            Daily
            <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent"> AI Briefings</span>
          </h2>
          <p className="mx-auto max-w-2xl text-base text-gray-400">
            Concise news episodes synthesized from top sources by Claude Sonnet 4.5, converted
            to audio by OpenAI TTS, and delivered fresh every morning and evening.
          </p>
        </div>

        {/* ── RSS Subscribe Card ── */}
        <div className="mb-14 rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-6">
          <div className="mb-5 flex items-center gap-3">
            <span className="text-2xl">📡</span>
            <div>
              <h3 className="font-semibold text-white">Subscribe via RSS</h3>
              <p className="text-sm text-gray-400">Works with any podcast app that accepts a feed URL.</p>
            </div>
          </div>

          {feedUrl ? (
            <>
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-white/8 bg-black/30 px-4 py-2.5">
                <code className="flex-1 truncate font-mono text-xs text-indigo-300">{feedUrl}</code>
                <CopyButton text={feedUrl} />
              </div>
              <div className="flex flex-wrap gap-2">
                {APP_LINKS.map((app) => (
                  <a
                    key={app.label}
                    href={app.href(feedUrl)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/5 px-3 py-1.5 text-xs text-gray-300 transition hover:border-indigo-500/30 hover:bg-indigo-500/10 hover:text-white"
                  >
                    <span>{app.icon}</span>
                    {app.label}
                  </a>
                ))}
              </div>
            </>
          ) : (
            <p className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-400">
              ⚠️ RSS feed URL is not configured. Set the <code className="font-mono">CLOUDFRONT_DOMAIN</code> environment variable.
            </p>
          )}
        </div>

        {/* ── Stats row ── */}
        {!loading && (
          <div className="mb-10 grid grid-cols-3 gap-3">
            {[
              { label: "Total Episodes",   value: episodes.length,    color: "text-white"         },
              { label: "With Audio",       value: withAudio.length,   color: "text-violet-400"    },
              { label: "No Audio Yet",     value: episodes.length - withAudio.length, color: "text-amber-400" },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-white/8 bg-white/2 px-4 py-4 text-center">
                <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                <p className="mt-1 text-xs text-gray-500">{s.label}</p>
              </div>
            ))}
          </div>
        )}

        {/* ── Episode List ── */}
        <div>
          <h3 className="mb-5 text-xs font-semibold uppercase tracking-widest text-gray-500">
            Episodes
          </h3>

          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-24 animate-pulse rounded-2xl bg-white/4" />
              ))}
            </div>
          )}

          {/* Error */}
          {!loading && error && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-5 py-4 text-sm text-red-400">
              ⚠️ {error}
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && episodes.length === 0 && (
            <div className="rounded-2xl border border-white/6 bg-white/2 px-6 py-12 text-center">
              <p className="text-3xl">🎙️</p>
              <p className="mt-3 text-sm text-gray-500">No episodes yet. The pipeline runs twice daily at 06:00 and 18:00 UTC.</p>
            </div>
          )}

          {/* Episode cards */}
          {!loading && !error && episodes.length > 0 && (
            <div className="space-y-4">
              {episodes.map((ep) => (
                <div
                  key={ep.episode_id}
                  className="rounded-2xl border border-white/8 bg-white/2 p-5 transition-colors hover:border-indigo-500/15 hover:bg-indigo-500/3"
                >
                  {/* Episode header */}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <h4 className="font-semibold text-white">
                        {ep.title ?? "(untitled episode)"}
                      </h4>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                        {ep.date && <span>📅 {ep.date}</span>}
                        {ep.source && <span>🗞️ {ep.source}</span>}
                        {ep.category && (
                          <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-indigo-400 ring-1 ring-indigo-500/15">
                            {ep.category}
                          </span>
                        )}
                        {ep.article_count !== undefined && (
                          <span>{ep.article_count} articles</span>
                        )}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {ep.status && (
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${
                          ep.status === "processed"
                            ? "bg-emerald-500/15 text-emerald-400 ring-emerald-500/20"
                            : ep.status === "distilled"
                            ? "bg-indigo-500/15 text-indigo-400 ring-indigo-500/20"
                            : "bg-gray-500/15 text-gray-400 ring-gray-500/20"
                        }`}>
                          {ep.status}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Summary preview */}
                  {ep.summary && (
                    <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-gray-400">
                      {ep.summary}
                    </p>
                  )}

                  {/* Audio player */}
                  {ep.audio_url && (
                    <AudioPlayer url={ep.audio_url} title={ep.title} />
                  )}

                  {/* No audio fallback */}
                  {!ep.audio_url && (
                    <p className="mt-3 text-xs text-gray-600 italic">Audio not yet generated for this episode.</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <footer className="mt-16 border-t border-white/6 px-6 py-6 text-center text-xs text-gray-600">
        Powered by Lambda 3 · OpenAI TTS (nova) · CloudFront CDN · RSS 2.0
      </footer>
    </main>
  )
}
