import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Pencil, Plus, Trash2, Users } from 'lucide-react'
import { ApiError } from '../api/client'
import { useDeleteTarget, useMeta, useTargets } from '../api/queries'
import type { Target, Venue } from '../api/types'
import { useCopy } from '../api/useCopy'
import { CopyAddress } from '../components/CopyAddress'
import { PageHeader } from '../components/PageHeader'
import { TargetFormDrawer } from '../components/TargetFormDrawer'
import { TargetSwitch } from '../components/TargetSwitch'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { EmptyState, ErrorState } from '../components/ui/EmptyState'
import { Skeleton } from '../components/ui/Skeleton'
import { useToast } from '../components/ui/toast-context'
import { cn } from '../lib/cn'
import { copyRate, formatInt, formatPct, formatRelative, formatUsd } from '../lib/format'
import { summarizeSizing } from '../lib/schema'
import { useNow } from '../lib/useNow'

export function TargetsPage() {
  const meta = useMeta()
  const targets = useTargets()
  const { activeVenue } = useCopy()
  const del = useDeleteTarget()
  const toast = useToast()
  const now = useNow(5000)
  const [params, setParams] = useSearchParams()

  const [editing, setEditing] = useState<Target | null>(null)
  const [deleting, setDeleting] = useState<Target | null>(null)
  const creating = params.get('new') === '1'
  const formOpen = creating || editing !== null

  const openCreate = () => setParams({ new: '1' })
  const closeForm = () => {
    setEditing(null)
    if (creating) setParams({}, { replace: true })
  }

  const confirmDelete = () => {
    if (!deleting) return
    const target = deleting
    del.mutate(target.id, {
      onSuccess: () => {
        toast({ title: 'Target deleted', description: target.name, variant: 'success' })
        setDeleting(null)
      },
      onError: (err) => {
        setDeleting(null)
        toast({
          title: `Couldn't delete ${target.name}`,
          description:
            err instanceof ApiError && err.status === 409
              ? `${err.message} Disable the target instead to stop copying new trades.`
              : err.message,
          variant: 'error',
        })
      },
    })
  }

  const list = (targets.data ?? []).filter((t) => t.venue === activeVenue?.id)

  return (
    <>
      <PageHeader
        title="Targets"
        description={`${activeVenue ? `${activeVenue.label} wallets` : 'Wallets'} whose trades are mirrored by the bot.`}
        actions={
          <Button
            variant="primary"
            icon={<Plus className="size-4" aria-hidden />}
            onClick={openCreate}
            disabled={!meta.data || !activeVenue}
          >
            Add target
          </Button>
        }
      />

      {targets.isPending || !activeVenue ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-56 rounded-xl" />
          ))}
        </div>
      ) : targets.isError ? (
        <Card>
          <ErrorState error={targets.error} onRetry={() => targets.refetch()} />
        </Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Users className="size-5" aria-hidden />}
            title={`No ${activeVenue.label} targets yet — add your first wallet to copy`}
            description="Pick a trader, paste their wallet address, and choose how large your copies should be."
            action={
              <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={openCreate}>
                Add target
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((t) => (
            <TargetCard
              key={t.id}
              target={t}
              venue={activeVenue}
              now={now}
              onEdit={() => setEditing(t)}
              onDelete={() => setDeleting(t)}
            />
          ))}
        </div>
      )}

      {meta.data && activeVenue && (
        <TargetFormDrawer
          open={formOpen}
          onClose={closeForm}
          meta={meta.data}
          venueId={activeVenue.id}
          target={editing}
        />
      )}

      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? 'target'}?`}
        message="The bot will stop tracking this wallet. Targets with open positions can't be deleted — disable them instead."
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </>
  )
}

interface TargetCardProps {
  target: Target
  venue: Venue | undefined
  now: number
  onEdit: () => void
  onDelete: () => void
}

function TargetCard({ target, venue, now, onEdit, onDelete }: TargetCardProps) {
  const { stats } = target
  const sizing = summarizeSizing(venue?.sizing_fields, target.sizing)
  const profileUrl = target.venue === 'predictions' ? `https://polymarket.com/profile/${target.wallet}` : null
  const rate = copyRate(stats.copied, stats.detected)

  return (
    <Card className={cn('flex flex-col transition-opacity', !target.enabled && 'opacity-70')}>
      <div className="flex items-start justify-between gap-3 p-4 pb-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-zinc-100">{target.name}</h3>
          <CopyAddress address={target.wallet} href={profileUrl} />
        </div>
        <TargetSwitch target={target} />
      </div>

      <div className="flex flex-wrap gap-1.5 px-4">
        <Badge tone={target.enabled ? 'success' : 'neutral'}>{target.enabled ? 'Copying' : 'Paused'}</Badge>
        {target.copy_closes ? (
          <Badge tone="accent">{venue?.close_label ?? 'Copies closes'}</Badge>
        ) : (
          <Badge>Opens only</Badge>
        )}
      </div>

      {sizing.length > 0 && (
        <dl className="mx-4 mt-3 grid grid-cols-1 gap-1 rounded-lg bg-zinc-950/50 px-3 py-2 text-xs">
          {sizing.map((s) => (
            <div key={s.label} className="flex justify-between gap-3">
              <dt className="truncate text-zinc-500">{s.label}</dt>
              <dd className="shrink-0 tabular-nums text-zinc-300">{s.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <dl className="grid grid-cols-4 gap-2 px-4 py-3 text-center">
        {(
          [
            ['Detected', stats.detected, 'text-zinc-200'],
            ['Copied', stats.copied, 'text-emerald-400'],
            ['Failed', stats.failed, stats.failed ? 'text-rose-400' : 'text-zinc-200'],
            ['Skipped', stats.skipped, 'text-zinc-400'],
          ] as const
        ).map(([label, value, color]) => (
          <div key={label}>
            <dt className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</dt>
            <dd className={cn('text-sm font-semibold tabular-nums', color)}>{formatInt(value)}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-zinc-800 px-4 py-2.5">
        <p className="text-xs text-zinc-500">
          <span className="tabular-nums text-zinc-300">{formatUsd(stats.open_usd)}</span> in{' '}
          {formatInt(stats.positions)} pos · {formatPct(rate, 0)} ·{' '}
          <span title="Last activity">{formatRelative(stats.last_activity_ms, now)}</span>
        </p>
        <div className="flex shrink-0 gap-1">
          <Button size="icon" variant="ghost" onClick={onEdit} aria-label={`Edit ${target.name}`} title="Edit">
            <Pencil className="size-4" aria-hidden />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={onDelete}
            aria-label={`Delete ${target.name}`}
            title="Delete"
            className="hover:text-rose-400"
          >
            <Trash2 className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
    </Card>
  )
}
