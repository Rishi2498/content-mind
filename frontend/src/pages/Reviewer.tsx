import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { Card, Chip, ErrorNote, SectionHeader, Spinner } from '../components/ui'
import type { ReviewerHistoryResponse, ReviewerResponse, ReviewerSuggestion } from '../types'

const PLATFORMS = ['', 'LinkedIn', 'Twitter', 'Instagram', 'YouTube', 'Blog', 'Newsletter', 'TikTok']

const SEVERITY_TONE: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'error'> = {
  critical: 'error',
  improve: 'primary',
  nice_to_have: 'default',
}

const CATEGORY_LABEL: Record<string, string> = {
  hook: 'Hook',
  clarity: 'Clarity',
  brand: 'Brand',
  structure: 'Structure',
  cta: 'Call to action',
  topic: 'Topic',
}

function ScoreGauge({ label, value }: { label: string; value: number }) {
  const tone = value >= 75 ? 'text-mint-400' : value >= 50 ? 'text-amber-glow' : 'text-rose-alert'
  const bar = value >= 75 ? 'bg-mint-500' : value >= 50 ? 'bg-amber-glow' : 'bg-rose-alert'
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-ink-400">{label}</span>
        <span className={`text-lg font-semibold tabular-nums ${tone}`}>{Math.round(value)}</span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
    </div>
  )
}

