import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { env } from '../../config/env'
import { api } from '../../shared/api/client'
import type { EpisodeKeyframes, GenerateResult, KeyframeOverview } from './types'

const POLL_MS = 3000

export const keyframeKeys = {
  overview: (seriesId: string) => ['series', seriesId, 'keyframes'] as const,
  episode: (episodeId: string) => ['episode', episodeId, 'keyframes'] as const,
}

/** The URL that serves an asset's file (an `<img>` or `<video>` src). */
export const assetUrl = (assetId: string) => `${env.apiUrl}/api/v1/assets/${assetId}/file`

export function useKeyframeOverview(seriesId: string) {
  return useQuery({
    queryKey: keyframeKeys.overview(seriesId),
    queryFn: ({ signal }) => api.get<KeyframeOverview>(`/series/${seriesId}/keyframes`, signal),
    refetchInterval: (query) => (query.state.data?.items.some((e) => e.working > 0) ? POLL_MS : false),
  })
}

/** One episode's scene > shot grid; refreshes while any keyframe is queued, blocked or running. */
export function useEpisodeKeyframes(episodeId: string | undefined) {
  return useQuery({
    queryKey: keyframeKeys.episode(episodeId ?? ''),
    queryFn: ({ signal }) => api.get<EpisodeKeyframes>(`/episodes/${episodeId}/keyframes`, signal),
    enabled: Boolean(episodeId),
    refetchInterval: (query) => (query.state.data && query.state.data.totals.working > 0 ? POLL_MS : false),
  })
}

export function useKeyframeActions(seriesId: string, episodeId: string) {
  const client = useQueryClient()
  const refresh = () => {
    void client.invalidateQueries({ queryKey: keyframeKeys.episode(episodeId) })
    void client.invalidateQueries({ queryKey: keyframeKeys.overview(seriesId) })
  }
  const generate = useMutation({
    mutationFn: (regenerate: boolean) =>
      api.post<GenerateResult>(`/episodes/${episodeId}/keyframes/generate`, { regenerate }),
    onSuccess: refresh,
  })
  const regenerate = useMutation({
    mutationFn: (shotId: string) => api.post<GenerateResult>(`/shots/${shotId}/keyframe/regenerate`),
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: (v: { requestId: string; decision: 'approve' | 'reject'; note?: string }) =>
      api.post(`/generation-requests/${v.requestId}/review`, { decision: v.decision, note: v.note }),
    onSuccess: refresh,
  })
  const retry = useMutation({
    mutationFn: (requestId: string) => api.post(`/generation-requests/${requestId}/retry`),
    onSuccess: refresh,
  })
  const check = useMutation({
    mutationFn: (requestId: string) => api.post(`/generation-requests/${requestId}/check`),
    onSuccess: refresh,
  })
  return { generate, regenerate, review, retry, check }
}
