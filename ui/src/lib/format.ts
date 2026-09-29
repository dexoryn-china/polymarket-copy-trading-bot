const DASH = '—'

const usdFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const sharesFmt = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const priceFmt = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
})

const intFmt = new Intl.NumberFormat('en-US')

export function formatUsd(value: number | null | undefined): string {
  return value == null ? DASH : usdFmt.format(value)
}

export function formatSignedUsd(value: number | null | undefined): string {
  if (value == null) return DASH
  const s = usdFmt.format(Math.abs(value))
  if (value > 0) return `+${s}`
  if (value < 0) return `-${s}`
  return s
}

export function formatShares(value: number | null | undefined): string {
  return value == null ? DASH : sharesFmt.format(value)
}

export function formatInt(value: number | null | undefined): string {
  return value == null ? DASH : intFmt.format(value)
}

export function formatPrice(value: number | null | undefined, venue?: string): string {
  if (value == null) return DASH
  if (venue === 'predictions') return `${(value * 100).toFixed(1)}¢`
  return priceFmt.format(value)
}

export function formatMs(value: number | null | undefined): string {
  return value == null ? DASH : `${Math.round(value)} ms`
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? DASH : `${value.toFixed(digits)}%`
}

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

export function formatRelative(ms: number | null | undefined, now = Date.now()): string {
  if (ms == null) return DASH
  const diff = Math.round((now - ms) / 1000)
  const abs = Math.abs(diff)
  let text: string
  if (abs < 5) return 'just now'
  if (abs < 60) text = `${abs}s`
  else if (abs < 3600) text = `${Math.floor(abs / 60)}m`
  else if (abs < 86400) text = `${Math.floor(abs / 3600)}h`
  else text = `${Math.floor(abs / 86400)}d`
  return diff >= 0 ? `${text} ago` : `in ${text}`
}

export function formatAge(ms: number, now = Date.now()): string {
  return formatDuration((now - ms) / 1000)
}

export function formatAbsolute(ms: number | null | undefined): string {
  if (ms == null) return DASH
  return new Date(ms).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function shortenAddress(address: string, chars = 4): string {
  if (address.length <= chars * 2 + 3) return address
  return `${address.slice(0, chars + 2)}…${address.slice(-chars)}`
}

export function copyRate(copied: number, detected: number): number | null {
  return detected > 0 ? (copied / detected) * 100 : null
}

export function humanizeKey(key: string): string {
  const s = key.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