export function Reviewer() {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [platform, setPlatform] = useState('')
  const [topic, setTopic] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ReviewerResponse | null>(null)
  const [history, setHistory] = useState<ReviewerHistoryResponse['items']>([])
  const [historyLoading, setHistoryLoading] = useState(true)

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await api.get<ReviewerHistoryResponse>('/reviewer/reviews', { params: { limit: 10 } })
      setHistory(data.items)
    } catch {
      // history is best-effort
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setReviewing(true)
    setError(null)
    try {
      const { data } = await api.post<ReviewerResponse>('/reviewer/review', {
        title: title || undefined,
        body,
        platform: platform || undefined,
        topic: topic || undefined,
      })
      setResult(data)
      await loadHistory()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setReviewing(false)
    }
  }

  return (
    <div className="min-h-screen py-6 bg-bg-primary">
      <div className="max-w-7xl mx-auto px-4">
        <SectionHeader
          title="Pre-Publish Reviewer"
          subtitle="Paste a draft before you publish. Get hook, clarity, and brand scores with evidence-based suggestions."
          action={
            <Link to="/media" className="btn btn-secondary">
              Review media assets →
            </Link>
          }
        />

        <div className="grid gap-6 lg:grid-cols-2">
          <form onSubmit={submit} className="space-y-6 lg:col-span-1">
            <Card>
              <h2 className="mb-4 text-sm font-semibold text-text-primary">Your draft</h2>
              <div className="space-y-5">
                <div>
                  <label className="label text-sm font-medium text-text-primary">
                    <span className="required text-text-error">*</span> Body
                  </label>
                  <textarea
                    id="r-body"
                    className="field min-h-48 resize-y"
                    required
                    minLength={10}
                    maxLength={20000}
                    placeholder="Paste the full post or script you are about to publish."
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                  />
                  <p className="mt-1 text-[0.68rem] text-text-tertiary">
                    {body.length} / 20,000 characters
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="label text-sm font-medium text-text-primary">
                      Platform
                    </label>
                    <select
                      className="field"
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                    >
                      {PLATFORMS.map((p) => (
                        <option key={p} value={p}>
                          {p || '(unspecified)'}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="label text-sm font-medium text-text-primary">
                      Topic
                    </label>
                    <input
                      className="field"
                      maxLength={120}
                      placeholder="AI automation"
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                    />
                  </div>
                </div>
                {error && <ErrorNote message={error} />}
                <div className="mt-4">
                  <button type="submit" className="btn btn-primary" disabled={reviewing}>
                    {reviewing ? 'Reviewing…' : 'Review draft'}
                  </button>
                </div>
              </div>
            </Card>
          </form>

          <div className="space-y-6 lg:col-span-1">
            {result ? (
              <>
                <Card className="border-brand-500/40">
                  <h2 className="text-sm font-semibold text-text-primary">Scores</h2>
                  <div className="mt-4 space-y-4">
                    <ScoreGauge label="Hook" value={result.hook_score} />
                    <ScoreGauge label="Clarity" value={result.clarity_score} />
                    <ScoreGauge label="Brand alignment" value={result.brand_alignment} />
                  </div>
                  {result.summary && (
                    <p className="mt-4 text-sm leading-relaxed text-ink-300">{result.summary}</p>
                  )}
                  {result.degraded && (
                    <p className="mt-3 text-xs text-amber-glow">
                      No LLM configured — scores come from the deterministic heuristic engine.
                    </p>
                  )}
                </Card>

                <Card>
                  <h2 className="text-sm font-semibold text-text-primary">
                    Suggestions ({result.suggestions.length})
                  </h2>
                  {result.suggestions.length === 0 ? (
                    <p className="mt-2 text-sm text-ink-400">
                      Nothing flagged — looks ready to publish.
                    </p>
                  ) : (
                    <ul className="mt-3 space-y-3">
                      {result.suggestions.map((s, i) => (
                        <SuggestionCard key={i} suggestion={s} />
                      ))}
                    </ul>
                  )}
                </Card>
              </>
            ) : (
              <Card>
                <h2 className="text-sm font-semibold text-text-primary">How reviews work</h2>
                <ol className="mt-3 space-y-2.5 text-sm text-text-tertiary">
                  {
                    [
                      'Your brand profile and learned memories are recalled as evidence.',
                      'The draft is scored on hook, clarity, and brand alignment (0-100).',
                      'Each suggestion cites the brand rule or memory that justifies it.',
                      'Edit the draft and re-review — history tracks your iterations.',
                    ].map((step, i) => (
                      <li key={step} className="flex gap-2.5">
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-ink-600 text-[0.65rem] text-ink-400">
                          {i + 1}
                        </span>
                        {step}
                      </li>
                    ))}
                  }
                </ol>
              </Card>
            )}

            <Card>
              <h2 className="text-sm font-semibold text-text-primary">Recent reviews</h2>
              {historyLoading ? (
                <div className="mt-3">
                  <Spinner label="Loading history…" />
                </div>
              ) : history.length === 0 ? (
                <p className="mt-2 text-sm text-ink-400">No reviews yet.</p>
              ) : (
                <ul className="mt-3 divide-y divide-border-light dark:divide-border-medium">
                  {history.map((h) => (
                    <li
                      key={h.id}
                      className="flex items-center justify-between gap-2 py-2 text-xs border-b border-border-light dark:border-border-medium last:mb-0 dark:text-ink-300"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-text-primary">
                          {h.title || h.draft_excerpt.slice(0, 40) || 'Untitled'}
                        </div>
                        <div className="text-ink-500 text-xs">
                          {h.source} · {new Date(h.created_at).toLocaleString()}
                        </div>
                      </div>
                      <Chip
                        tone={h.overall_score >= 75 ? 'success' : h.overall_score >= 50 ? 'primary' : 'warning'}
                      >
                        {Math.round(h.overall_score)}
                      </Chip>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </>
  )
}

function SuggestionCard({ suggestion }: { suggestion: ReviewerSuggestion }) {
  return (
    <li className="rounded-lg border border-ink-700 bg-ink-900/40 p-3.5">
      <div className="flex items-center gap-2">
        <Chip tone={SEVERITY_TONE[suggestion.severity] ?? 'default'}>
          {CATEGORY_LABEL[suggestion.category] ?? suggestion.category}
        </Chip>
        <span className="text-[0.68rem] text-ink-500">{suggestion.severity.replace('_', ' ')}</span>
      </div>
      <p className="mt-2 text-sm font-medium leading-relaxed">{suggestion.suggestion}</p>
      {suggestion.rationale && <p className="mt-1.5 text-xs text-ink-400">{suggestion.rationale}</p>}
      {suggestion.evidence && (
        <p className="mt-2 border-l-2 border-brand-500/50 pl-2.5 text-[0.68rem] italic text-ink-500">
          {suggestion.evidence}
        </p>
      )}
    </li>
  )
}