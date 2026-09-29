import { useState } from 'react'
import { Activity as ActivityIcon, FilterX } from 'lucide-react'
import { useActivity, useMeta, useTargets } from '../api/queries'
import { ACTIVITY_KINDS, type ActivityFilters } from '../api/types'
import { ActivityItem } from '../components/ActivityItem'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState, ErrorState } from '../components/ui/EmptyState'
import { FilterSelect } from '../components/ui/Form'
import { SkeletonRows } from '../components/ui/Skeleton'
import { useNow } from '../lib/useNow'

export function ActivityPage() {
  const meta = useMeta()
  const targets = useTargets()
  const now = useNow(5000)
  const [venue, setVenue] = useState('')
  const [targetId, setTargetId] = useState('')
  const [kind, setKind] = useState('')

  const filters: ActivityFilters = {}
  if (venue) filters.venue = venue
  if (targetId) filters.target_id = targetId
  if (kind) filters.kind = kind

  const activity = useActivity(filters)
  const items = activity.data?.pages.flatMap((p) => p.items) ?? []
  const hasFilters = Boolean(venue || targetId || kind)
  const targetOptions = (targets.data ?? [])
    .filter((t) => !venue || t.venue === venue)
    .map((t) => ({ value: t.id, label: t.name }))

  const clear = () => {
    setVenue('')
    setTargetId('')
    setKind('')
  }

  return (
    <>
      <PageHeader title="Activity" description="Everything the bot has seen and done, newest first." />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <FilterSelect
          label="Venue"
          value={venue}
          onChange={(v) => {
            setVenue(v)
            setTargetId('')
          }}
          allLabel="All venues"
          options={(meta.data?.venues ?? []).map((v) => ({ value: v.id, label: v.label }))}
        />
        <FilterSelect label="Target" value={targetId} onChange={setTargetId} allLabel="All targets" options={targetOptions} />
        <FilterSelect label="Kind" value={kind} onChange={setKind} allLabel="All kinds" options={ACTIVITY_KINDS} />
        {hasFilters && (
          <Button size="sm" variant="ghost" icon={<FilterX className="size-4" aria-hidden />} onClick={clear}>
            Clear filters
          </Button>
        )}
      </div>

      <Card>
        {activity.isPending ? (
          <SkeletonRows rows={8} />
        ) : activity.isError ? (
          <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<ActivityIcon className="size-5" aria-hidden />}
            title={hasFilters ? 'No matching activity' : 'No activity yet'}
            description={hasFilters ? 'Try widening your filters.' : 'Events will appear here as the bot runs.'}
          />
        ) : (
          <>
            <div className="divide-y divide-zinc-800/70">
              {items.map((item) => (
                <ActivityItem key={item.id} item={item} now={now} />
              ))}
            </div>
            <div className="flex justify-center border-t border-zinc-800 p-3">
              {activity.hasNextPage ? (
                <Button size="sm" loading={activity.isFetchingNextPage} onClick={() => activity.fetchNextPage()}>
                  Load more
                </Button>
              ) : (
                <p className="text-xs text-zinc-600">End of history</p>
              )}
            </div>
          </>
        )}
      </Card>
    </>
  )
}
