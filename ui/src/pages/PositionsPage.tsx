import { useState } from 'react'
import { Briefcase, Clock, ExternalLink } from 'lucide-react'
import { useOrders, usePositions, useTargets } from '../api/queries'
import type { Order, Position } from '../api/types'
import { useCopy } from '../api/useCopy'
import { PageHeader } from '../components/PageHeader'
import { PnlText, SideBadge } from '../components/TradeBits'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState, ErrorState } from '../components/ui/EmptyState'
import { FilterSelect } from '../components/ui/Form'
import { Progress } from '../components/ui/Progress'
import { SkeletonRows } from '../components/ui/Skeleton'
import { TBody, TD, TH, THead, TR, Table } from '../components/ui/Table'
import { cn } from '../lib/cn'
import {
  formatAbsolute,
  formatAge,
  formatDuration,
  formatPrice,
  formatShares,
  formatSignedUsd,
  formatUsd,
} from '../lib/format'
import { useNow } from '../lib/useNow'

export function PositionsPage() {
  const { copy } = useCopy()
  const targets = useTargets()
  const venue = copy?.venue
  const [selectedTarget, setTargetId] = useState('')
  const now = useNow()

  const venueTargets = (targets.data ?? []).filter((t) => t.venue === venue)
  // A target picked before a venue switch no longer applies.
  const targetId = venueTargets.some((t) => t.id === selectedTarget) ? selectedTarget : ''

  const positions = usePositions({ venue, target_id: targetId || undefined }, Boolean(venue))
  const orders = useOrders()

  const venueOrders = (orders.data ?? []).filter(
    (o) => o.venue === venue && (!targetId || o.target_id === targetId),
  )
  const totals = (positions.data ?? []).reduce(
    (acc, p) => ({ value: acc.value + p.value_usd, pnl: acc.pnl + (p.pnl_usd ?? 0) }),
    { value: 0, pnl: 0 },
  )

  return (
    <>
      <PageHeader
        title="Positions"
        description={`Open copied ${copy ? `${copy.venue_label} ` : ''}positions and resting orders being monitored.`}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <FilterSelect
          label="Target"
          value={targetId}
          onChange={setTargetId}
          allLabel="All targets"
          options={venueTargets.map((t) => ({ value: t.id, label: t.name }))}
        />
      </div>

      <Card>
        <CardHeader
          icon={<Briefcase className="size-4" aria-hidden />}
          title="Open positions"
          subtitle={
            positions.data && positions.data.length > 0 ? (
              <>
                {positions.data.length} positions · {formatUsd(totals.value)} ·{' '}
                <span className={totals.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {formatSignedUsd(totals.pnl)}
                </span>
              </>
            ) : undefined
          }
        />
        {positions.isPending || !venue ? (
          <SkeletonRows rows={5} />
        ) : positions.isError ? (
          <ErrorState error={positions.error} onRetry={() => positions.refetch()} />
        ) : positions.data.length === 0 ? (
          <EmptyState
            icon={<Briefcase className="size-5" aria-hidden />}
            title="No open positions"
            description="Copied positions will appear here once your targets trade."
          />
        ) : (
          <PositionsTable positions={positions.data} venue={venue} now={now} />
        )}
      </Card>

      <Card className="mt-6">
        <CardHeader
          icon={<Clock className="size-4" aria-hidden />}
          title="Open orders"
          subtitle="Resting limit orders the bot is monitoring"
        />
        {orders.isPending || !venue ? (
          <SkeletonRows rows={3} />
        ) : orders.isError ? (
          <ErrorState error={orders.error} onRetry={() => orders.refetch()} />
        ) : venueOrders.length === 0 ? (
          <EmptyState icon={<Clock className="size-5" aria-hidden />} title="No resting orders" />
        ) : (
          <OrdersTable orders={venueOrders} venue={venue} now={now} />
        )}
      </Card>
    </>
  )
}

function PositionsTable({ positions, venue, now }: { positions: Position[]; venue: string; now: number }) {
  return (
    <Table>
      <THead>
        <tr>
          <TH>Market</TH>
          <TH>Side</TH>
          <TH className="text-right">Size</TH>
          <TH className="text-right">Entry</TH>
          <TH className="text-right">Value</TH>
          <TH className="text-right">PnL</TH>
          <TH className="text-right">Age</TH>
        </tr>
      </THead>
      <TBody>
        {positions.map((p) => (
          <TR key={p.id}>
            <TD className="max-w-xs">
              <div className="flex items-center gap-1.5">
                <span className="truncate font-medium text-zinc-100" title={p.label}>
                  {p.label}
                </span>
                {p.url && (
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 rounded text-zinc-500 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
                    aria-label={`Open ${p.label}`}
                  >
                    <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                )}
              </div>
              <p className="truncate text-xs text-zinc-500">
                {p.sublabel && <span className="text-zinc-400">{p.sublabel} · </span>}
                {p.target_name}
              </p>
            </TD>
            <TD>
              <SideBadge side={p.side} />
            </TD>
            <TD className="text-right tabular-nums">{formatShares(p.size)}</TD>
            <TD className="text-right tabular-nums">{formatPrice(p.entry_price, venue)}</TD>
            <TD className="text-right tabular-nums text-zinc-100">{formatUsd(p.value_usd)}</TD>
            <TD className="text-right">
              <PnlText value={p.pnl_usd} />
            </TD>
            <TD className="whitespace-nowrap text-right text-xs text-zinc-500" title={formatAbsolute(p.opened_at_ms)}>
              {formatAge(p.opened_at_ms, now)}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  )
}

function OrdersTable({ orders, venue, now }: { orders: Order[]; venue: string; now: number }) {
  return (
    <Table>
      <THead>
        <tr>
          <TH>Market</TH>
          <TH>Side</TH>
          <TH className="text-right">Price</TH>
          <TH className="text-right">Size</TH>
          <TH className="w-40">Filled</TH>
          <TH className="text-right">Placed</TH>
          <TH className="text-right">Expires</TH>
        </tr>
      </THead>
      <TBody>
        {orders.map((o) => {
          const pct = o.size > 0 ? (o.filled / o.size) * 100 : 0
          const remaining = o.expires_at_ms != null ? (o.expires_at_ms - now) / 1000 : null
          return (
            <TR key={o.id}>
              <TD className="max-w-xs">
                <p className="truncate font-medium text-zinc-100" title={o.label}>
                  {o.label}
                </p>
                <p className="truncate text-xs text-zinc-500">{o.target_name}</p>
              </TD>
              <TD>
                <SideBadge side={o.side} />
              </TD>
              <TD className="text-right tabular-nums">{formatPrice(o.price, venue)}</TD>
              <TD className="text-right tabular-nums">{formatShares(o.size)}</TD>
              <TD>
                <div className="flex items-center gap-2">
                  <Progress value={pct} tone="accent" label={`${o.label} fill progress`} className="flex-1" />
                  <span className="w-10 text-right text-xs tabular-nums text-zinc-400">{Math.round(pct)}%</span>
                </div>
              </TD>
              <TD className="whitespace-nowrap text-right text-xs text-zinc-500" title={formatAbsolute(o.placed_at_ms)}>
                {formatAge(o.placed_at_ms, now)} ago
              </TD>
              <TD
                className={cn(
                  'whitespace-nowrap text-right text-xs tabular-nums',
                  remaining == null ? 'text-zinc-500' : remaining < 30 ? 'text-amber-400' : 'text-zinc-300',
                )}
                title={o.expires_at_ms != null ? formatAbsolute(o.expires_at_ms) : 'Good till cancelled'}
              >
                {remaining == null ? 'GTC' : remaining <= 0 ? 'Expiring…' : formatDuration(remaining)}
              </TD>
            </TR>
          )
        })}
      </TBody>
    </Table>
  )
}
