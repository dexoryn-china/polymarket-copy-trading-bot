import { SECRET_MASK } from '../lib/schema'
import type {
  Activity,
  ActivityKind,
  ActivityLevel,
  CopyState,
  Feed,
  Field,
  FieldValue,
  Meta,
  Order,
  Position,
  SettingsSection,
  SettingsView,
  Status,
  Target,
  TargetInput,
  VenueId,
  WsMessage,
} from './types'

const now = () => Date.now()
const rand = (min: number, max: number) => min + Math.random() * (max - min)
const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(Math.random() * xs.length)]
const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d
const hex = (len: number) => Array.from({ length: len }, () => Math.floor(Math.random() * 16).toString(16)).join('')
const WALLET_RE = /^0x[0-9a-fA-F]{40}$/

const meta: Meta = {
  name: 'Polymarket Copy Bot',
  mode: 'dry_run',
  version: '0.9.0-mock',
  venues: [
    {
      id: 'predictions',
      label: 'Prediction markets',
      wallet_label: 'Polymarket wallet',
      wallet_placeholder: "0x… (proxy wallet from the trader's profile)",
      close_label: 'Mirror sells',
      sizing_fields: [
        {
          key: 'mode',
          label: 'Sizing mode',
          type: 'select',
          default: 'fixed',
          group: 'basic',
          options: [
            { value: 'fixed', label: 'Fixed USD per copy' },
            { value: 'percent_of_target', label: "Percent of target's spend" },
          ],
        },
        { key: 'fixed_usd_per_fill', label: 'Order size', type: 'number', default: 10, group: 'basic', min: 0.01, step: 0.5, unit: 'USD', help: 'USD spent on each copied buy.', show_if: { key: 'mode', equals: 'fixed' } },
        { key: 'percent_of_target', label: 'Percent of target', type: 'number', default: 5, group: 'basic', min: 0.01, max: 100, step: 0.5, unit: '%', help: "Share of the target's USD spend on each batched chunk.", show_if: { key: 'mode', equals: 'percent_of_target' } },
        { key: 'max_open_usd', label: 'Max open exposure', type: 'number', default: 100, group: 'basic', min: 1, step: 10, unit: 'USD', help: "Cap on the cost basis of this target's open positions." },
        { key: 'min_target_shares_to_copy', label: 'Batch threshold', type: 'number', default: 10, group: 'advanced', min: 0.01, step: 1, unit: 'shares', help: "Accumulate the target's buys per market until this many shares, then copy. Use ~1 for short-lived markets." },
      ],
    },
    {
      id: 'perps',
      label: 'Perps',
      wallet_label: 'Perps account',
      wallet_placeholder: '0x… (account address from the Perps leaderboard / profile)',
      close_label: 'Mirror reductions & closes',
      sizing_fields: [
        {
          key: 'mode',
          label: 'Sizing mode',
          type: 'select',
          default: 'percent_of_target',
          group: 'basic',
          options: [
            { value: 'percent_of_target', label: "Percent of target's size" },
            { value: 'fixed_notional', label: 'Fixed notional per entry' },
          ],
        },
        { key: 'percent_of_target', label: 'Percent of target', type: 'number', default: 10, group: 'basic', min: 0.01, max: 1000, step: 1, unit: '%', help: "Our size change = target's size change × this percent.", show_if: { key: 'mode', equals: 'percent_of_target' } },
        { key: 'fixed_notional_usd', label: 'Order size', type: 'number', default: 50, group: 'basic', min: 1, step: 10, unit: 'USD', help: 'Each time the target opens or adds, open this much notional.', show_if: { key: 'mode', equals: 'fixed_notional' } },
        { key: 'max_open_notional_usd', label: 'Max open notional', type: 'number', default: 500, group: 'basic', min: 1, step: 50, unit: 'USD', help: "Cap on the entry notional of this target's open positions." },
        { key: 'leverage', label: 'Leverage', type: 'number', default: 3, group: 'basic', min: 1, max: 100, step: 1, unit: 'x', help: 'Applied per instrument before opening from flat (clamped to the instrument max).' },
      ],
    },
  ],
}

const MARKETS = [
  { label: 'Will the Fed cut rates in December?', outcomes: ['Yes', 'No'] },
  { label: 'Bitcoin above $150k on Dec 31?', outcomes: ['Yes', 'No'] },
  { label: 'Who will win the 2026 NBA Finals?', outcomes: ['Celtics', 'Thunder', 'Nuggets'] },
  { label: 'US recession in 2026?', outcomes: ['Yes', 'No'] },
  { label: 'Will GPT-6 be released before 2027?', outcomes: ['Yes', 'No'] },
  { label: 'Ethereum ETF net inflows > $1B this week?', outcomes: ['Yes', 'No'] },
]
const PERPS = [
  { label: 'BTC-PERP', price: 97250 },
  { label: 'ETH-PERP', price: 3620 },
  { label: 'SOL-PERP', price: 212.4 },
  { label: 'HYPE-PERP', price: 38.15 },
]

