import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { Card, Chip, EmptyState, ErrorNote, PageHeader, PreviewTile, SegmentedControl, Spinner } from '../components/ui'
import type { PlanGenerateResponse, PlanItem } from '../types'
import { fullDate } from '../utils/format'

const PLATFORM_OPTIONS = ['LinkedIn', 'Blog', 'Newsletter', 'Twitter', 'YouTube']

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function localDayKey(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function addDays(base: Date, days: number): Date {
  const d = new Date(base)
  d.setDate(d.getDate() + days)
  return d
}

export function ContentPlanner() {
  const [days, setDays] = useState(7)
  const [postsPerDay, setPostsPerDay] = useState(1)
  const [platforms, setPlatforms] = useState<string[]>(['LinkedIn', 'Blog'])
  const [campaign, setCampaign] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PlanGenerateResponse | null>(null)

  function togglePlatform(p: string) {
    setPlatforms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]))
  }

  async function generate() {
    setGenerating(true)
    setError(null)
    setResult(null)
    try {
      const { data } = await api.post<PlanGenerateResponse>('/plans/generate', {
        days,
        posts_per_day: postsPerDay,
        platforms: platforms.length ? platforms : ['LinkedIn'],
        campaign: campaign.trim() || undefined,
      })
      setResult(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="min-h-screen py-6 bg-bg-primary">
      <div className="max-w-7xl mx-auto px-4">
        <PageHeader
          eyebrow="Planner"
          title="Content Planner"
          subtitle="Every recommendation is traceable to something ContentMind remembers."
          actions={
            <Link to="/learned" className="btn btn-secondary">
              What it's learned
            </Link>
          }
        />

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          {/* Brief panel */}
          <Card className="h-fit p-5 xl:sticky xl:top-20">
            <div className="mb-4 flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round">
                  <path d="M4 6h16M4 12h10M4 18h7" />
                </svg>
              </div>
              <h2 className="text-sm font-semibold text-text-primary">Editorial brief</h2>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label text-sm font-medium text-text-primary">Days</label>
                  <input
                    className="input"
                    id="days"
                    type="number"
                    min={1}
                    max={30}
                    value={days}
                    onChange={(e) => setDays(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="label text-sm font-medium text-text-primary">
                    Posts / day
                  </label>
                  <input
                    className="input"
                    id="ppd"
                    type="number"
                    min={1}
                    max={3}
                    value={postsPerDay}
                    onChange={(e) => setPostsPerDay(Number(e.target.value))}
                  />
                </div>
              </div>

              <div>
                <label className="label text-sm font-medium text-text-primary">Platforms</label>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {PLATFORM_OPTIONS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => togglePlatform(p)}
                      className={`chip ${platforms.includes(p) ? 'border-primary-500 bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300' : ''}`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="label text-sm font-medium text-text-primary">
                  Campaign focus (optional)
                </label>
                <input
                  className="input"
                  placeholder="e.g. AI security series"
                  value={campaign}
                  onChange={(e) => setCampaign(e.target.value)}
                />
                <p className="mt-1.5 text-[0.68rem] leading-relaxed text-text-tertiary">
                  The first two slots will be reserved for this theme.
                </p>
              </div>

              <button className="btn btn-primary w-full justify-center" onClick={generate} disabled={generating}>
                {generating ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    Recalling and planning…
                  </>
                ) : (
                  'Generate plan'
                )}
              </button>
            </div>
          </Card>

          {/* Workspace */}
          <div className="space-y-6">
            {error && <ErrorNote message={error} />}

            {generating && (
              <Card className="flex items-center gap-3 p-6">
                <Spinner label="Recalling memories, checking gaps, and composing your calendar…" />
              </Card>
            )}

            {!result && !error && !generating && (
              <EmptyState
                icon="▦"
                title="No plan yet"
                body="Set your brief and generate. ContentMind will recall what has worked, detect what you have not covered, and produce a calendar where every item explains itself."
              />
            )}

            {result && <PlanView result={result} />}
          </div>
        </div>
      </div>
    </>
  )
}

function PlanView({ result }: { result: PlanGenerateResponse }) {
  const { plan, gaps, explanation } = result
  const [view, setView] = useState<'list' | 'calendar'>('list')
  const [query, setQuery] = useState('')
  const [platformFilter, setPlatformFilter] = useState<string>('')
  const [weekOffset, setWeekOffset] = useState(0)

  const itemPlatforms = useMemo(
    () => Array.from(new Set(plan.items.map((i) => i.platform))).slice(0, 6),
    [plan.items],
  )

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    return plan.items.filter((item) => {
      if (platformFilter && item.platform !== platformFilter) return false
      if (!q) return true
      return (
        item.title.toLowerCase().includes(q) ||
        item.topic.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
      )
    })
  }, [plan.items, platformFilter, query])

  const planStart = useMemo(() => {
    const d = new Date(plan.start_date)
    return Number.isNaN(d.getTime()) ? new Date() : d
  }, [plan.start_date])

  const planEnd = useMemo(() => {
    const d = new Date(plan.end_date)
    return Number.isNaN(d.getTime()) ? addDays(planStart, 6) : d
  }, [plan.end_date, planStart])

  const totalWeeks = Math.max(
    1,
    Math.ceil((Math.round((planEnd.getTime() - planStart.getTime()) / 86400000) + 1) / 7),
  )
  const currentWeekStart = addDays(planStart, weekOffset * 7)

  const byDay = useMemo(() => {
    const map = new Map<string, PlanItem[]>()
    for (const item of filteredItems) {
      const key = localDayKey(item.date)
      const list = map.get(key)
      if (list) list.push(item)
      else map.set(key, [item])
    }
    return map
  }, [filteredItems])

  return (
    <div className="space-y-5">
      {/* Plan summary */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-text-primary">{plan.title}</h2>
              <Chip tone="success">Generated</Chip>
            </div>
            <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-text-secondary">{plan.strategy_summary}</p>
          </div>
          <div className="shrink-0 rounded-lg bg-bg-primary/70 px-3 py-2 text-right text-xs text-text-secondary dark:bg-ink-850/70">
            <div className="font-semibold text-text-primary">{plan.date_range}</div>
            <div className="mt-0.5 tabular-nums">
              {plan.total_items} items · {plan.items.length} planned
            </div>
            <div className="mt-0.5 tabular-nums">{gaps.length} gaps considered</div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {Array.from(new Set(plan.items.map((i) => i.topic)))
            .filter(Boolean)
            .slice(0, 6)
            .map((topic) => (
              <Chip key={topic} tone="primary">
                {topic}
              </Chip>
            ))}
        </div>

        {explanation && <p className="mt-3 text-xs leading-relaxed text-text-tertiary">{explanation}</p>}
      </Card>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl<'list' | 'calendar'>
          ariaLabel="Planner view"
          value={view}
          onChange={setView}
          options={[
            { value: 'list', label: 'List' },
            { value: 'calendar', label: 'Calendar' },
          ]}
        />

        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
          </svg>
          <input
            className="input pl-8"
            placeholder="Search plan…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search plan"
          />
        </div>

        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setPlatformFilter('')}
            className={`chip ${platformFilter === '' ? 'border-primary-500 bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300' : ''}`}
          >
            All platforms
          </button>
          {itemPlatforms.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPlatformFilter(p === platformFilter ? '' : p)}
              className={`chip ${platformFilter === p ? 'border-primary-500 bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300' : ''}`}
            >
              {p}
            </button>
          ))}
        </div>

        <span className="ml-auto text-xs text-text-tertiary tabular-nums">
          {filteredItems.length} of {plan.items.length} items
        </span>
      </div>

      {filteredItems.length === 0 ? (
        <EmptyState
          icon="⌕"
          title="Nothing matches"
          body="No plan items match the current search or platform filter."
        />
      ) : view === 'list' ? (
        <ListView items={filteredItems} />
      ) : (
        <CalendarView
          weekStart={currentWeekStart}
          itemsByDay={byDay}
          weekOffset={weekOffset}
          totalWeeks={totalWeeks}
          onPrev={() => setWeekOffset((w) => Math.max(0, w - 1))}
          onNext={() => setWeekOffset((w) => Math.min(totalWeeks - 1, w + 1))}
        />
      )}
    </div>
  )
}

