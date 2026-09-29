import { lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity as ActivityIcon,
  ArrowRight,
  CirclePause,
  Gauge,
  Play,
  Plus,
  Radio,
  Target as TargetIcon,
  Timer,
  Wallet,
} from 'lucide-react'
import { useActivity, useStatus, useTargets } from '../api/queries'
import type { Counts, Latency, Status, VenueStatus } from '../api/types'
import { useCopy } from '../api/useCopy'
import { ActivityItem } from '../components/ActivityItem'
import { PageHeader } from '../components/PageHeader'
import { FeedChip, ModeBadge } from '../components/StatusBits'
import { TargetSwitch } from '../components/TargetSwitch'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState, ErrorState } from '../components/ui/EmptyState'
import { Progress } from '../components/ui/Progress'
import { Skeleton, SkeletonRows } from '../components/ui/Skeleton'
import {
  copyRate,
  formatDuration,
  formatInt,
  formatMs,
  formatPct,
  formatRelative,
  formatUsd,
} from '../lib/format'
import { useNow } from '../lib/useNow'

const LatencyChart = lazy(() => import('../components/LatencyChart'))

export function OverviewPage() {
  const status = useStatus()
  const now = useNow()
  const s = status.data
  const uptime = s ? s.uptime_s + Math.max(0, (now - status.dataUpdatedAt) / 1000) : 0
  const venue = s?.venues.find((v) => v.active)

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            Overview <ModeBadge mode={s?.mode} />
          </span>
        }
        description={
          s ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span>
                Uptime <span className="tabular-nums text-zinc-200">{formatDuration(uptime)}</span>
              </span>
              {s.copy.running && s.feeds.length > 0 ? (
                s.feeds.map((f) => <FeedChip key={f.id} feed={f} now={now} />)
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400">
                  <Radio className="size-3.5" aria-hidden />
                  Not running
                </span>
              )}
            </span>
          ) : (
            <Skeleton className="h-5 w-64" />
          )
        }
      />

      <StoppedHero />

      {status.isError && !s ? (
        <Card>
          <ErrorState error={status.error} onRetry={() => status.refetch()} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {s ? venue && <VenueCard venue={venue} /> : <Skeleton className="h-40 rounded-xl" />}
          {s ? <CountsCard counts={s.counts} /> : <Skeleton className="h-40 rounded-xl" />}
          {s ? <LatencyCard latency={s.latency} /> : <Skeleton className="h-40 rounded-xl" />}
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <LiveFeed now={now} className="lg:col-span-3" />
        <TargetsSummary status={s} className="lg:col-span-2" />
      </div>
    </>
  )
}

function StoppedHero() {
  const { copy, state, activeVenue, start, pending } = useCopy()
  const targets = useTargets()
  if (!copy || (state !== 'stopped' && state !== 'starting')) return null

  const venueLabel = activeVenue?.label ?? copy.venue_label
  const enabled = (targets.data ?? []).filter((t) => t.venue === copy.venue && t.enabled).length
  const noTargets = targets.isSuccess && enabled === 0

  return (
    <Card className="mb-6 border-indigo-500/20 bg-indigo-500/5">
      <div className="flex flex-col items-start gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-zinc-800/80 text-zinc-300">
            <CirclePause className="size-5" aria-hidden />
          </div>
          <div>
            <h2 className="text-base font-semibold text-zinc-50">Copying is stopped</h2>
            <p className="mt-1 text-sm text-zinc-400">
              <span className="text-zinc-200">{venueLabel}</span> ·{' '}
              {targets.isPending ? '…' : `${formatInt(enabled)} enabled target${enabled === 1 ? '' : 's'}`}
            </p>
            {noTargets && <p className="mt-1 text-sm text-amber-300">Add a target wallet first.</p>}
          </div>
        </div>
        {noTargets ? (
          <Link
            to="/targets?new=1"
            className="inline-flex h-11 shrink-0 items-center gap-2 rounded-lg bg-indigo-600 px-5 text-sm font-medium text-white hover:bg-indigo-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
          >
            <Plus className="size-4" aria-hidden />
            Add target
          </Link>
        ) : (
          <Button
            variant="primary"
            className="h-11 px-6 text-base"
            icon={<Play className="size-4" aria-hidden />}
            loading={pending}
            onClick={start}
          >
            Start copying
          </Button>
        )}
      </div>
    </Card>
  )
}

