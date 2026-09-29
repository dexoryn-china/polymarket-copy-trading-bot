import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query'
import { ApiError, api } from './client'
import type {
  Activity,
  ActivityFilters,
  ActivityPage,
  SettingsView,
  Status,
  Target,
  TargetInput,
  VenueId,
} from './types'

const ACTIVITY_PAGE_SIZE = 100

export const queryKeys = {
  meta: ['meta'] as const,
  status: ['status'] as const,
  targets: ['targets'] as const,
  positionsAll: ['positions'] as const,
  positions: (f: { venue?: string; target_id?: string }) => ['positions', f] as const,
  orders: ['orders'] as const,
  activityAll: ['activity'] as const,
  activity: (f: ActivityFilters) => ['activity', f] as const,
  settings: ['settings'] as const,
}

export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

export function useMeta() {
  return useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, staleTime: Infinity })
}

export function useStatus() {
  return useQuery({ queryKey: queryKeys.status, queryFn: api.status, refetchInterval: 10_000 })
}

export function useTargets() {
  return useQuery({ queryKey: queryKeys.targets, queryFn: api.targets })
}

export function usePositions(filters: { venue?: string; target_id?: string }, enabled = true) {
  return useQuery({
    queryKey: queryKeys.positions(filters),
    queryFn: () => api.positions(filters),
    refetchInterval: 15_000,
    enabled,
  })
}

export function useOrders() {
  return useQuery({ queryKey: queryKeys.orders, queryFn: api.orders, refetchInterval: 15_000 })
}

export function useActivity(filters: ActivityFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.activity(filters),
    queryFn: ({ pageParam }) =>
      api.activity({ ...filters, limit: ACTIVITY_PAGE_SIZE, before_id: pageParam }),
    initialPageParam: null as number | null,
    getNextPageParam: (last: ActivityPage) => last.next_before_id,
  })
}

function matchesFilters(item: Activity, f: ActivityFilters): boolean {
  if (f.venue && item.venue !== f.venue) return false
  if (f.target_id && item.target_id !== f.target_id) return false
  if (f.kind && item.kind !== f.kind) return false
  return true
}

export function prependActivity(qc: QueryClient, item: Activity) {
  const queries = qc.getQueryCache().findAll({ queryKey: queryKeys.activityAll })
  for (const query of queries) {
    const filters = (query.queryKey[1] ?? {}) as ActivityFilters
    if (!matchesFilters(item, filters)) continue
    qc.setQueryData<InfiniteData<ActivityPage, number | null>>(query.queryKey, (data) => {
      if (!data || data.pages.length === 0) return data
      const [first, ...rest] = data.pages
      if (first.items.some((a) => a.id === item.id)) return data
      return { ...data, pages: [{ ...first, items: [item, ...first.items] }, ...rest] }
    })
  }
}

export function usePause() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.setPaused,
    onSuccess: (status) => qc.setQueryData(queryKeys.status, status),
  })
}

export const copyMutationKeys = {
  select: ['copy', 'select'] as const,
  start: ['copy', 'start'] as const,
  stop: ['copy', 'stop'] as const,
}

/** Copy control calls return the new status; on failure resync, since another tab may have changed it. */
function useCopyMutation<V>(mutationKey: readonly string[], mutationFn: (vars: V) => Promise<Status>) {
  const qc = useQueryClient()
  return useMutation({
    mutationKey,
    mutationFn,
    onSuccess: (status) => qc.setQueryData(queryKeys.status, status),
    onError: () => qc.invalidateQueries({ queryKey: queryKeys.status }),
  })
}

export function useSelectVenue() {
  return useCopyMutation<VenueId>(copyMutationKeys.select, api.selectVenue)
}

/** Starts the currently selected venue. */
export function useStartCopy() {
  return useCopyMutation<void>(copyMutationKeys.start, () => api.startCopy())
}

export function useStopCopy() {
  return useCopyMutation<void>(copyMutationKeys.stop, () => api.stopCopy())
}

export function useSaveTarget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id?: string; input: TargetInput }) =>
      id ? api.updateTarget(id, input) : api.createTarget(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.targets }),
  })
}

/** Partial update (e.g. `{ sizing: { key: value } }` — the server merges sizing). */
export function useUpdateTarget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<TargetInput> }) => api.updateTarget(id, input),
    onSuccess: (target) =>
      qc.setQueryData<Target[]>(queryKeys.targets, (list) =>
        list?.map((t) => (t.id === target.id ? target : t)),
      ),
  })
}

export function useToggleTarget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.setTargetEnabled(id, enabled),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: queryKeys.targets })
      const previous = qc.getQueryData<Target[]>(queryKeys.targets)
      qc.setQueryData<Target[]>(queryKeys.targets, (list) =>
        list?.map((t) => (t.id === id ? { ...t, enabled } : t)),
      )
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.targets, ctx.previous)
    },
    onSuccess: (target) =>
      qc.setQueryData<Target[]>(queryKeys.targets, (list) =>
        list?.map((t) => (t.id === target.id ? target : t)),
      ),
  })
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: api.getSettings })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (view: SettingsView) => {
      qc.setQueryData(queryKeys.settings, view)
      qc.invalidateQueries({ queryKey: queryKeys.settings })
      qc.invalidateQueries({ queryKey: queryKeys.status })
    },
  })
}

export function useDeleteTarget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteTarget,
    onSuccess: (_data, id) => {
      qc.setQueryData<Target[]>(queryKeys.targets, (list) => list?.filter((t) => t.id !== id))
      qc.invalidateQueries({ queryKey: queryKeys.targets })
    },
  })
}
