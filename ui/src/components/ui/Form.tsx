import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

const control =
  'w-full rounded-lg border bg-zinc-950/60 px-3 text-sm text-zinc-100 placeholder:text-zinc-600 transition-colors ' +
  'focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500 disabled:opacity-50'

export function Input({
  className,
  invalid,
  unit,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; unit?: string }) {
  const input = (
    <input
      aria-invalid={invalid || undefined}
      className={cn(
        control,
        'h-9',
        invalid ? 'border-rose-500/70' : 'border-zinc-700',
        unit && (unit.length > 3 ? 'pr-16' : 'pr-12'),
        className,
      )}
      {...rest}
    />
  )
  if (!unit) return input
  return (
    <div className="relative">
      {input}
      <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-zinc-500">
        {unit}
      </span>
    </div>
  )
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(control, 'h-9 border-zinc-700 pr-8', className)} {...rest}>
      {children}
    </select>
  )
}

interface FieldProps {
  label: ReactNode
  htmlFor: string
  help?: ReactNode
  error?: string | null
  children: ReactNode
}

export function FormField({ label, htmlFor, help, error, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-zinc-300">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-xs text-rose-400">
          {error}
        </p>
      ) : (
        help && <p className="text-xs text-zinc-500">{help}</p>
      )}
    </div>
  )
}

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  allLabel: string
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] font-medium uppercase tracking-wider text-zinc-500">
      {label}
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 min-w-40 text-xs normal-case tracking-normal"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
    </label>
  )
}
