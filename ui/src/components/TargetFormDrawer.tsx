import { useId, useMemo, useState, type FormEvent } from 'react'
import { AlertCircle } from 'lucide-react'
import { useSaveTarget } from '../api/queries'
import type { Field, FieldValue, Meta, Target, TargetInput, Venue, VenueId } from '../api/types'
import { fromDraft, isFieldVisible, toDraft, validateDraft, visibleFields, type DraftValues } from '../lib/schema'
import { SchemaField } from './SchemaField'
import { Button } from './ui/Button'
import { Disclosure } from './ui/Disclosure'
import { FormField, Input } from './ui/Form'
import { Drawer } from './ui/Modal'
import { Switch } from './ui/Switch'
import { useToast } from './ui/toast-context'

const WALLET_RE = /^0x[0-9a-fA-F]{40}$/

function initialSizing(venue: Venue | undefined, sizing: Record<string, FieldValue> = {}): DraftValues {
  const values: DraftValues = {}
  for (const f of venue?.sizing_fields ?? []) values[f.key] = toDraft(f, sizing[f.key])
  return values
}

interface TargetFormDrawerProps {
  open: boolean
  onClose: () => void
  meta: Meta
  /** Venue for new targets; an edited target keeps its own. */
  venueId: VenueId
  target?: Target | null
}

export function TargetFormDrawer(props: TargetFormDrawerProps) {
  if (!props.open) return null
  return <TargetForm key={props.target?.id ?? `new-${props.venueId}`} {...props} />
}

function TargetForm({ onClose, meta, venueId: newVenueId, target }: TargetFormDrawerProps) {
  const editing = Boolean(target)
  const formId = useId()
  const save = useSaveTarget()
  const toast = useToast()

  const venueId = target?.venue ?? newVenueId
  const venue = meta.venues.find((v) => v.id === venueId)

  const [name, setName] = useState(target?.name ?? '')
  const [wallet, setWallet] = useState(target?.wallet ?? '')
  const [enabled, setEnabled] = useState(target?.enabled ?? true)
  const [copyCloses, setCopyCloses] = useState(target?.copy_closes ?? true)
  const [sizing, setSizing] = useState<DraftValues>(() => initialSizing(venue, target?.sizing))
  const [touched, setTouched] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const fields = venue?.sizing_fields ?? []
  const basicFields = visibleFields(fields, sizing, 'basic')
  const advancedFields = visibleFields(fields, sizing, 'advanced')

  const errors = useMemo(() => {
    const e: Record<string, string> = {}
    if (!name.trim()) e.name = 'Name is required'
    if (!WALLET_RE.test(wallet.trim())) e.wallet = 'Must be 0x followed by 40 hex characters'
    for (const f of fields) {
      if (!isFieldVisible(f, sizing)) continue
      const problem = validateDraft(f, sizing[f.key] ?? '')
      if (problem) e[f.key] = problem
    }
    return e
  }, [name, wallet, fields, sizing])

  const errorFor = (key: string) => (touched ? errors[key] : undefined)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    setServerError(null)
    if (advancedFields.some((f) => errors[f.key])) setShowAdvanced(true)
    if (Object.keys(errors).length > 0) return

    const out: Record<string, FieldValue> = {}
    for (const f of fields) {
      const draft = sizing[f.key] ?? toDraft(f, undefined)
      if (!validateDraft(f, draft)) out[f.key] = fromDraft(f, draft)
    }
    const input: TargetInput = {
      name: name.trim(),
      venue: venueId,
      wallet: wallet.trim(),
      enabled,
      copy_closes: copyCloses,
      sizing: out,
    }
    save.mutate(
      { id: target?.id, input },
      {
        onSuccess: (saved) => {
          toast({ title: editing ? 'Target updated' : 'Target added', description: saved.name, variant: 'success' })
          onClose()
        },
        onError: (err) => setServerError(err.message),
      },
    )
  }

  const fieldId = (key: string) => `${formId}-${key}`

  const renderField = (field: Field) => (
    <SchemaField
      key={field.key}
      id={fieldId(field.key)}
      field={field}
      value={sizing[field.key] ?? toDraft(field, undefined)}
      error={errorFor(field.key)}
      onChange={(v) => setSizing((s) => ({ ...s, [field.key]: v }))}
    />
  )

  return (
    <Drawer
      open
      onClose={onClose}
      title={editing ? `Edit ${target?.name}` : 'Add target'}
      description={
        editing
          ? `Update how this ${venue?.label ?? ''} wallet is copied.`
          : `Copy ${venue?.label ?? ''} trades from a wallet you want to follow.`
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={save.isPending}>
            {editing ? 'Save changes' : 'Add target'}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="space-y-5">
        {serverError && (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {serverError}
          </div>
        )}

        <FormField label="Name" htmlFor={fieldId('name')} error={errorFor('name')}>
          <Input
            id={fieldId('name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Whale #1"
            invalid={Boolean(errorFor('name'))}
            autoComplete="off"
          />
        </FormField>

        <FormField label={venue?.wallet_label ?? 'Wallet address'} htmlFor={fieldId('wallet')} error={errorFor('wallet')}>
          <Input
            id={fieldId('wallet')}
            value={wallet}
            onChange={(e) => setWallet(e.target.value)}
            placeholder={venue?.wallet_placeholder ?? '0x…'}
            invalid={Boolean(errorFor('wallet'))}
            aria-describedby={errorFor('wallet') ? `${fieldId('wallet')}-error` : undefined}
            className="font-mono"
            spellCheck={false}
            autoComplete="off"
          />
        </FormField>

        <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <Switch checked={enabled} onChange={setEnabled} label="Enabled" showLabel />
          <Switch
            checked={copyCloses}
            onChange={setCopyCloses}
            label={venue?.close_label ?? 'Copy closes'}
            showLabel
          />
        </div>

        {basicFields.length > 0 && (
          <fieldset className="space-y-4">
            <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Sizing</legend>
            {basicFields.map(renderField)}
          </fieldset>
        )}

        {advancedFields.length > 0 && (
          <Disclosure title="Advanced" open={showAdvanced} onToggle={setShowAdvanced}>
            {advancedFields.map(renderField)}
          </Disclosure>
        )}
      </form>
    </Drawer>
  )
}
