import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import { api, apiErrorMessage } from '../api'
import {
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorNote,
  PageHeader,
  PreviewTile,
  Skeleton,
  Spinner,
  Stat,
} from '../components/ui'
import type {
  InsightReportResponse,
  MetricSnapshot,
  PerformanceAnalyticsResponse,
  PerformanceInsight,
  PublishedPost,
  PublishedPostDetail,
  PublishedPostListResponse,
} from '../types'

const PLATFORMS = ['LinkedIn', 'X', 'Instagram', 'YouTube', 'Blog', 'Newsletter', 'TikTok', 'Other']

type ChipTone = 'default' | 'primary' | 'success' | 'warning' | 'error'

const CONFIDENCE_TONE: Record<string, ChipTone> = {
  strong: 'success',
  moderate: 'primary',
  weak: 'warning',
  insufficient: 'default',
}

/** Render an unknown metric as an em dash — visibly different from a real 0. */
function Num({ value, pct = false, digits = 0 }: { value: number | null | undefined; pct?: boolean; digits?: number }) {
  if (value === null || value === undefined) {
    return (
      <span className="text-text-tertiary" title="Not recorded">
        —
      </span>
    )
  }
  if (pct) return <span className="tabular-nums">{(value * 100).toFixed(digits)}%</span>
  return <span className="tabular-nums">{value.toLocaleString(undefined, { maximumFractionDigits: digits })}</span>
}

function InsightCard({ insight }: { insight: PerformanceInsight }) {
  const insufficient = insight.status === 'insufficient_data'
  return (
    <Card className={insufficient ? 'opacity-80' : ''}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 text-sm font-medium text-text-primary">
          {insufficient ? 'Needs more data' : insight.finding}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Chip tone={CONFIDENCE_TONE[insight.confidence] ?? 'default'}>{insight.confidence}</Chip>
          <span className="text-xs tabular-nums text-text-tertiary">n={insight.posts_analyzed}</span>
        </div>
      </div>
      {insufficient && <p className="mt-2 text-sm leading-relaxed text-text-tertiary">{insight.finding}</p>}
      {!insufficient && (
        <p className="mt-2 text-xs text-text-tertiary">
          {insight.metric} · {insight.comparison}
          {insight.observation_period && <> · {insight.observation_period}</>}
        </p>
      )}
      {insight.evidence.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-border-light pt-3 dark:border-border-medium">
          {insight.evidence.slice(0, 4).map((e, i) => (
            <li key={i} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="min-w-0 truncate text-text-secondary">
                {e.title || e.note || `Post ${e.post_id ?? '?'}`}
                {e.platform && <span className="ml-2 text-text-quaternary">{e.platform}</span>}
              </span>
              <span className="shrink-0 tabular-nums text-text-tertiary">
                {e.value !== null && e.value !== undefined ? `${(e.value * 100).toFixed(1)}%` : '—'}
              </span>
            </li>
          ))}
        </ul>
      )}
      {insight.limitations.length > 0 && (
        <details className="mt-3 text-xs text-text-quaternary">
          <summary className="cursor-pointer select-none hover:text-text-secondary">
            Limitations ({insight.limitations.length})
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-4">
            {insight.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      )}
      {insight.recommendation && (
        <p className="mt-3 border-t border-border-light pt-3 text-xs leading-relaxed text-text-secondary dark:border-border-medium">
          <span className="font-semibold text-text-tertiary">Experiment: </span>
          {insight.recommendation}
        </p>
      )}
    </Card>
  )
}

