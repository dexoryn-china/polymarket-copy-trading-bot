import { useState, type FormEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, KeyRound, Server } from 'lucide-react'
import { setToken, useToken } from '../../api/auth'
import { useMeta, useStatus } from '../../api/queries'
import { formatDuration } from '../../lib/format'
import { ConnectionIndicator, ModeBadge } from '../StatusBits'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { FormField, Input } from '../ui/Form'
import { Skeleton } from '../ui/Skeleton'
import { useToast } from '../ui/toast-context'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <dt className="text-sm text-zinc-400">{label}</dt>
      <dd className="text-right text-sm text-zinc-200">{children}</dd>
    </div>
  )
}

export function BotInfoCard() {
  const meta = useMeta()
  const status = useStatus()

  const apiState = status.isError ? (
    <Badge tone="danger" title={status.error.message}>
      Unreachable
    </Badge>
  ) : status.isSuccess ? (
    <Badge tone="success">Connected</Badge>
  ) : (
    <Badge tone="warning">Checking…</Badge>
  )

  return (
    <Card>
      <CardHeader icon={<Server className="size-4" aria-hidden />} title="Bot" subtitle={meta.data?.name} />
      <CardBody className="py-2">
        <dl className="divide-y divide-zinc-800/70">
          <Row label="API">{apiState}</Row>
          <Row label="Realtime">
            <ConnectionIndicator />
          </Row>
          <Row label="Mode">{meta.data ? <ModeBadge mode={meta.data.mode} /> : <Skeleton className="h-5 w-16" />}</Row>
          <Row label="Version">
            {meta.data ? <span className="font-mono text-xs">{meta.data.version}</span> : <Skeleton className="h-5 w-16" />}
          </Row>
          <Row label="Uptime">{status.data ? formatDuration(status.data.uptime_s) : '—'}</Row>
          <Row label="Copying venue">
            {status.data ? (
              <Badge tone={status.data.copy.running ? 'success' : 'neutral'}>
                {status.data.copy.venue_label}
                {!status.data.copy.running && ' (stopped)'}
              </Badge>
            ) : (
              '—'
            )}
          </Row>
        </dl>
      </CardBody>
    </Card>
  )
}

export function TokenCard() {
  const token = useToken()
  const qc = useQueryClient()
  const toast = useToast()
  const [value, setValue] = useState(token)
  const [reveal, setReveal] = useState(false)

  const save = (e: FormEvent) => {
    e.preventDefault()
    setToken(value)
    qc.invalidateQueries()
    toast({ title: value.trim() ? 'Token saved' : 'Token cleared', variant: 'success' })
  }

  return (
    <Card>
      <CardHeader
        icon={<KeyRound className="size-4" aria-hidden />}
        title="Access token"
        subtitle="Stored in this browser only"
        actions={token ? <Badge tone="success">Set</Badge> : <Badge>Not set</Badge>}
      />
      <CardBody>
        <form onSubmit={save} className="space-y-4">
          <FormField
            label="Bearer token"
            htmlFor="settings-token"
            help="Only required if the bot is configured with a dashboard token."
          >
            <div className="relative">
              <Input
                id="settings-token"
                type={reveal ? 'text' : 'password'}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                className="pr-10 font-mono"
                placeholder="No token"
              />
              <button
                type="button"
                onClick={() => setReveal((r) => !r)}
                aria-label={reveal ? 'Hide token' : 'Show token'}
                className="absolute inset-y-0 right-2 my-auto h-fit rounded p-1 text-zinc-500 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500"
              >
                {reveal ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
              </button>
            </div>
          </FormField>
          <div className="flex justify-end gap-2">
            {token && (
              <Button
                variant="ghost"
                onClick={() => {
                  setValue('')
                  setToken('')
                  qc.invalidateQueries()
                  toast({ title: 'Token cleared', variant: 'info' })
                }}
              >
                Clear
              </Button>
            )}
            <Button type="submit" variant="primary" disabled={value.trim() === token}>
              Save
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  )
}