function Stat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums text-zinc-100 ${className ?? ''}`}>{value}</p>
    </div>
  )
}

function VenueCard({ venue }: { venue: VenueStatus }) {
  const pct = venue.cap_usd ? (venue.open_usd / venue.cap_usd) * 100 : null
  return (
    <Card>
      <CardHeader icon={<Wallet className="size-4" aria-hidden />} title={venue.label} />
      <CardBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Balance" value={formatUsd(venue.balance_usd)} />
          <Stat label="Positions" value={formatInt(venue.positions)} />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-zinc-500">Open exposure</span>
            <span className="tabular-nums text-zinc-300">
              {formatUsd(venue.open_usd)}
              <span className="text-zinc-500"> / {venue.cap_usd != null ? formatUsd(venue.cap_usd) : 'no cap'}</span>
            </span>
          </div>
          <Progress value={pct ?? 0} label={`${venue.label} exposure vs cap`} />
        </div>
      </CardBody>
    </Card>
  )
}

function CountsCard({ counts }: { counts: Counts }) {
  const rate = copyRate(counts.copied, counts.detected)
  return (
    <Card>
      <CardHeader
        icon={<Gauge className="size-4" aria-hidden />}
        title="Copy stats"
        actions={
          <Badge tone={rate == null ? 'neutral' : rate >= 80 ? 'success' : rate >= 50 ? 'warning' : 'danger'}>
            {formatPct(rate)} copy rate
          </Badge>
        }
      />
      <CardBody className="grid grid-cols-2 gap-3">
        <Stat label="Detected" value={formatInt(counts.detected)} />
        <Stat label="Copied" value={formatInt(counts.copied)} className="text-emerald-400" />
        <Stat label="Failed" value={formatInt(counts.failed)} className={counts.failed ? 'text-rose-400' : undefined} />
        <Stat label="Skipped" value={formatInt(counts.skipped)} className="text-zinc-400" />
      </CardBody>
    </Card>
  )
}

function LatencyCard({ latency }: { latency: Latency }) {
  return (
    <Card>
      <CardHeader icon={<Timer className="size-4" aria-hidden />} title="Latency" subtitle="Detect → order placed" />
      <CardBody className="space-y-2">
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Last" value={formatMs(latency.last_ms)} />
          <Stat label="Avg" value={formatMs(latency.avg_ms)} />
          <Stat label="P95" value={formatMs(latency.p95_ms)} />
        </div>
        <Suspense fallback={<Skeleton className="h-20 w-full" />}>
          <LatencyChart data={latency.recent} />
        </Suspense>
      </CardBody>
    </Card>
  )
}

function LiveFeed({ now, className }: { now: number; className?: string }) {
  const activity = useActivity({})
  const items = activity.data?.pages[0]?.items.slice(0, 20) ?? []

  return (
    <Card className={className}>
      <CardHeader
        icon={<ActivityIcon className="size-4" aria-hidden />}
        title="Live activity"
        actions={
          <Link
            to="/activity"
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-indigo-300 hover:text-indigo-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            View all <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {activity.isPending ? (
        <SkeletonRows rows={6} />
      ) : activity.isError ? (
        <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ActivityIcon className="size-5" aria-hidden />}
          title="No activity yet"
          description="Trades from your targets will stream in here in real time."
        />
      ) : (
        <div className="divide-y divide-zinc-800/70">
          {items.map((item) => (
            <ActivityItem key={item.id} item={item} now={now} compact />
          ))}
        </div>
      )}
    </Card>
  )
}

function TargetsSummary({ status, className }: { status: Status | undefined; className?: string }) {
  const targets = useTargets()
  const now = useNow(5000)
  const copy = status?.copy
  const list = (targets.data ?? []).filter((t) => t.venue === copy?.venue)

  return (
    <Card className={className}>
      <CardHeader
        icon={<TargetIcon className="size-4" aria-hidden />}
        title="Targets"
        subtitle={status?.paused && copy?.running ? 'Global pause is active' : copy?.venue_label}
        actions={
          <Link
            to="/targets"
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-indigo-300 hover:text-indigo-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            Manage <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {targets.isPending || !copy ? (
        <SkeletonRows rows={4} />
      ) : targets.isError ? (
        <ErrorState error={targets.error} onRetry={() => targets.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<TargetIcon className="size-5" aria-hidden />}
          title={`No ${copy.venue_label} targets yet`}
          description="Add your first wallet to copy."
          action={
            <Link
              to="/targets?new=1"
              className="inline-flex h-8 items-center rounded-lg bg-indigo-600 px-3 text-xs font-medium text-white hover:bg-indigo-500"
            >
              Add target
            </Link>
          }
        />
      ) : (
        <ul className="divide-y divide-zinc-800/70">
          {list.map((t) => (
            <li key={t.id} className="flex items-center gap-3 px-4 py-3">
              <TargetSwitch target={t} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-200">{t.name}</p>
                <p className="text-xs text-zinc-500">
                  {formatInt(t.stats.positions)} pos · {formatRelative(t.stats.last_activity_ms, now)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm tabular-nums text-zinc-200">{formatUsd(t.stats.open_usd)}</p>
                <p className="text-[11px] tabular-nums text-zinc-500">
                  {t.stats.copied}/{t.stats.detected} copied
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
