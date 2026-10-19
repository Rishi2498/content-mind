import { useState } from 'react'

import type { MemoryRecord } from '../types'

/**
 * Provenance is the whole point of the product, so recalled memories are
 * always rendered with where they came from, not as anonymous assertions.
 */
export function MemoryCitations({
  memories,
  title = 'Memories used',
  emptyHint,
}: {
  memories: MemoryRecord[]
  title?: string
  emptyHint?: string
}) {
  if (memories.length === 0) {
    return emptyHint ? (
      <div className="rounded-lg border border-dashed border-ink-600 px-3.5 py-3 text-xs text-ink-400">
        {emptyHint}
      </div>
    ) : null
  }

  return (
    <div>
      <div className="mb-2 text-[0.7rem] font-medium uppercase tracking-wider text-ink-400">
        {title} ({memories.length})
      </div>
      <ul className="space-y-2">
        {memories.map((memory) => (
          <li
            key={memory.id}
            className="rounded-lg border border-ink-700 bg-ink-900/70 px-3.5 py-2.5 text-sm"
          >
            <div className="flex flex-wrap items-center gap-2 text-[0.68rem] text-ink-400">
              <span className="rounded border border-ink-600 px-1.5 py-0.5 uppercase">
                {memory.kind}
              </span>
              {memory.document_id && <span>doc: {memory.document_id}</span>}
              <span>score {memory.score.toFixed(2)}</span>
              <span className="text-ink-600">via {memory.backend}</span>
            </div>
            <div className="mt-1.5 leading-relaxed text-ink-100">{memory.text}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ExpandableMemoryList({
  memories,
  initial = 3,
  label = 'memories',
}: {
  memories: MemoryRecord[]
  initial?: number
  label?: string
}) {
  const [expanded, setExpanded] = useState(false)
  if (memories.length === 0) return null
  const shown = expanded ? memories : memories.slice(0, initial)

  return (
    <div>
      <ul className="space-y-1.5">
        {shown.map((memory) => (
          <li key={memory.id} className="text-sm leading-relaxed text-ink-300">
            <span className="mr-1.5 text-ink-600">·</span>
            {memory.text}
          </li>
        ))}
      </ul>
      {memories.length > initial && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs text-brand-400 hover:underline"
        >
          {expanded ? 'Show fewer' : `Show all ${memories.length} ${label}`}
        </button>
      )}
    </div>
  )
}