function SnapshotForm({ postId, onDone }: { postId: number; onDone: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fields: { key: string; label: string; step?: string }[] = [
    { key: 'views', label: 'Views' },
    { key: 'impressions', label: 'Impressions' },
    { key: 'likes', label: 'Likes' },
    { key: 'comments', label: 'Comments' },
    { key: 'shares', label: 'Shares' },
    { key: 'saves', label: 'Saves' },
    { key: 'link_clicks', label: 'Link clicks' },
    { key: 'watch_time_seconds', label: 'Watch time (s)', step: '0.1' },
    { key: 'avg_watch_duration_seconds', label: 'Avg watch (s)', step: '0.1' },
    { key: 'audience_retention_pct', label: 'Retention %', step: '0.1' },
    { key: 'ctr_pct', label: 'CTR %', step: '0.1' },
  ]

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, number> = {}
      for (const { key } of fields) {
        const raw = form[key]?.trim()
        if (raw !== undefined && raw !== '') payload[key] = Number(raw)
      }
      await api.post(`/performance/posts/${postId}/snapshots`, payload)
      setForm({})
      onDone()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 border-t border-border-light pt-4 dark:border-border-medium">
      <div className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
        Record a new snapshot (blank = unknown)
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {fields.map(({ key, label, step }) => (
          <label key={key} className="block text-xs text-text-tertiary">
            {label}
            <input
              type="number"
              min="0"
              step={step ?? '1'}
              value={form[key] ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
              className="input mt-1 w-full"
            />
          </label>
        ))}
      </div>
      {error && (
        <div className="mt-3">
          <ErrorNote message={error} />
        </div>
      )}
      <button type="submit" disabled={saving} className="btn btn-primary mt-3">
        {saving ? 'Saving…' : 'Add snapshot'}
      </button>
    </form>
  )
}

function PostDetailPanel({
  post,
  onClose,
  onChanged,
}: {
  post: PublishedPostDetail
  onClose: () => void
  onChanged: () => void
}) {
  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-text-primary">{post.title || '(untitled)'}</div>
          <div className="mt-0.5 text-xs text-text-tertiary">
            {post.platform} · published {new Date(post.published_at).toLocaleDateString()}
            {post.url && (
              <>
                {' · '}
                <a
                  href={post.url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="font-semibold text-primary-600 hover:underline dark:text-primary-400"
                >
                  original post
                </a>
              </>
            )}
          </div>
        </div>
        <button onClick={onClose} className="btn btn-ghost btn-sm">
          Close
        </button>
      </CardHeader>

      <div className="overflow-x-auto px-5 py-4">
        <table className="table">
          <thead>
            <tr>
              <th>Recorded</th>
              <th>Day</th>
              <th className="text-right">Views</th>
              <th className="text-right">Impr.</th>
              <th className="text-right">Likes</th>
              <th className="text-right">Cmt</th>
              <th className="text-right">Shares</th>
              <th className="text-right">Eng/view</th>
            </tr>
          </thead>
          <tbody>
            {post.snapshots.map((s: MetricSnapshot) => {
              const eng = (s.likes ?? 0) + (s.comments ?? 0) + (s.shares ?? 0)
              const hasEng = s.likes !== null || s.comments !== null || s.shares !== null
              const er = hasEng && s.views ? `${((eng / s.views) * 100).toFixed(1)}%` : null
              return (
                <tr key={s.id}>
                  <td className="whitespace-nowrap text-text-quaternary">{new Date(s.recorded_at).toLocaleDateString()}</td>
                  <td>
                    <Num value={s.days_since_published} />
                  </td>
                  <td className="text-right">
                    <Num value={s.views} />
                  </td>
                  <td className="text-right">
                    <Num value={s.impressions} />
                  </td>
                  <td className="text-right">
                    <Num value={s.likes} />
                  </td>
                  <td className="text-right">
                    <Num value={s.comments} />
                  </td>
                  <td className="text-right">
                    <Num value={s.shares} />
                  </td>
                  <td className="text-right">{er ? <span className="tabular-nums">{er}</span> : <Num value={null} />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="px-5 pb-5">
        <SnapshotForm postId={post.id} onDone={onChanged} />
      </div>
    </Card>
  )
}

export function Performance() {
  const [analytics, setAnalytics] = useState<PerformanceAnalyticsResponse | null>(null)
  const [posts, setPosts] = useState<PublishedPost[]>([])
  const [postsTotal, setPostsTotal] = useState(0)
  const [insights, setInsights] = useState<InsightReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [platformFilter, setPlatformFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedPost, setSelectedPost] = useState<PublishedPostDetail | null>(null)
  const [showRegister, setShowRegister] = useState(false)

  // Register-post form
  const [reg, setReg] = useState({
    platform: 'LinkedIn',
    title: '',
    published_at: '',
    url: '',
    external_id: '',
    views: '',
    likes: '',
  })
  const [registering, setRegistering] = useState(false)
  const [registerError, setRegisterError] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (platformFilter) params.platform = platformFilter
      if (startDate) params.start = new Date(startDate).toISOString()
      if (endDate) params.end = new Date(endDate + 'T23:59:59').toISOString()
      const [a, p, ins] = await Promise.all([
        api.get<PerformanceAnalyticsResponse>('/performance/analytics', { params }),
        api.get<PublishedPostListResponse>('/performance/posts', {
          params: { ...(platformFilter ? { platform: platformFilter } : {}), limit: 100 },
        }),
        api.get<InsightReportResponse>('/performance/insights'),
      ])
      setAnalytics(a.data)
      setPosts(p.data.items)
      setPostsTotal(p.data.total)
      setInsights(ins.data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [platformFilter, startDate, endDate])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  async function openPost(id: number) {
    try {
      const { data } = await api.get<PublishedPostDetail>(`/performance/posts/${id}`)
      setSelectedPost(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  async function registerPost(e: FormEvent) {
    e.preventDefault()
    setRegistering(true)
    setRegisterError(null)
    try {
      const payload: Record<string, unknown> = {
        platform: reg.platform,
        title: reg.title,
        published_at: new Date(reg.published_at).toISOString(),
        url: reg.url,
        external_id: reg.external_id,
      }
      const snapshot: Record<string, number> = {}
      if (reg.views.trim() !== '') snapshot.views = Number(reg.views)
      if (reg.likes.trim() !== '') snapshot.likes = Number(reg.likes)
      if (Object.keys(snapshot).length > 0) payload.initial_snapshot = snapshot
      await api.post('/performance/posts', payload)
      setReg({ ...reg, title: '', url: '', external_id: '', views: '', likes: '' })
      setShowRegister(false)
      await loadAll()
    } catch (err) {
      setRegisterError(apiErrorMessage(err))
    } finally {
      setRegistering(false)
    }
  }

  const hasAnyData = (analytics?.post_count ?? 0) > 0

  const filteredPosts = useMemo(() => posts, [posts])

  if (loading && !analytics) {
    return (
      <>
        <PageHeader title="Performance" subtitle="Actual results from your published posts." />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="mt-4">
          <Spinner label="Loading performance data…" />
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Performance"
        title="Performance workspace"
        subtitle="Register published posts and record their real metrics. Every number here comes from your entries — nothing is estimated."
        actions={
          <button onClick={() => setShowRegister((v) => !v)} className="btn btn-primary">
            {showRegister ? 'Close' : 'Register a published post'}
          </button>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorNote message={error} />
        </div>
      )}

      {showRegister && (
        <Card className="mb-5">
          <CardHeader>
            <h2 className="text-sm font-semibold text-text-primary">Register a published post</h2>
            <span className="text-xs text-text-tertiary">Only metrics you enter are stored</span>
          </CardHeader>
          <form onSubmit={registerPost} className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="label" htmlFor="perf-platform">
                Platform *
              </label>
              <select
                id="perf-platform"
                value={reg.platform}
                onChange={(e) => setReg({ ...reg, platform: e.target.value })}
                className="select mt-1 w-full"
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="perf-title">
                Title
              </label>
              <input
                id="perf-title"
                className="input mt-1 w-full"
                value={reg.title}
                onChange={(e) => setReg({ ...reg, title: e.target.value })}
                maxLength={300}
              />
            </div>
            <div>
              <label className="label" htmlFor="perf-date">
                Published date *
              </label>
              <input
                id="perf-date"
                type="date"
                required
                value={reg.published_at}
                onChange={(e) => setReg({ ...reg, published_at: e.target.value })}
                className="input mt-1 w-full"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label" htmlFor="perf-url">
                URL
              </label>
              <input
                id="perf-url"
                type="url"
                value={reg.url}
                placeholder="https://…"
                onChange={(e) => setReg({ ...reg, url: e.target.value })}
                className="input mt-1 w-full"
              />
            </div>
            <div>
              <label className="label" htmlFor="perf-ext">
                External ID
              </label>
              <input
                id="perf-ext"
                className="input mt-1 w-full"
                value={reg.external_id}
                onChange={(e) => setReg({ ...reg, external_id: e.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor="perf-views">
                Initial views
              </label>
              <input
                id="perf-views"
                type="number"
                min="0"
                value={reg.views}
                onChange={(e) => setReg({ ...reg, views: e.target.value })}
                className="input mt-1 w-full"
              />
            </div>
            <div>
              <label className="label" htmlFor="perf-likes">
                Initial likes
              </label>
              <input
                id="perf-likes"
                type="number"
                min="0"
                value={reg.likes}
                onChange={(e) => setReg({ ...reg, likes: e.target.value })}
                className="input mt-1 w-full"
              />
            </div>
            {registerError && (
              <div className="sm:col-span-2 lg:col-span-3">
                <ErrorNote message={registerError} />
              </div>
            )}
            <div className="sm:col-span-2 lg:col-span-3">
              <button type="submit" className="btn btn-primary" disabled={registering}>
                {registering ? 'Saving…' : 'Register post'}
              </button>
            </div>
          </form>
        </Card>
      )}

      {/* Filters — this endpoint supports platform + start/end date params */}
      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-xl border border-border-light bg-bg-secondary px-4 py-3 shadow-xs dark:border-border-medium">
        <div>
          <label className="label" htmlFor="perf-f-platform">
            Platform
          </label>
          <select
            id="perf-f-platform"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            className="select mt-1"
          >
            <option value="">All</option>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="perf-f-from">
            From
          </label>
          <input
            id="perf-f-from"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="input mt-1"
          />
        </div>
        <div>
          <label className="label" htmlFor="perf-f-to">
            To
          </label>
          <input
            id="perf-f-to"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="input mt-1"
          />
        </div>
        {(platformFilter || startDate || endDate) && (
          <button
            onClick={() => {
              setPlatformFilter('')
              setStartDate('')
              setEndDate('')
            }}
            className="btn btn-ghost btn-sm mb-0.5"
          >
            Clear filters
          </button>
        )}
        {analytics && (
          <span className="mb-1 ml-auto text-xs text-text-tertiary">
            Coverage: {analytics.date_range.start ? new Date(analytics.date_range.start).toLocaleDateString() : '—'} →{' '}
            {analytics.date_range.end ? new Date(analytics.date_range.end).toLocaleDateString() : '—'}
          </span>
        )}
      </div>

      {!hasAnyData ? (
        <EmptyState
          icon="◈"
          title="No published posts yet"
          body="Register a post you have already published and enter its actual results. ContentMind only shows numbers you record — nothing is estimated."
          action={
            <button onClick={() => setShowRegister(true)} className="btn btn-primary">
              Register your first published post
            </button>
          }
        />
      ) : (
        <>
          {analytics && analytics.warnings.length > 0 && (
            <div className="mb-4 space-y-1">
              {analytics.warnings.map((w, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-warning-200 bg-warning-50 px-3.5 py-2 text-xs text-warning-700 dark:border-warning-800 dark:bg-warning-900/30 dark:text-warning-300"
                >
                  ⚠ {w}
                </div>
              ))}
            </div>
          )}

          {/* Summary cards */}
          {analytics && (
            <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Registered posts"
                value={analytics.post_count}
                hint={`${analytics.posts_with_metrics} with metrics`}
              />
              <Stat label="Total views" value={<Num value={analytics.total_views} />} hint="sum of latest snapshots" tone="brand" />
              <Stat
                label="Avg engagement / view"
                value={<Num value={analytics.avg_engagement_rate_per_view} pct digits={1} />}
                hint="(likes+comments+shares) / views"
                tone="success"
              />
              <Stat
                label="Avg engagement / impression"
                value={<Num value={analytics.avg_engagement_rate_per_impression} pct digits={2} />}
                hint="separate denominator — not interchangeable"
              />
            </div>
          )}

          {/* Platform breakdown */}
          {analytics && analytics.by_platform.length > 0 && (
            <Card className="mb-5">
              <CardHeader>
                <h2 className="text-sm font-semibold text-text-primary">By platform</h2>
              </CardHeader>
              <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
                {analytics.by_platform.map((p) => (
                  <div
                    key={p.platform}
                    className="rounded-xl border border-border-light bg-bg-primary/70 p-3.5 dark:border-border-medium dark:bg-ink-850/70"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold text-text-primary">{p.platform}</span>
                      <span className="text-xs tabular-nums text-text-tertiary">{p.post_count} posts</span>
                    </div>
                    <dl className="mt-2.5 space-y-1.5 text-xs">
                      <div className="flex justify-between">
                        <dt className="text-text-tertiary">Views</dt>
                        <dd>
                          <Num value={p.total_views} />
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-text-tertiary">Eng/view</dt>
                        <dd>
                          <Num value={p.avg_engagement_rate_per_view} pct digits={1} />
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-text-tertiary">CTR (reported)</dt>
                        <dd>
                          <Num value={p.avg_ctr_pct !== null ? p.avg_ctr_pct / 100 : null} pct digits={1} />
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-text-tertiary">Retention</dt>
                        <dd>
                          <Num value={p.avg_retention_pct !== null ? p.avg_retention_pct / 100 : null} pct digits={0} />
                        </dd>
                      </div>
                    </dl>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Post detail */}
          {selectedPost && (
            <PostDetailPanel
              post={selectedPost}
              onClose={() => setSelectedPost(null)}
              onChanged={async () => {
                const id = selectedPost.id
                await loadAll()
                try {
                  const { data } = await api.get<PublishedPostDetail>(`/performance/posts/${id}`)
                  setSelectedPost(data)
                } catch {
                  setSelectedPost(null)
                }
              }}
            />
          )}

          {/* Posts list */}
          <Card className="mb-5 overflow-hidden">
            <CardHeader>
              <h2 className="text-sm font-semibold text-text-primary">Published posts</h2>
              <Chip>{postsTotal}</Chip>
            </CardHeader>
            {filteredPosts.length === 0 ? (
              <p className="px-5 py-6 text-sm text-text-tertiary">No posts match the current filters.</p>
            ) : (
              <div className="divide-y divide-border-light dark:divide-border-medium">
                {filteredPosts.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => openPost(p.id)}
                    className="flex w-full flex-wrap items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-bg-primary/70 dark:hover:bg-ink-850/70"
                  >
                    <PreviewTile seed={p.external_id || p.title || String(p.id)} className="h-10 w-10 shrink-0 text-xs" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-text-primary">{p.title || '(untitled)'}</div>
                      <div className="mt-0.5 text-xs text-text-tertiary">
                        {p.platform} · {new Date(p.published_at).toLocaleDateString()} · {p.snapshot_count} snapshot
                        {p.snapshot_count === 1 ? '' : 's'}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-4 text-xs tabular-nums text-text-secondary">
                      <span>
                        <span className="text-text-tertiary">views </span>
                        <Num value={p.latest_snapshot?.views ?? null} />
                      </span>
                      <span>
                        <span className="text-text-tertiary">likes </span>
                        <Num value={p.latest_snapshot?.likes ?? null} />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </Card>

          {/* Insights */}
          <div>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-base font-semibold tracking-tight text-text-primary">Insights</h2>
              {insights && <span className="text-xs text-text-tertiary">{insights.message}</span>}
            </div>
            {insights && insights.insights.length > 0 ? (
              <div className="grid gap-4 lg:grid-cols-2">
                {insights.insights.map((ins) => (
                  <InsightCard key={ins.key} insight={ins} />
                ))}
              </div>
            ) : (
              <EmptyState
                icon="◈"
                title="Not enough data for insights"
                body={insights?.message ?? 'Register posts and record their metrics to unlock evidence-based insights about your topics, formats, platforms, and review scores.'}
              />
            )}
          </div>
        </>
      )}
    </>
  )
}
