import type { Field, FieldGroup, FieldValue } from '../api/types'
import { formatInt } from './format'

/** What the server returns for a secret that is set; echoing it back means "keep". */
export const SECRET_MASK = '••••••••'

/** Raw input state: numbers and lists stay strings while being typed. */
export type DraftValue = string | boolean | string[]
export type DraftValues = Record<string, DraftValue>

export function isFieldVisible(field: Field, values: Record<string, unknown>): boolean {
  if (!field.show_if) return true
  return String(values[field.show_if.key] ?? '') === field.show_if.equals
}

export function visibleFields(fields: Field[], values: Record<string, unknown>, group?: FieldGroup): Field[] {
  return fields.filter((f) => (!group || f.group === group) && isFieldVisible(f, values))
}

/** The field a user most likely wants to tweak inline (e.g. "Order size" for the current mode). */
export function primaryNumberField(fields: Field[], values: Record<string, unknown>): Field | undefined {
  return fields.find((f) => f.group === 'basic' && f.type === 'number' && isFieldVisible(f, values))
}

function splitList(text: string): string[] {
  return [...new Set(text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean))]
}

export function toDraft(field: Field, value: FieldValue | undefined): DraftValue {
  const v = value === undefined ? field.default : value
  switch (field.type) {
    case 'boolean':
      return Boolean(v)
    case 'multiselect':
      return Array.isArray(v) ? v.map(String) : []
    case 'list':
      return Array.isArray(v) ? v.join(', ') : String(v ?? '')
    default:
      return v == null ? '' : String(v)
  }
}

export function fromDraft(field: Field, draft: DraftValue): FieldValue {
  switch (field.type) {
    case 'boolean':
      return Boolean(draft)
    case 'multiselect':
      return Array.isArray(draft) ? draft : []
    case 'list':
      return splitList(String(draft))
    case 'number': {
      const raw = String(draft).trim()
      return raw === '' && field.nullable ? null : Number(raw)
    }
    default:
      return String(draft)
  }
}

export function validateDraft(field: Field, draft: DraftValue): string | undefined {
  if (field.type !== 'number') return undefined
  const raw = String(draft).trim()
  if (raw === '') return field.nullable ? undefined : 'Enter a number'
  const n = Number(raw)
  if (!Number.isFinite(n)) return 'Enter a number'
  if (field.min != null && n < field.min) return `Must be at least ${field.min}`
  if (field.max != null && n > field.max) return `Must be at most ${field.max}`
  return undefined
}

export function isDraftDirty(field: Field, draft: DraftValue, saved: FieldValue | undefined): boolean {
  const a = fromDraft(field, draft)
  const b = saved === undefined ? field.default : saved
  if (Array.isArray(a) || Array.isArray(b)) {
    const norm = (v: FieldValue) => {
      const xs = Array.isArray(v) ? v : []
      return JSON.stringify(field.type === 'multiselect' ? [...xs].sort() : xs)
    }
    return norm(a) !== norm(b)
  }
  return a !== b
}

export function formatFieldValue(field: Field, value: FieldValue | undefined): string {
  if (value === null) return field.nullable ? 'No limit' : '—'
  if (value === undefined || value === '') return '—'
  if (field.type === 'secret') return value ? 'Set' : 'Not set'
  if (field.type === 'boolean') return value ? 'On' : 'Off'
  const optionLabel = (v: string) => field.options?.find((o) => o.value === v)?.label ?? v
  if (Array.isArray(value)) return value.length ? value.map(optionLabel).join(', ') : '—'
  if (field.type === 'select') return optionLabel(String(value))
  const n = typeof value === 'number' ? value : Number(value)
  const text = Number.isFinite(n) ? formatInt(n) : String(value)
  if (!field.unit) return text
  if (field.unit === '$' || field.unit.toUpperCase() === 'USD') return `$${text}`
  return field.unit === '%' ? `${text}%` : `${text} ${field.unit}`
}

export function summarizeSizing(
  fields: Field[] | undefined,
  sizing: Record<string, FieldValue>,
  max = 3,
): { label: string; value: string }[] {
  if (!fields) {
    return Object.entries(sizing)
      .slice(0, max)
      .map(([k, v]) => ({ label: k, value: String(v) }))
  }
  return fields
    .filter((f) => isFieldVisible(f, sizing) && f.type !== 'boolean')
    .slice(0, max)
    .map((f) => ({ label: f.label, value: formatFieldValue(f, sizing[f.key]) }))
}
