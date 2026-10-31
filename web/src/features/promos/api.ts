import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { env } from '../../config/env'
import { api, type Listed } from '../../shared/api/client'
import type { ItemChanges, MissingResult, NewItem, Promo, PromoKind, PromoRender, PromoRenderKind } from './types'

const POLL_MS = 3000
const listKey = (seriesId: string) => ['series', seriesId, 'promos'] as const

export const fileUrl = (path: string) => `${env.apiUrl}${path}`

const busy = (promo: Promo) =>
  promo.progress.working > 0 || Object.values(promo.renders ?? {}).some((r) => r && ['queued', 'running'].includes(r.status))

/** Every teaser and trailer of the series, each with its latest renders. Refreshes while something is being made. */
export function usePromos(seriesId: string) {
  return useQuery({
    queryKey: listKey(seriesId),
    queryFn: async ({ signal }) => {
      const list = await api.get<Listed<Promo>>(`/series/${seriesId}/promos`, signal)
      return Promise.all(list.items.map(async (p) => ({ ...p, renders: (await api.get<Promo>(`/promos/${p.id}`, signal)).renders ?? {} })))
    },
    refetchInterval: (query) => (query.state.data?.some(busy) ? POLL_MS : false),
  })
}

export function usePromoActions(seriesId: string) {
  const client = useQueryClient()
  const refresh = () => client.invalidateQueries({ queryKey: listKey(seriesId) })

  const create = useMutation({
    mutationFn: (v: { kind: PromoKind; title?: string; target_duration_seconds?: number; notes?: string; plan: boolean }) =>
      api.post<Promo>(`/series/${seriesId}/promos`, v),
    onSuccess: refresh,
  })
  const update = useMutation({
    mutationFn: (v: { id: string; changes: Partial<Pick<Promo, 'title' | 'target_duration_seconds' | 'notes' | 'hook' | 'music_mood'>> }) =>
      api.put<Promo>(`/promos/${v.id}`, v.changes),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: (id: string) => api.delete(`/promos/${id}`), onSuccess: refresh })
  const plan = useMutation({ mutationFn: (id: string) => api.post<Promo>(`/promos/${id}/plan`), onSuccess: refresh })
  const addItem = useMutation({ mutationFn: (v: { id: string; item: NewItem }) => api.post(`/promos/${v.id}/items`, v.item), onSuccess: refresh })
  const updateItem = useMutation({
    mutationFn: (v: { id: string; itemId: string; changes: ItemChanges }) => api.put(`/promos/${v.id}/items/${v.itemId}`, v.changes),
    onSuccess: refresh,
  })
  const removeItem = useMutation({ mutationFn: (v: { id: string; itemId: string }) => api.delete(`/promos/${v.id}/items/${v.itemId}`), onSuccess: refresh })
  const reorder = useMutation({ mutationFn: (v: { id: string; itemIds: string[] }) => api.post(`/promos/${v.id}/reorder`, { item_ids: v.itemIds }), onSuccess: refresh })
  const generateMissing = useMutation({ mutationFn: (id: string) => api.post<MissingResult>(`/promos/${id}/generate-missing`), onSuccess: refresh })
  const render = useMutation({
    mutationFn: (v: { id: string; kind: PromoRenderKind }) => api.post<PromoRender>(`/promos/${v.id}/renders`, { kind: v.kind }),
    onSuccess: refresh,
  })
  return { create, update, remove, plan, addItem, updateItem, removeItem, reorder, generateMissing, render }
}
