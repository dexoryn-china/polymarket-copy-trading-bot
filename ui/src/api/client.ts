import { getToken, markAuthRequired } from './auth'
import type {
  ActivityFilters,
  ActivityPage,
  FieldValue,
  Meta,
  Order,
  Position,
  SettingsView,
  Status,
  Target,
  TargetInput,
  VenueId,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function buildQuery(params: object): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params) as [string, unknown][]) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const s = qs.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Unable to reach the bot API')
  }

  if (res.status === 401) markAuthRequired()

  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`.trim()
    try {
      const data = (await res.json()) as { error?: unknown }
      if (typeof data.error === 'string' && data.error) message = data.error
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  meta: () => request<Meta>('GET', '/meta'),
  status: () => request<Status>('GET', '/status'),
  setPaused: (paused: boolean) => request<Status>('POST', '/pause', { paused }),
  selectVenue: (venue: VenueId) => request<Status>('PUT', '/copy', { venue }),
  startCopy: (venue?: VenueId) => request<Status>('POST', '/copy/start', venue ? { venue } : {}),
  stopCopy: () => request<Status>('POST', '/copy/stop'),

  targets: () => request<Target[]>('GET', '/targets'),
  createTarget: (input: TargetInput) => request<Target>('POST', '/targets', input),
  updateTarget: (id: string, input: Partial<TargetInput>) =>
    request<Target>('PUT', `/targets/${encodeURIComponent(id)}`, input),
  setTargetEnabled: (id: string, enabled: boolean) =>
    request<Target>('PATCH', `/targets/${encodeURIComponent(id)}`, { enabled }),
  deleteTarget: (id: string) => request<void>('DELETE', `/targets/${encodeURIComponent(id)}`),

  getSettings: () => request<SettingsView>('GET', '/settings'),
  updateSettings: (values: Record<string, FieldValue>) => request<SettingsView>('PUT', '/settings', { values }),

  positions: (params: { venue?: string; target_id?: string } = {}) =>
    request<Position[]>('GET', `/positions${buildQuery(params)}`),
  orders: () => request<Order[]>('GET', '/orders'),
  activity: (params: ActivityFilters & { limit?: number; before_id?: number | null } = {}) =>
    request<ActivityPage>('GET', `/activity${buildQuery(params)}`),
}

export function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = getToken()
  const qs = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}//${window.location.host}/api/ws${qs}`
}
