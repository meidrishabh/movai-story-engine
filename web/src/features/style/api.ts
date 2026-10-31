import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import type { StyleBibleResponse, StyleFields } from './types'

export const styleKey = (seriesId: string) => ['series', seriesId, 'style-bible'] as const

export function useStyleBible(seriesId: string) {
  return useQuery({
    queryKey: styleKey(seriesId),
    queryFn: ({ signal }) => api.get<StyleBibleResponse>(`/series/${seriesId}/style-bible`, signal),
  })
}

/** Generate, save and approve all answer with the new state of the style bible. */
export function useStyleActions(seriesId: string) {
  const client = useQueryClient()
  const onSuccess = (data: StyleBibleResponse) => client.setQueryData(styleKey(seriesId), data)
  const generate = useMutation({
    mutationFn: (replace: boolean) => api.post<StyleBibleResponse>(`/series/${seriesId}/style-bible/generate`, { replace }),
    onSuccess,
  })
  const save = useMutation({
    mutationFn: (fields: Partial<StyleFields>) => api.put<StyleBibleResponse>(`/series/${seriesId}/style-bible`, fields),
    onSuccess,
  })
  const approve = useMutation({
    mutationFn: () => api.post<StyleBibleResponse>(`/series/${seriesId}/style-bible/approve`),
    onSuccess,
  })
  return { generate, save, approve }
}
