import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { useHealth } from '../context/HealthContext'
import { Card, Chip, EmptyState, ErrorNote, SectionHeader, Spinner } from '../components/ui'
import type { LearnedInsight, LearnedResponse, MemoryRecord } from '../types'
import { dayLabel } from '../utils/format'

const CATEGORY_ORDER = [
  'performance',
  'topics',
  'formats',
  'audience',
  'content_history',
  'strategy',
  'gaps',
  'brand',
]

const CATEGORY_LABELS: Record<string, string> = {
  performance: 'What performs',
  topics: 'Topics that work',
  formats: 'Formats that work',
  audience: 'Audience signals',
  content_history: 'From your content',
  strategy: 'Strategy patterns',
  gaps: 'Gaps to fill',
  brand: 'Brand voice',
}

export function Learned() {
  const { health } = useHealth()
  const [data, setData] = useState<LearnedResponse | null>(null)
  const [memories, setMemories] = useState<MemoryRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<string>('all')

  useEffect(() => {
    Promise.all([
      api.get<LearnedResponse>('/memory'),
      api.get<{ memories: MemoryRecord[] }>('/memory/list?limit=60'),
    ])
      .then(([learned, list]) => {
        setData(learned.data)
        setMemories(list.data.memories)
      })
      .catch((err) => setError(apiErrorMessage(err)))
  }, [])

  const categories = useMemo(() => {
    if (!data) return []
    const keys = Object.keys(data.categories)
    return [
      ...CATEGORY_ORDER.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !CATEGORY_ORDER.includes(k)),
    ]
  }, [data])

  if (error) {
    return (
      <>
        <SectionHeader title="What I've Learned" />
        <ErrorNote message={error} />
      </>
    )
  }
  if (!data) return <Spinner label="Reading long-term memory…" />

  if (data.total === 0) {
    return (
      <>
        <SectionHeader title="What I've Learned" />
        <EmptyState
          title="Nothing learned yet"
          body="ContentMind learns from every item you add. Once there is history, the patterns it extracts show up here — with the source attached to each one."
          action={
            <div className="flex gap-2.5">
              <Link to="/content/new" className="btn btn-primary">
                Add content
              </Link>
              <Link to="/demo" className="btn btn-secondary">
                Run the demo
              </Link>
            </div>
          }
        />
      </>
    )
  }

  const visible = active === 'all' ? data.insights : (data.categories[active] ?? [])
  const degraded = data.degraded || health?.memory.degraded

  return (
    <>
      <SectionHeader
        title="What I've Learned"
        subtitle="The long-term memory, made visible. Every insight below traces back to the content that produced it."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatPill label="Insights" value={data.total} />
        <StatPill label="Memories" value={data.memory_count} />
        <StatPill label="Items analysed" value={data.content_analyzed} />
        {degraded && <Chip tone="warning">served from local fallback</Chip>}
      </div>

      <div className="mb-5 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setActive('all')}
          className={active === 'all' ? 'chip border-brand-500 text-brand-400' : 'chip'}
        >
          All ({data.insights.length})
        </button>
        {categories.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setActive(key)}
            className={active === key ? 'chip border-brand-500 text-brand-400' : 'chip'}
          >
            {CATEGORY_LABELS[key] ?? key} ({data.categories[key].length})
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2.5 lg:col-span-2">
          {visible.slice(0, 60).map((insight) => (
            <InsightRow key={insight.id} insight={insight} />
          ))}
        </div>

        <div className="space-y-4">
          {data.message && (
            <Card>
              <h2 className="text-sm font-semibold">How this was built</h2>
              <p className="mt-2 text-sm leading-relaxed text-ink-300">{data.message}</p>
            </Card>
          )}

          <Card>
            <h2 className="mb-1 text-sm font-semibold">Raw memories</h2>
            <p className="mb-3 text-xs text-ink-400">
              The statements actually stored in {health?.memory.backend ?? 'memory'}.
            </p>
            {!memories ? (
              <p className="text-sm text-ink-400">Loading…</p>
            ) : memories.length === 0 ? (
              <p className="text-sm text-ink-400">No raw statements available.</p>
            ) : (
              <ul className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                {memories.map((m) => (
                  <li key={m.id} className="rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-[0.65rem] text-ink-400">
                      <span className="rounded border border-ink-600 px-1.5 py-0.5 uppercase">
                        {m.kind}
                      </span>
                      {m.document_id && <span>{m.document_id}</span>}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-ink-200">{m.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function InsightRow({ insight }: { insight: LearnedInsight }) {
  return (
    <Card hover>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-relaxed text-ink-100">{insight.text}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[0.68rem] text-ink-400">
            <Chip>{insight.category}</Chip>
            <span>via {insight.origin.replace(/_/g, ' ')}</span>
            {insight.content_id && (
              <Link to="/content" className="text-brand-400 hover:underline">
                source item #{insight.content_id}
              </Link>
            )}
            {insight.created_at && <span>{dayLabel(insight.created_at)}</span>}
          </div>
          {insight.evidence && (
            <p className="mt-1.5 font-mono text-[0.68rem] leading-relaxed text-ink-600">
              {insight.evidence}
            </p>
          )}
        </div>
        <ConfidenceBadge value={insight.confidence} />
      </div>
    </Card>
  )
}

function ConfidenceBadge({ value }: { value: number }) {
  const pctValue = Math.round(value * 100)
  const tone = value >= 0.8 ? 'text-mint-400' : value >= 0.5 ? 'text-amber-glow' : 'text-ink-400'
  return (
    <div className="shrink-0 text-right" title="Confidence in this insight">
      <div className={`text-sm font-semibold tabular-nums ${tone}`}>{pctValue}%</div>
      <div className="text-[0.6rem] uppercase tracking-wider text-ink-600">conf</div>
    </div>
  )
}

function StatPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-1.5">
      <span className="text-[0.68rem] uppercase tracking-wider text-ink-400">{label} </span>
      <span className="text-sm font-semibold tabular-nums">{value.toLocaleString()}</span>
    </div>
  )
}
