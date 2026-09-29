import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Field, FieldValue, SettingsView } from '../api/types'
import {
  fromDraft,
  isDraftDirty,
  isFieldVisible,
  toDraft,
  validateDraft,
  type DraftValue,
  type DraftValues,
} from './schema'

export interface SettingsForm {
  fields: Field[]
  /** Effective (edited or saved) draft for every field — also drives `show_if`. */
  values: DraftValues
  setValue: (key: string, value: DraftValue) => void
  dirtyKeys: Set<string>
  errors: Record<string, string>
  /** Partial update payload: only dirty keys. */
  changes: () => Record<string, FieldValue>
  reset: () => void
}

/**
 * Only edited keys are held locally, so background refetches of the settings
 * query never clobber unsaved edits and untouched fields stay in sync.
 */
export function useSettingsForm(view: SettingsView | undefined): SettingsForm {
  const [edits, setEdits] = useState<DraftValues>({})
  const fields = useMemo(() => view?.sections.flatMap((s) => s.fields) ?? [], [view])

  const values = useMemo(() => {
    const out: DraftValues = {}
    for (const f of fields) out[f.key] = edits[f.key] ?? toDraft(f, view?.values[f.key])
    return out
  }, [fields, edits, view])

  const dirtyFields = useMemo(
    () => fields.filter((f) => f.key in edits && isDraftDirty(f, edits[f.key], view?.values[f.key])),
    [fields, edits, view],
  )

  const errors = useMemo(() => {
    const out: Record<string, string> = {}
    for (const f of dirtyFields) {
      const problem = isFieldVisible(f, values) ? validateDraft(f, values[f.key]) : undefined
      if (problem) out[f.key] = problem
    }
    return out
  }, [dirtyFields, values])

  const changes = useCallback(() => {
    const out: Record<string, FieldValue> = {}
    for (const f of dirtyFields) {
      if (validateDraft(f, values[f.key])) continue
      out[f.key] = fromDraft(f, values[f.key])
    }
    return out
  }, [dirtyFields, values])

  const setValue = useCallback((key: string, value: DraftValue) => setEdits((e) => ({ ...e, [key]: value })), [])
  const reset = useCallback(() => setEdits({}), [])

  const hasChanges = dirtyFields.length > 0
  useEffect(() => {
    if (!hasChanges) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [hasChanges])

  return {
    fields,
    values,
    setValue,
    dirtyKeys: new Set(dirtyFields.map((f) => f.key)),
    errors,
    changes,
    reset,
  }
}
