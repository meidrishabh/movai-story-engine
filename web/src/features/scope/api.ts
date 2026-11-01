import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import type { PrepareResult, ReferenceScope, ScopeChecklist, WorkingScenes } from './types'

const scenesKey = (episodeId: string) => ['episode', episodeId, 'working-scenes'] as const
const checklistKey = (episodeId: string) => ['episode', episodeId, 'scope-checklist'] as const
const referenceScopeKey = (seriesId: string) => ['series', seriesId, 'reference-scope'] as const

export function useWorkingScenes(episodeId: string) {
  return useQuery({ queryKey: scenesKey(episodeId), queryFn: ({ signal }) => api.get<WorkingScenes>(`/episodes/${episodeId}/working-scenes`, signal) })
}

export function useScopeChecklist(episodeId: string, enabled: boolean) {
  return useQuery({
    queryKey: checklistKey(episodeId),
    queryFn: ({ signal }) => api.get<ScopeChecklist>(`/episodes/${episodeId}/scope-checklist`, signal),
    enabled,
  })
}

export function useReferenceScope(seriesId: string) {
  return useQuery({ queryKey: referenceScopeKey(seriesId), queryFn: ({ signal }) => api.get<ReferenceScope>(`/series/${seriesId}/reference-scope`, signal) })
}

/** Changing the scope changes what every board shows and counts, so everything is refetched. */
export function useScopeActions(seriesId: string, episodeId?: string) {
  const client = useQueryClient()
  const refresh = () => client.invalidateQueries()

  const setScenes = useMutation({
    mutationFn: (sceneIds: string[]) => api.put<WorkingScenes>(`/episodes/${episodeId}/working-scenes`, { scene_ids: sceneIds }),
    onSuccess: refresh,
  })
  const prepare = useMutation({
    mutationFn: (v: { sceneIds: string[]; requestReferences: boolean }) =>
      api.post<PrepareResult>(`/episodes/${episodeId}/scope/prepare`, { scene_ids: v.sceneIds, request_references: v.requestReferences }),
    onSuccess: refresh,
  })
  const setReferenceScope = useMutation({
    mutationFn: (scope: Partial<ReferenceScope> & { limited: boolean }) => api.put<ReferenceScope>(`/series/${seriesId}/reference-scope`, scope),
    onSuccess: refresh,
  })
  const selectForScenes = useMutation({
    mutationFn: (id: string) => api.post(`/series/${seriesId}/reference-scope/select-for-scenes`, { episode_id: id }),
    onSuccess: refresh,
  })
  return { setScenes, prepare, setReferenceScope, selectForScenes }
}
