import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { useHealth } from '../context/HealthContext'
import { MemoryCitations } from '../components/MemoryCitations'
import { Card, Chip, ErrorNote, SectionHeader } from '../components/ui'
import type { ChatResponse } from '../types'
import { renderInline, splitBlocks } from '../utils/format'

interface Turn {
  id: number
  question: string
  response: ChatResponse
}

const STARTERS = [
  'What should I post next week?',
  'Which topics should I double down on?',
  'Where are my biggest content gaps?',
  'What formats perform best?',
]

export function Chat() {
  const { health } = useHealth()
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nextId = useRef(1)
  const scrollRef = useRef<HTMLDivElement>(null)

  const hasHistory = (health?.database.content_count ?? 0) > 0

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, busy])

  async function ask(question: string) {
    const trimmed = question.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError(null)
    setInput('')
    try {
      const { data } = await api.post<ChatResponse>('/chat', { message: trimmed })
      setTurns((prev) => [...prev, { id: nextId.current++, question: trimmed, response: data }])
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen py-6 bg-bg-primary">
      <div className="max-w-7xl mx-auto px-4">
        <SectionHeader
          title="AI Strategy Chat"
          subtitle="Ask anything about your content strategy. The answer shows its sources."
          action={
            <Link to="/learned" className="btn btn-secondary">
              What it's learned
            </Link>
          }
        />

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="lg:col-span-2">
            <Card className="flex min-h-[32rem] flex-col p-0">
              <div
                ref={scrollRef}
                className="flex-1 space-y-5 overflow-y-auto p-5"
              >
                {turns.length === 0 && (
                  <div className="flex h-full flex-col items-center justify-center py-12 text-center">
                    <h2 className="text-sm font-semibold">
                      {hasHistory ? 'Ask about your content strategy' : 'ContentMind has nothing to work with yet'}
                    </h2>
                    <p className="mx-auto mt-1.5 max-w-md text-sm text-ink-400">
                      {hasHistory
                        ? 'Every answer cites the long-term memories it used, so you can check the reasoning rather than trust it.'
                        : 'Without history, any answer would be generic. Add content, or run the demo, and then ask again.'}
                    </p>
                    <div className="mt-5 flex flex-wrap justify-center gap-2">
                      {(hasHistory ? STARTERS : []).map((s) => (
                        <button key={s} type="button" className="chip" onClick={() => void ask(s)}>
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {turns.map((turn) => (
                  <TurnView key={turn.id} turn={turn} />
                ))}

                {busy && (
                  <div className="flex items-center gap-2.5 text-sm text-text-tertiary">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-600 border-t-brand-400" />
                    Recalling memories…
                  </div>
                )}
              </div>

              <div className="border-t border-border-light p-4">
                {error && <ErrorNote message={`${error}`} />}
                <form
                  className="mt-3 flex gap-2.5"
                  onSubmit={(e) => {
                    e.preventDefault()
                    void ask(input)
}}
                >
                  <input
                    className="field flex-1"
                    placeholder="What should I post next week?"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    disabled={busy}
                  />
                  <button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>
                    Ask
                  </button>
                </form>
              </div>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <h2 className="text-sm font-semibold text-text-primary">How answers are built</h2>
              <ol className="mt-3 space-y-2 text-sm text-text-tertiary">
                {
                  [
                    'Your question is decomposed into aspects.',
                    'Each aspect triggers a separate recall against long-term memory.',
                    'Performance data is computed live from your history.',
                    'The model reasons over both, then cites the memories it used.',
                  ].map((step, i) => (
                    <li key={step} className="flex gap-2.5">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-ink-600 text-[0.65rem] text-text-tertiary">
                        {i + 1}
                      </span>
                      {step}
                    </li>
                  ))}
                </ol>
            </Card>

            <Card>
              <h2 className="text-sm font-semibold text-text-primary">Right now</h2>
              <dl className="mt-3 space-y-1.5 text-sm">
                <SideRow label="Memory" value={health?.memory.backend ?? '—'} />
                <SideRow label="Memories" value={String(health?.memory.memory_count ?? 0)} />
                <SideRow label="Items analysed" value={String(health?.database.content_count ?? 0)} />
                <SideRow
                  label="Degraded"
                  value={health?.memory.degraded ? 'yes — local fallback' : 'no'}
                />
              </dl>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

function TurnView({ turn }: { turn: Turn }) {
  const { response } = turn
  const confidenceTone =
    response.confidence === 'high' ? 'success' : response.confidence === 'medium' ? 'warning' : 'default'

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2 text-sm">
          {turn.question}
        </div>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Chip tone={confidenceTone}>confidence: {response.confidence}</Chip>
          <Chip tone={response.memory_count > 0 ? 'success' : 'warning'}>
            {response.memory_count} memories used
          </Chip>
          <Chip>{response.content_analyzed} items analysed</Chip>
        </div>

        <div className="prose-answer rounded-xl border border-ink-700 bg-ink-900/70 px-4 py-3 text-sm text-ink-100">
          {splitBlocks(response.answer).map((block, i) =>
            block.kind === 'bullet' ? (
              <ul key={i}>
                <li dangerouslySetInnerHTML={{ __html: renderInline(block.value) }} />
              </ul>
            ) : block.kind === 'heading' ? (
              <h3 key={i} className="mb-1.5 mt-3 text-sm font-semibold text-ink-100 first:mt-0">
                {block.value}
              </h3>
            ) : (
              <p key={i} dangerouslySetInnerHTML={{ __html: renderInline(block.value) }} />
            ),
          )}
        </div>

        {response.memories_used.length > 0 && (
          <details className="mt-2.5 rounded-xl border border-ink-700 bg-ink-900/50 px-4 py-2.5">
            <summary className="cursor-pointer text-xs text-ink-400 hover:text-ink-200">
              Show the {response.memories_used.length} memories behind this answer
            </summary>
            <div className="mt-3">
              <MemoryCitations memories={response.memories_used} title="Recalled for this question" />
            </div>
          </details>
        )}

        {response.suggestions.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {response.suggestions.map((s) => (
              <span key={s} className="chip">
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SideRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-400">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  )
}