function emptyStats(): Target['stats'] {
  return { detected: 0, copied: 0, failed: 0, skipped: 0, open_usd: 0, positions: 0, last_activity_ms: null }
}

let nextTargetId = 5
const targets: Target[] = [
  {
    id: 't1',
    name: 'Domer',
    venue: 'predictions',
    wallet: '0x9d84ce0306f8551e02efef1680475fc0f1dc1344',
    enabled: true,
    copy_closes: true,
    sizing: { mode: 'fixed', fixed_usd_per_fill: 25, percent_of_target: 5, max_open_usd: 500, min_target_shares_to_copy: 10 },
    stats: { detected: 142, copied: 128, failed: 3, skipped: 11, open_usd: 0, positions: 0, last_activity_ms: now() - 95_000 },
  },
  {
    id: 't2',
    name: 'Election whale',
    venue: 'predictions',
    wallet: '0x1f2dd6d473f3e824cd2f8a89d9c69fb96f6ad0cf',
    enabled: true,
    copy_closes: false,
    sizing: { mode: 'percent_of_target', fixed_usd_per_fill: 10, percent_of_target: 2, max_open_usd: 1500, min_target_shares_to_copy: 25 },
    stats: { detected: 58, copied: 49, failed: 1, skipped: 8, open_usd: 0, positions: 0, last_activity_ms: now() - 26 * 60_000 },
  },
  {
    id: 't3',
    name: 'Sports degen',
    venue: 'predictions',
    wallet: '0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b',
    enabled: false,
    copy_closes: true,
    sizing: { mode: 'fixed', fixed_usd_per_fill: 5, percent_of_target: 5, max_open_usd: 300, min_target_shares_to_copy: 1 },
    stats: { detected: 311, copied: 201, failed: 14, skipped: 96, open_usd: 0, positions: 0, last_activity_ms: now() - 3 * 86_400_000 },
  },
  {
    id: 't4',
    name: 'HL momentum',
    venue: 'perps',
    wallet: '0x5b5d51203a0f9079f8aeb098a6523a13f298c060',
    enabled: true,
    copy_closes: true,
    sizing: { mode: 'fixed_notional', percent_of_target: 10, fixed_notional_usd: 200, max_open_notional_usd: 2500, leverage: 5 },
    stats: { detected: 87, copied: 83, failed: 2, skipped: 2, open_usd: 0, positions: 0, last_activity_ms: now() - 4 * 60_000 },
  },
]

let nextPositionId = 1
const positions: Position[] = []

function addPosition(target: Target, openedAgoMs = 0): Position {
  let p: Position
  if (target.venue === 'predictions') {
    const m = pick(MARKETS)
    const outcome = pick(m.outcomes)
    const entry = round(rand(0.08, 0.92), 3)
    const size = round(rand(20, 400))
    const mark = Math.min(0.99, Math.max(0.01, entry + rand(-0.12, 0.12)))
    p = {
      id: `p${nextPositionId++}`,
      venue: 'predictions',
      target_id: target.id,
      target_name: target.name,
      label: m.label,
      sublabel: outcome,
      side: outcome === 'No' ? 'no' : 'yes',
      size,
      entry_price: entry,
      value_usd: round(size * mark),
      pnl_usd: round(size * (mark - entry)),
      opened_at_ms: now() - openedAgoMs,
      url: 'https://polymarket.com',
    }
  } else {
    const perp = pick(PERPS)
    const side = pick(['long', 'short'] as const)
    const entry = round(perp.price * rand(0.97, 1.03), 4)
    const size = round(rand(200, 3000) / perp.price, 4)
    const move = rand(-0.03, 0.03)
    p = {
      id: `p${nextPositionId++}`,
      venue: 'perps',
      target_id: target.id,
      target_name: target.name,
      label: perp.label,
      sublabel: null,
      side,
      size,
      entry_price: entry,
      value_usd: round(size * entry * (1 + move)),
      pnl_usd: round(size * entry * move * (side === 'long' ? 1 : -1)),
      opened_at_ms: now() - openedAgoMs,
      url: null,
    }
  }
  positions.unshift(p)
  return p
}

for (const t of targets) {
  const n = t.id === 't3' ? 2 : t.venue === 'perps' ? 3 : 4
  for (let i = 0; i < n; i++) addPosition(t, rand(10 * 60_000, 5 * 86_400_000))
}

let nextOrderId = 1
const orders: Order[] = []

function addOrder(target: Target) {
  const isPred = target.venue === 'predictions'
  const perp = pick(PERPS)
  const size = isPred ? round(rand(20, 200)) : round(rand(300, 1500) / perp.price, 4)
  orders.unshift({
    id: `o${nextOrderId++}`,
    venue: target.venue,
    target_id: target.id,
    target_name: target.name,
    label: isPred ? pick(MARKETS).label : perp.label,
    side: isPred ? pick(['BUY', 'SELL']) : pick(['LONG', 'SHORT']),
    price: isPred ? round(rand(0.1, 0.9), 3) : round(perp.price * rand(0.99, 1.01), 4),
    size,
    filled: round(size * rand(0, 0.7), 4),
    placed_at_ms: now() - rand(5_000, 600_000),
    expires_at_ms: Math.random() < 0.25 ? null : now() + rand(60_000, 900_000),
  })
}

