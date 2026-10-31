import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import type { GenerateAllResult, ReferenceOverview, RefTarget, TargetType } from './types'

export const referenceKey = (seriesId: string) => ['series', seriesId, 'references'] as const

const WORKING = ['queued', 'running']

function isWorking(data: ReferenceOverview | undefined): boolean {
  if (!data) return false
  const requests = [
    ...data.style_anchors,
    ...[...data.characters, ...data.places, ...data.objects].flatMap((t) => [
      ...t.views.map((v) => v.request),
      ...(t.costumes ?? []).flatMap((c) => c.views.map((v) => v.request)),
    ]),
  ]
  return requests.some((r) => r && WORKING.includes(r.status))
}

/** The gallery. Refreshes every few seconds while the job runner still has pictures to make. */
export function useReferences(seriesId: string) {
  return useQuery({
    queryKey: referenceKey(seriesId),
    queryFn: ({ signal }) => api.get<ReferenceOverview>(`/series/${seriesId}/references`, signal),
    refetchInterval: (query) => (isWorking(query.state.data) ? 3000 : false),
  })
}

export function useReferenceActions(seriesId: string) {
  const client = useQueryClient()
  const refresh = () => client.invalidateQueries({ queryKey: referenceKey(seriesId) })
  const options = { onSuccess: refresh }

  const generateAnchors = useMutation({
    mutationFn: (count: number) => api.post(`/series/${seriesId}/references/style-anchors/generate`, { count }),
    ...options,
  })
  const pickAnchor = useMutation({
    mutationFn: (requestId: string) => api.post(`/series/${seriesId}/references/style-anchors/${requestId}/pick`),
    ...options,
  })
  const generateAll = useMutation({
    mutationFn: () => api.post<GenerateAllResult>(`/series/${seriesId}/references/generate-all`),
    ...options,
  })
  const generate = useMutation({
    mutationFn: (v: { target: Pick<RefTarget, 'target_type' | 'target_id'>; views?: string[]; force?: boolean }) =>
      api.post(`/series/${seriesId}/references/generate`, {
        target_type: v.target.target_type as TargetType,
        target_id: v.target.target_id,
        views: v.views,
        force: v.force ?? false,
      }),
    ...options,
  })
  const review = useMutation({
    mutationFn: (v: { requestId: string; decision: 'approve' | 'reject'; note?: string }) =>
      api.post(`/generation-requests/${v.requestId}/review`, { decision: v.decision, note: v.note }),
    ...options,
  })
  const retry = useMutation({
    mutationFn: (requestId: string) => api.post(`/generation-requests/${requestId}/retry`),
    ...options,
  })
  const recheck = useMutation({
    mutationFn: (requestId: string) => api.post(`/generation-requests/${requestId}/consistency-check`),
    ...options,
  })
  return { generateAnchors, pickAnchor, generateAll, generate, review, retry, recheck }
}
