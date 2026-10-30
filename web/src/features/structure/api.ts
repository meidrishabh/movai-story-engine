import { useQuery } from '@tanstack/react-query'

import { api } from '../../shared/api/client'
import type { Continuity, MasterScript, Timeline } from './types'

const key = (seriesId: string, part: string) => ['series', seriesId, 'structure', part] as const

export function useTimeline(seriesId: string) {
  return useQuery({ queryKey: key(seriesId, 'timeline'), queryFn: ({ signal }) => api.get<Timeline>(`/series/${seriesId}/timeline`, signal) })
}

export function useContinuity(seriesId: string) {
  return useQuery({
    queryKey: key(seriesId, 'continuity'),
    queryFn: ({ signal }) => api.get<Continuity>(`/series/${seriesId}/continuity/states`, signal),
  })
}

/** The master script is 404 until the analysis has produced one; that reads as "nothing yet", not an error. */
export function useMasterScript(seriesId: string) {
  return useQuery({
    queryKey: key(seriesId, 'master-script'),
    queryFn: ({ signal }) => api.get<MasterScript>(`/series/${seriesId}/master-script`, signal),
    retry: false,
  })
}
