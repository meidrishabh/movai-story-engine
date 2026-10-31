import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { env } from '../../config/env'
import { api } from '../../shared/api/client'
import type { Budget, PlanResult, RenderKind, RenderView, VideoBoard } from './types'

const POLL_MS = 3000
const boardKey = (episodeId: string) => ['episode', episodeId, 'video'] as const

/** A stored file or render is served by the API at a path; the browser needs the full address. */
export const fileUrl = (path: string) => `${env.apiUrl}${path}`

const isWorking = (board: VideoBoard | undefined) =>
  !!board &&
  (board.shots.some((s) => s.clip && ['queued', 'running'].includes(s.clip.status)) ||
    Object.values(board.renders).some((r) => r && ['queued', 'running'].includes(r.status)))

/** The clip board of an episode; refreshes while a clip is being made or a render is running. */
export function useVideoBoard(episodeId: string | undefined) {
  return useQuery({
    queryKey: boardKey(episodeId ?? ''),
    queryFn: ({ signal }) => api.get<VideoBoard>(`/episodes/${episodeId}/video`, signal),
    enabled: !!episodeId,
    refetchInterval: (query) => (isWorking(query.state.data) ? POLL_MS : false),
  })
}

export function useVideoActions(episodeId: string) {
  const client = useQueryClient()
  const refresh = () => client.invalidateQueries({ queryKey: boardKey(episodeId) })

  const plan = useMutation({
    mutationFn: (options: { limit?: number; allow_text_to_video?: boolean; hold_last_frame?: boolean }) =>
      api.post<PlanResult>(`/episodes/${episodeId}/video/plan`, options),
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: (v: { requestId: string; decision: 'approve' | 'reject'; note?: string }) =>
      api.post(`/video-clips/${v.requestId}/review`, { decision: v.decision, note: v.note || null }),
    onSuccess: refresh,
  })
  const holdLastFrame = useMutation({
    mutationFn: (v: { requestId: string; hold: boolean }) => api.post(`/video-clips/${v.requestId}/options`, { hold_last_frame: v.hold }),
    onSuccess: refresh,
  })
  const budget = useMutation({
    mutationFn: (changes: Partial<Pick<Budget, 'max_retries_per_shot' | 'max_cost' | 'paused'>>) =>
      api.put(`/episodes/${episodeId}/video/budget`, changes),
    onSuccess: refresh,
  })
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.post(`/episodes/${episodeId}/video/${paused ? 'pause' : 'resume'}`),
    onSuccess: refresh,
  })
  const render = useMutation({
    mutationFn: (kind: RenderKind) => api.post<RenderView>(`/episodes/${episodeId}/renders`, { kind }),
    onSuccess: refresh,
  })
  return { plan, review, holdLastFrame, budget, pause, render }
}
