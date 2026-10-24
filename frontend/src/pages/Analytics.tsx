import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar as RechartsBar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api, apiErrorMessage } from '../api'
import { Bar, Card, Chip, EmptyState, ErrorNote, PageHeader, PreviewTile, SegmentedControl, Spinner, Stat } from '../components/ui'
import { Tooltip as RechartsTooltip } from 'recharts'
import type { AnalyticsResponse, GroupStat } from '../types'
import { compact, fullDate, indexLabel, pct } from '../utils/format'

const BAR_COLOR = (v: number) => (v >= 1 ? '#16A34A' : v >= 0.8 ? '#D97706' : '#DC2626')

const PIE_COLORS = ['#635BFF', '#22C67D', '#F5B544', '#F2557A', '#5B6CFF', '#4ADE9B', '#7C8CFF', '#98A2B3']

const CHART_TOOLTIP = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border-medium)',
  borderRadius: 10,
  fontSize: 12,
  boxShadow: 'var(--shadow-md)',
}

type Dimension = 'by_topic' | 'by_platform' | 'by_content_type' | 'by_audience'

export function Analytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dimension, setDimension] = useState<Dimension>('by_topic')

  useEffect(() => {
    api
      .get<AnalyticsResponse>('/analytics')
      .then((res) => setData(res.data))
      .catch((err) => setError(apiErrorMessage(err)))
  }, [])

  if (error) {
    return (
      <>

        <PageHeader title="Analytics" subtitle="Every number is derived from the content you have recorded." />
        <ErrorNote message={error} />
      </>
    )
  }
  if (!data) {
    return (
      <>

        <PageHeader title="Analytics" />
        <Spinner label="Crunching your numbers…" />
      </>
    )
  }

  if (data.content_count === 0) {
    return (
      <>
        <PageHeader title="Analytics" subtitle="Every number is derived from the content you have recorded, not from a black box." />
        <EmptyState
          icon="◈"
          title="No data to analyse"
          body="Analytics are calculated from your content history. Add some content and this page fills in."
          action={
            <Link to="/content/new" className="btn btn-primary">
              Add content
            </Link>
          }
        />
      </>
    )
  }

  const coverageStart = data.date_range.start ? fullDate(data.date_range.start) : '—'
  const coverageEnd = data.date_range.end ? fullDate(data.date_range.end) : '—'

  const groups = data[dimension]
  const chartData = groups.map((g) => ({
    name: g.key.length > 18 ? `${g.key.slice(0, 17)}…` : g.key,
    fullName: g.key,
    index: g.index_vs_average,
    engagement: Number((g.avg_engagement_rate * 100).toFixed(2)),
    count: g.count,
  }))

  const trend = (data.over_time ?? []).map((p) => ({
    date: p.period.length > 10 ? p.period.slice(5) : p.period,
    engagement: Number((p.engagement_rate * 100).toFixed(2)),
    impressions: p.impressions,
  }))

  const platformShare = data.by_platform
    .filter((p) => p.impressions > 0)
    .map((p) => ({ name: p.key, value: p.impressions }))
    .slice(0, 6)

  return (
    <>
      <PageHeader
        eyebrow="Analytics"
        title="Analytics workspace"
        subtitle="Every number is derived from the content you have recorded, not from a black box."
        actions={
          <Link to="/content/new" className="btn btn-secondary">
            Add content
          </Link>
        }
      />

      {/* Coverage strip — the /analytics endpoint has no date parameters, so
          the covered range is shown read-only rather than as a fake filter. */}
      <div className="mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-border-light bg-bg-secondary px-4 py-2.5 text-xs text-text-secondary shadow-xs dark:border-border-medium">
        <span className="inline-flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-primary-500" />
          <span className="font-semibold text-text-primary">Data coverage</span>
        </span>
        <span>
          {coverageStart} → {coverageEnd}
        </span>
        <span aria-hidden="true" className="text-border-strong">
          ·
        </span>
        <span>{data.content_count} items analysed</span>
        <span aria-hidden="true" className="text-border-strong">
          ·
        </span>
        <span>{data.published_with_metrics} with metrics</span>
        <span className="ml-auto text-text-tertiary">
          Date filtering available on the <Link to="/performance" className="font-semibold text-primary-600 hover:underline dark:text-primary-400">Performance</Link> page
        </span>
      </div>

      {data.warnings.length > 0 && (
        <div className="mb-5 space-y-1.5">
          {data.warnings.map((w) => (
            <div
              key={w}
              className="rounded-lg border border-warning-200 bg-warning-50 px-3.5 py-2 text-sm text-warning-700 dark:border-warning-800 dark:bg-warning-900/30 dark:text-warning-300"
            >
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Avg engagement"
          value={pct(data.avg_engagement_rate)}
          tone="brand"
          hint={`median ${pct(data.median_engagement_rate)}`}
        />
        <Stat label="Avg CTR" value={pct(data.avg_ctr)} hint="clicks / impressions" />
        <Stat
          label="Impressions"
          value={compact(data.total_impressions)}
          hint={`${compact(data.total_engagements)} engagements`}
        />
        <Stat
          label="Items with metrics"
          value={`${data.published_with_metrics}/${data.content_count}`}
          tone={data.published_with_metrics === data.content_count ? 'success' : 'amber'}
          hint={
            data.published_with_metrics === data.content_count
              ? 'fully instrumented'
              : 'add results to sharpen ranks'
          }
        />
        <Stat
          label="Content items"
          value={String(data.content_count)}
          tone="primary"
          hint={"Total analysed items"}
        />
      </div>

      {/* Big trend chart */}
      <Card className="mb-5 p-5">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Performance over time</h2>
            <p className="mt-0.5 text-xs text-text-tertiary">
              Impressions (bars) against average engagement rate (line), by publication date.
            </p>
          </div>
          <div className="flex items-center gap-4 text-[0.7rem] text-text-tertiary">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--color-mint-500)' }} />
              Impressions
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded-full" style={{ background: 'var(--color-primary-500)' }} />
              Engagement rate
            </span>
          </div>
        </div>

        {trend.length < 2 ? (
          <div className="flex h-72 items-center justify-center rounded-xl border border-dashed border-border-medium bg-bg-primary/50 text-sm text-text-tertiary dark:bg-ink-850/50">
            Need at least two dated items to plot a trend.
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={trend} margin={{ left: -8, right: 4, top: 8 }}>
                <CartesianGrid stroke="var(--color-border-light)" strokeDasharray="3 4" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: 'var(--color-text-tertiary)', fontSize: 11 }}
                  stroke="var(--color-border-medium)"
                  minTickGap={30}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="left"
                  tick={{ fill: 'var(--color-text-tertiary)', fontSize: 11 }}
                  stroke="var(--color-border-medium)"
                  tickFormatter={(v: number) => `${v}%`}
                  tickLine={false}
                  width={48}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fill: 'var(--color-text-tertiary)', fontSize: 11 }}
                  stroke="var(--color-border-medium)"
                  tickFormatter={(v: number) => compact(v)}
                  tickLine={false}
                  width={48}
                />
                <Tooltip
                  contentStyle={CHART_TOOLTIP}
                  formatter={(value, name) => [
                    name === 'engagement' ? `${Number(value).toFixed(2)}%` : Number(value).toLocaleString(),
                    name === 'engagement' ? 'Engagement rate' : 'Impressions',
                  ]}
                />
                <RechartsBar
                  yAxisId="right"
                  dataKey="impressions"
                  fill="var(--color-mint-500)"
                  fillOpacity={0.55}
                  radius={[4, 4, 0, 0]}
                  barSize={14}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="engagement"
                  stroke="var(--color-primary-500)"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: 'var(--color-primary-500)', strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* Breakdowns */}
      <div className="mb-5 grid gap-4 xl:grid-cols-5">
        <Card className="p-5 xl:col-span-3">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Performance by {dimensionLabel(dimension)}</h2>
              <p className="mt-0.5 text-xs text-text-tertiary">
                Index of 1.00x = your account average. Green beats it, amber trails, red underperforms.
              </p>
            </div>
            <SegmentedControl<Dimension>
              ariaLabel="Breakdown dimension"
              value={dimension}
              onChange={setDimension}
              options={[
                { value: 'by_topic', label: 'Topic' },
                { value: 'by_platform', label: 'Platform' },
                { value: 'by_content_type', label: 'Format' },
                { value: 'by_audience', label: 'Audience' },
              ]}
            />
          </div>

          {chartData.length === 0 ? (
            <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border-medium bg-bg-primary/50 text-sm text-text-tertiary dark:bg-ink-850/50">
              Not enough data to group by this dimension.
            </div>
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} layout="vertical" margin={{ left: 4, right: 20, top: 4 }}>
                  <CartesianGrid stroke="var(--color-border-light)" horizontal={false} strokeDasharray="3 4" />
                  <XAxis
                    type="number"
                    domain={[0, 'dataMax']}
                    tick={{ fill: 'var(--color-text-tertiary)', fontSize: 11 }}
                    stroke="var(--color-border-medium)"
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={124}
                    tick={{ fill: 'var(--color-text-secondary)', fontSize: 11 }}
                    stroke="var(--color-border-medium)"
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(99, 91, 255, 0.06)' }}
                    contentStyle={CHART_TOOLTIP}
                    formatter={(value, _name, item) => {
                      const payload = item?.payload as { count?: number; fullName?: string } | undefined
                      return [
                        `${Number(value).toFixed(2)}x${payload?.count !== undefined ? ` (n=${payload.count})` : ''}`,
                        payload?.fullName ?? 'index',
                      ]
                    }}
                  />
                  <RechartsBar dataKey="index" radius={[0, 6, 6, 0]} barSize={16}>
                    {chartData.map((entry) => (
                      <Cell key={entry.fullName} fill={BAR_COLOR(entry.index)} />
                    ))}
                  </RechartsBar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

<div className="mt-4 grid gap-4 border-t border-border-light pt-4 dark:border-border-medium sm:grid-cols-2">
            <GroupList
              title="Strongest"
              tone="success"
              groups={groups.filter((g) => g.index_vs_average >= 1).slice(0, 5)}
              max={Math.max(...groups.map((g) => g.avg_engagement_rate), 0.01)}
            />
            <GroupList
              title="Underperforming"
              tone="error"
              groups={groups.filter((g) => g.index_vs_average < 1).slice(-5).reverse()}
              max={Math.max(...groups.map((g) => g.avg_engagement_rate), 0.01)}
            /></div>
          </Card>

          <Card className="p-5 xl:col-span-2" style={{ transitionProperty: 'background', transitionDuration: '200ms }}>
          <h2 className="text-sm font-semibold text-text-primary">Reach share by platform</h2>
          <p className="mt-0.5 text-xs text-text-tertiary">Impressions distribution across platforms.</p>

          {platformShare.length === 0 ? (
            <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border-medium bg-bg-primary/50 text-sm text-text-tertiary dark:bg-ink-850/50">
              No impressions recorded yet.
            </div>
          ) : (
            <>
              <div className="mt-2 h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={platformShare}
                      dataKey="value"
                      nameKey="name"
                      innerRadius="58%"
                      outerRadius="86%"
                      paddingAngle={3}
                      strokeWidth={0}
                    >
                      {platformShare.map((entry, i) => (
                        <Cell key={entry.name} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={CHART_TOOLTIP} formatter={(v, n) => [Number(v).toLocaleString(), n]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="mt-2 space-y-2">
                {platformShare.map((entry, i) => {
                  const total = platformShare.reduce((sum, p) => sum + p.value, 0)
                  const share = total > 0 ? (entry.value / total) * 100 : 0
                  return (
                    <li key={entry.name} className="flex items-center gap-2.5 text-xs">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      <span className="min-w-0 flex-1 truncate text-text-primary">{entry.name}</span>
                      <span className="tabular-nums text-text-tertiary">{compact(entry.value)}</span>
                      <span className="w-12 shrink-0 text-right font-semibold tabular-nums text-text-secondary">
                        {share.toFixed(0)}%
                      </span>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </Card>
      </div>

      {/* Top content table */}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-5 py-4 dark:border-border-medium">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Top content</h2>
            <p className="mt-0.5 text-xs text-text-tertiary">Ranked by engagement rate across your history.</p>
          </div>
          <Link to="/performance" className="text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400">
            Register results →
          </Link>
        </div>

        {data.best_content.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-text-tertiary">No items with metrics yet.</p>
        ) : (
<div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="w-8" className="text-left text-xs font-medium text-text-tertiary uppercase tracking-wider">#</th>
                    <th className="text-left text-xs font-medium text-text-tertiary uppercase tracking-wider">Content</th>
                    <th className="text-left text-xs font-medium text-text-tertiary uppercase tracking-wider">Platform</th>
                    <th className="text-left text-xs font-medium text-text-tertiary uppercase tracking-wider">Published</th>
                    <th className="text-right text-xs font-medium text-text-tertiary uppercase tracking-wider">Impressions</th>
                    <th className="text-right text-xs font-medium text-text-tertiary uppercase tracking-wider">Engagement</th>
                    <th className="text-right text-xs font-medium text-text-tertiary uppercase tracking-wider">CTR</th>
                  </tr>
                </thead>
                <tbody>
                  {data.best_content.slice(0, 10).map((item, i) => (
                    <tr
                      key={item.id}
                      className="hover:bg-bg-secondary transition-colors dark:hover:bg-ink-800"
                    >
                      <td className="text-text-quaternary tabular-nums">{i + 1}</td>
                      <td>
                        <div className="flex items-center gap-3">
                          <PreviewTile seed={item.topic || item.title} className="h-8 w-8 shrink-0 text-xs" />
                          <div className="min-w-0">
                            <div className="max-w-md truncate font-medium text-text-primary">{item.title}</div>
                            <div className="text-[0.7rem] text-text-tertiary">{item.topic}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <Chip>{item.platform}</Chip>
                      </td>
                      <td className="whitespace-nowrap text-text-secondary">{fullDate(item.published_at)}</td>
                      <td className="text-right tabular-nums">{compact(item.impressions)}</td>
                      <td className="text-right font-semibold tabular-nums text-success-600 dark:text-success-400">
                        {pct(item.engagement_rate)}
                      </td>
                      <td className="text-right tabular-nums text-text-secondary">{pct(item.ctr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
        )}
      </Card>
    </>
  )
}

function dimensionLabel(key: string): string {
  return { by_topic: 'topic', by_platform: 'platform', by_content_type: 'format', by_audience: 'audience' }[key] ?? key
}

function GroupList({
  title,
  groups,
  max,
  tone,
}: {
  title: string
  groups: GroupStat[]
  max: number
  tone: 'success' | 'error'
}) {
  if (groups.length === 0) {
    return (
      <div>
        <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">{title}</h3>
        <p className="text-sm text-text-tertiary">Nothing in this bucket.</p>
      </div>
    )
  }
  return (
    <div>
      <h3 className="mb-2.5 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">{title}</h3>
      <div className="space-y-2.5">
        {groups.map((g) => (
          <div key={g.key}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="truncate font-medium text-text-primary">{g.key}</span>
              <span className="shrink-0 tabular-nums text-text-tertiary">
                {pct(g.avg_engagement_rate)} · {indexLabel(g.index_vs_average)} · n={g.count}
              </span>
            </div>
            <div className="mt-1">
              <Bar value={g.avg_engagement_rate} max={max} tone={tone} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
