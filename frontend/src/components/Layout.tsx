import { useState } from 'react'
import { Link, NavLink as NavLinkBase, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import { useAuth } from '../context/AuthContext'
import { useHealth } from '../context/HealthContext'
import { useTheme } from '../context/ThemeContext'

type NavItem = { to: string; label: string; icon: NavIconName }

type NavIconName =
  | 'grid'
  | 'chart'
  | 'trend'
  | 'library'
  | 'plus'
  | 'photo'
  | 'clipboard'
  | 'instagram'
  | 'compass'
  | 'calendar'
  | 'bulb'
  | 'chat'
  | 'sparkles'

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: 'grid' },
      { to: '/analytics', label: 'Analytics', icon: 'chart' },
      { to: '/performance', label: 'Performance', icon: 'trend' },
    ],
  },
  {
    label: 'Content',
    items: [
      { to: '/content', label: 'Content Library', icon: 'library' },
      { to: '/content/new', label: 'Add Content', icon: 'plus' },
      { to: '/media', label: 'Media Library', icon: 'photo' },
      { to: '/reviewer', label: 'Reviewer', icon: 'clipboard' },
      { to: '/planner', label: 'Content Planner', icon: 'calendar' },
    ],
  },
  {
    label: 'Channels',
    items: [{ to: '/instagram', label: 'Instagram', icon: 'instagram' }],
  },
  {
    label: 'AI Strategy',
    items: [
      { to: '/strategy', label: 'Strategy', icon: 'compass' },
      { to: '/chat', label: 'Strategy Chat', icon: 'chat' },
      { to: '/learned', label: "What I've Learned", icon: 'bulb' },
      { to: '/demo', label: 'Memory Demo', icon: 'sparkles' },
    ],
  },
]

const PAGE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/analytics': 'Analytics',
  '/performance': 'Performance',
  '/content': 'Content Library',
  '/content/new': 'Add Content',
  '/media': 'Media Library',
  '/reviewer': 'Reviewer',
  '/planner': 'Content Planner',
  '/instagram': 'Instagram',
  '/strategy': 'Strategy',
  '/chat': 'Strategy Chat',
  '/learned': "What I've Learned",
  '/demo': 'Memory Demo',
}

const ICON_PATHS: Record<NavIconName, ReactNode> = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />
    </>
  ),
  trend: (
    <>
      <path d="M3 17l6-6 4 4 7-7" />
      <path d="M14 8h7v7" />
    </>
  ),
  library: (
    <>
      <path d="M4 5.5A2.5 2.5 0 016.5 3H11v16H6.5A2.5 2.5 0 004 21.5v-16z" />
      <path d="M20 5.5A2.5 2.5 0 0017.5 3H13v16h4.5a2.5 2.5 0 012.5 2.5v-16z" />
    </>
  ),
  plus: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v8M8 12h8" />
    </>
  ),
  photo: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="M4 17l4.5-4.5a2 2 0 012.8 0L16 17M14 15l1.7-1.7a2 2 0 012.8 0L21 16" />
    </>
  ),
  clipboard: (
    <>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4a2 2 0 012-2h2a2 2 0 012 2" />
      <path d="M9 13l2 2 4-4" />
    </>
  ),
  instagram: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.2" cy="6.8" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  compass: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M15.5 8.5l-2 5-5 2 2-5 5-2z" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2.5" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </>
  ),
  bulb: (
    <>
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 00-3.5 10.9c.6.5.9 1.2.9 1.9v.2h5.2v-.2c0-.7.3-1.4.9-1.9A6 6 0 0012 3z" />
    </>
  ),
  chat: (
    <>
      <path d="M21 12a8 8 0 01-8 8H4l2-3a8 8 0 1115-5z" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3z" />
      <path d="M18.5 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1z" />
    </>
  ),
}

function NavIcon({ name, className = 'h-[1.15rem] w-[1.15rem]' }: { name: NavIconName; className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICON_PATHS[name]}
    </svg>
  )
}

