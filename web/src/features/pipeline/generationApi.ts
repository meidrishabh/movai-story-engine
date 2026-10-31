import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import { pipelineKeys } from './api'
import type { GenerationOverview } from './types'

const overviewKey = (seriesId: string) => ['series', seriesId, 'generation-overview'] as const

/** Spend, request counts and per-episode budgets; refreshes now and then because requests finish in the background. */
export function useGenerationOverview(seriesId: string) {
  return useQuery({
    queryKey: overviewKey(seriesId),
    queryFn: ({ signal }) => api.get<GenerationOverview>(`/series/${seriesId}/generation/overview`, signal),
    refetchInterval: 10000,
  })
}

/** Pause (true) or resume (false) everything queued for the series. */
export function useSeriesPause(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (paused: boolean) => api.post(`/series/${seriesId}/generation/${paused ? 'pause' : 'resume'}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: overviewKey(seriesId) })
      void client.invalidateQueries({ queryKey: pipelineKeys.status(seriesId) })
    },
  })
}
