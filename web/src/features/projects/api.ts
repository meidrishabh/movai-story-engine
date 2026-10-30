import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Listed } from '../../shared/api/client'
import type { Series } from '../series/types'
import type { Project } from './types'

export const projectKeys = {
  all: ['projects'] as const,
  detail: (id: string) => ['projects', id] as const,
  series: (id: string) => ['projects', id, 'series'] as const,
}

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: ({ signal }) => api.get<Listed<Project>>('/projects', signal),
  })
}

export function useProject(projectId: string) {
  return useQuery({
    queryKey: projectKeys.detail(projectId),
    queryFn: ({ signal }) => api.get<Project>(`/projects/${projectId}`, signal),
  })
}

export function useCreateProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { title: string; description?: string }) => api.post<Project>('/projects', input),
    onSuccess: () => client.invalidateQueries({ queryKey: projectKeys.all }),
  })
}

export function useProjectSeries(projectId: string) {
  return useQuery({
    queryKey: projectKeys.series(projectId),
    queryFn: ({ signal }) => api.get<Listed<Series>>(`/projects/${projectId}/series`, signal),
  })
}

export function useCreateSeries(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { title: string; genre?: string }) => api.post<Series>(`/projects/${projectId}/series`, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: projectKeys.series(projectId) })
      void client.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}