addOrder(targets[1])
addOrder(targets[1])
addOrder(targets[3])

const counts = { detected: 0, copied: 0, failed: 0, skipped: 0 }
for (const t of targets) {
  counts.detected += t.stats.detected
  counts.copied += t.stats.copied
  counts.failed += t.stats.failed
  counts.skipped += t.stats.skipped
}

const startedAt = now() - 3 * 3600_000 - 17 * 60_000
let paused = false
const copy: { venue: VenueId; state: CopyState; startedAt: number | null } = {
  venue: 'predictions',
  state: 'stopped',
  startedAt: null,
}
const COPY_START_MS = 1200
const COPY_STOP_MS = 2500
const FAIL_PERPS_START = import.meta.env.VITE_MOCK_FAIL_PERPS_START === '1'

const latencies: { ts_ms: number; total_ms: number }[] = Array.from({ length: 30 }, (_, i) => ({
  ts_ms: now() - (30 - i) * 45_000,
  total_ms: round(rand(180, 650), 0),
}))
const feeds: (Feed & { venue: VenueId })[] = [
  { id: 'poly_ws', venue: 'predictions', label: 'Polymarket WS', connected: true, last_event_ms: now() - 2_000, reconnects: 1 },
  { id: 'perps_poll', venue: 'perps', label: 'Perps poller', connected: true, last_event_ms: now() - 4_000, reconnects: 0 },
]

const venueLabel = (id: VenueId) => meta.venues.find((v) => v.id === id)!.label

function refreshTargetStats() {
  for (const t of targets) {
    const mine = positions.filter((p) => p.target_id === t.id)
    t.stats.positions = mine.length
    t.stats.open_usd = round(mine.reduce((s, p) => s + p.value_usd, 0))
  }
}

function buildStatus(): Status {
  refreshTargetStats()
  const sorted = latencies.map((l) => l.total_ms).sort((a, b) => a - b)
  const avg = sorted.reduce((s, x) => s + x, 0) / Math.max(1, sorted.length)
  const venueStatus = (id: VenueId, balance: number, cap: number | null) => {
    const ps = positions.filter((p) => p.venue === id)
    const venue = meta.venues.find((v) => v.id === id)!
    return {
      id,
      label: venue.label,
      active: id === copy.venue,
      balance_usd: balance,
      open_usd: round(ps.reduce((s, p) => s + p.value_usd, 0)),
      cap_usd: cap,
      positions: ps.length,
    }
  }
  const running = copy.state === 'running'
  return {
    mode: meta.mode,
    copy: {
      venue: copy.venue,
      venue_label: venueLabel(copy.venue),
      state: copy.state,
      running,
      started_at_ms: copy.startedAt,
    },
    paused,
    started_at_ms: startedAt,
    uptime_s: Math.floor((now() - startedAt) / 1000),
    feeds: feeds
      .filter((f) => running && f.venue === copy.venue)
      .map(({ venue: _venue, ...f }) => ({ ...f, last_event_ms: f.connected ? now() - rand(200, 5000) : f.last_event_ms })),
    venues: [venueStatus('predictions', 2481.37, 4000), venueStatus('perps', 9120.5, null)],
    counts: { ...counts },
    latency: {
      last_ms: latencies.at(-1)?.total_ms ?? null,
      avg_ms: round(avg, 0),
      p95_ms: sorted[Math.floor(sorted.length * 0.95)] ?? null,
      recent: latencies.slice(),
    },
  }
}

let nextActivityId = 1
const activity: Activity[] = []

function makeActivity(
  kind: ActivityKind,
  level: ActivityLevel,
  target: Target | null,
  summary: string,
  data: Record<string, unknown>,
  ts = now(),
): Activity {
  return {
    id: nextActivityId++,
    ts_ms: ts,
    venue: target?.venue ?? 'system',
    target_id: target?.id ?? null,
    target_name: target?.name ?? null,
    kind,
    level,
    summary,
    data,
  }
}

