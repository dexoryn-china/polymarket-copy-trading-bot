import { useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Info,
  type LucideIcon,
} from 'lucide-react'
import type { Activity, ActivityLevel } from '../api/types'
import { ACTIVITY_KINDS } from '../api/types'
import { cn } from '../lib/cn'
import { formatAbsolute, formatClock, formatRelative, humanizeKey } from '../lib/format'
import { Badge } from './ui/Badge'

const levelStyles: Record<ActivityLevel, { icon: LucideIcon; color: string; ring: string }> = {
  info: { icon: Info, color: 'text-sky-300', ring: 'bg-sky-500/10' },
  success: { icon: CheckCircle2, color: 'text-emerald-400', ring: 'bg-emerald-500/10' },
  warning: { icon: AlertTriangle, color: 'text-amber-400', ring: 'bg-amber-500/10' },
  error: { icon: AlertCircle, color: 'text-rose-400', ring: 'bg-rose-500/10' },
}

const kindLabel = Object.fromEntries(ACTIVITY_KINDS.map((k) => [k.value, k.label])) as Record<string, string>

function LevelIcon({ level }: { level: ActivityLevel }) {
  const s = levelStyles[level] ?? levelStyles.info
  const Icon = s.icon
  return (
    <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full', s.ring)}>
      <Icon className={cn('size-4', s.color)} aria-label={level} />
    </span>
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

function DataList({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) return <p className="text-xs text-zinc-500">No additional data.</p>
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[max-content_1fr]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-xs font-medium text-zinc-500">{humanizeKey(k)}</dt>
          <dd className="whitespace-pre-wrap break-all font-mono text-xs text-zinc-300">{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

interface ActivityItemProps {
  item: Activity
  now: number
  compact?: boolean
}

export function ActivityItem({ item, now, compact }: ActivityItemProps) {
  const [open, setOpen] = useState(false)
  const expandable = !compact && Object.keys(item.data ?? {}).length > 0

  const content = (
    <>
      <LevelIcon level={item.level} />
      <div className="min-w-0 flex-1">
        <p className={cn('text-sm text-zinc-200', compact && 'truncate')}>{item.summary}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
          {!compact && <Badge>{kindLabel[item.kind] ?? item.kind}</Badge>}
          {item.target_name && <span className="text-zinc-400">{item.target_name}</span>}
          {item.venue && <span className="capitalize">· {item.venue}</span>}
        </div>
      </div>
      <time
        dateTime={new Date(item.ts_ms).toISOString()}
        title={formatAbsolute(item.ts_ms)}
        className="shrink-0 whitespace-nowrap text-right text-xs tabular-nums text-zinc-500"
      >
        {formatRelative(item.ts_ms, now)}
        {!compact && <span className="block text-[11px] text-zinc-600">{formatClock(item.ts_ms)}</span>}
      </time>
      {expandable && (
        <ChevronRight
          className={cn('mt-1.5 size-4 shrink-0 text-zinc-600 transition-transform', open && 'rotate-90')}
          aria-hidden
        />
      )}
    </>
  )

  if (!expandable) {
    return <div className="flex items-start gap-3 px-4 py-3">{content}</div>
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-800/30 focus-visible:bg-zinc-800/40 focus-visible:outline-none"
      >
        {content}
      </button>
      {open && (
        <div className="mx-4 mb-3 ml-14 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <DataList data={item.data} />
        </div>
      )}
    </div>
  )
}
