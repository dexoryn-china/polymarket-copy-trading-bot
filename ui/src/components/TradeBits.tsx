import type { Tone } from './ui/Badge'
import { Badge } from './ui/Badge'
import { cn } from '../lib/cn'
import { formatSignedUsd } from '../lib/format'

const sideTones: Record<string, Tone> = {
  long: 'success',
  yes: 'success',
  buy: 'success',
  short: 'danger',
  no: 'danger',
  sell: 'danger',
}

export function SideBadge({ side }: { side: string }) {
  return (
    <Badge tone={sideTones[side.toLowerCase()] ?? 'neutral'} className="uppercase">
      {side}
    </Badge>
  )
}

export function PnlText({ value, className }: { value: number | null; className?: string }) {
  return (
    <span
      className={cn(
        'tabular-nums',
        value == null || value === 0 ? 'text-zinc-400' : value > 0 ? 'text-emerald-400' : 'text-rose-400',
        className,
      )}
    >
      {formatSignedUsd(value)}
    </span>
  )
}