function tradeEvents(target: Target, ts: number, allowCopy: boolean): Activity[] {
  const isPred = target.venue === 'predictions'
  const market = isPred ? pick(MARKETS) : null
  const perp = isPred ? null : pick(PERPS)
  const label = market ? `${market.label} — ${pick(market.outcomes)}` : perp!.label
  const side = isPred ? pick(['BUY', 'SELL']) : pick(['LONG', 'SHORT'])
  const price = isPred ? round(rand(0.05, 0.95), 3) : round(perp!.price * rand(0.995, 1.005), 2)
  const targetUsd = round(rand(50, 5000))
  const priceText = isPred ? `${(price * 100).toFixed(1)}¢` : `$${price}`
  const fill = makeActivity(
    'target_fill',
    'info',
    target,
    `${target.name} ${side} ${label} @ ${priceText} ($${targetUsd.toFixed(2)})`,
    { market: label, side, price, target_usd: targetUsd, tx: `0x${hex(64)}` },
    ts,
  )
  const latency = round(rand(160, 900), 0)
  const roll = Math.random()
  let result: Activity
  if (!allowCopy) {
    result = makeActivity('copy_skipped', 'warning', target, 'Skipped — copying is paused', { reason: 'paused' }, ts + latency)
  } else if (roll < 0.72) {
    const usd = round(Number(target.sizing.fixed_usd_per_fill ?? target.sizing.fixed_notional_usd ?? 25) * rand(0.9, 1.1))
    result = makeActivity(
      'copy_success',
      'success',
      target,
      `Copied ${side} ${label} for $${usd.toFixed(2)}`,
      { market: label, side, price, copied_usd: usd, order_id: `0x${hex(16)}`, latency_ms: latency, dry_run: meta.mode === 'dry_run' },
      ts + latency,
    )
  } else if (roll < 0.9) {
    result = makeActivity(
      'copy_skipped',
      'warning',
      target,
      pick(['Skipped — below minimum order size', 'Skipped — price above max entry', 'Skipped — exposure cap reached']),
      { market: label, side, price, reason: 'filter' },
      ts + latency,
    )
  } else {
    result = makeActivity(
      'copy_failure',
      'error',
      target,
      pick(['Order rejected: insufficient liquidity', 'Order rejected: price moved beyond slippage', 'Timeout waiting for order ack']),
      { market: label, side, price, attempts: 2, latency_ms: latency },
      ts + latency,
    )
  }
  return [fill, result]
}

function seedActivity() {
  const items: Activity[] = []
  let ts = now() - 220 * 90_000
  items.push(makeActivity('system', 'info', null, `Bot started in ${meta.mode === 'real' ? 'LIVE' : 'DRY RUN'} mode`, { version: meta.version }, ts))
  for (let i = 0; i < 220; i++) {
    ts += rand(30_000, 150_000)
    const r = Math.random()
    if (r < 0.03) {
      items.push(makeActivity('error', 'error', null, 'Feed disconnected: Polymarket WS (reconnecting)', { feed: 'poly_ws', code: 1006 }, ts))
    } else if (r < 0.08) {
      const t = pick(targets)
      items.push(makeActivity('order_update', 'info', t, 'Resting order partially filled (42%)', { order_id: `0x${hex(16)}`, filled_pct: 42 }, ts))
    } else {
      items.push(...tradeEvents(pick(targets), ts, true))
    }
  }
  activity.push(...items.reverse())
}
seedActivity()

type Reply = [number, unknown]
type Handler = (ctx: { url: URL; method: string; body: unknown; params: string[] }) => Reply | Promise<Reply>

function err(status: number, error: string): [number, unknown] {
  return [status, { error }]
}

type Coerced = { ok: true; value: FieldValue } | { ok: false; error: string }

function coerceField(field: Field, raw: unknown): Coerced {
  if (field.nullable && (raw === null || raw === '')) return { ok: true, value: null }
  const fail = (error: string): Coerced => ({ ok: false, error })
  switch (field.type) {
    case 'boolean':
      return typeof raw === 'boolean' ? { ok: true, value: raw } : fail(`${field.label} must be true/false`)
    case 'select': {
      const v = String(raw)
      const allowed = field.options?.map((o) => o.value) ?? []
      return allowed.includes(v) ? { ok: true, value: v } : fail(`${field.label} must be one of ${allowed.join(', ')}`)
    }
    case 'list':
    case 'multiselect': {
      const items = Array.isArray(raw) ? raw.map(String) : String(raw ?? '').split(',')
      const values = [...new Set(items.map((s) => s.trim()).filter(Boolean))]
      const unknown = values.filter((v) => field.type === 'multiselect' && !field.options?.some((o) => o.value === v))
      return unknown.length ? fail(`${field.label}: unknown option ${unknown.join(', ')}`) : { ok: true, value: values }
    }
    case 'number': {
      const n = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() ? Number(raw) : NaN
      if (!Number.isFinite(n)) return fail(`${field.label} must be a number`)
      if (field.min != null && n < field.min) return fail(`${field.label} must be at least ${field.min}`)
      if (field.max != null && n > field.max) return fail(`${field.label} must be at most ${field.max}`)
      return { ok: true, value: n }
    }
    default:
      return raw == null || typeof raw === 'object' ? fail(`${field.label} must be text`) : { ok: true, value: String(raw).trim() }
  }
}

function validateInput(input: Partial<TargetInput>, id?: string): string | null {
  if (!input.name?.trim()) return 'Name is required'
  if (!input.wallet || !WALLET_RE.test(input.wallet)) return 'Wallet must be a 0x-prefixed 40-character hex address'
  const venue = meta.venues.find((v) => v.id === input.venue)
  if (!venue) return `Unknown venue: ${String(input.venue)}`
  const dup = targets.find((t) => t.wallet.toLowerCase() === input.wallet!.toLowerCase() && t.venue === input.venue && t.id !== id)
  if (dup) return `This wallet is already tracked as “${dup.name}”`
  for (const f of venue.sizing_fields) {
    const r = coerceField(f, input.sizing?.[f.key] ?? f.default)
    if (!r.ok) return r.error
  }
  return null
}

