import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import type { Entities, EntityKind, ReviewStatus } from './types'

const key = (seriesId: string) => ['series', seriesId, 'entities'] as const

export function useEntities(seriesId: string) {
  return useQuery({ queryKey: key(seriesId), queryFn: ({ signal }) => api.get<Entities>(`/series/${seriesId}/entities`, signal) })
}

export function useUpdateEntity(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { kind: EntityKind; id: string; changes: { name?: string; description?: string; review_status?: ReviewStatus } }) =>
      api.patch(`/entities/${input.kind}/${input.id}`, input.changes),
    onSuccess: () => client.invalidateQueries({ queryKey: key(seriesId) }),
  })
}

export function useMergeEntity(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { kind: EntityKind; id: string; intoId: string }) =>
      api.post(`/entities/${input.kind}/${input.id}/merge`, { into_id: input.intoId }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(seriesId) }),
  })
}
