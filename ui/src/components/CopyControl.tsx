import { useId, useState } from 'react'
import { Pause, Play, Square } from 'lucide-react'
import { usePause } from '../api/queries'
import type { CopyState, Venue, VenueId } from '../api/types'
import { useCopy } from '../api/useCopy'
import { cn } from '../lib/cn'
import { formatAbsolute, formatDuration } from '../lib/format'
import { useNow } from '../lib/useNow'
import { PauseControl } from './PauseControl'
import { Button } from './ui/Button'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { Skeleton } from './ui/Skeleton'
import { useToast } from './ui/toast-context'

const SWITCH_HINT = 'Stop copying to switch'

type Confirm = { kind: 'stop' } | { kind: 'switch'; venue: Venue }

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/**
 * Venue picker + Start/Stop (+ Pause while running). `stack` fits the 240px
 * sidebar; `row` wraps horizontally for narrow screens.
 */
export function CopyControl({ layout = 'stack', className }: { layout?: 'stack' | 'row'; className?: string }) {
  const { status, copy, state, venues, activeVenue, venueStatus, select, start, stop, pending } = useCopy()
  const pause = usePause()
  const toast = useToast()
  const hintId = useId()
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const stack = layout === 'stack'

  if (!status || !copy || !state || venues.length === 0) {
    return <Skeleton className={cn(stack ? 'h-32' : 'h-16', 'w-full rounded-lg', className)} />
  }

  const stopped = state === 'stopped'
  const running = state === 'running'
  const openPositions = venueStatus?.positions ?? 0
  const venueLabel = activeVenue?.label ?? copy.venue_label

  const requestStop = () => (openPositions > 0 ? setConfirm({ kind: 'stop' }) : stop())
  const requestSwitch = (id: VenueId) => {
    const next = venues.find((v) => v.id === id)
    if (!next || id === copy.venue) return
    if (openPositions > 0) setConfirm({ kind: 'switch', venue: next })
    else select(id)
  }
  const pauseInstead = () =>
    pause.mutate(true, {
      onSuccess: () => {
        setConfirm(null)
        toast({ title: 'Copying paused', description: 'New entries are skipped; exits are still mirrored.', variant: 'warning' })
      },
      onError: (err) => toast({ title: 'Could not pause', description: err.message, variant: 'error' }),
    })

  const buttonSize = stack ? 'md' : 'sm'
  const fill = stack ? 'w-full justify-center' : undefined

  const mainButton = stopped || state === 'starting' ? (
    <Button
      variant="primary"
      size={buttonSize}
      className={fill}
      icon={<Play className="size-4" aria-hidden />}
      loading={state === 'starting'}
      disabled={pending}
      onClick={start}
    >
      {state === 'starting' ? 'Starting…' : 'Start copying'}
    </Button>
  ) : (
    <Button
      variant="secondary"
      size={buttonSize}
      className={fill}
      icon={<Square className="size-3.5 fill-current text-rose-400" aria-hidden />}
      loading={state === 'stopping'}
      disabled={pending}
      onClick={requestStop}
    >
      {state === 'stopping' ? 'Stopping…' : 'Stop copying'}
    </Button>
  )

  const venueSwitch = (
    <VenueSwitch
      venues={venues}
      value={copy.venue}
      disabled={!stopped || pending}
      describedBy={stopped ? undefined : hintId}
      onChange={requestSwitch}
    />
  )
  const hint = !stopped && (
    <p id={hintId} className="text-[11px] text-zinc-500">
      {SWITCH_HINT}
    </p>
  )
  const stateLine = <CopyStateLine state={state} paused={status.paused} startedAt={copy.started_at_ms} />

  return (
    <div className={className}>
      {stack ? (
        <div className="space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Copying</span>
            {stateLine}
          </div>
          {venueSwitch}
          {hint}
          {mainButton}
          {running && <PauseControl status={status} className={fill} />}
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            {stateLine}
            {hint}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {venueSwitch}
            {mainButton}
            {running && <PauseControl status={status} size="sm" />}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirm?.kind === 'stop'}
        tone="danger"
        title={`Stop copying ${venueLabel}?`}
        message={
          <>
            <p>
              <strong className="text-zinc-100">{plural(openPositions, 'open position')}</strong> — while stopped, your
              targets' exits won't be mirrored.
            </p>
            <p className="mt-2 text-zinc-400">
              {status.paused
                ? 'Copying is already paused, which keeps mirroring exits without opening new positions.'
                : 'Pause instead to keep mirroring exits without opening new positions.'}
            </p>
          </>
        }
        confirmLabel="Stop copying"
        extraAction={
          !status.paused && (
            <Button
              variant="warning"
              icon={<Pause className="size-4" aria-hidden />}
              loading={pause.isPending}
              onClick={pauseInstead}
            >
              Pause instead
            </Button>
          )
        }
        onConfirm={() => {
          setConfirm(null)
          stop()
        }}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm?.kind === 'switch'}
        tone="warning"
        title={confirm?.kind === 'switch' ? `Switch to ${confirm.venue.label}?` : 'Switch venue?'}
        message={
          <p>
            <strong className="text-zinc-100">
              {plural(openPositions, `open ${venueLabel} position`)}
            </strong>{' '}
            won't be managed while {confirm?.kind === 'switch' ? confirm.venue.label : 'another venue'} is selected —
            their exits won't be mirrored until you switch back.
          </p>
        }
        confirmLabel="Switch venue"
        onConfirm={() => {
          if (confirm?.kind === 'switch') select(confirm.venue.id)
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

interface VenueSwitchProps {
  venues: Venue[]
  value: VenueId
  disabled: boolean
  describedBy?: string
  onChange: (id: VenueId) => void
}

function VenueSwitch({ venues, value, disabled, describedBy, onChange }: VenueSwitchProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Venue to copy"
      aria-describedby={describedBy}
      title={disabled ? SWITCH_HINT : undefined}
      className="flex rounded-lg border border-zinc-800 bg-zinc-900 p-1"
    >
      {venues.map((v) => {
        const active = v.id === value
        return (
          <button
            key={v.id}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(v.id)}
            className={cn(
              'flex-auto whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
              'focus-visible:outline-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed',
              active
                ? 'bg-zinc-800 text-zinc-50 shadow-sm ring-1 ring-inset ring-indigo-500/30'
                : 'text-zinc-400 enabled:hover:text-zinc-200 disabled:opacity-50',
            )}
          >
            {v.label}
          </button>
        )
      })}
    </div>
  )
}

const STATE_STYLES: Record<CopyState, { text: string; dot: string }> = {
  stopped: { text: 'Stopped', dot: 'bg-zinc-500' },
  starting: { text: 'Starting…', dot: 'bg-amber-400 animate-pulse' },
  running: { text: 'Copying', dot: 'bg-emerald-400 animate-pulse' },
  stopping: { text: 'Stopping…', dot: 'bg-amber-400 animate-pulse' },
}

function CopyStateLine({ state, paused, startedAt }: { state: CopyState; paused: boolean; startedAt: number | null }) {
  const now = useNow()
  const isPaused = state === 'running' && paused
  const s = isPaused ? { text: 'Paused', dot: 'bg-amber-400' } : STATE_STYLES[state]
  const since = state === 'running' && startedAt != null ? startedAt : null
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1.5 text-xs text-zinc-300"
      title={since != null ? `Copying since ${formatAbsolute(since)}` : undefined}
    >
      <span className={cn('size-2 rounded-full', s.dot)} aria-hidden />
      {s.text}
      {since != null && <span className="tabular-nums text-zinc-500">· {formatDuration((now - since) / 1000)}</span>}
    </span>
  )
}