const settingsSections: SettingsSection[] = [
  {
    id: 'trading',
    label: 'Prediction markets',
    venue: 'predictions',
    description: 'How copies are executed on the Polymarket CLOB. Per-wallet order size lives on each target.',
    fields: [
      {
        key: 'execution.order_type', label: 'Order type', type: 'select', default: 'taker', group: 'basic',
        options: [{ value: 'taker', label: 'Taker — fill now (FAK)' }, { value: 'maker', label: 'Maker — rest on the book (GTC)' }],
        help: 'Taker fills immediately against the book; maker posts a limit order and waits.',
      },
      { key: 'risk.max_open_usd_total', label: 'Total exposure cap', type: 'number', default: null, group: 'basic', min: 1, step: 10, unit: 'USD', nullable: true, help: 'Across ALL prediction targets (each target also has its own cap). Empty = no total cap.' },
      { key: 'maker_settings.rest_timeout_s', label: 'Cancel unfilled after', type: 'number', default: 30, group: 'basic', min: 1, step: 5, unit: 's', nullable: true, show_if: { key: 'execution.order_type', equals: 'maker' }, help: 'Resting maker orders still open after this are cancelled. Empty = never.' },
      { key: 'slippage.entry_bps_max', label: 'Max entry slippage', type: 'number', default: 1000, group: 'advanced', min: 1, max: 9999, step: 50, unit: 'bps', show_if: { key: 'execution.order_type', equals: 'taker' }, help: 'Buy limit = target price × (1 + bps/10000). 100 bps = 1%. Wider fills more often.' },
      { key: 'slippage.exit_bps_max', label: 'Max exit slippage', type: 'number', default: 1000, group: 'advanced', min: 1, max: 9999, step: 50, unit: 'bps', show_if: { key: 'execution.order_type', equals: 'taker' }, help: 'Sell limit = target price × (1 − bps/10000).' },
      { key: 'maker_settings.price_offset_ticks', label: 'Maker price offset', type: 'number', default: 0, group: 'advanced', min: -10, max: 10, step: 1, unit: 'ticks', show_if: { key: 'execution.order_type', equals: 'maker' }, help: "0 = the target's price; positive = more aggressive for buys." },
      {
        key: 'order_minimum.mode', label: 'Order minimum rule', type: 'select', default: 'shares', group: 'advanced',
        options: [{ value: 'dollar', label: 'Minimum order value (USD)' }, { value: 'shares', label: 'Minimum share count' }],
        help: 'Copies smaller than the market minimum are bumped up (entries) or batched (exits).',
      },
      { key: 'order_minimum.min_usd', label: 'Minimum order value', type: 'number', default: 1, group: 'advanced', min: 0.01, step: 0.5, unit: 'USD', show_if: { key: 'order_minimum.mode', equals: 'dollar' } },
      { key: 'order_minimum.min_shares', label: 'Minimum shares', type: 'number', default: 5, group: 'advanced', min: 0.01, step: 1, unit: 'shares', show_if: { key: 'order_minimum.mode', equals: 'shares' } },
      { key: 'position_expiry.buffer_s', label: 'Release exposure after market end', type: 'number', default: 60, group: 'advanced', min: 0, step: 30, unit: 's', help: 'A resolved market stops counting toward caps this long after its end date.' },
      { key: 'position_expiry.fallback_ttl_min', label: 'Fallback position lifetime', type: 'number', default: 1440, group: 'advanced', min: 5, step: 60, unit: 'min', help: "Used when a market's end date is unknown." },
    ],
  },
  {
    id: 'perps',
    label: 'Perps',
    venue: 'perps',
    description: 'Polymarket Perps copying. Per-wallet size and leverage live on each target.',
    fields: [
      { key: 'perps.max_open_notional_total', label: 'Total notional cap', type: 'number', default: null, group: 'basic', min: 1, step: 50, unit: 'USD', nullable: true, help: 'Across ALL perps targets. Empty = no total cap.' },
      { key: 'perps.slippage_bps', label: 'Max slippage', type: 'number', default: 50, group: 'advanced', min: 1, max: 9999, step: 5, unit: 'bps', help: "IOC limit = mark × (1 ± bps/10000), kept inside the instrument's price band." },
      { key: 'perps.poll_interval_s', label: 'Poll interval', type: 'number', default: 1, group: 'advanced', min: 0.25, max: 60, step: 0.25, unit: 's', help: "How often each target's portfolio is checked. Lower = faster copies, more requests." },
      {
        key: 'perps.margin_mode', label: 'Margin mode', type: 'select', default: 'isolated', group: 'advanced',
        options: [{ value: 'isolated', label: 'Isolated' }, { value: 'cross', label: 'Cross' }],
        help: 'Applied when opening an instrument from flat.',
      },
    ],
  },
  {
    id: 'notifications',
    label: 'Telegram',
    venue: null,
    description: 'Push notifications to one or more Telegram chats.',
    fields: [
      { key: 'telegram.enabled', label: 'Send notifications', type: 'boolean', default: false, group: 'basic' },
      { key: 'telegram.bot_token', label: 'Bot token', type: 'secret', default: null, group: 'basic', help: 'From @BotFather. Stored on the bot machine only.' },
      { key: 'telegram.chat_id', label: 'Chat IDs', type: 'list', default: [], group: 'basic', help: 'Comma-separated. Group / channel ids are negative.' },
      {
        key: 'telegram.notify_on', label: 'Notify on', type: 'multiselect', group: 'advanced',
        default: ['copy_failure', 'copy_start', 'copy_stop', 'copy_success', 'error', 'shutdown', 'startup'],
        options: [
          { value: 'copy_start', label: 'Copying started' },
          { value: 'copy_stop', label: 'Copying stopped' },
          { value: 'copy_success', label: 'Trade copied' },
          { value: 'copy_failure', label: 'Copy failed' },
          { value: 'copy_skipped', label: 'Copy skipped' },
          { value: 'target_fill', label: 'Target traded (noisy)' },
          { value: 'order_update', label: 'Resting order finished' },
          { value: 'error', label: 'Errors' },
          { value: 'startup', label: 'Bot started' },
          { value: 'shutdown', label: 'Bot stopped' },
        ],
      },
    ],
  },
]

