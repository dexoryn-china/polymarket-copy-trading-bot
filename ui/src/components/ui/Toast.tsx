import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { cn } from '../../lib/cn'
import { ToastContext, type ToastInput, type ToastVariant } from './toast-context'

interface ToastItem extends Required<Omit<ToastInput, 'description'>> {
  id: number
  description?: string
}

const MAX_TOASTS = 5

const styles: Record<ToastVariant, { icon: ReactNode; accent: string }> = {
  success: { icon: <CheckCircle2 className="size-5 text-emerald-400" aria-hidden />, accent: 'border-l-emerald-500' },
  error: { icon: <XCircle className="size-5 text-rose-400" aria-hidden />, accent: 'border-l-rose-500' },
  warning: { icon: <AlertTriangle className="size-5 text-amber-400" aria-hidden />, accent: 'border-l-amber-500' },
  info: { icon: <Info className="size-5 text-indigo-300" aria-hidden />, accent: 'border-l-indigo-500' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback((input: ToastInput) => {
    const item: ToastItem = {
      id: nextId.current++,
      variant: 'info',
      durationMs: input.variant === 'error' ? 8000 : 5000,
      ...input,
    }
    setToasts((list) => [...list, item].slice(-MAX_TOASTS))
  }, [])

  return (
    <ToastContext value={toast}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end"
      >
        {toasts.map((t) => (
          <ToastView key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext>
  )
}

function ToastView({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  const [hovered, setHovered] = useState(false)

  useEffect(() => {
    if (hovered) return
    const timer = window.setTimeout(() => onDismiss(toast.id), toast.durationMs)
    return () => window.clearTimeout(timer)
  }, [hovered, onDismiss, toast.id, toast.durationMs])

  const { icon, accent } = styles[toast.variant]
  return (
    <div
      role={toast.variant === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        'animate-pop-in pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border border-l-4 border-zinc-800 bg-zinc-900/95 p-3 shadow-xl backdrop-blur',
        accent,
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-zinc-100">{toast.title}</p>
        {toast.description && <p className="mt-0.5 break-words text-xs text-zinc-400">{toast.description}</p>}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="shrink-0 rounded p-0.5 text-zinc-500 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
      >
        <X className="size-4" aria-hidden />
      </button>
    </div>
  )
}
