import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface TabsProps<T extends string> {
  value: T
  onChange: (value: T) => void
  items: { value: T; label: ReactNode; count?: number }[]
  label: string
}

export function Tabs<T extends string>({ value, onChange, items, label }: TabsProps<T>) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-lg border border-zinc-800 bg-zinc-900 p-1">
      {items.map((item) => {
        const active = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              'focus-visible:outline-2 focus-visible:outline-indigo-500',
              active ? 'bg-zinc-800 text-zinc-50 shadow-sm' : 'text-zinc-400 hover:text-zinc-200',
            )}
          >
            {item.label}
            {item.count != null && (
              <span
                className={cn(
                  'rounded px-1.5 text-[11px] tabular-nums',
                  active ? 'bg-indigo-500/20 text-indigo-300' : 'bg-zinc-800 text-zinc-500',
                )}
              >
                {item.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
