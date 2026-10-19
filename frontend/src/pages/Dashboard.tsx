import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api, apiErrorMessage } from '../api'
import { useHealth } from '../context/HealthContext'
import type { AnalyticsResponse, GapResponse, InstagramConnection, InstagramConnectionListResponse, MemoryRecord } from '../types'
import { Card, Chip, EmptyState, PageHeader, PreviewTile, Spinner, Stat } from '../components/ui'
import { MemoryCitations } from '../components/MemoryCitations'
import { compact, fullDate, indexLabel, pct } from '../utils/format'

const DEMO_QUESTION = 'What should I post next week?'

const ICONS = {
  sparkles: (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3z" />
      <path d="M18.5 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1z" />
    </svg>
  ),
  library: (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5.5A2.5 2.5 0 016.5 3H11v16H6.5A2.5 2.5 0 004 21.5v-16z" />
      <path d="M20 5.5A2.5 2.5 0 0017.5 3H13v16h4.5a2.5 2.5 0 012.5 2.5v-16z" />
    </svg>
  ),
  trend: (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l6-6 4 4 7-7" />
      <path d="M14 8h7v7" />
    </svg>
  ),
  reach: (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.5" />
    </svg>
  ),
  instagram: (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.2" cy="6.8" r="1" fill="currentColor" stroke="none" />
    </svg>
  ),
}

export function Dashboard() {
  const { health } = useHealth()
  const { data: analytics } = useFetch<AnalyticsResponse>('/analytics')

  if (!health) return <Spinner label="Loading your strategy workspace…" />

  const count = health.database.content_count
  const hasHistory = count > 0

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Content Overview"
        subtitle="ContentMind reasons over your history, remembers what it learns, and shows its work."
        actions={
          <>
            <Link to="/content/new" className="btn btn-secondary">
              Add content
            </Link>
            {hasHistory ? (
              <Link to="/planner" className="btn btn-primary">
                Generate this week's plan
              </Link>
            ) : (
              <Link to="/demo" className="btn btn-primary">
                Run the memory demo
              </Link>
            )}
          </>
        }
      />

      <KpiRow contentCount={count} analytics={analytics} />

      {!hasHistory ? (
        <div className="mt-6">
          <EmptyState
            icon="✦"
            title="No content history yet"
            body="ContentMind cannot personalise anything until it has seen what you have published. Add a few posts, or run the memory demo to see the before/after in one click."
            action={
              <>
                <Link to="/content/new" className="btn btn-primary">
                  Add your content
                </Link>
                <Link to="/demo" className="btn btn-secondary">
                  Run the demo
                </Link>
              </>
            }
          />
        </div>
      ) : (
        <DashboardWithHistory question={DEMO_QUESTION} analytics={analytics} />
      )}
    </>
  )
}

function KpiRow({ contentCount, analytics }: { contentCount: number; analytics: AnalyticsResponse | null }) {
  const h = useHealth().health
  if (!h) return null

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Stat
        label="Memories"
        value={h.memory.memory_count.toLocaleString()}
        hint={`bank: ${h.memory.bank}`}
        tone="brand"
        icon={ICONS.sparkles}
      />
      <Stat
        label="Content items"
        value={contentCount.toLocaleString()}
        hint={`${h.database.insight_count} insights extracted`}
        icon={ICONS.library}
      />
      <Stat
        label="Avg engagement"
        value={analytics ? pct(analytics.avg_engagement_rate) : '—'}
        hint={analytics ? `median ${pct(analytics.median_engagement_rate)}` : 'loading analytics…'}
        tone="success"
        icon={ICONS.trend}
      />
      <Stat
        label="Impressions"
        value={analytics ? compact(analytics.total_impressions) : '—'}
        hint={
          analytics
            ? `${analytics.published_with_metrics}/${analytics.content_count} items with metrics`
            : 'loading analytics…'
        }
        icon={ICONS.reach}
      />
    </div>
  )
}

