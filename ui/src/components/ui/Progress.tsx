import { cn } from '../../lib/cn'

interface ProgressProps {
  value: number
  label: string
  className?: string
  tone?: 'auto' | 'accent'
}

export function Progress({ value, label, className, tone = 'auto' }: ProgressProps) {
  const pct = Math.max(0, Math.min(100, value))
  const color =
    tone === 'accent'
      ? 'bg-indigo-500'
      : pct >= 90
        ? 'bg-rose-500'
        : pct >= 70
          ? 'bg-amber-500'
          : 'bg-emerald-500'
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-zinc-800', className)}
    >
      <div className={cn('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${pct}%` }} />
    </div>
  )
}
