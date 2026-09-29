import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  Briefcase,
  LayoutDashboard,
  Menu,
  PauseCircle,
  Settings,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useMeta, useStatus } from '../api/queries'
import { useLiveSocket } from '../api/ws'
import { cn } from '../lib/cn'
import { CopyControl } from './CopyControl'
import { ConnectionIndicator, ModeBadge } from './StatusBits'
import { TokenPrompt } from './TokenPrompt'

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/targets', label: 'Targets', icon: Users },
  { to: '/positions', label: 'Positions', icon: Briefcase },
  { to: '/activity', label: 'Activity', icon: Activity },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function Logo() {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span className="text-sm font-semibold leading-tight tracking-tight text-zinc-50">
        Polymarket{' '}
        <span className="block text-xs font-medium text-zinc-400">Copy Bot</span>
      </span>
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <ul className="space-y-1">
      {NAV.map(({ to, label, icon: Icon }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                'focus-visible:outline-2 focus-visible:outline-indigo-500',
                isActive
                  ? 'bg-indigo-500/10 text-indigo-200 ring-1 ring-inset ring-indigo-500/20'
                  : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-100',
              )
            }
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </NavLink>
        </li>
      ))}
    </ul>
  )
}

export function Layout() {
  useLiveSocket()
  const { data: meta } = useMeta()
  const { data: status } = useStatus()
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setMenuOpen(false), [location.pathname])

  const mode = status?.mode ?? meta?.mode

  return (
    <div className="min-h-dvh md:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-indigo-600 focus:px-3 focus:py-2 focus:text-sm focus:text-white"
      >
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/80 md:flex">
        <div className="flex h-14 items-center justify-between px-4">
          <Logo />
          <ModeBadge mode={mode} />
        </div>
        <CopyControl className="border-y border-zinc-800/80 px-4 py-4" />
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
          <NavItems />
        </nav>
        <div className="space-y-1 border-t border-zinc-800/80 px-4 py-3">
          <ConnectionIndicator />
          {meta?.version && <p className="text-[11px] text-zinc-600">v{meta.version}</p>}
        </div>
      </aside>

      <header className="sticky top-0 z-40 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur md:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <Logo />
          <div className="flex items-center gap-3">
            <ConnectionIndicator />
            <ModeBadge mode={mode} />
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-2 focus-visible:outline-indigo-500"
            >
              {menuOpen ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Main" className="border-t border-zinc-800/80 px-3 py-3">
            <NavItems onNavigate={() => setMenuOpen(false)} />
          </nav>
        )}
      </header>

      <main id="main" className="min-w-0 flex-1">
        <CopyControl layout="row" className="border-b border-zinc-800/80 px-4 py-3 md:hidden" />
        {status?.paused && status.copy.running && (
          <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-300 md:px-8">
            <PauseCircle className="size-4 shrink-0" aria-hidden />
            Copying is paused — new entries are skipped, exits are still mirrored.
          </div>
        )}
        <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </div>
      </main>

      <TokenPrompt />
    </div>
  )
}