function DashboardWithHistory({
  question,
  analytics,
}: {
  question: string
  analytics: AnalyticsResponse | null
}) {
  const { data: gaps } = useFetch<GapResponse>('/analytics/gaps?limit=5')
  const { data: context } = useFetch<{ memories: MemoryRecord[]; summary: Record<string, unknown> }>(
    `/memory/context?request=${encodeURIComponent(question)}`,
  )
  const { data: instagram } = useFetch<InstagramConnectionListResponse>('/instagram/connections')

  if (!analytics) {
    return (
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <div className="card h-80 animate-pulse lg:col-span-2" />
        <div className="card h-80 animate-pulse" />
      </div>
    )
  }

  const topTopic = analytics.top_topic
  const topPlatform = analytics.top_platform

  return (
    <div className="mt-6 space-y-6">
      {/* Trend + publishing summary */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Engagement &amp; reach trend</h2>
              <p className="mt-0.5 text-xs text-text-tertiary">
                Average engagement rate and impressions by publication date.
              </p>
            </div>
            <Link to="/analytics" className="text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400">
              Full analytics →
            </Link>
          </div>
          <TrendChart analytics={analytics} />
        </Card>

        <Card className="flex flex-col p-5">
          <h2 className="text-sm font-semibold text-text-primary">Publishing snapshot</h2>
          <p className="mt-0.5 text-xs text-text-tertiary">Where your reach comes from right now.</p>

          <div className="mt-4 space-y-3">
            {analytics.by_platform.slice(0, 4).map((p) => (
              <div key={p.key}>
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="truncate font-medium text-text-primary">{p.key}</span>
                  <span className="shrink-0 tabular-nums text-text-tertiary">{compact(p.impressions)} impr</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-bg-tertiary dark:bg-ink-700">
                  <div
                    className="h-full rounded-full bg-primary-500"
                    style={{
                      width: `${Math.round(
                        (p.impressions / Math.max(1, analytics.by_platform[0]?.impressions || 1)) * 100,
                      )}%`,
                    }}
                  />
                </div>
              </div>
            ))}
            {analytics.by_platform.length === 0 && (
              <p className="text-sm text-text-tertiary">No platform data yet.</p>
            )}
          </div>

          <div className="mt-4 space-y-2 border-t border-border-light pt-4 text-xs dark:border-border-medium">
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-tertiary">Strongest topic</span>
              <span className="truncate font-medium text-text-primary">{topTopic?.key ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-tertiary">Best platform</span>
              <span className="truncate font-medium text-text-primary">{topPlatform?.key ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-tertiary">Content format</span>
              <span className="truncate font-medium text-text-primary">{analytics.top_content_type?.key ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-tertiary">Target audience</span>
              <span className="truncate font-medium text-text-primary">{analytics.top_audience?.key ?? '—'}</span>
            </div>
          </div>

          {analytics.warnings.length > 0 && (
            <ul className="mt-4 space-y-1.5 border-t border-border-light pt-4 dark:border-border-medium">
              {analytics.warnings.slice(0, 3).map((w) => (
                <li key={w} className="flex gap-1.5 text-xs leading-relaxed text-warning-600 dark:text-warning-400">
                  <span aria-hidden="true">⚠</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* Top content + AI recommendations */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Top performing content</h2>
              <p className="mt-0.5 text-xs text-text-tertiary">Ranked by engagement rate, not vanity reach.</p>
            </div>
            <Link to="/performance" className="text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400">
              Performance →
            </Link>
          </div>

          {analytics.best_content.length === 0 ? (
            <p className="py-6 text-center text-sm text-text-tertiary">
              No items with metrics yet — register results on the Performance page to rank your content.
            </p>
          ) : (
            <ul className="divide-y divide-border-light dark:divide-border-medium">
              {analytics.best_content.slice(0, 5).map((item, i) => (
                <li key={item.id} className="flex items-center gap-4 py-3 first:pt-0 last:pb-0">
                  <span className="w-4 shrink-0 text-center text-xs font-bold text-text-quaternary tabular-nums">
                    {i + 1}
                  </span>
                  <PreviewTile seed={item.topic || item.title} className="h-11 w-11 shrink-0 text-sm" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text-primary">{item.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.7rem] text-text-tertiary">
                      <Chip tone="default">{item.platform}</Chip>
                      <span>{item.topic}</span>
                      <span aria-hidden="true">·</span>
                      <span>{fullDate(item.published_at)}</span>
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-sm font-semibold tabular-nums text-success-600 dark:text-success-400">
                      {pct(item.engagement_rate)}
                    </div>
                    <div className="text-[0.7rem] tabular-nums text-text-tertiary">
                      {compact(item.impressions)} impr · ctr {pct(item.ctr)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex flex-col p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300">
              {ICONS.sparkles}
            </div>
            <h2 className="text-sm font-semibold text-text-primary">AI recommendations</h2>
          </div>
          <p className="mt-1 text-xs text-text-tertiary">Gaps detected across your content history.</p>

          <div className="mt-4 flex-1 space-y-3">
            {gaps?.gaps?.length ? (
              gaps.gaps.slice(0, 4).map((gap) => (
                <div key={gap.topic} className="rounded-xl border border-border-light bg-bg-primary/70 p-3 dark:border-border-medium dark:bg-ink-850/70">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-text-primary">{gap.topic}</span>
                    <Chip tone={gap.priority === 'high' ? 'warning' : gap.priority === 'medium' ? 'primary' : 'default'}>
                      {gap.priority}
                    </Chip>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-text-secondary">{gap.reason}</p>
                  {gap.suggested_formats.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {gap.suggested_formats.slice(0, 3).map((f) => (
                        <span key={f} className="rounded-md bg-bg-secondary px-1.5 py-0.5 text-[0.65rem] text-text-tertiary ring-1 ring-border-light dark:bg-ink-800 dark:ring-border-medium">
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="py-4 text-center text-sm text-text-tertiary">
                No gaps yet — add more content to sharpen this.
              </p>
            )}
          </div>

          <div className="mt-4 flex flex-col gap-2 border-t border-border-light pt-4 dark:border-border-medium">
            <Link to="/planner" className="btn btn-primary btn-sm w-full">
              Turn gaps into a plan
            </Link>
            <Link to="/strategy" className="btn btn-secondary btn-sm w-full">
              Open strategy workspace
            </Link>
          </div>
        </Card>
      </div>

      {/* Instagram + memory recall */}
      <div className="grid gap-4 lg:grid-cols-3">
        <InstagramPanel connections={instagram?.items ?? []} />
        <Card className="p-5 lg:col-span-2">
          <div className="mb-1 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-text-primary">Memory recalled for today</h2>
            <Link to="/learned" className="text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400">
              What it's learned →
            </Link>
          </div>
          <p className="mb-3 text-xs text-text-tertiary">
            {context?.summary
              ? `${(context.summary.memories_recalled as number) ?? 0} of ${analytics.content_count} items consulted for “${question}”`
              : 'Recalling relevant memories…'}
          </p>
          {context?.memories ? (
            <MemoryCitations memories={context.memories} title="Recalled now" />
          ) : (
            <p className="text-sm text-text-tertiary">Recalling…</p>
          )}
        </Card>
      </div>

      {analytics.topic_coverage.length > 0 && (
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-text-primary">Topic coverage</h2>
          <p className="mb-4 mt-0.5 text-xs text-text-tertiary">
            How much you have published per topic, and when. Stale winners are the cheapest wins.
          </p>
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {analytics.topic_coverage.slice(0, 9).map((topic) => (
              <div key={topic.topic} className="rounded-xl border border-border-light bg-bg-primary/70 px-3.5 py-2.5 dark:border-border-medium dark:bg-ink-850/70">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-text-primary">{topic.topic}</span>
                  <span
                    className={`text-xs font-semibold tabular-nums ${
                      topic.index_vs_average >= 1 ? 'text-success-600 dark:text-success-400' : 'text-text-tertiary'
                    }`}
                  >
                    {indexLabel(topic.index_vs_average)}
                  </span>
                </div>
                <div className="mt-0.5 text-[0.7rem] text-text-tertiary">
                  {topic.count} item{topic.count === 1 ? '' : 's'}
                  {topic.days_since_published !== null &&
                    ` · ${fullDate(new Date(Date.now() - topic.days_since_published * 86400000).toISOString())} ago`}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function InstagramPanel({ connections }: { connections: InstagramConnection[] }) {
  const conn = connections[0]
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-error-50 text-error-500 dark:bg-error-900/40">
          {ICONS.instagram}
        </div>
        <h2 className="text-sm font-semibold text-text-primary">Instagram</h2>
        {conn && (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-success-50 px-2 py-0.5 text-[0.65rem] font-semibold text-success-600 dark:bg-success-900/40 dark:text-success-400">
            <span className="h-1.5 w-1.5 rounded-full bg-success-500" />
            Connected
          </span>
        )}
      </div>

      {conn ? (
        <div className="mt-4 flex-1">
          <div className="flex items-center gap-3">
            {conn.profile_picture_url ? (
              <img src={conn.profile_picture_url} alt="" className="h-11 w-11 rounded-full object-cover ring-2 ring-border-light dark:ring-border-medium" />
            ) : (
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary-50 font-bold uppercase text-primary-600 dark:bg-primary-900/40 dark:text-primary-300">
                {conn.username.slice(0, 1)}
              </div>
            )}
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-text-primary">@{conn.username}</div>
              <div className="text-xs text-text-tertiary">{conn.account_type}</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-bg-primary/70 py-2.5 dark:bg-ink-850/70">
              <div className="text-sm font-semibold tabular-nums text-text-primary">
                {conn.followers_count?.toLocaleString() ?? '—'}
              </div>
              <div className="text-[0.65rem] uppercase tracking-wide text-text-tertiary">Followers</div>
            </div>
            <div className="rounded-xl bg-bg-primary/70 py-2.5 dark:bg-ink-850/70">
              <div className="text-sm font-semibold tabular-nums text-text-primary">{conn.media_count ?? '—'}</div>
              <div className="text-[0.65rem] uppercase tracking-wide text-text-tertiary">Posts</div>
            </div>
            <div className="rounded-xl bg-bg-primary/70 py-2.5 dark:bg-ink-850/70">
              <div className="text-sm font-semibold text-text-primary">
                {conn.last_sync_at ? fullDate(conn.last_sync_at) : 'Never'}
              </div>
              <div className="text-[0.65rem] uppercase tracking-wide text-text-tertiary">Last sync</div>
            </div>
          </div>
          <Link to="/instagram" className="btn btn-secondary btn-sm mt-4 w-full">
            Manage connection
          </Link>
        </div>
      ) : (
        <div className="mt-4 flex flex-1 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border-medium bg-bg-primary/50 px-4 py-6 text-center dark:bg-ink-850/50">
          <p className="text-xs leading-relaxed text-text-secondary">
            Connect Instagram to import media and sync real performance metrics automatically.
          </p>
          <Link to="/instagram" className="btn btn-primary btn-sm">
            Connect Instagram
          </Link>
        </div>
      )}
    </Card>
  )
}

function TrendChart({ analytics }: { analytics: AnalyticsResponse }) {
  const series = (analytics.over_time ?? []).map((p) => ({
    date: p.period.length > 10 ? p.period.slice(5) : p.period,
    engagement: Number((p.engagement_rate * 100).toFixed(2)),
    impressions: p.impressions,
  }))

  if (series.length < 2) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border-medium bg-bg-primary/50 text-sm text-text-tertiary dark:bg-ink-850/50">
        Need at least two dated items to plot a trend.
      </div>
    )
  }

  return (
    <div className="mt-4 h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ left: -18, right: 6, top: 4 }}>
          <defs>
            <linearGradient id="engagementFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary-500)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--color-primary-500)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--color-border-light)" strokeDasharray="3 4" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            stroke="var(--color-border-medium)"
            minTickGap={28}
            tickLine={false}
          />
          <YAxis
            yAxisId="left"
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            stroke="var(--color-border-medium)"
            tickFormatter={(v: number) => `${v}%`}
            tickLine={false}
            width={46}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            stroke="var(--color-border-medium)"
            tickFormatter={(v: number) => compact(v)}
            tickLine={false}
            width={44}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border-medium)',
              borderRadius: 10,
              fontSize: 12,
              boxShadow: 'var(--shadow-md)',
            }}
            formatter={(value, name) => [
              name === 'engagement' ? `${Number(value).toFixed(2)}%` : Number(value).toLocaleString(),
              name === 'engagement' ? 'Engagement rate' : 'Impressions',
            ]}
          />
          <Area
            yAxisId="right"
            type="monotone"
            dataKey="impressions"
            stroke="var(--color-mint-500)"
            strokeWidth={1.5}
            fill="none"
            strokeDasharray="4 4"
            dot={false}
          />
          <Area
            yAxisId="left"
            type="monotone"
            dataKey="engagement"
            stroke="var(--color-primary-500)"
            strokeWidth={2.5}
            fill="url(#engagementFill)"
            dot={{ r: 3, fill: 'var(--color-primary-500)', strokeWidth: 0 }}
            activeDot={{ r: 4.5 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Minimal GET helper — the app only needs read-on-mount fetching for these. */
function useFetch<T>(url: string): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .get<T>(url)
      .then((res) => {
        if (active) setData(res.data)
      })
      .catch((err) => {
        if (active) setError(apiErrorMessage(err))
      })
    return () => {
      active = false
    }
  }, [url])

  return { data, error }
}
