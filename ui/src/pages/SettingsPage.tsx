import { useMemo, useState } from 'react'
import { Info } from 'lucide-react'
import { useMeta, useSettings, useUpdateSettings } from '../api/queries'
import type { FieldGroup, SettingsView, Target } from '../api/types'
import { useCopy } from '../api/useCopy'
import { PageHeader } from '../components/PageHeader'
import { BotInfoCard, TokenCard } from '../components/settings/AboutCards'
import { SaveBar } from '../components/settings/SaveBar'
import { SettingsSectionCard } from '../components/settings/SettingsSectionCard'
import { TargetWalletsCard } from '../components/settings/TargetWalletsCard'
import { TargetFormDrawer } from '../components/TargetFormDrawer'
import { Card } from '../components/ui/Card'
import { ErrorState } from '../components/ui/EmptyState'
import { Skeleton } from '../components/ui/Skeleton'
import { Tabs } from '../components/ui/Tabs'
import { useToast } from '../components/ui/toast-context'
import { useSettingsForm, type SettingsForm } from '../lib/useSettingsForm'

export function SettingsPage() {
  const meta = useMeta()
  const settings = useSettings()
  const update = useUpdateSettings()
  const toast = useToast()
  const { copy, activeVenue } = useCopy()
  const venue = copy?.venue
  // The form only tracks the visible sections, so edits hidden by a venue switch are never saved.
  const view = useMemo<SettingsView | undefined>(
    () =>
      settings.data && venue
        ? {
            ...settings.data,
            sections: settings.data.sections.filter((s) => s.venue === null || s.venue === venue),
          }
        : undefined,
    [settings.data, venue],
  )
  const form = useSettingsForm(view)
  const [tab, setTab] = useState<FieldGroup>('basic')
  const [drawer, setDrawer] = useState<{ target: Target | null } | null>(null)

  const labelOf = (key: string) => form.fields.find((f) => f.key === key)?.label ?? key
  const dirtyIn = (group: FieldGroup) => form.fields.filter((f) => f.group === group && form.dirtyKeys.has(f.key)).length

  const save = () => {
    const invalid = Object.keys(form.errors)
    if (invalid.length > 0) {
      toast({ title: 'Fix invalid settings', description: invalid.map(labelOf).join(', '), variant: 'error' })
      return
    }
    const changes = form.changes()
    if (Object.keys(changes).length === 0) {
      form.reset()
      return
    }
    update.mutate(changes, {
      onSuccess: () => {
        form.reset()
        toast({ title: 'Settings saved', description: 'Changes are live.', variant: 'success' })
      },
      onError: (err) => toast({ title: "Couldn't save settings", description: err.message, variant: 'error' }),
    })
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Copy-trading settings apply live. Mode, API keys and the web server stay in config.yaml."
      />

      {copy && (
        <p className="mb-4 flex items-center gap-2 text-sm text-zinc-400">
          <Info className="size-4 shrink-0 text-zinc-500" aria-hidden />
          <span>
            Showing settings for <span className="font-medium text-zinc-200">{activeVenue?.label ?? copy.venue_label}</span>{' '}
            — switch venue from the copy control.
          </span>
        </p>
      )}

      <div className="mb-5">
        <Tabs
          label="Settings level"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'basic', label: 'Basic', count: dirtyIn('basic') || undefined },
            { value: 'advanced', label: 'Advanced', count: dirtyIn('advanced') || undefined },
          ]}
        />
      </div>

      {tab === 'basic' ? (
        <div className="space-y-4">
          <TargetWalletsCard
            onAdd={() => setDrawer({ target: null })}
            onEdit={(target) => setDrawer({ target })}
          />
          <SectionCards group="basic" settings={settings} view={view} form={form} />

          <section aria-labelledby="settings-about" className="pt-4">
            <h2 id="settings-about" className="mb-3 text-sm font-semibold text-zinc-200">
              About
            </h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <TokenCard />
              <BotInfoCard />
            </div>
          </section>
        </div>
      ) : (
        <div className="space-y-4">
          <SectionCards group="advanced" settings={settings} view={view} form={form} />
        </div>
      )}

      <SaveBar count={form.dirtyKeys.size} saving={update.isPending} onSave={save} onDiscard={form.reset} />

      {meta.data && venue && (
        <TargetFormDrawer
          open={drawer !== null}
          onClose={() => setDrawer(null)}
          meta={meta.data}
          venueId={venue}
          target={drawer?.target}
        />
      )}
    </>
  )
}

interface SectionCardsProps {
  group: FieldGroup
  settings: ReturnType<typeof useSettings>
  /** Settings filtered to the active venue. */
  view: SettingsView | undefined
  form: SettingsForm
}

function SectionCards({ group, settings, view, form }: SectionCardsProps) {
  if (settings.isPending || (settings.isSuccess && !view)) {
    return (
      <>
        {Array.from({ length: 2 }, (_, i) => (
          <Skeleton key={i} className="h-48 rounded-xl" />
        ))}
      </>
    )
  }
  if (settings.isError) {
    return (
      <Card>
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      </Card>
    )
  }
  if (!view) return null
  return view.sections.map((s) => (
    <SettingsSectionCard key={s.id} section={s} group={group} form={form} />
  ))
}
