import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Listed } from '../../shared/api/client'
import type { EpisodePlan } from './types'

export const plansKeys = {
  all: (seriesId: string) => ['series', seriesId, 'plans'] as const,
}

const POLL_MS = 3000

export function usePlans(seriesId: string, polling: boolean) {
  return useQuery({
    queryKey: plansKeys.all(seriesId),
    queryFn: ({ signal }) => api.get<Listed<EpisodePlan>>(`/series/${seriesId}/episode-plans`, signal),
    select: (data) => data.items,
    refetchInterval: polling ? POLL_MS : false,
  })
}

function useRefresh(seriesId: string) {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: plansKeys.all(seriesId) })
}

export function useApprovePlan(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({ mutationFn: (planId: string) => api.post(`/episode-plans/${planId}/approve`), onSuccess: refresh })
}

export function useApproveAll(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({ mutationFn: () => api.post(`/series/${seriesId}/episode-plans/approve-all`), onSuccess: refresh })
}

export function useRejectPlan(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({
    mutationFn: (input: { planId: string; note: string }) => api.post(`/episode-plans/${input.planId}/reject`, { review_note: input.note }),
    onSuccess: refresh,
  })
}

/** Queue a re-plan for the selected adaptation. The plans list is polled until the job replaces the drafts. */
export function useReplan(seriesId: string) {
  const refresh = useRefresh(seriesId)
  return useMutation({ mutationFn: () => api.post(`/series/${seriesId}/episode-plans/generate`), onSuccess: refresh })
}
