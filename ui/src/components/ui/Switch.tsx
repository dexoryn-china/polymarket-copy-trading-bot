import { cn } from '../../lib/cn'

interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  showLabel?: boolean
  disabled?: boolean
  size?: 'sm' | 'md'
  id?: string
}

export function Switch({
  checked,
  onChange,
  label,
  showLabel,
  disabled,
  size = 'md',
  id,
}: SwitchProps) {
  const track = size === 'sm' ? 'h-5 w-9' : 'h-6 w-11'
  const thumb = size === 'sm' ? 'size-4' : 'size-5'
  const shift = size === 'sm' ? 'translate-x-4' : 'translate-x-5'

  const button = (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={showLabel ? undefined : label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500',
        'disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-emerald-500' : 'bg-zinc-700',
        track,
      )}
    >
      <span
        aria-hidden
        className={cn(
          'rounded-full bg-white shadow transition-transform',
          thumb,
          checked ? shift : 'translate-x-0',
        )}
      />
    </button>
  )

  if (!showLabel) return button
  return (
    <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm text-zinc-200">
      {button}
      <span>{label}</span>
    </label>
  )
}
