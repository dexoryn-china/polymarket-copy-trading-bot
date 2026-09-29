import { useId, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '../../lib/cn'

interface DisclosureProps {
  title: ReactNode
  open: boolean
  onToggle: (open: boolean) => void
  hint?: ReactNode
  children: ReactNode
}

export function Disclosure({ title, open, onToggle, hint, children }: DisclosureProps) {
  const panelId = useId()
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onToggle(!open)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-zinc-400 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
      >
        <ChevronRight className={cn('size-4 transition-transform', open && 'rotate-90')} aria-hidden />
        {title}
        {hint && <span className="ml-auto text-[11px] font-normal normal-case tracking-normal text-zinc-500">{hint}</span>}
      </button>
      {open && (
        <div id={panelId} className="space-y-4 border-t border-zinc-800 px-3 py-4">
          {children}
        </div>
      )}
    </div>
  )
}
