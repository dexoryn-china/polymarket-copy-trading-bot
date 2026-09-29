import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export type Tone = 'neutral' | 'success' | 'danger' | 'warning' | 'accent' | 'info'

const tones: Record<Tone, string> = {
  neutral: 'bg-zinc-800 text-zinc-300 ring-zinc-700',
  success: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/30',
  danger: 'bg-rose-500/10 text-rose-400 ring-rose-500/30',
  warning: 'bg-amber-500/10 text-amber-400 ring-amber-500/30',
  accent: 'bg-indigo-500/10 text-indigo-300 ring-indigo-500/30',
  info: 'bg-sky-500/10 text-sky-300 ring-sky-500/30',
}

interface BadgeProps {
  tone?: Tone
  icon?: ReactNode
  className?: string
  title?: string
  children: ReactNode
}

export function Badge({ tone = 'neutral', icon, className, title, children }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset',
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}
