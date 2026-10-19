import { useCallback, useEffect, useState } from 'react'

import { api, apiErrorMessage } from '../api'
import {
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorNote,
  PageHeader,
  Skeleton,
  Stat,
} from '../components/ui'
import type {
  Experiment,
  FeedbackRequest,
  Recommendation,
  StrategyGenerateResponse,
  StrategyProfile,
} from '../types'

type ChipTone = 'default' | 'primary' | 'success' | 'warning' | 'error'

const STATUS_TONE: Record<string, ChipTone> = {
  proposed: 'default',
  accepted: 'success',
  edited: 'primary',
  rejected: 'error',
  deferred: 'warning',
  completed: 'success',
}

const STATUS_LABEL: Record<string, string> = {
  proposed: 'Proposed',
  accepted: 'Accepted',
  edited: 'Edited',
  rejected: 'Rejected',
  deferred: 'Deferred',
  completed: 'Completed',
}

const CONFIDENCE_TONE: Record<string, ChipTone> = {
  strong: 'success',
  moderate: 'primary',
  weak: 'warning',
  insufficient: 'default',
}

const STATUS_FILTERS = ['', 'proposed', 'accepted', 'edited', 'rejected', 'deferred', 'completed'] as const

const ICONS = {
  sparkles: (
    <svg className="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />
    </svg>
  ),
  flask: (
    <svg className="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 006.2 21h11.6a2 2 0 001.7-2.5L14 9V3" />
    </svg>
  ),
  user: (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0115 0" />
    </svg>
  ),
}

