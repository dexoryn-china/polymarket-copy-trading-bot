import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { dismissAuthPrompt, getToken, setToken, useAuthRequired } from '../api/auth'
import { Button } from './ui/Button'
import { FormField, Input } from './ui/Form'
import { Modal } from './ui/Modal'

export function TokenPrompt() {
  const required = useAuthRequired()
  if (!required) return null
  return <TokenPromptDialog />
}

function TokenPromptDialog() {
  const qc = useQueryClient()
  const [value, setValue] = useState(getToken)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setToken(value)
    qc.invalidateQueries()
  }

  return (
    <Modal
      open
      onClose={dismissAuthPrompt}
      title={
        <span className="inline-flex items-center gap-2">
          <KeyRound className="size-4 text-indigo-300" aria-hidden />
          Authentication required
        </span>
      }
      description="The bot API rejected the request. Enter the dashboard access token."
    >
      <form onSubmit={submit} className="space-y-4">
        <FormField label="Access token" htmlFor="token-prompt">
          <Input
            id="token-prompt"
            type="password"
            autoComplete="current-password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste token"
          />
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={dismissAuthPrompt}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!value.trim()}>
            Save token
          </Button>
        </div>
      </form>
    </Modal>
  )
}
