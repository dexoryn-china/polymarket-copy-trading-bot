import { useIsMutating } from '@tanstack/react-query'
import { useToast } from '../components/ui/toast-context'
import { copyMutationKeys, useMeta, useSelectVenue, useStartCopy, useStatus, useStopCopy } from './queries'
import type { CopyState, VenueId } from './types'

/**
 * Single source for the copy lifecycle (venue, start/stop) so every page and
 * control agrees. Pending flags are global, so a Start pressed in one place
 * spins everywhere.
 */
export function useCopy() {
  const meta = useMeta()
  const status = useStatus()
  const toast = useToast()
  const selectVenue = useSelectVenue()
  const startCopy = useStartCopy()
  const stopCopy = useStopCopy()
  const selecting = useIsMutating({ mutationKey: copyMutationKeys.select }) > 0
  const starting = useIsMutating({ mutationKey: copyMutationKeys.start }) > 0
  const stopping = useIsMutating({ mutationKey: copyMutationKeys.stop }) > 0

  const copy = status.data?.copy
  const state: CopyState | undefined = starting ? 'starting' : stopping ? 'stopping' : copy?.state
  const venues = meta.data?.venues ?? []

  const select = (venue: VenueId) =>
    selectVenue.mutate(venue, {
      onError: (err) => toast({ title: "Couldn't switch venue", description: err.message, variant: 'error' }),
    })

  const start = () =>
    startCopy.mutate(undefined, {
      onSuccess: (s) => toast({ title: 'Copying started', description: s.copy.venue_label, variant: 'success' }),
      onError: (err) => toast({ title: "Couldn't start copying", description: err.message, variant: 'error' }),
    })

  const stop = () =>
    stopCopy.mutate(undefined, {
      onSuccess: (s) => toast({ title: 'Copying stopped', description: s.copy.venue_label, variant: 'info' }),
      onError: (err) => toast({ title: "Couldn't stop copying", description: err.message, variant: 'error' }),
    })

  return {
    status: status.data,
    copy,
    state,
    venues,
    /** Meta for the selected venue (labels, sizing fields). */
    activeVenue: venues.find((v) => v.id === copy?.venue),
    /** Live balance / exposure / position count for the selected venue. */
    venueStatus: status.data?.venues.find((v) => v.id === copy?.venue),
    select,
    start,
    stop,
    pending: selecting || state === 'starting' || state === 'stopping',
  }
}
