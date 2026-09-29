import { useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Users } from 'lucide-react'
import { useTargets, useUpdateTarget } from '../../api/queries'
import type { Field, Target, Venue } from '../../api/types'
import { useCopy } from '../../api/useCopy'
import { cn } from '../../lib/cn'
import { formatFieldValue, fromDraft, isDraftDirty, primaryNumberField, toDraft, validateDraft } from '../../lib/schema'
import { CopyAddress } from '../CopyAddress'
import { TargetSwitch } from '../TargetSwitch'
import { Button } from '../ui/Button'
import { Card, CardHeader } from '../ui/Card'
import { EmptyState, ErrorState } from '../ui/EmptyState'
import { Input } from '../ui/Form'
import { Skeleton } from '../ui/Skeleton'
import { useToast } from '../ui/toast-context'

interface TargetWalletsCardProps {
  onAdd: () => void
  onEdit: (target: Target) => void
}

export function TargetWalletsCard({ onAdd, onEdit }: TargetWalletsCardProps) {
  const targets = useTargets()
  const { activeVenue } = useCopy()
  const list = (targets.data ?? []).filter((t) => t.venue === activeVenue?.id)

  return (
    <Card>
      <CardHeader
        icon={<Users className="size-4" aria-hidden />}
        title="Target wallets"
        subtitle={`${activeVenue ? `${activeVenue.label} wallets` : 'Wallets'} whose trades are copied`}
        actions={
          <>
            <Link
              to="/targets"
              className="hidden rounded-md px-2 py-1 text-xs font-medium text-zinc-400 hover:text-zinc-100 focus-visible:outline-2 focus-visible:outline-indigo-500 sm:inline"
            >
              Manage
            </Link>
            <Button
              size="sm"
              variant="primary"
              icon={<Plus className="size-4" aria-hidden />}
              onClick={onAdd}
              disabled={!activeVenue}
            >
              Add target
            </Button>
          </>
        }
      />
      {targets.isPending || !activeVenue ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : targets.isError ? (
        <ErrorState error={targets.error} onRetry={() => targets.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          className="py-8"
          icon={<Users className="size-5" aria-hidden />}
          title={`No ${activeVenue.label} target wallets yet`}
          description="Add a wallet to start copying its trades."
        />
      ) : (
        <ul className="divide-y divide-zinc-800/70">
          {list.map((t) => (
            <TargetRow key={t.id} target={t} venue={activeVenue} onEdit={() => onEdit(t)} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function TargetRow({ target, venue, onEdit }: { target: Target; venue: Venue; onEdit: () => void }) {
  const sizeField = primaryNumberField(venue.sizing_fields, target.sizing)
  return (
    <li
      className={cn(
        'flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-opacity',
        !target.enabled && 'opacity-70',
      )}
    >
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-zinc-100">{target.name}</span>
        <CopyAddress address={target.wallet} />
      </div>
      <div className="flex items-end gap-3">
        {sizeField && <SizeInput target={target} field={sizeField} />}
        <div className="flex h-9 items-center gap-1">
          <TargetSwitch target={target} size="sm" />
          <Button size="icon" variant="ghost" onClick={onEdit} aria-label={`Edit ${target.name}`} title="Edit">
            <Pencil className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
    </li>
  )
}

/** Saves on blur / Enter via a partial `sizing` update; Escape reverts. */
function SizeInput({ target, field }: { target: Target; field: Field }) {
  const update = useUpdateTarget()
  const toast = useToast()
  const savedValue = target.sizing[field.key]
  const saved = String(toDraft(field, savedValue))
  const [draft, setDraft] = useState(saved)
  const [syncedFrom, setSyncedFrom] = useState(`${field.key}:${saved}`)

  if (syncedFrom !== `${field.key}:${saved}`) {
    setSyncedFrom(`${field.key}:${saved}`)
    setDraft(saved)
  }

  const id = `target-size-${target.id}`
  const error = validateDraft(field, draft)

  const commit = () => {
    if (!isDraftDirty(field, draft, savedValue)) return
    if (error) {
      setDraft(saved)
      toast({ title: `${field.label} not saved`, description: error, variant: 'error' })
      return
    }
    update.mutate(
      { id: target.id, input: { sizing: { [field.key]: fromDraft(field, draft) } } },
      {
        onSuccess: (t) =>
          toast({
            title: `${field.label} updated`,
            description: `${t.name}: ${formatFieldValue(field, t.sizing[field.key])}`,
            variant: 'success',
          }),
        onError: (err) => {
          setDraft(saved)
          toast({ title: `Couldn't update ${target.name}`, description: err.message, variant: 'error' })
        },
      },
    )
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') e.currentTarget.blur()
    else if (e.key === 'Escape') setDraft(saved)
  }

  return (
    <div className="w-32 sm:w-36">
      <label htmlFor={id} className="mb-1 block truncate text-[10px] font-medium uppercase tracking-wider text-zinc-500">
        {field.label}
      </label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        value={draft}
        unit={field.unit}
        min={field.min}
        max={field.max}
        step={field.step ?? 'any'}
        invalid={Boolean(error)}
        title={error}
        disabled={update.isPending}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        className="tabular-nums"
      />
    </div>
  )
}
