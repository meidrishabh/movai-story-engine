import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { api } from '../../shared/api/client'
import { pipelineKeys } from '../pipeline/api'
import type { Estimate, Series, SourceInfo } from './types'

export const seriesKeys = {
  detail: (id: string) => ['series', id] as const,
  estimate: (id: string) => ['series', id, 'estimate'] as const,
}

/** The series id from the route. Every series screen is mounted under /series/:seriesId. */
export function useSeriesId(): string {
  const { seriesId } = useParams()
  if (!seriesId) throw new Error('This screen must be rendered under /series/:seriesId')
  return seriesId
}

export function useSeries(seriesId: string) {
  return useQuery({
    queryKey: seriesKeys.detail(seriesId),
    queryFn: ({ signal }) => api.get<Series>(`/series/${seriesId}`, signal),
  })
}

export function useEstimate(seriesId: string, enabled: boolean) {
  return useQuery({
    queryKey: seriesKeys.estimate(seriesId),
    queryFn: ({ signal }) => api.get<Estimate>(`/series/${seriesId}/analysis-estimate`, signal),
    enabled,
    retry: false,
  })
}

export function useUploadSource(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title: string }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('title', title)
      return api.upload<SourceInfo>(`/series/${seriesId}/sources/upload`, form)
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: pipelineKeys.status(seriesId) })
      void client.invalidateQueries({ queryKey: seriesKeys.estimate(seriesId) })
    },
  })
}

export function useAnalyze(seriesId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ id: string }>(`/series/${seriesId}/analyze`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: pipelineKeys.status(seriesId) }),
  })
}