export function MemoryStatusBanner() {
  const { loading, error } = useHealth()

  if (loading || !error) return null
  return (
    <div className="border-b border-error-200 bg-error-50 px-5 py-1.5 text-center text-xs font-medium text-error-600 dark:border-error-800 dark:bg-error-900/40 dark:text-error-300">
      Backend unreachable — {error}
    </div>
  )
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { email, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const { health } = useHealth()

  return (
    <div className="flex h-full flex-col">
      <Link to="/" onClick={onNavigate} className="flex items-center gap-3 px-5 pb-5 pt-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-500 text-base font-bold text-white shadow-[0_4px_12px_rgba(99,91,255,0.45)]">
          C
        </div>
        <div className="min-w-0">
          <div className="text-[0.95rem] font-semibold leading-tight tracking-tight text-white">ContentMind</div>
          <div className="text-[0.65rem] leading-tight text-navy-500">Your content strategy remembers.</div>
        </div>
      </Link>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-4 last:mb-0">
            <div className="px-3 pb-1.5 text-[0.62rem] font-semibold uppercase tracking-[0.14em] text-navy-600">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLinkBase
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[0.8125rem] font-medium transition-colors ${
                      isActive
                        ? 'bg-white/10 text-white'
                        : 'text-navy-500 hover:bg-white/[0.06] hover:text-gray-200'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span
                        className={`absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary-500 transition-opacity ${
                          isActive ? 'opacity-100' : 'opacity-0'
                        }`}
                      />
                      <NavIcon name={item.icon} className={`h-[1.15rem] w-[1.15rem] shrink-0 ${isActive ? 'text-primary-400' : ''}`} />
                      <span className="truncate">{item.label}</span>
                    </>
                  )}
                </NavLinkBase>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/10 px-3 py-4">
        <div className="mb-3 flex items-center gap-1 rounded-lg bg-white/[0.06] p-1">
          {(['light', 'dark', 'system'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setTheme(mode)}
              className={`flex-1 rounded-md px-2 py-1.5 text-[0.68rem] font-semibold capitalize transition-colors ${
                theme === mode ? 'bg-primary-500 text-white shadow-xs' : 'text-navy-500 hover:text-gray-300'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>

        {email && (
          <div className="flex items-center justify-between gap-2 px-1">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-500/20 text-[0.7rem] font-bold uppercase text-primary-300">
                {email.slice(0, 1)}
              </div>
              <div className="truncate text-[0.7rem] text-navy-500">{email}</div>
            </div>
            <button
              onClick={logout}
              className="shrink-0 rounded-md px-2 py-1 text-[0.68rem] font-medium text-navy-500 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              Sign out
            </button>
          </div>
        )}

        <p className="mt-3 px-1 text-[0.6rem] leading-relaxed text-navy-600">
          Hindsight by Vectorize is the long-term memory layer.
        </p>

        {health?.memory.degraded && (
          <p className="mt-1 flex items-center gap-1.5 px-1 text-[0.6rem] leading-relaxed text-warning-500/90">
            <span className="h-1 w-1 shrink-0 rounded-full bg-warning-500" />
            Local memory fallback active
          </p>
        )}
      </div>
    </div>
  )
}

function HealthPill() {
  const { health, error } = useHealth()

  if (error) {
    return (
      <span className="hidden items-center gap-2 rounded-full border border-error-200 bg-error-50 px-3 py-1 text-[0.7rem] font-medium text-error-600 dark:border-error-800 dark:bg-error-900/40 dark:text-error-300 sm:inline-flex">
        <span className="h-1.5 w-1.5 rounded-full bg-error-500" />
        Backend offline
      </span>
    )
  }

  if (!health) {
    return (
      <span className="hidden items-center gap-2 rounded-full border border-border-light bg-bg-secondary px-3 py-1 text-[0.7rem] font-medium text-text-tertiary sm:inline-flex">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-text-tertiary" />
        Connecting…
      </span>
    )
  }

  const healthy = health.status === 'ok'
  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border-light bg-bg-secondary px-3 py-1 text-[0.7rem] font-medium text-text-secondary sm:inline-flex"
      title={`${health.llm.model} · memory: ${health.memory.backend} · db: ${health.database.content_count} items`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${healthy ? 'bg-success-500' : 'bg-warning-500'}`} />
      {health.memory.memory_count.toLocaleString()} memories
      <span className="text-border-strong">·</span>
      {health.database.content_count.toLocaleString()} items
    </span>
  )
}

const THEME_ICON: Record<'light' | 'dark' | 'system', ReactNode> = {
  light: (
    <path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M17.657 17.657l.707.707M4 12a8 8 0 1116 0 8 8 0 01-16 0z" />
  ),
  dark: (
    <path d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
  ),
  system: (
    <path d="M9.75 17L9 20l-1 1h8l-1-1-.707.707-13.14-13.14a2.121 2.121 0 010-3L11 7.364V5.5a2.5 2.5 0 00-5 0v2.843l-7 7 7 7 1.414-1.414L5.5 16.757A24.05 24.05 0 017 14c2.28 0 4.383.919 5.879 2.4.915.88 1.616 2.034 1.99 3.331.324 1.13.91 2.165 1.347 3.388l.64-.64a5.93 5.93 0 001.312-4.277C18.091 7.678 19 6.133 19 4.44 19 3.052 17.849 2 16.44 2c-2.337 0-4.503.872-6.188 2.377l-.752-.752a40.086 40.086 0 0114.287 0 9 9 0 10-12.727 12.73z" />
  ),
}

export function Layout({ children }: { children: ReactNode }) {
  const { theme, toggleTheme } = useTheme()
  const { email } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] ?? 'ContentMind'

  return (
    <div className="flex min-h-screen bg-bg-primary">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 bg-navy-900 dark:bg-navy-950 lg:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 w-[276px] max-w-[85vw] bg-navy-900 shadow-2xl dark:bg-navy-950">
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <MemoryStatusBanner />

        {/* Compact header */}
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-border-light bg-bg-secondary/90 px-4 backdrop-blur-md dark:border-border-medium dark:bg-bg-secondary/80 lg:px-8">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-border-light text-text-secondary transition-colors hover:bg-bg-hover lg:hidden"
            aria-label="Open navigation"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>

          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-500 text-sm font-bold text-white lg:hidden">
            C
          </div>

          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold leading-tight text-text-primary">{title}</div>
            <div className="hidden truncate text-[0.68rem] text-text-tertiary sm:block">
              ContentMind AI workspace
            </div>
          </div>

          <HealthPill />

          <button
            type="button"
            onClick={toggleTheme}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-border-light text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            aria-label={`Current theme: ${theme}. Click to cycle light, dark, system.`}
            title={`Theme: ${theme}`}
          >
            <svg className="h-[1.15rem] w-[1.15rem]" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
              {THEME_ICON[theme]}
            </svg>
          </button>

          {email && (
            <div
              className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-500 text-xs font-bold uppercase text-white"
              title={email}
            >
              {email.slice(0, 1)}
            </div>
          )}
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 pb-16 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
          <footer className="border-t border-border-light pt-8 text-center text-sm text-text-tertiary dark:border-border-medium dark:text-bg-secondary/50">
            <a href="/privacy-policy" className="underline font-medium text-primary-600 dark:text-primary-400">Privacy Policy</a>
            <span className="mx-4">|</span>
            <a href="/terms-of-service" className="underline font-medium text-primary-600 dark:text-primary-400">Terms of Service</a>
          </footer>
        </main>
      </div>
    </div>
  )
}
