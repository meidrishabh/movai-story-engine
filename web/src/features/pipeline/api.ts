import { useQuery } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import { isRunActive } from './stages'
import type { Pipeline } from './types'

export const pipelineKeys = {
  status: (seriesId: string) => ['series', seriesId, 'pipeline'] as const,
}

const POLL_MS = 3000

/** Pipeline status; refreshes every few seconds while a run is queued or running. */
export function usePipeline(seriesId: string) {
  return useQuery({
    queryKey: pipelineKeys.status(seriesId),
    queryFn: ({ signal }) => api.get<Pipeline>(`/series/${seriesId}/pipeline`, signal),
    refetchInterval: (query) => (isRunActive(query.state.data?.analysis_run) ? POLL_MS : false),
  })
}
