export type Mode = 'dry_run' | 'real'
export type VenueId = 'predictions' | 'perps'
export type FieldValue = number | string | boolean | string[] | null
type FieldType = 'number' | 'select' | 'boolean' | 'text' | 'secret' | 'list' | 'multiselect'
export type FieldGroup = 'basic' | 'advanced'

interface FieldOption {
  value: string
  label: string
}

export interface Field {
  key: string
  label: string
  type: FieldType
  default: FieldValue
  group: FieldGroup
  options?: FieldOption[]
  min?: number
  max?: number
  step?: number
  unit?: string
  help?: string
  show_if?: { key: string; equals: string }
  nullable?: boolean
}

export interface SettingsSection {
  id: string
  label: string
  description: string
  /** null = shared across venues (e.g. Telegram). */
  venue: VenueId | null
  fields: Field[]
}

export interface SettingsView {
  sections: SettingsSection[]
  values: Record<string, FieldValue>
}

export interface Venue {
  id: VenueId
  label: string
  wallet_label: string
  wallet_placeholder: string
  close_label: string
  sizing_fields: Field[]
}

export interface Meta {
  name: string
  mode: Mode
  version: string
  venues: Venue[]
}

export interface Feed {
  id: string
  label: string
  connected: boolean
  last_event_ms: number | null
  reconnects: number
}

export interface VenueStatus {
  id: VenueId
  label: string
  /** The venue currently selected for copying. */
  active: boolean
  balance_usd: number | null
  open_usd: number
  cap_usd: number | null
  positions: number
}

export interface Counts {
  detected: number
  copied: number
  failed: number
  skipped: number
}

export interface Latency {
  last_ms: number | null
  avg_ms: number | null
  p95_ms: number | null
  recent: { ts_ms: number; total_ms: number }[]
}

export type CopyState = 'stopped' | 'starting' | 'running' | 'stopping'

interface CopyStatus {
  venue: VenueId
  venue_label: string
  state: CopyState
  running: boolean
  started_at_ms: number | null
}

export interface Status {
  mode: Mode
  copy: CopyStatus
  /** Blocks new entries (exits are still mirrored); only matters while running. */
  paused: boolean
  started_at_ms: number
  uptime_s: number
  feeds: Feed[]
  venues: VenueStatus[]
  counts: Counts
  latency: Latency
}

interface TargetStats extends Counts {
  open_usd: number
  positions: number
  last_activity_ms: number | null
}

export interface Target {
  id: string
  name: string
  venue: VenueId
  wallet: string
  enabled: boolean
  copy_closes: boolean
  sizing: Record<string, FieldValue>
  stats: TargetStats
}

export interface TargetInput {
  name: string
  venue: VenueId
  wallet: string
  enabled: boolean
  copy_closes: boolean
  sizing: Record<string, FieldValue>
}

export interface Position {
  id: string
  venue: string
  target_id: string
  target_name: string
  label: string
  sublabel: string | null
  side: string
  size: number
  entry_price: number | null
  value_usd: number
  pnl_usd: number | null
  opened_at_ms: number
  url: string | null
}

export interface Order {
  id: string
  venue: string
  target_id: string
  target_name: string
  label: string
  side: string
  price: number
  size: number
  filled: number
  placed_at_ms: number
  expires_at_ms: number | null
}

export type ActivityKind =
  | 'target_fill'
  | 'copy_success'
  | 'copy_failure'
  | 'copy_skipped'
  | 'order_update'
  | 'system'
  | 'error'

export type ActivityLevel = 'info' | 'success' | 'warning' | 'error'

export interface Activity {
  id: number
  ts_ms: number
  venue: string
  target_id: string | null
  target_name: string | null
  kind: ActivityKind
  level: ActivityLevel
  summary: string
  data: Record<string, unknown>
}

export interface ActivityPage {
  items: Activity[]
  next_before_id: number | null
}

export interface ActivityFilters {
  venue?: string
  target_id?: string
  kind?: string
}

export type WsMessage = { type: 'activity'; item: Activity } | { type: 'status'; status: Status }

export const ACTIVITY_KINDS: { value: ActivityKind; label: string }[] = [
  { value: 'target_fill', label: 'Target fill' },
  { value: 'copy_success', label: 'Copy success' },
  { value: 'copy_failure', label: 'Copy failure' },
  { value: 'copy_skipped', label: 'Copy skipped' },
  { value: 'order_update', label: 'Order update' },
  { value: 'system', label: 'System' },
  { value: 'error', label: 'Error' },
]