function ListView({ items }: { items: PlanItem[] }) {
  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <Card key={item.id ?? `${item.date}-${index}`} className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-4 border-b border-border-light px-5 py-4 dark:border-border-medium">
            <div className="flex flex-col items-center justify-center rounded-xl bg-primary-50 px-3 py-1.5 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300">
              <span className="text-[0.6rem] font-semibold uppercase leading-none tracking-wide">
                {new Date(item.date).toLocaleDateString(undefined, { month: 'short' })}
              </span>
              <span className="text-base font-bold leading-tight tabular-nums">
                {new Date(item.date).getDate()}
              </span>
            </div>
            <PreviewTile seed={item.topic || item.title} className="h-11 w-11 shrink-0 text-sm" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-text-primary">{item.title}</span>
                <Chip tone="primary">Planned</Chip>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-text-tertiary">
                <span className="font-medium text-text-secondary">{item.platform}</span>
                <span aria-hidden="true">·</span>
                <span>{item.format}</span>
                <span aria-hidden="true">·</span>
                <span>{item.topic}</span>
                <span aria-hidden="true">·</span>
                <span>{fullDate(item.date)}</span>
              </div>
            </div>
          </div>

          <div className="space-y-3 px-5 py-4">
            <p className="text-sm leading-relaxed text-text-secondary">{item.description}</p>

            <div className="rounded-lg border border-border-light bg-bg-primary/70 px-3.5 py-2.5 dark:border-border-medium dark:bg-ink-850/70">
              <div className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
                Why this, why now
              </div>
              <p className="mt-1 text-xs leading-relaxed text-text-secondary">{item.reason}</p>
            </div>

            {item.memory_used.length > 0 && (
              <div>
                <div className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
                  Memories used
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {item.memory_used.map((m) => (
                    <Chip key={m} className="max-w-full truncate text-[0.65rem]">
                      {m}
                    </Chip>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}

function CalendarView({
  weekStart,
  itemsByDay,
  weekOffset,
  totalWeeks,
  onPrev,
  onNext,
}: {
  weekStart: Date
  itemsByDay: Map<string, PlanItem[]>
  weekOffset: number
  totalWeeks: number
  onPrev: () => void
  onNext: () => void
}) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border-light px-5 py-3.5 dark:border-border-medium">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onPrev}
          disabled={weekOffset === 0}
          aria-label="Previous week"
        >
          ← Prev
        </button>
        <div className="text-sm font-semibold text-text-primary">
          {fullDate(weekStart.toISOString())} — {fullDate(days[6].toISOString())}
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onNext}
          disabled={weekOffset >= totalWeeks - 1}
          aria-label="Next week"
        >
          Next →
        </button>
      </div>

      <div className="grid grid-cols-7 divide-x divide-border-light border-b border-border-light dark:divide-border-medium dark:border-border-medium">
        {WEEKDAYS.map((d) => (
          <div key={d} className="px-2 py-2 text-center text-[0.65rem] font-semibold uppercase tracking-wider text-text-tertiary">
            {d}
          </div>
        ))}
      </div>

      <div className="grid min-h-[22rem] grid-cols-7 divide-x divide-border-light dark:divide-border-medium">
        {days.map((day) => {
          const key = localDayKey(day.toISOString())
          const dayItems = itemsByDay.get(key) ?? []
          return (
            <div key={key} className="min-w-0 p-2">
              <div className="mb-1.5 text-center text-xs font-semibold tabular-nums text-text-secondary">
                {day.getDate()}
              </div>
              <div className="space-y-1.5">
                {dayItems.map((item, i) => (
                  <div
                    key={item.id ?? i}
                    className="rounded-md border border-primary-200 bg-primary-50 px-1.5 py-1.5 text-[0.65rem] leading-tight text-primary-700 dark:border-primary-800 dark:bg-primary-900/30 dark:text-primary-300"
                    title={`${item.title} — ${item.platform}`}
                  >
                    <div className="truncate font-semibold">{item.title}</div>
                    <div className="mt-0.5 truncate opacity-75">{item.platform}</div>
                  </div>
                ))}
                {dayItems.length === 0 && (
                  <div className="rounded-md border border-dashed border-border-light px-1.5 py-2 text-center text-[0.6rem] text-text-quaternary dark:border-border-medium">
                    —
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