const settingsFields = new Map(settingsSections.flatMap((s) => s.fields).map((f) => [f.key, f]))
const settingsValues: Record<string, FieldValue> = {
  'execution.order_type': 'taker',
  'risk.max_open_usd_total': 4000,
  'maker_settings.rest_timeout_s': 30,
  'slippage.entry_bps_max': 1000,
  'slippage.exit_bps_max': 1000,
  'maker_settings.price_offset_ticks': 0,
  'order_minimum.mode': 'shares',
  'order_minimum.min_usd': 1,
  'order_minimum.min_shares': 5,
  'position_expiry.buffer_s': 60,
  'position_expiry.fallback_ttl_min': 1440,
  'perps.max_open_notional_total': null,
  'perps.slippage_bps': 50,
  'perps.poll_interval_s': 1,
  'perps.margin_mode': 'isolated',
  'telegram.enabled': true,
  'telegram.bot_token': '123456:mock-token',
  'telegram.chat_id': ['-1001234567890'],
  'telegram.notify_on': ['copy_failure', 'copy_start', 'copy_stop', 'copy_success', 'error', 'shutdown', 'startup'],
}

function settingsView(): SettingsView {
  const values: Record<string, FieldValue> = {}
  for (const [key, field] of settingsFields) {
    const v = settingsValues[key]
    values[key] = field.type === 'secret' ? (v ? SECRET_MASK : '') : v
  }
  return { sections: settingsSections, values }
}

