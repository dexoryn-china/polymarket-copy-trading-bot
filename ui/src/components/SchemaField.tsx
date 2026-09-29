import { useState, type ReactNode } from 'react'
import { Check, Eye, EyeOff } from 'lucide-react'
import type { Field } from '../api/types'
import { cn } from '../lib/cn'
import { SECRET_MASK, type DraftValue } from '../lib/schema'
import { Button } from './ui/Button'
import { FormField, Input, Select } from './ui/Form'
import { Switch } from './ui/Switch'

export interface SchemaFieldProps {
  id: string
  field: Field
  value: DraftValue
  onChange: (value: DraftValue) => void
  error?: string
}

export function SchemaField(props: SchemaFieldProps) {
  const { id, field, value, onChange, error } = props
  const label = field.label

  switch (field.type) {
    case 'boolean':
      return (
        <div className="space-y-1">
          <div className="flex">
            <Switch id={id} checked={Boolean(value)} onChange={onChange} label={field.label} showLabel />
          </div>
          <Help>{field.help}</Help>
        </div>
      )

    case 'select':
      return (
        <FormField label={label} htmlFor={id} help={field.help} error={error}>
          <Select id={id} value={String(value)} onChange={(e) => onChange(e.target.value)}>
            {field.options?.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
      )

    case 'multiselect':
      return <MultiSelect {...props} label={label} />

    case 'secret':
      return <SecretInput {...props} label={label} />

    case 'number':
      return (
        <FormField label={label} htmlFor={id} help={field.help} error={error}>
          <Input
            id={id}
            type="number"
            inputMode="decimal"
            value={String(value)}
            unit={field.unit}
            min={field.min}
            max={field.max}
            step={field.step ?? 'any'}
            placeholder={field.nullable ? 'No limit' : undefined}
            invalid={Boolean(error)}
            aria-describedby={error ? `${id}-error` : undefined}
            onChange={(e) => onChange(e.target.value)}
          />
        </FormField>
      )

    default:
      return (
        <FormField
          label={label}
          htmlFor={id}
          help={field.help ?? (field.type === 'list' ? 'Comma-separated' : undefined)}
          error={error}
        >
          <Input
            id={id}
            value={String(value)}
            unit={field.unit}
            invalid={Boolean(error)}
            aria-describedby={error ? `${id}-error` : undefined}
            onChange={(e) => onChange(e.target.value)}
            className={field.type === 'list' ? 'font-mono' : undefined}
            spellCheck={false}
            autoComplete="off"
          />
        </FormField>
      )
  }
}

function Help({ children }: { children?: ReactNode }) {
  return children ? <p className="text-xs text-zinc-500">{children}</p> : null
}

function MultiSelect({ id, field, value, onChange, label }: SchemaFieldProps & { label: ReactNode }) {
  const selected = Array.isArray(value) ? value : []
  const options = field.options ?? []

  const toggle = (v: string) => {
    const next = selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]
    onChange(options.map((o) => o.value).filter((o) => next.includes(o)))
  }

  return (
    <div role="group" aria-labelledby={`${id}-label`} className="space-y-1.5">
      <p id={`${id}-label`} className="text-xs font-medium text-zinc-300">
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = selected.includes(o.value)
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(o.value)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors',
                'focus-visible:outline-2 focus-visible:outline-indigo-500',
                on
                  ? 'border-indigo-500/50 bg-indigo-500/15 text-indigo-200'
                  : 'border-zinc-700 bg-zinc-950/60 text-zinc-400 hover:text-zinc-200',
              )}
            >
              {on && <Check className="size-3.5" aria-hidden />}
              {o.label}
            </button>
          )
        })}
      </div>
      <Help>{field.help}</Help>
    </div>
  )
}

function SecretInput({ id, field, value, onChange, error, label }: SchemaFieldProps & { label: ReactNode }) {
  const [reveal, setReveal] = useState(false)
  const text = String(value)
  const saved = text === SECRET_MASK

  return (
    <FormField label={label} htmlFor={id} help={field.help} error={error}>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Input
            id={id}
            type={reveal ? 'text' : 'password'}
            value={saved ? '' : text}
            placeholder={saved ? 'Saved — type to replace' : 'Not set'}
            onChange={(e) => onChange(e.target.value)}
            invalid={Boolean(error)}
            autoComplete="new-password"
            spellCheck={false}
            className="pr-10 font-mono"
          />
          {!saved && text && (
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              aria-label={reveal ? `Hide ${field.label}` : `Show ${field.label}`}
              className="absolute inset-y-0 right-2 my-auto h-fit rounded p-1 text-zinc-500 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
            >
              {reveal ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </button>
          )}
        </div>
        {saved && (
          <Button variant="ghost" onClick={() => onChange('')}>
            Clear
          </Button>
        )}
      </div>
    </FormField>
  )
}
