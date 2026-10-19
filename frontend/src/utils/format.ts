export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}

export function indexLabel(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}x`
}

/** Dates arrive as ISO strings; render the day only, in the user's locale. */
export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function fullDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

/**
 * The LLM layer returns a small, predictable subset of Markdown. Rendering it
 * with a regex pass keeps the app dependency-free; anything else is shown as
 * plain text, never injected as HTML.
 */
export function renderInline(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

export function splitBlocks(answer: string): { kind: 'text' | 'bullet' | 'heading'; value: string }[] {
  const blocks: { kind: 'text' | 'bullet' | 'heading'; value: string }[] = []
  for (const rawLine of answer.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue
    if (/^[-•]\s+/.test(line)) {
      blocks.push({ kind: 'bullet', value: line.replace(/^[-•]\s+/, '') })
    } else if (/^\*\*[^*]+\*\*:?$/.test(line) || /^#{1,4}\s+/.test(line)) {
      blocks.push({ kind: 'heading', value: line.replace(/^#{1,4}\s+/, '').replace(/\*\*|:$/g, '') })
    } else {
      blocks.push({ kind: 'text', value: line })
    }
  }
  return blocks
}