function updateSettings(changes: unknown): [number, unknown] {
  if (!changes || typeof changes !== 'object' || Object.keys(changes).length === 0) return err(400, 'send at least one setting')
  const unknown = Object.keys(changes).filter((k) => !settingsFields.has(k))
  if (unknown.length) return err(400, `unknown settings: ${unknown.join(', ')}`)

  const candidate = { ...settingsValues }
  for (const [key, raw] of Object.entries(changes)) {
    const field = settingsFields.get(key)!
    if (field.type === 'secret' && raw === SECRET_MASK) continue
    const r = coerceField(field, raw)
    if (!r.ok) return err(400, r.error)
    candidate[key] = r.value
  }

  const chats = (candidate['telegram.chat_id'] as string[] | null) ?? []
  if (chats.some((c) => !/^-?\d+$/.test(c))) return err(400, 'Chat IDs must be numeric')
  if (candidate['telegram.enabled'] && (!candidate['telegram.bot_token'] || chats.length === 0)) {
    return err(400, 'Telegram needs a bot token and at least one chat ID')
  }

  const changed = Object.keys(candidate).filter((k) => JSON.stringify(candidate[k]) !== JSON.stringify(settingsValues[k]))
  Object.assign(settingsValues, candidate)
  if (changed.length) {
    const labels = changed.map((k) => settingsFields.get(k)!.label).join(', ')
    emitAll({ type: 'activity', item: makeActivity('system', 'info', null, `Settings updated: ${labels}`, { keys: changed }) })
  }
  return [200, settingsView()]
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function setCopyState(state: CopyState) {
  copy.state = state
  copy.startedAt = state === 'running' ? now() : state === 'stopped' ? null : copy.startedAt
  emitAll({ type: 'status', status: buildStatus() })
}

function isVenue(v: unknown): v is VenueId {
  return meta.venues.some((x) => x.id === v)
}

function selectVenue(body: unknown): Reply {
  const venue = (body as { venue?: unknown } | undefined)?.venue
  if (!isVenue(venue)) return err(400, `unknown venue: ${String(venue)}`)
  if (copy.state !== 'stopped') return err(409, 'stop copying before switching venue')
  if (venue !== copy.venue) {
    copy.venue = venue
    emitAll({ type: 'status', status: buildStatus() })
    record(makeActivity('system', 'info', null, `Copy venue set to ${venueLabel(venue)}`, { venue }))
  }
  return [200, buildStatus()]
}

async function startCopy(body: unknown): Promise<Reply> {
  if (copy.state !== 'stopped') return err(409, 'copying is already running')
  if ((body as { venue?: unknown } | undefined)?.venue !== undefined) {
    const reply = selectVenue(body)
    if (reply[0] !== 200) return reply
  }
  setCopyState('starting')
  await sleep(COPY_START_MS)
  if (FAIL_PERPS_START && copy.venue === 'perps') {
    setCopyState('stopped')
    return err(400, "couldn't start Perps copying: polymarket.private_key is not set")
  }
  setCopyState('running')
  record(makeActivity('system', 'success', null, `Copying started: ${venueLabel(copy.venue)}`, { venue: copy.venue }))
  return [200, buildStatus()]
}

async function stopCopy(): Promise<Reply> {
  if (copy.state === 'stopped') return [200, buildStatus()]
  if (copy.state !== 'running') return err(409, `copying is ${copy.state}`)
  setCopyState('stopping')
  await sleep(COPY_STOP_MS)
  setCopyState('stopped')
  record(makeActivity('system', 'warning', null, `Copying stopped: ${venueLabel(copy.venue)}`, { venue: copy.venue }))
  return [200, buildStatus()]
}

const routes: [string, RegExp, Handler][] = [
  ['GET', /^\/api\/meta$/, () => [200, meta]],
  ['GET', /^\/api\/status$/, () => [200, buildStatus()]],
  ['PUT', /^\/api\/copy$/, ({ body }) => selectVenue(body)],
  ['POST', /^\/api\/copy\/start$/, ({ body }) => startCopy(body)],
  ['POST', /^\/api\/copy\/stop$/, () => stopCopy()],
  [
    'POST',
    /^\/api\/pause$/,
    ({ body }) => {
      paused = Boolean((body as { paused?: boolean }).paused)
      emitAll({ type: 'activity', item: makeActivity('system', 'warning', null, paused ? 'Copying paused by user' : 'Copying resumed by user', {}) })
      return [200, buildStatus()]
    },
  ],
  [
    'GET',
    /^\/api\/targets$/,
    () => {
      refreshTargetStats()
      return [200, targets]
    },
  ],
  [
    'POST',
    /^\/api\/targets$/,
    ({ body }) => {
      const input = body as TargetInput
      const problem = validateInput(input)
      if (problem) return err(400, problem)
      const t: Target = { ...input, id: `t${nextTargetId++}`, name: input.name.trim(), stats: emptyStats() }
      targets.push(t)
      return [201, t]
    },
  ],
  [
    'PUT',
    /^\/api\/targets\/([^/]+)$/,
    ({ body, params }) => {
      const t = targets.find((x) => x.id === params[0])
      if (!t) return err(404, 'Target not found')
      const patch = body as Partial<TargetInput>
      const input: TargetInput = { ...t, ...patch, sizing: { ...t.sizing, ...patch.sizing } }
      if (input.venue !== t.venue) return err(400, 'Venue cannot be changed')
      const problem = validateInput(input, t.id)
      if (problem) return err(400, problem)
      Object.assign(t, { name: input.name.trim(), wallet: input.wallet, enabled: input.enabled, copy_closes: input.copy_closes, sizing: input.sizing })
      return [200, t]
    },
  ],
  [
    'PATCH',
    /^\/api\/targets\/([^/]+)$/,
    ({ body, params }) => {
      const t = targets.find((x) => x.id === params[0])
      if (!t) return err(404, 'Target not found')
      t.enabled = Boolean((body as { enabled?: boolean }).enabled)
      return [200, t]
    },
  ],
  [
    'DELETE',
    /^\/api\/targets\/([^/]+)$/,
    ({ params }) => {
      const idx = targets.findIndex((x) => x.id === params[0])
      if (idx < 0) return err(404, 'Target not found')
      const open = positions.filter((p) => p.target_id === params[0]).length
      if (open > 0) return err(409, `Target still has ${open} open position${open === 1 ? '' : 's'}.`)
      targets.splice(idx, 1)
      return [204, null]
    },
  ],
  [
    'GET',
    /^\/api\/positions$/,
    ({ url }) => {
      const venue = url.searchParams.get('venue')
      const targetId = url.searchParams.get('target_id')
      return [200, positions.filter((p) => (!venue || p.venue === venue) && (!targetId || p.target_id === targetId))]
    },
  ],
  ['GET', /^\/api\/settings$/, () => [200, settingsView()]],
  ['PUT', /^\/api\/settings$/, ({ body }) => updateSettings((body as { values?: unknown } | undefined)?.values)],
  ['GET', /^\/api\/orders$/, () => [200, orders.filter((o) => o.expires_at_ms == null || o.expires_at_ms > now())]],
  [
    'GET',
    /^\/api\/activity$/,
    ({ url }) => {
      const q = url.searchParams
      const limit = Number(q.get('limit') ?? 100)
      const before = q.get('before_id')
      const filtered = activity.filter(
        (a) =>
          (!before || a.id < Number(before)) &&
          (!q.get('venue') || a.venue === q.get('venue')) &&
          (!q.get('target_id') || a.target_id === q.get('target_id')) &&
          (!q.get('kind') || a.kind === q.get('kind')),
      )
      const items = filtered.slice(0, limit)
      const next = filtered.length > limit ? items[items.length - 1].id : null
      return [200, { items, next_before_id: next }]
    },
  ],
]

async function handle(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, window.location.origin)
  const method = (init?.method ?? 'GET').toUpperCase()
  const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined
  await new Promise((r) => setTimeout(r, rand(80, 260)))

  for (const [m, re, handler] of routes) {
    const match = url.pathname.match(re)
    if (!match || m !== method) continue
    const [status, payload] = await handler({ url, method, body, params: match.slice(1) })
    if (status === 204) return new Response(null, { status })
    return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
  }
  return new Response(JSON.stringify({ error: `Mock: no route for ${method} ${url.pathname}` }), {
    status: 404,
    headers: { 'Content-Type': 'application/json' },
  })
}

