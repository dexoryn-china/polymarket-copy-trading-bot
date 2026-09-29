import { useToggleTarget } from '../api/queries'
import type { Target } from '../api/types'
import { Switch } from './ui/Switch'
import { useToast } from './ui/toast-context'

export function TargetSwitch({ target, size = 'md' }: { target: Target; size?: 'sm' | 'md' }) {
  const toggle = useToggleTarget()
  const toast = useToast()
  return (
    <Switch
      size={size}
      checked={target.enabled}
      label={`${target.enabled ? 'Disable' : 'Enable'} copying ${target.name}`}
      onChange={(enabled) =>
        toggle.mutate(
          { id: target.id, enabled },
          {
            onError: (err) =>
              toast({
                title: `Couldn't ${enabled ? 'enable' : 'disable'} ${target.name}`,
                description: err.message,
                variant: 'error',
              }),
          },
        )
      }
    />
  )
}
