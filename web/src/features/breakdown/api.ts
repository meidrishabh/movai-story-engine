import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Listed } from '../../shared/api/client'
import type { Breakdown, EpisodeBreakdownStatus } from './types'

const key = (seriesId: string) => ['series', seriesId, 'breakdown'] as const

const POLL_MS = 3000
const isActive = (e: EpisodeBreakdownStatus) => e.job_status === 'queued' || e.job_status === 'running'

/** Per-episode breakdown state; refreshes while any breakdown job is queued or running. */
export function useBreakdownOverview(seriesId: string) {
  return useQuery({
    queryKey: key(seriesId),
    queryFn: ({ signal }) => api.get<Listed<EpisodeBreakdownStatus>>(`/series/${seriesId}/breakdown`, signal),
    select: (data) => data.items,
    refetchInterval: (query) => (query.state.data?.items.some(isActive) ? POLL_MS : false),
  })
}

export function useEpisodeBreakdown(episodeId: string) {
  return useQuery({
    queryKey: ['episode', episodeId, 'breakdown'] as const,
    queryFn: ({ signal }) => api.get<Breakdown>(`/episodes/${episodeId}/breakdown`, signal),
  })
}

export function useQueueBreakdown(seriesId: string) {
  const client = useQueryClient()
  const refresh = () => {
    void client.invalidateQueries({ queryKey: key(seriesId) })
    void client.invalidateQueries({ queryKey: ['episode'] })
  }
  const all = useMutation({ mutationFn: () => api.post<{ queued: number }>(`/series/${seriesId}/breakdown`), onSuccess: refresh })
  const one = useMutation({ mutationFn: (episodeId: string) => api.post(`/episodes/${episodeId}/breakdown`), onSuccess: refresh })
  return { all, one }
}
