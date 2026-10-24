import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { useHealth } from '../context/HealthContext'
import { Card, Chip, ErrorNote, SectionHeader } from '../components/ui'
import type { IngestResponse } from '../types'
import { pct } from '../utils/format'

const PLATFORMS = ['LinkedIn', 'Blog', 'Newsletter', 'Twitter', 'YouTube', 'Podcast']
const TYPES = ['carousel', 'text post', 'blog post', 'case study', 'video', 'thread', 'how-to guide', 'thought leadership']
const STATUSES = ['published', 'draft', 'planned']

const BLANK = {
  title: '',
  body: '',
  platform: 'LinkedIn',
  content_type: 'carousel',
  topic: '',
  status: 'published',
  impressions: 0,
  likes: 0,
  comments: 0,
  shares: 0,
  clicks: 0,
  analyze: true,
}

export function AddContent() {
  const { health } = useHealth()
  const [form, setForm] = useState({ ...BLANK })
  const [publishedAt, setPublishedAt] = useState<Date | string>('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<IngestResponse | null>(null)

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const hasMetrics =
    form.impressions > 0 || form.likes > 0 || form.comments > 0 || form.shares > 0 || form.clicks > 0

  const engagementPreview =
    form.impressions > 0
      ? (form.likes + form.comments + form.shares) / form.impressions
      : null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setResult(null)
    try {
      const { data } = await api.post<IngestResponse>('/content', {
        ...form,
        impressions: Number(form.impressions),
        likes: Number(form.likes),
        comments: Number(form.comments),
        shares: Number(form.shares),
        clicks: Number(form.clicks),
        published_at: publishedAt ? new Date(publishedAt).toISOString() : undefined,
      })
      setResult(data)
      setForm({ ...BLANK })
      setPublishedAt('')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <SectionHeader
        title="Add Content"
        subtitle="Every item you add is analysed, learned from, and written to long-term memory."
        action={
          <Link to="/content" className="btn btn-secondary">
            Back to library
          </Link>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <form onSubmit={submit} className="space-y-5 lg:col-span-2">
          <Card>
            <h2 className="mb-4 text-sm font-semibold">The content</h2>
            <div className="space-y-4">
              <div>
                <label className="label" htmlFor="title">
                  Title <span className="text-error-500">*</span>
                </label>
                <input
                  id="title"
                  className="field"
                  required
                  minLength={5}
                  maxLength={300}
                  placeholder="How we cut reporting time by 60% with AI"
                  value={form.title}
                  onChange={(e) => set('title', e.target.value)}
                />
                <p className="mt-1 text-[0.68rem] text-text-tertiary">At least 5 characters.</p>
              </div>

              <div>
                <label className="label" htmlFor="body">
                  Body / summary <span className="text-error-500">*</span>
                </label>
                <textarea
                  id="body"
                  className="field min-h-32 resize-y"
                  required
                  minLength={10}
                  placeholder="Paste the post, or a summary of it. This is what the analyser reads."
                  value={form.body}
                  onChange={(e) => set('body', e.target.value)}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <label className="label" htmlFor="platform">
                    Platform
                  </label>
                  <select
                    id="platform"
                    className="field"
                    value={form.platform}
                    onChange={(e) => set('platform', e.target.value)}
                  >
                    {PLATFORMS.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="type">
                    Format
                  </label>
                  <select
                    id="type"
                    className="field"
                    value={form.content_type}
                    onChange={(e) => set('content_type', e.target.value)}
                  >
                    {TYPES.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="status">
                    Status
                  </label>
                  <select
                    id="status"
                    className="field"
                    value={form.status}
                    onChange={(e) => set('status', e.target.value)}
                  >
                    {STATUSES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="topic">
                    Topic <span className="text-error-500">*</span>
                  </label>
                  <input
                    id="topic"
                    className="field"
                    required
                    placeholder="AI automation"
                    value={form.topic}
                    onChange={(e) => set('topic', e.target.value)}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="published">
                    Published at
                  </label>
                  <input
                    id="published"
                    type="datetime-local"
                    className="field"
                    value={publishedAt}
                    onChange={(e) => setPublishedAt(e.target.value)}
                  />
                </div>
              </div>
            </div>
          </Card>

          <Card>
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Performance</h2>
              {engagementPreview !== null && (
                <Chip tone="success">engagement {pct(engagementPreview)}</Chip>
              )}
            </div>
            <p className="mb-4 text-xs text-text-tertiary">
              Leave these at zero if the post is still new. ContentMind will still learn the topic and format,
              but it cannot judge performance yet.
            </p>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              {(
                [
                  ['impressions', 'Impressions'],
                  ['likes', 'Likes'],
                  ['comments', 'Comments'],
                  ['shares', 'Shares'],
                  ['clicks', 'Clicks'],
                ] as const
              ).map(([key, label]) => (
                <div key={key}>
                  <label className="label" htmlFor={key}>
                    {label}
                  </label>
                  <input
                    id={key}
                    type="number"
                    min={0}
                    className="field tabular-nums"
                    value={form[key]}
                    onChange={(e) => set(key, Number(e.target.value))}
                  />
                </div>
              ))}
            </div>
            <p className="mt-3 text-[0.68rem] text-text-tertiary">
              engagement_rate = (likes + comments + shares) / impressions · ctr = clicks / impressions
            </p>
          </Card>

          {error && <ErrorNote message={error} />}

          <div className="flex items-center gap-3">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Analysing and remembering…' : 'Add and remember'}
            </button>
            <label className="flex items-center gap-2 text-sm text-text-tertiary">
              <input
                type="checkbox"
                checked={form.analyze}
                onChange={(e) => set('analyze', e.target.checked)}
              />
              Analyse on ingest
            </label>
          </div>
        </form>

        <div className="space-y-4">
          {result ? (
            <Card className="border-success-500/40">
              <h2 className="text-sm font-semibold text-success-600 dark:text-success-400">Learned</h2>
              <p className="mt-2 text-sm leading-relaxed text-text-tertiary">{result.message}</p>
              <dl className="mt-4 space-y-1.5 text-sm">
                <Row label="Insights extracted" value={String(result.insights_extracted)} />
                <Row label="Memories written" value={String(result.memories_written)} />
                <Row label="Memory backend" value={result.memory_backend} />
              </dl>
              {result.degraded && (
                <p className="mt-3 text-xs text-warning-500">
                  Written to the local fallback, not Hindsight.
                </p>
              )}
              <div className="mt-4 flex gap-2">
                <Link to="/learned" className="btn btn-secondary">
                  See what it learned
                </Link>
                <button type="button" className="btn btn-secondary" onClick={() => setResult(null)}>
                  Add another
                </button>
              </div>
            </Card>
          ) : (
            <Card>
              <h2 className="text-sm font-semibold">What happens when you save</h2>
              <ol className="mt-3 space-y-2.5 text-sm text-text-tertiary">
                {[
                  'Metrics are normalised into engagement rate and CTR.',
                  'The content is analysed for patterns, gaps, and lessons.',
                  'Statements are written to long-term memory with the source attached.',
                  'Future plans and answers can now cite this item.',
                ].map((step, i) => (
                  <li key={step} className="flex gap-2.5">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border-medium text-[0.65rem] text-text-tertiary">
                      {i + 1}
                    </span>
                    {step}
                  </li>
                ))}
              </ol>
            </Card>
          )}

          <Card>
            <h2 className="text-sm font-semibold">System state</h2>
            <dl className="mt-3 space-y-1.5 text-sm">
              <Row label="Memory backend" value={health?.memory.backend ?? '—'} />
              <Row label="Memories held" value={String(health?.memory.memory_count ?? 0)} />
              <Row label="LLM" value={health?.llm.model ?? '—'} />
            </dl>
            {!hasMetrics && (
              <p className="mt-3 text-xs text-text-tertiary">
                Tip: you can save without metrics. Topics and formats are still worth remembering.
              </p>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-text-tertiary">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}