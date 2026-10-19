import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { useHealth } from '../context/HealthContext'
import { ExpandableMemoryList } from '../components/MemoryCitations'
import { Card, Chip, ErrorNote, SectionHeader } from '../components/ui'
import type { ChatResponse, DemoResetResponse } from '../types'
import { renderInline, splitBlocks } from '../utils/format'

interface ComparePayload {
  without_memory: ChatResponse
  with_memory: ChatResponse
  difference: string
}

export function Demo() {
  const { health, refresh } = useHealth()
  const [compare, setCompare] = useState<ComparePayload | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resetNote, setResetNote] = useState<string | null>(null)

  async function seed() {
    setBusy('seed')
    setError(null)
    setResetNote(null)
    setCompare(null)
    try {
      await api.post('/demo/reset')
      await api.post('/demo/seed', {})
      await refresh()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function reset() {
    setBusy('reset')
    setError(null)
    setCompare(null)
    try {
      const { data } = await api.post<DemoResetResponse>('/demo/reset')
      setResetNote(data.message)
      await refresh()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function runCompare() {
    setBusy('compare')
    setError(null)
    setResetNote(null)
    try {
      const { data } = await api.post<ComparePayload>('/demo/compare')
      setCompare(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function publishAndLearn() {
    setBusy('learn')
    setError(null)
    setResetNote(null)
    try {
      await api.post('/demo/publish-plan', { days: 7, posts_per_day: 2, platforms: ['LinkedIn'] })
      await refresh()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const hasHistory = (health?.database.content_count ?? 0) > 0

  return (
    <>
      <SectionHeader
        title="Memory Demo"
        subtitle="The same question, answered with and without long-term memory. Then feed results back and watch the recommendation change."
        action={
          <Link to="/learned" className="btn btn-secondary">
            What it's learned
          </Link>
        }
      />

      <Card className="mb-5">
        <h2 className="text-sm font-semibold">Run the story</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-300">
          Each step is idempotent. Start from a clean slate, load 72 synthetic content items with realistic
          performance patterns, ask the question both ways, then publish the plan and observe what the next
          recommendation does.
        </p>
        <div className="mt-4 flex flex-wrap gap-2.5">
          <button type="button" className="btn btn-primary" onClick={seed} disabled={busy !== null}>
            {busy === 'seed' ? 'Loading demo data…' : '1. Reset and seed 72 items'}
          </button>
          <button type="button" className="btn btn-secondary" onClick={runCompare} disabled={busy !== null || !hasHistory}>
            {busy === 'compare' ? 'Asking both ways…' : '2. Ask with and without memory'}
          </button>
          <button type="button" className="btn btn-secondary" onClick={publishAndLearn} disabled={busy !== null || !hasHistory}>
            {busy === 'learn' ? 'Publishing and learning…' : '3. Publish the plan and learn'}
          </button>
          <button type="button" className="btn btn-secondary" onClick={reset} disabled={busy !== null}>
            Reset everything
          </button>
        </div>
        {error && (
          <div className="mt-4">
            <ErrorNote message={error} />
          </div>
        )}
        {resetNote && (
          <p className="mt-3 text-sm text-mint-400">{resetNote}</p>
        )}
        {!hasHistory && !error && (
          <p className="mt-3 text-sm text-ink-400">
            No content yet. Start with step 1 to load the demo corpus.
          </p>
        )}
      </Card>

      {compare ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Without memory</h3>
              <Chip tone="warning">
                {compare.without_memory.memory_count} memories · confidence{' '}
                {compare.without_memory.confidence}
              </Chip>
            </div>
            <Answer answer={compare.without_memory.answer} />
            {compare.without_memory.memories_used.length === 0 && (
              <p className="mt-3 text-xs text-ink-600">
                No memories were used — this is what a stateless assistant would say.
              </p>
            )}
          </Card>

          <Card className="border-brand-500/40">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-brand-400">With memory</h3>
              <Chip tone="success">
                {compare.with_memory.memory_count} memories · confidence{' '}
                {compare.with_memory.confidence}
              </Chip>
            </div>
            <Answer answer={compare.with_memory.answer} />
            {compare.with_memory.memories_used.length > 0 && (
              <div className="mt-3 border-t border-ink-700 pt-3">
                <ExpandableMemoryList memories={compare.with_memory.memories_used} initial={2} />
              </div>
            )}
          </Card>

          {compare.difference && (
            <Card className="lg:col-span-2">
              <h3 className="text-sm font-semibold">Why this matters</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-300">{compare.difference}</p>
            </Card>
          )}
        </div>
      ) : (
        <Card>
          <h3 className="text-sm font-semibold">What to expect</h3>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div>
              <div className="text-xs font-medium uppercase tracking-wider text-amber-glow">
                Without memory
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-300">
                Generic advice. It will tell you to know your audience, post consistently, and use good
                visuals — none of which is specific to you.
              </p>
            </div>
            <div>
              <div className="text-xs font-medium uppercase tracking-wider text-mint-400">With memory</div>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-300">
                Names your actual winners and losers, quotes your real engagement rates, points at the
                specific gaps in your coverage, and cites the memories it used to do it.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card className="mt-5">
        <h3 className="text-sm font-semibold">The full loop</h3>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ['Remember', 'Every content item is written to long-term memory as traceable statements.'],
            ['Recall', 'Each question is decomposed into aspects and recalled separately.'],
            ['Reason', 'The model weighs recalled memory against live performance data.'],
            ['Recommend', 'Plans and answers arrive with reasons and citations attached.'],
            ['Learn', 'Publishing and observing results writes new memory, changing the next answer.'],
          ].map(([title, body], i) => (
            <li key={title} className="rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-brand-500/50 text-[0.65rem] text-brand-400">
                  {i + 1}
                </span>
                <span className="text-sm font-medium">{title}</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-400">{body}</p>
            </li>
          ))}
        </ol>
      </Card>
    </>
  )
}

function Answer({ answer }: { answer: string }) {
  return (
    <div className="prose-answer max-h-96 overflow-y-auto text-sm text-ink-100">
      {splitBlocks(answer).map((block, i) =>
        block.kind === 'bullet' ? (
          <ul key={i}>
            <li dangerouslySetInnerHTML={{ __html: renderInline(block.value) }} />
          </ul>
        ) : block.kind === 'heading' ? (
          <h4 key={i} className="mb-1.5 mt-3 text-sm font-semibold first:mt-0">
            {block.value}
          </h4>
        ) : (
          <p key={i} dangerouslySetInnerHTML={{ __html: renderInline(block.value) }} />
        ),
      )}
    </div>
  )
}
