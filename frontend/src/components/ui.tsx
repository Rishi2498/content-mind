import type { ReactNode } from 'react'

export type Tone = 'default' | 'brand' | 'primary' | 'success' | 'warning' | 'error' | 'amber'

const TONE_TEXT: Record<Tone, string> = {
  default: 'text-text-primary',
  brand: 'text-primary-600 dark:text-primary-400',
  primary: 'text-primary-600 dark:text-primary-400',
  success: 'text-success-600 dark:text-success-400',
  warning: 'text-warning-600 dark:text-warning-400',
  error: 'text-error-600 dark:text-error-400',
  amber: 'text-warning-600 dark:text-warning-400',
}

const TONE_ICON_BG: Record<Tone, string> = {
  default: 'bg-bg-tertiary text-text-secondary',
  brand: 'bg-primary-50 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300',
  primary: 'bg-primary-50 text-primary-600 dark:bg-primary-900/40 dark:text-primary-300',
  success: 'bg-success-50 text-success-600 dark:bg-success-900/40 dark:text-success-300',
  warning: 'bg-warning-50 text-warning-600 dark:bg-warning-900/40 dark:text-warning-300',
  error: 'bg-error-50 text-error-600 dark:bg-error-900/40 dark:text-error-300',
  amber: 'bg-warning-50 text-warning-600 dark:bg-warning-900/40 dark:text-warning-300',
}

export function Card({
  children,
  className = '',
  hover = false,
  style,
}: {
  children: ReactNode
  className?: string
  hover?: boolean
  style?: React.CSSProperties
}) {
  return (
    <div className={`${hover ? 'card-interactive' : 'card'} ${className}`} style={style}>{children}</div>
  )
}

export function CardHeader({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`flex items-center justify-between gap-3 border-b border-border-light px-5 py-3.5 dark:border-border-medium ${className}`}>
      {children}
    </div>
  )
}

export function CardContent({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`p-5 ${className}`}>{children}</div>
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  eyebrow?: string
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-primary-600 dark:text-primary-400">
            {eyebrow}
          </div>
        )}
        <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-text-primary">
          {title}
        </h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text-secondary">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </div>
  )
}

/** Back-compat alias — older pages call SectionHeader. */
export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: ReactNode
}) {
  return <PageHeader title={title} subtitle={subtitle} actions={action} />
}

export function Stat({
  label,
  value,
  hint,
  tone = 'default',
  icon,
  delta,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: Tone
  icon?: ReactNode
  delta?: ReactNode
}) {
  return (
    <div className="card flex items-start gap-4 p-5">
      {icon !== undefined && (
        <div className={`hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl sm:flex ${TONE_ICON_BG[tone]}`}>
          {icon}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-text-tertiary">{label}</span>
          {delta && <span className="shrink-0">{delta}</span>}
        </div>
        <div className={`mt-1.5 truncate text-[1.65rem] font-semibold leading-none tabular-nums ${TONE_TEXT[tone]}`}>
          {value}
        </div>
        {hint && <div className="mt-2 truncate text-xs text-text-tertiary">{hint}</div>}
      </div>
    </div>
  )
}

export function DeltaPill({ value, invert = false }: { value: string; invert?: boolean }) {
  const negative = value.startsWith('-')
  const good = invert ? negative : !negative
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[0.68rem] font-semibold tabular-nums ${
        good ? 'bg-success-50 text-success-600 dark:bg-success-900/40 dark:text-success-400' : 'bg-error-50 text-error-600 dark:bg-error-900/40 dark:text-error-400'
      }`}
    >
      {negative ? '↓' : '↑'} {value}
    </span>
  )
}

export function EmptyState({
  title,
  body,
  action,
  icon,
}: {
  title: string
  body: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="card flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="empty-state-icon text-xl">{icon ?? '✦'}</div>
      <h3 className="empty-state-title">{title}</h3>
      <p className="empty-state-body">{body}</p>
      {action && <div className="mt-1 flex flex-wrap justify-center gap-2.5">{action}</div>}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 text-sm text-text-tertiary">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border-medium border-t-primary-500" />
      {label ?? 'Loading…'}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`loading-skeleton ${className}`} />
}

export function ErrorNote({ message }: { message: string }) {
  return <div className="alert alert-error">{message}</div>
}

export function SuccessNote({ message }: { message: string }) {
  return <div className="alert alert-success">{message}</div>
}

export function Chip({
  children,
  tone = 'default',
  className = '',
}: {
  children: ReactNode
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'error'
  className?: string
}) {
  const cls = {
    default: 'badge badge-default',
    primary: 'badge badge-primary',
    success: 'badge badge-success',
    warning: 'badge badge-warning',
    error: 'badge badge-error',
  }[tone]
  return <span className={`${cls} ${className}`}>{children}</span>
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  ariaLabel,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  ariaLabel?: string
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-bg-tertiary p-1 dark:border-border-medium dark:bg-ink-850"
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={`rounded-md font-semibold transition-all ${
              size === 'sm' ? 'px-2.5 py-1 text-[0.7rem]' : 'px-3 py-1.5 text-xs'
            } ${
              active
                ? 'bg-bg-secondary text-primary-600 shadow-xs dark:bg-ink-700 dark:text-primary-300'
                : 'text-text-tertiary hover:text-text-secondary'
            }`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

export function Bar({
  value,
  max,
  tone = 'primary',
}: {
  value: number
  max: number
  tone?: 'primary' | 'success' | 'error'
}) {
  const pctValue = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  const bg = { primary: 'bg-primary-500', success: 'bg-success-500', error: 'bg-error-500' }[tone]
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-tertiary dark:bg-ink-700">
      <div className={`h-full rounded-full ${bg}`} style={{ width: `${pctValue}%` }} />
    </div>
  )
}

/** Small square tile used wherever content needs a visual placeholder. */
export function PreviewTile({
  seed,
  label,
  className = '',
}: {
  seed: string
  label?: string
  className?: string
}) {
  const palette = [
    'from-violet-500/80 to-indigo-500/80',
    'from-primary-500/80 to-primary-800/80',
    'from-emerald-500/80 to-teal-600/80',
    'from-amber-500/80 to-orange-600/80',
    'from-rose-500/80 to-pink-600/80',
    'from-sky-500/80 to-blue-600/80',
  ]
  const code = Array.from(seed).reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 7)
  const gradient = palette[code % palette.length]
  const initial = (seed.trim()[0] ?? '?').toUpperCase()
  return (
    <div
      className={`flex items-center justify-center overflow-hidden rounded-lg bg-gradient-to-br ${gradient} font-semibold text-white shadow-xs ring-1 ring-black/5 ${className}`}
      aria-hidden="true"
    >
      {label ?? initial}
    </div>
  )
}
