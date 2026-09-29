import { Save } from 'lucide-react'
import { Button } from '../ui/Button'

interface SaveBarProps {
  count: number
  saving: boolean
  onSave: () => void
  onDiscard: () => void
}

export function SaveBar({ count, saving, onSave, onDiscard }: SaveBarProps) {
  if (count === 0) return null
  return (
    <div className="sticky bottom-4 z-30 mt-6">
      <div
        role="region"
        aria-label="Unsaved changes"
        className="animate-pop-in flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-500/30 bg-zinc-900/95 px-4 py-3 shadow-2xl shadow-black/40 backdrop-blur"
      >
        <p className="text-sm text-zinc-200">
          <span className="font-semibold tabular-nums">{count}</span> unsaved change{count === 1 ? '' : 's'}
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onDiscard} disabled={saving}>
            Discard
          </Button>
          <Button variant="primary" icon={<Save className="size-4" aria-hidden />} onClick={onSave} loading={saving}>
            Save
          </Button>
        </div>
      </div>
    </div>
  )
}
