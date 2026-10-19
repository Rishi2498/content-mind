import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { Bar, Card, Chip, EmptyState, ErrorNote, SectionHeader, Skeleton } from '../components/ui'
import type { ContentItem } from '../types'
import { fullDate, pct } from '../utils/format'

export function ContentLibrary() {
  const [items, setItems] = useState<ContentItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [platform, setPlatform] = useState('all')
  const [sort, setSort] = useState<'recent' | 'engagement' | 'reach'>('recent')

  const load = () => {
    setError(null)
    api
      .get<{ items: ContentItem[]; total: number }>('/content', { params: { limit: 200 } })
      .then((res) => setItems(res.data.items))
      .catch((err) => setError(apiErrorMessage(err)))
  }

  useEffect(load, [])

  const platforms = useMemo(
    () => Array.from(new Set((items ?? []).map((i) => i.platform))).sort(),
    [items],
  )

  const filtered = useMemo(() => {
    let rows = items ?? []
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      rows = rows.filter(
        (i) =>
          i.title.toLowerCase().includes(q) ||
          i.topic.toLowerCase().includes(q) ||
          i.body.toLowerCase().includes(q),
      )
    }
    if (platform !== 'all') rows = rows.filter((i) => i.platform === platform)
    return [...rows].sort((a, b) => {
      if (sort === 'engagement') return b.engagement_rate - a.engagement_rate
      if (sort === 'reach') return b.impressions - a.impressions
      return new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
    })
  }, [items, query, platform, sort])

  if (error) {
    return (
      <>
        <SectionHeader title="Content Library" />
        <ErrorNote message={error} />
      </>
    )
  }

  return (
    <>
      <SectionHeader
        title="Content Library"
        subtitle={
          items
            ? `${items.length} item${items.length === 1 ? '' : 's'} · showing ${filtered.length}`
            : 'Everything ContentMind knows about your content.'
        }
        action={
          <Link to="/content/new" className="btn btn-primary">
            Add content
          </Link>
        }
      />

      {items && items.length > 0 && (
        <Card className="mb-4 flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label className="label" htmlFor="lib-search">
              Search
            </label>
            <input
              id="lib-search"
              className="field"
              placeholder="Title, topic, or body text…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="lib-platform">
              Platform
            </label>
            <select
              id="lib-platform"
              className="field"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="all">All platforms</option>
              {platforms.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="lib-sort">
              Sort by
            </label>
            <select
              id="lib-sort"
              className="field"
              value={sort}
              onChange={(e) => setSort(e.target.value as typeof sort)}
            >
              <option value="recent">Most recent</option>
              <option value="engagement">Engagement rate</option>
              <option value="reach">Impressions</option>
            </select>
          </div>
        </Card>
      )}

      {items === null ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Your library is empty"
          body="Add your published content — the more you add, the more precisely ContentMind can tell you what worked. No metrics yet? It will still learn topics and formats."
          action={
            <div className="flex gap-2.5">
              <Link to="/content/new" className="btn btn-primary">
                Add content
              </Link>
              <Link to="/demo" className="btn btn-secondary">
                Seed demo data
              </Link>
            </div>
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="Nothing matches those filters"
          body="Try a different search term, or clear the platform filter."
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((item) => (
            <ContentRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </>
  )
}

function ContentRow({ item }: { item: ContentItem }) {
  const maxRate = item.impressions > 0 ? 1 : 0
  return (
    <Card hover className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-64 flex-1">
        <div className="text-sm font-medium">{item.title}</div>
        <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-tertiary">{item.body}</div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Chip tone="primary">{item.platform}</Chip>
          <Chip>{item.content_type}</Chip>
          <Chip>{item.topic}</Chip>
          <span className="text-[0.68rem] text-text-tertiary">{fullDate(item.published_at)}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-5 sm:gap-8">
        <MetricBlock
          label="Engagement"
          value={item.impressions > 0 ? pct(item.engagement_rate) : 'no data'}
          tone={item.engagement_rate > 0.1 ? 'success' : 'default'}
        />
        <MetricBlock
          label="Impressions"
          value={item.impressions > 0 ? item.impressions.toLocaleString() : '—'}
        />
        <div className="min-w-24">
          <div className="text-[0.68rem] uppercase tracking-wider text-text-tertiary">CTR</div>
          <div className="mt-1 text-sm font-semibold tabular-nums">
            {item.impressions > 0 ? pct(item.ctr) : '—'}
          </div>
          <div className="mt-2">
            <Bar value={item.engagement_rate} max={maxRate} tone="success" />
          </div>
        </div>
      </div>
    </Card>
  )
}

function MetricBlock({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'success' | 'warning' | 'error' }) {
  return (
    <div>
      <div className="text-[0.68rem] uppercase tracking-wider text-text-tertiary">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${tone === 'success' ? 'text-success-600 dark:text-success-400' : tone === 'warning' ? 'text-warning-600 dark:text-warning-400' : tone === 'error' ? 'text-error-600 dark:text-error-400' : 'text-text-primary'}`}>{value}</div>
    </div>
  )
}