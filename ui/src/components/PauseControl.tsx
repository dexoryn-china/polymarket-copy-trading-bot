import { useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { usePause } from '../api/queries'
import type { Status } from '../api/types'
import { Button, type ButtonProps } from './ui/Button'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { useToast } from './ui/toast-context'

interface PauseControlProps {
  status: Status | undefined
  size?: ButtonProps['size']
  className?: string
}

export function PauseControl({ status, size, className }: PauseControlProps) {
  const pause = usePause()
  const toast = useToast()
  const [confirming, setConfirming] = useState(false)

  const apply = (paused: boolean) =>
    pause.mutate(paused, {
      onSuccess: () => {
        setConfirming(false)
        toast({
          title: paused ? 'Copying paused' : 'Copying resumed',
          description: paused ? 'New entries are skipped; exits are still mirrored.' : undefined,
          variant: paused ? 'warning' : 'success',
        })
      },
      onError: (err) => toast({ title: 'Could not update pause state', description: err.message, variant: 'error' }),
    })

  if (!status) {
    return (
      <Button disabled size={size} className={className} icon={<Pause className="size-4" aria-hidden />}>
        Pause
      </Button>
    )
  }

  if (status.paused) {
    return (
      <Button
        variant="success"
        size={size}
        className={className}
        loading={pause.isPending}
        icon={<Play className="size-4" aria-hidden />}
        onClick={() => apply(false)}
      >
        Resume copying
      </Button>
    )
  }

  return (
    <>
      <Button
        variant="warning"
        size={size}
        className={className}
        loading={pause.isPending && !confirming}
        icon={<Pause className="size-4" aria-hidden />}
        onClick={() => (status.mode === 'real' ? setConfirming(true) : apply(true))}
      >
        Pause copying
      </Button>
      <ConfirmDialog
        open={confirming}
        tone="warning"
        title="Pause live copying?"
        message="The bot is running in LIVE mode. While paused, no new positions are opened, but your targets' exits are still mirrored."
        confirmLabel="Pause"
        loading={pause.isPending}
        onConfirm={() => apply(true)}
        onCancel={() => setConfirming(false)}
      />
    </>
  )
}
