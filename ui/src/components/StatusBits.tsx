import { Radio } from 'lucide-react'
import type { Feed, Mode } from '../api/types'
import { useWsState } from '../api/ws'
import { cn } from '../lib/cn'
import { formatRelative } from '../lib/format'
import { Badge } from './ui/Badge'

export function ModeBadge({ mode, className }: { mode: Mode | undefined; className?: string }) {
  if (!mode) return null
  return mode === 'real' ? (
    <Badge tone="success" className={cn('uppercase tracking-wider', className)}>
      <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden />
      Live
    </Badge>
  ) : (
    <Badge tone="warning" className={cn('uppercase tracking-wider', className)}>
      Dry run
    </Badge>
  )
}

const wsLabels = {
  open: { text: 'Live', dot: 'bg-emerald-400', title: 'Realtime updates connected' },
  connecting: { text: 'Connecting', dot: 'bg-amber-400 animate-pulse', title: 'Connecting to realtime updates…' },
  closed: { text: 'Offline', dot: 'bg-rose-500', title: 'Realtime updates disconnected — retrying' },
} as const

export function ConnectionIndicator({ className }: { className?: string }) {
  const state = useWsState()
  const s = wsLabels[state]
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 text-xs text-zinc-400', className)}
      title={s.title}
      role="status"
      aria-label={s.title}
    >
      <span className={cn('size-2 rounded-full', s.dot)} aria-hidden />
      {s.text}
    </span>
  )
}

export function FeedChip({ feed, now }: { feed: Feed; now: number }) {
  const title = [
    feed.connected ? 'Connected' : 'Disconnected',
    `last event ${formatRelative(feed.last_event_ms, now)}`,
    `${feed.reconnects} reconnect${feed.reconnects === 1 ? '' : 's'}`,
  ].join(' · ')
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
        feed.connected
          ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-300'
          : 'border-rose-500/30 bg-rose-500/5 text-rose-300',
      )}
    >
      <Radio className="size-3.5" aria-hidden />
      {feed.label}
      <span className="text-zinc-500">{formatRelative(feed.last_event_ms, now)}</span>
    </span>
  )
}
