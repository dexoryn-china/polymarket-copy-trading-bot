import { useEffect, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useToast, type ToastVariant } from '../components/ui/toast-context'
import { useToken } from './auth'
import { wsUrl } from './client'
import { prependActivity, queryKeys } from './queries'
import type { Activity, ActivityKind, WsMessage } from './types'

export type WsState = 'connecting' | 'open' | 'closed'

let state: WsState = 'connecting'
const listeners = new Set<() => void>()

function setState(next: WsState) {
  if (state === next) return
  state = next
  listeners.forEach((l) => l())
}

export function useWsState(): WsState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => state,
  )
}

const TOAST_KINDS: Partial<Record<ActivityKind, { title: string; variant: ToastVariant }>> = {
  copy_success: { title: 'Trade copied', variant: 'success' },
  copy_failure: { title: 'Copy failed', variant: 'error' },
  error: { title: 'Error', variant: 'error' },
}

const INVALIDATE_DEBOUNCE_MS = 500
const MAX_BACKOFF_MS = 15_000

export function useLiveSocket() {
  const qc = useQueryClient()
  const toast = useToast()
  const token = useToken()

  useEffect(() => {
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let invalidateTimer: number | undefined
    let attempt = 0
    let disposed = false

    const scheduleInvalidate = () => {
      window.clearTimeout(invalidateTimer)
      invalidateTimer = window.setTimeout(() => {
        qc.invalidateQueries({ queryKey: queryKeys.targets })
        qc.invalidateQueries({ queryKey: queryKeys.positionsAll })
        qc.invalidateQueries({ queryKey: queryKeys.orders })
      }, INVALIDATE_DEBOUNCE_MS)
    }

    const onActivity = (item: Activity) => {
      prependActivity(qc, item)
      scheduleInvalidate()
      const t = TOAST_KINDS[item.kind]
      if (t) {
        const who = item.target_name ? `${item.target_name} · ` : ''
        toast({ title: t.title, description: `${who}${item.summary}`, variant: t.variant })
      }
    }

    const connect = () => {
      if (disposed) return
      setState('connecting')
      socket = new WebSocket(wsUrl())

      socket.onopen = () => {
        attempt = 0
        setState('open')
      }

      socket.onmessage = (event: MessageEvent) => {
        let msg: WsMessage
        try {
          msg = JSON.parse(String(event.data)) as WsMessage
        } catch {
          return
        }
        if (msg.type === 'activity') onActivity(msg.item)
        else if (msg.type === 'status') qc.setQueryData(queryKeys.status, msg.status)
      }

      socket.onclose = () => {
        socket = null
        if (disposed) return
        setState('closed')
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt) + Math.random() * 500
        attempt += 1
        retryTimer = window.setTimeout(connect, delay)
      }

      socket.onerror = () => socket?.close()
    }

    connect()

    return () => {
      disposed = true
      window.clearTimeout(retryTimer)
      window.clearTimeout(invalidateTimer)
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [qc, toast, token])
}
