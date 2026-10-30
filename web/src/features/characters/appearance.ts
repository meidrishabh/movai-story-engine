import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'

export interface Costume {
  id: string
  name: string
  description: string
  color_palette: string[]
  accessories: string[]
  when: string | null
}

export interface AppearanceSheet {
  character_id: string
  version_number: number
  description: string
  face_and_body_design: string | null
  clothing_and_accessories: string | null
  distinctive_features: string | null
  color_palette: string[]
  voice: string | null
  status: 'draft' | 'approved'
  change_notes: string | null
  costumes: Costume[]
}

export type AppearanceInput = Pick<
  AppearanceSheet,
  'description' | 'face_and_body_design' | 'clothing_and_accessories' | 'distinctive_features' | 'color_palette' | 'voice'
>

const key = (seriesId: string) => ['series', seriesId, 'appearance'] as const
const POLL_MS = 4000

/** Reference sheets by character id. Polls while a regenerate is running. */
export function useAppearance(seriesId: string, polling: boolean) {
  return useQuery({
    queryKey: key(seriesId),
    queryFn: ({ signal }) => api.get<{ items: AppearanceSheet[] }>(`/series/${seriesId}/appearance`, signal),
    select: (data) => new Map(data.items.map((sheet) => [sheet.character_id, sheet])),
    refetchInterval: polling ? POLL_MS : false,
  })
}

export function useSaveAppearance(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { characterId: string; sheet: AppearanceInput }) => api.put(`/characters/${input.characterId}/appearance`, input.sheet),
    onSuccess: () => client.invalidateQueries({ queryKey: key(seriesId) }),
  })
}

export function useGenerateAppearance(seriesId: string) {
  return useMutation({ mutationFn: () => api.post(`/series/${seriesId}/appearance/generate`) })
}

export interface LookSheet {
  entity_type: 'location' | 'object'
  entity_id: string
  version_number: number
  description: string
  form: string | null
  atmosphere: string | null
  distinctive_features: string | null
  color_palette: string[]
  status: 'draft' | 'approved'
  change_notes: string | null
}

export type LookInput = Pick<LookSheet, 'description' | 'form' | 'atmosphere' | 'distinctive_features' | 'color_palette'>

const looksKey = (seriesId: string) => ['series', seriesId, 'looks'] as const

/** Look sheets for places and objects, by entity id. Polls while a regenerate is running. */
export function useLooks(seriesId: string, polling: boolean) {
  return useQuery({
    queryKey: looksKey(seriesId),
    queryFn: ({ signal }) => api.get<{ items: LookSheet[] }>(`/series/${seriesId}/looks`, signal),
    select: (data) => new Map(data.items.map((sheet) => [sheet.entity_id, sheet])),
    refetchInterval: polling ? POLL_MS : false,
  })
}

export function useSaveLook(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { kind: 'location' | 'object'; id: string; sheet: LookInput }) => api.put(`/entities/${input.kind}/${input.id}/look`, input.sheet),
    onSuccess: () => client.invalidateQueries({ queryKey: looksKey(seriesId) }),
  })
}