function RecommendationCard({
  rec,
  onUpdate,
  onFeedback,
  onExperiment,
}: {
  rec: Recommendation
  onUpdate: (id: number, patch: { status?: string; edited_title?: string; edited_notes?: string }) => void
  onFeedback: (id: number, feedback: FeedbackRequest) => void
  onExperiment: (recId: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(rec.edited_title || rec.working_title)
  const [notes, setNotes] = useState(rec.edited_notes || '')
  const [note, setNote] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-border-light px-5 py-4 dark:border-border-medium">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300">
          <span className="text-sm font-bold tabular-nums">D{rec.sequence_day + 1}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-text-primary">
            {rec.edited_title || rec.working_title || rec.topic}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.7rem] text-text-tertiary">
            <span className="font-medium text-text-secondary">{rec.platform}</span>
            <span aria-hidden="true">·</span>
            <span>{rec.format}</span>
            {rec.pillar && (
              <>
                <span aria-hidden="true">·</span>
                <span>{rec.pillar}</span>
              </>
            )}
            <span aria-hidden="true">·</span>
            <span>{rec.topic}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {rec.is_hypothesis ? (
            <Chip tone="warning">Hypothesis</Chip>
          ) : (
            <Chip tone={CONFIDENCE_TONE[rec.confidence] ?? 'default'}>
              {rec.confidence} · n={rec.sample_size ?? '?'}
            </Chip>
          )}
          <Chip tone={STATUS_TONE[rec.status] ?? 'default'}>{STATUS_LABEL[rec.status] ?? rec.status}</Chip>
        </div>
      </div>

      <div className="space-y-3 px-5 py-4">
        {rec.hook && <p className="text-sm italic leading-relaxed text-text-secondary">“{rec.hook}”</p>}
        {rec.reason && <p className="text-xs leading-relaxed text-text-tertiary">{rec.reason}</p>}

        {rec.evidence.length > 0 && (
          <div>
            <div className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
              Evidence
            </div>
            <ul className="space-y-1">
              {rec.evidence.slice(0, 3).map((e, i) => (
                <li key={i} className="flex gap-2 text-xs leading-relaxed text-text-secondary">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary-400" />
                  <span>{e}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {rec.test_method && (
          <details className="rounded-lg border border-border-light bg-bg-primary/70 px-3.5 py-2.5 text-xs dark:border-border-medium dark:bg-ink-850/70">
            <summary className="cursor-pointer select-none font-semibold text-text-secondary hover:text-text-primary">
              How to test this
            </summary>
            <p className="mt-2 leading-relaxed text-text-secondary">{rec.test_method}</p>
            {rec.success_metric && (
              <p className="mt-1.5 text-text-tertiary">Success metric: {rec.success_metric}</p>
            )}
          </details>
        )}

        {rec.feedback_note && (
          <p className="rounded-lg border border-border-light px-3 py-2 text-xs text-text-tertiary dark:border-border-medium">
            Your note: {rec.feedback_note}
          </p>
        )}

        {editing ? (
          <div className="space-y-2 border-t border-border-light pt-3 dark:border-border-medium">
            <input
              className="input w-full"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
            />
            <textarea
              className="input w-full"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Production notes"
            />
            <div className="flex gap-2">
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  onUpdate(rec.id, { edited_title: title, edited_notes: notes, status: 'edited' })
                  setEditing(false)
                }}
              >
                Save
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2 border-t border-border-light pt-3 dark:border-border-medium">
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              className="btn btn-sm border-success-200 bg-success-50 text-success-700 hover:bg-success-100 dark:border-success-800 dark:bg-success-900/30 dark:text-success-300"
              onClick={() => onFeedback(rec.id, { status: 'accepted' })}
            >
              Accept
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowFeedback((s) => !s)}>
              Reject / Defer
            </button>
            <button
              className="ml-auto text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400"
              onClick={() => onExperiment(rec.id)}
            >
              Track as experiment →
            </button>
          </div>
        )}

        {showFeedback && (
          <div className="space-y-2 border-t border-border-light pt-3 dark:border-border-medium">
            <textarea
              className="input w-full"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why? (optional)"
            />
            <div className="flex flex-wrap gap-2">
              <button
                className="btn btn-secondary btn-sm border-error-200 text-error-600 hover:bg-error-50 dark:border-error-800 dark:text-error-400"
                onClick={() => {
                  onFeedback(rec.id, { status: 'rejected', note })
                  setShowFeedback(false)
                  setNote('')
                }}
              >
                Reject
              </button>
              <button
                className="btn btn-secondary btn-sm border-warning-200 text-warning-600 hover:bg-warning-50 dark:border-warning-800 dark:text-warning-400"
                onClick={() => {
                  onFeedback(rec.id, { status: 'deferred', note })
                  setShowFeedback(false)
                  setNote('')
                }}
              >
                Defer
              </button>
              <button
                className="btn btn-secondary btn-sm border-success-200 text-success-600 hover:bg-success-50 dark:border-success-800 dark:text-success-400"
                onClick={() => {
                  onFeedback(rec.id, { status: 'completed', note })
                  setShowFeedback(false)
                  setNote('')
                }}
              >
                Mark completed
              </button>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function ProfileForm({ profile, onSave }: { profile: StrategyProfile; onSave: (p: Partial<StrategyProfile>) => void }) {
  const [form, setForm] = useState({
    niche: profile.niche,
    topics: profile.topics.join(', '),
    target_audience: profile.target_audience,
    audience_needs: profile.audience_needs,
    goals: profile.goals,
    content_pillars: profile.content_pillars.join(', '),
    avoid_topics: profile.avoid_topics.join(', '),
    publishing_frequency: profile.publishing_frequency,
    constraints: profile.constraints,
  })

  const toggleGoal = (g: string) =>
    setForm((f) => ({
      ...f,
      goals: f.goals.includes(g) ? f.goals.filter((x) => x !== g) : [...f.goals, g],
    }))

  const field = (id: string, label: string, value: string, onChange: (v: string) => void, textarea = false) => (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      {textarea ? (
        <textarea className="input mt-1 w-full" id={id} rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input className="input mt-1 w-full" id={id} value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  )

  return (
    <Card>
      <CardHeader>
        <h2 className="text-sm font-semibold text-text-primary">Strategy profile</h2>
        <span className="text-xs text-text-tertiary">Drives every recommendation</span>
      </CardHeader>
      <div className="grid gap-4 p-5 md:grid-cols-2">
        {field('niche', 'Niche', form.niche, (v) => setForm({ ...form, niche: v }))}
        {field('topics', 'Topics (comma-separated)', form.topics, (v) => setForm({ ...form, topics: v }))}
        {field('target_audience', 'Target audience', form.target_audience, (v) => setForm({ ...form, target_audience: v }))}
        {field('audience_needs', 'Audience needs', form.audience_needs, (v) => setForm({ ...form, audience_needs: v }), true)}
        <div className="md:col-span-2">
          <span className="label">Goals</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {['education', 'awareness', 'community', 'leads', 'conversion'].map((g) => (
              <button
                key={g}
                type="button"
                className={`chip ${form.goals.includes(g) ? 'border-primary-500 bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300' : ''}`}
                onClick={() => toggleGoal(g)}
              >
                {g}
              </button>
            ))}
          </div>
        </div>
        {field('content_pillars', 'Content pillars (comma-separated)', form.content_pillars, (v) =>
          setForm({ ...form, content_pillars: v }),
        )}
        {field('avoid_topics', 'Avoid topics (comma-separated)', form.avoid_topics, (v) =>
          setForm({ ...form, avoid_topics: v }),
        )}
        {field('publishing_frequency', 'Publishing frequency', form.publishing_frequency, (v) =>
          setForm({ ...form, publishing_frequency: v }),
        )}
        {field('constraints', 'Constraints', form.constraints, (v) => setForm({ ...form, constraints: v }))}
        <div className="md:col-span-2">
          <button
            className="btn btn-primary"
            onClick={() =>
              onSave({
                ...form,
                topics: form.topics.split(',').map((t) => t.trim()).filter(Boolean),
                content_pillars: form.content_pillars.split(',').map((t) => t.trim()).filter(Boolean),
                avoid_topics: form.avoid_topics.split(',').map((t) => t.trim()).filter(Boolean),
              })
            }
          >
            Save profile
          </button>
        </div>
      </div>
    </Card>
  )
}

function ProfileSummary({ profile, onEdit }: { profile: StrategyProfile; onEdit: () => void }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-primary-500">{ICONS.user}</span>
          <h2 className="text-sm font-semibold text-text-primary">Your strategy profile</h2>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onEdit}>
          Edit profile
        </button>
      </CardHeader>
      <div className="space-y-4 p-5">
        <div>
          <div className="text-sm font-semibold text-text-primary">{profile.niche || 'No niche set'}</div>
          <p className="mt-1 text-xs leading-relaxed text-text-secondary">
            {profile.target_audience || 'No target audience set.'}
            {profile.audience_needs && <> — {profile.audience_needs}</>}
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Goals</div>
            <div className="flex flex-wrap gap-1.5">
              {profile.goals.length ? (
                profile.goals.map((g) => (
                  <Chip key={g} tone="primary">
                    {g}
                  </Chip>
                ))
              ) : (
                <span className="text-xs text-text-tertiary">None set</span>
              )}
            </div>
          </div>
          <div>
            <div className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Pillars</div>
            <div className="flex flex-wrap gap-1.5">
              {profile.content_pillars.length ? (
                profile.content_pillars.map((p) => <Chip key={p}>{p}</Chip>)
              ) : (
                <span className="text-xs text-text-tertiary">None set</span>
              )}
            </div>
          </div>
        </div>
        {(profile.publishing_frequency || profile.constraints) && (
          <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border-light pt-3 text-xs text-text-secondary dark:border-border-medium">
            {profile.publishing_frequency && (
              <span>
                <span className="text-text-tertiary">Frequency: </span>
                {profile.publishing_frequency}
              </span>
            )}
            {profile.constraints && (
              <span>
                <span className="text-text-tertiary">Constraints: </span>
                {profile.constraints}
              </span>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

export function Strategy() {
  const [profile, setProfile] = useState<StrategyProfile | null>(null)
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [genResult, setGenResult] = useState<StrategyGenerateResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [showProfile, setShowProfile] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [p, r, e] = await Promise.all([
        api.get<StrategyProfile>('/strategy/profile'),
        api.get<{ items: Recommendation[]; total: number }>('/strategy/recommendations'),
        api.get<Experiment[]>('/strategy/experiments'),
      ])
      setProfile(p.data)
      setRecs(r.data.items)
      setExperiments(e.data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const saveProfile = async (payload: Partial<StrategyProfile>) => {
    try {
      const r = await api.put<StrategyProfile>('/strategy/profile', payload)
      setProfile(r.data)
      setShowProfile(false)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const generate = async () => {
    setGenerating(true)
    setError('')
    try {
      const r = await api.post<StrategyGenerateResponse>('/strategy/generate', { period: 'week' })
      setGenResult(r.data)
      setRecs(r.data.recommendations)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setGenerating(false)
    }
  }

  const updateRec = async (id: number, patch: { status?: string; edited_title?: string; edited_notes?: string }) => {
    try {
      await api.patch(`/strategy/recommendations/${id}`, patch)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const giveFeedback = async (id: number, feedback: FeedbackRequest) => {
    try {
      await api.post(`/strategy/recommendations/${id}/feedback`, feedback)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const createExperiment = async (recId: number) => {
    try {
      await api.post('/strategy/experiments', { recommendation_id: recId, title: `Test rec ${recId}` })
      await load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const updateExperiment = async (id: number, patch: { status?: string; actual_result?: string }) => {
    try {
      await api.patch(`/strategy/experiments/${id}`, patch)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const filteredRecs = statusFilter ? recs.filter((r) => r.status === statusFilter) : recs

  if (loading) {
    return (
      <>
        <PageHeader title="Content Strategy" subtitle="Personalized, evidence-backed recommendations" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-24 sm:col-span-3" />
          <Skeleton className="h-40 sm:col-span-2" />
          <Skeleton className="h-40" />
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Strategy"
        title="Content Strategy"
        subtitle="Evidence-backed recommendations from your own performance data, ContentDNA, reviews, and memory."
        actions={
          <>
            <button className="btn btn-secondary" onClick={() => setShowProfile((s) => !s)}>
              {showProfile ? 'Hide profile' : 'Edit profile'}
            </button>
            <button className="btn btn-primary" onClick={generate} disabled={generating}>
              {generating ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  Generating…
                </>
              ) : (
                'Generate strategy'
              )}
            </button>
          </>
        }
      />

      {error && <ErrorNote message={error} />}

      {/* Summary row */}
      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <Stat
          label="Recommendations"
          value={recs.length}
          hint={`${recs.filter((r) => r.status === 'proposed').length} awaiting review`}
          tone="brand"
          icon={ICONS.sparkles}
        />
        <Stat
          label="Experiments"
          value={experiments.length}
          hint={`${experiments.filter((e) => e.status === 'running').length} running`}
          icon={ICONS.flask}
        />
        <Stat
          label="Accepted"
          value={recs.filter((r) => r.status === 'accepted' || r.status === 'completed').length}
          hint="accepted or completed"
          tone="success"
        />
      </div>

      {profile && !showProfile && (
        <div className="mb-5">
          <ProfileSummary profile={profile} onEdit={() => setShowProfile(true)} />
        </div>
      )}

      {showProfile && profile && <div className="mb-5">{<ProfileForm profile={profile} onSave={saveProfile} />}</div>}

      {genResult && (
        <Card className="mb-5 border-primary-200 dark:border-primary-800">
          <div className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-text-primary">Plan generated</span>
              <Chip tone="success">New</Chip>
            </div>
            <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">{genResult.summary}</p>
            {genResult.warnings.length > 0 && (
              <div className="mt-3 space-y-1">
                {genResult.warnings.map((w, i) => (
                  <div key={i} className="text-xs text-warning-600 dark:text-warning-400">
                    ⚠ {w}
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-text-tertiary">
              <span className="mr-1">Sources:</span>
              {Object.entries(genResult.evidence_sources).map(([k, v]) => (
                <Chip key={k} tone={v ? 'success' : 'default'}>
                  {k}
                </Chip>
              ))}
            </div>
            {genResult.memory_degraded && (
              <p className="mt-2 text-xs text-warning-600 dark:text-warning-400">
                Memory degraded — plan not persisted to long-term memory.
              </p>
            )}
          </div>
        </Card>
      )}

      {/* Filter chips */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Filter</span>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s || 'all'}
            type="button"
            className={`chip ${statusFilter === s ? 'border-primary-500 bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300' : ''}`}
            onClick={() => setStatusFilter(s)}
          >
            {s || 'all'}
          </button>
        ))}
      </div>

      {filteredRecs.length === 0 ? (
        <div className="mb-6">
          <EmptyState
            icon="◈"
            title="No recommendations yet"
            body="Set your strategy profile (topics, audience, goals) and/or register published posts with metrics, then generate a strategy."
            action={
              <button className="btn btn-primary" onClick={generate} disabled={generating}>
                {generating ? 'Generating…' : 'Generate strategy'}
              </button>
            }
          />
        </div>
      ) : (
        <div className="mb-6 space-y-4">
          {filteredRecs.map((rec) => (
            <RecommendationCard
              key={rec.id}
              rec={rec}
              onUpdate={updateRec}
              onFeedback={giveFeedback}
              onExperiment={createExperiment}
            />
          ))}
        </div>
      )}

      {/* Experiments */}
      <div className="mb-2 flex items-center gap-2">
        <h2 className="text-base font-semibold tracking-tight text-text-primary">Experiments</h2>
        <Chip>{experiments.length}</Chip>
      </div>
      <p className="mb-4 text-sm text-text-secondary">
        Turn a hypothesis into an experiment. Record what you changed, the intended metric, and the actual result.
      </p>

      {experiments.length === 0 ? (
        <EmptyState
          icon="⚗"
          title="No experiments tracked"
          body="Accept a recommendation and click “Track as experiment” to start measuring."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {experiments.map((exp) => (
            <Card key={exp.id} className="flex flex-col overflow-hidden">
              <div className="flex items-start justify-between gap-3 border-b border-border-light px-5 py-4 dark:border-border-medium">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-text-primary">{exp.title}</div>
                  {exp.hypothesis && <p className="mt-1 text-xs leading-relaxed text-text-secondary">{exp.hypothesis}</p>}
                </div>
                <Chip
                  tone={exp.status === 'completed' ? 'success' : exp.status === 'running' ? 'primary' : 'default'}
                >
                  {exp.status === 'planned' ? 'Planned' : exp.status === 'running' ? 'Running' : 'Completed'}
                </Chip>
              </div>
              <div className="flex-1 space-y-2 px-5 py-4">
                {exp.intended_metric && (
                  <div className="text-xs text-text-secondary">
                    <span className="text-text-tertiary">Intended metric: </span>
                    {exp.intended_metric}
                  </div>
                )}
                {exp.variation && (
                  <div className="text-xs text-text-secondary">
                    <span className="text-text-tertiary">Variation: </span>
                    {exp.variation}
                  </div>
                )}
                {exp.actual_result && (
                  <div className="rounded-lg border border-border-light bg-bg-primary/70 px-3.5 py-2.5 text-xs leading-relaxed text-text-secondary dark:border-border-medium dark:bg-ink-850/70">
                    <span className="font-semibold text-text-primary">Result: </span>
                    {exp.actual_result}
                    <span className="ml-1 text-text-quaternary">(single observation, not proof)</span>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2 border-t border-border-light px-5 py-3 dark:border-border-medium">
                {exp.status === 'planned' && (
                  <button className="btn btn-secondary btn-sm" onClick={() => updateExperiment(exp.id, { status: 'running' })}>
                    Start running
                  </button>
                )}
                {exp.status === 'running' && (
                  <button
                    className="btn btn-sm border-success-200 bg-success-50 text-success-700 hover:bg-success-100 dark:border-success-800 dark:bg-success-900/30 dark:text-success-300"
                    onClick={() => {
                      const result = window.prompt('Actual result (observed, not causal):')
                      if (result !== null) {
                        updateExperiment(exp.id, { status: 'completed', actual_result: result })
                      }
                    }}
                  >
                    Record result & complete
                  </button>
                )}
                {exp.status === 'completed' && (
                  <span className="text-xs text-text-tertiary">
                    Completed{exp.completed_at ? ` · ${new Date(exp.completed_at).toLocaleDateString()}` : ''}
                  </span>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