const sockets = new Set<FakeSocket>()

function emitAll(msg: WsMessage) {
  sockets.forEach((s) => s.push(msg))
}

function record(item: Activity) {
  activity.unshift(item)
  const t = targets.find((x) => x.id === item.target_id)
  if (t) t.stats.last_activity_ms = item.ts_ms
  const bump = (key: keyof typeof counts) => {
    counts[key]++
    if (t) t.stats[key]++
  }
  if (item.kind === 'target_fill') bump('detected')
  if (item.kind === 'copy_success') {
    bump('copied')
    latencies.push({ ts_ms: item.ts_ms, total_ms: Number(item.data.latency_ms ?? 300) })
    if (latencies.length > 40) latencies.shift()
    if (t && Math.random() < 0.5) addPosition(t)
  }
  if (item.kind === 'copy_failure') bump('failed')
  if (item.kind === 'copy_skipped') bump('skipped')
  emitAll({ type: 'activity', item })
}

let simTimer: number | undefined

function scheduleSimulation() {
  simTimer = window.setTimeout(() => {
    const active = copy.state === 'running' ? targets.filter((t) => t.enabled && t.venue === copy.venue) : []
    if (active.length > 0) {
      const [fill, result] = tradeEvents(pick(active), now(), !paused)
      record(fill)
      window.setTimeout(() => record({ ...result, ts_ms: now() }), Number(result.ts_ms - fill.ts_ms))
    }
    if (Math.random() < 0.15 && orders.length > 0) {
      const o = pick(orders)
      o.filled = Math.min(o.size, round(o.filled + o.size * rand(0.1, 0.4), 4))
    }
    scheduleSimulation()
  }, rand(3500, 8000))
}

class FakeSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readyState = FakeSocket.CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  private statusTimer: number | undefined

  constructor() {
    window.setTimeout(() => {
      if (this.readyState !== FakeSocket.CONNECTING) return
      this.readyState = FakeSocket.OPEN
      sockets.add(this)
      if (sockets.size === 1 && simTimer === undefined) scheduleSimulation()
      this.onopen?.(new Event('open'))
      this.statusTimer = window.setInterval(() => this.push({ type: 'status', status: buildStatus() }), 2000)
    }, 400)
  }

  push(msg: WsMessage) {
    if (this.readyState !== FakeSocket.OPEN) return
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(msg) }))
  }

  send() {}

  close() {
    if (this.readyState === FakeSocket.CLOSED) return
    this.readyState = FakeSocket.CLOSED
    sockets.delete(this)
    window.clearInterval(this.statusTimer)
    this.onclose?.(new CloseEvent('close', { code: 1000 }))
  }
}

export function installMock() {
  const realFetch = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' || input instanceof URL ? String(input) : input.url
    const path = new URL(raw, window.location.origin).pathname
    return path.startsWith('/api/') ? handle(input, init) : realFetch(input, init)
  }

  const RealWebSocket = window.WebSocket
  const PatchedWebSocket = function (url: string | URL, protocols?: string | string[]) {
    if (new URL(String(url), window.location.href).pathname === '/api/ws') return new FakeSocket()
    return new RealWebSocket(url, protocols)
  } as unknown as typeof WebSocket
  Object.assign(PatchedWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3, prototype: RealWebSocket.prototype })
  window.WebSocket = PatchedWebSocket

  console.info('%c[Polymarket Copy Bot] mock API enabled', 'color:#818cf8')
}
