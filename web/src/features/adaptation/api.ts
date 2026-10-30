import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import { plansKeys } from '../plans/api'
import type { AdaptationItem, BeatAction, BeatDecisionResult, MainKind } from './types'

export const adaptationKeys = {
  all: (seriesId: string) => ['series', seriesId, 'adaptations'] as const,
}

const POLL_MS = 3000

/** Adaptation options; refreshes while a trailer, teaser or cut is being generated. */
export function useAdaptations(seriesId: string) {
  return useQuery({
    queryKey: adaptationKeys.all(seriesId),
    queryFn: ({ signal }) => api.get<{ items: AdaptationItem[] }>(`/series/${seriesId}/adaptations`, signal),
    select: (data) => data.items,
    refetchInterval: (query) => (query.state.data?.items.some((i) => i.status === 'generating') ? POLL_MS : false),
  })
}

function useRefresh(seriesId: string) {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: adaptationKeys.all(seriesId) })
    void client.invalidateQueries({ queryKey: plansKeys.all(seriesId) })
  }
}

export function useBeatDecision(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({
    mutationFn: (input: { unit: number; beat: number | null; action: BeatAction }) =>
      api.put<BeatDecisionResult>(`/series/${seriesId}/adaptations/concentrated/beats`, input),
    onSuccess: refresh,
  })
}

export function useSelectMain(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({
    mutationFn: (main: MainKind) => api.put(`/series/${seriesId}/adaptation-selection`, { main }),
    onSuccess: refresh,
  })
}

export function useGenerate(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({
    mutationFn: (input: { kind: 'concentrated' | 'trailer' | 'teaser'; target_seconds?: number }) =>
      api.post(`/series/${seriesId}/adaptations/${input.kind}/generate`, { target_seconds: input.target_seconds }),
    onSuccess: refresh,
  })
}
