import { Bell, ChartLine, SlidersHorizontal, TrendingUp, type LucideIcon } from 'lucide-react'
import type { Field, FieldGroup, SettingsSection } from '../../api/types'
import { visibleFields } from '../../lib/schema'
import type { SettingsForm } from '../../lib/useSettingsForm'
import { SchemaField } from '../SchemaField'
import { Badge } from '../ui/Badge'
import { Card, CardBody, CardHeader } from '../ui/Card'

const SECTION_ICONS: Record<string, LucideIcon> = {
  trading: ChartLine,
  perps: TrendingUp,
  notifications: Bell,
}

const WIDE_TYPES = new Set<Field['type']>(['multiselect', 'list', 'secret'])

interface SettingsSectionCardProps {
  section: SettingsSection
  group: FieldGroup
  form: SettingsForm
}

export function SettingsSectionCard({ section, group, form }: SettingsSectionCardProps) {
  const inGroup = section.fields.filter((f) => f.group === group)
  if (inGroup.length === 0) return null

  const fields = visibleFields(inGroup, form.values)
  const edited = inGroup.filter((f) => form.dirtyKeys.has(f.key)).length
  const Icon = SECTION_ICONS[section.id] ?? SlidersHorizontal

  return (
    <Card>
      <CardHeader
        icon={<Icon className="size-4" aria-hidden />}
        title={section.label}
        actions={edited > 0 && <Badge tone="accent">{edited} edited</Badge>}
      />
      <CardBody className="space-y-5">
        {section.description && <p className="text-xs text-zinc-500">{section.description}</p>}
        <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2">
          {fields.map((f) => (
            <div key={f.key} className={WIDE_TYPES.has(f.type) ? 'sm:col-span-2' : undefined}>
              <SchemaField
                id={`setting-${f.key}`}
                field={f}
                value={form.values[f.key]}
                onChange={(v) => form.setValue(f.key, v)}
                error={form.errors[f.key]}
              />
            </div>
          ))}
        </div>
        {fields.length === 0 && (
          <p className="text-sm text-zinc-500">Nothing to configure with the current selections.</p>
        )}
      </CardBody>
    </Card>
  )
}
