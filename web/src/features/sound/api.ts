import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { env } from '../../config/env'
import { api } from '../../shared/api/client'
import type { CastList, SoundBoard, SubtitlePreview, VoiceFields } from './types'

const POLL_MS = 3000

export const audioUrl = (path: string) => `${env.apiUrl}${path}`

export const castKey = (seriesId: string) => ['series', seriesId, 'voice-casts'] as const
export const boardKey = (episodeId: string) => ['episode', episodeId, 'sound'] as const

/** The cast list; refreshes while a voice preview is still being made. */
export function useCast(seriesId: string) {
  return useQuery({
    queryKey: castKey(seriesId),
    queryFn: ({ signal }) => api.get<CastList>(`/series/${seriesId}/voice-casts`, signal),
    refetchInterval: (query) => {
      const data = query.state.data
      const pending = [data?.narrator.cast, ...(data?.characters.map((c) => c.cast) ?? [])].some(
        (cast) => cast?.preview && (cast.preview.status === 'queued' || cast.preview.status === 'running'),
      )
      return pending ? POLL_MS : false
    },
  })
}

export function useCastActions(seriesId: string) {
  const client = useQueryClient()
  const onSuccess = () => void client.invalidateQueries({ queryKey: castKey(seriesId) })
  const save = useMutation({
    mutationFn: ({ who, fields }: { who: string; fields: Partial<VoiceFields> }) =>
      api.put<CastList>(`/series/${seriesId}/voice-casts/${who}`, fields),
    onSuccess: (data) => client.setQueryData(castKey(seriesId), data),
  })
  const preview = useMutation({
    mutationFn: ({ who, text }: { who: string; text?: string }) => api.post(`/series/${seriesId}/voice-casts/${who}/preview`, { text }),
    onSuccess,
  })
  return { save, preview }
}

const active = (b: SoundBoard) =>
  b.job?.status === 'queued' ||
  b.job?.status === 'running' ||
  Object.entries(b.counts).some(([status, n]) => (status === 'queued' || status === 'running') && (n ?? 0) > 0)

/** The sound board of one episode; refreshes while the job or any sound is still being made. */
export function useSoundBoard(episodeId: string | null) {
  return useQuery({
    queryKey: boardKey(episodeId ?? 'none'),
    enabled: episodeId !== null,
    queryFn: ({ signal }) => api.get<SoundBoard>(`/episodes/${episodeId}/sound`, signal),
    refetchInterval: (query) => (query.state.data && active(query.state.data) ? POLL_MS : false),
  })
}

export function useSubtitles(episodeId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['episode', episodeId ?? 'none', 'subtitles'] as const,
    enabled: enabled && episodeId !== null,
    queryFn: ({ signal }) => api.get<SubtitlePreview>(`/episodes/${episodeId}/subtitles`, signal),
  })
}

export function useSoundActions(episodeId: string) {
  const client = useQueryClient()
  const refresh = () => {
    void client.invalidateQueries({ queryKey: boardKey(episodeId) })
    void client.invalidateQueries({ queryKey: ['episode', episodeId, 'subtitles'] })
  }
  const generate = useMutation({
    mutationFn: (redesign: boolean) => api.post(`/episodes/${episodeId}/sound/generate`, { redesign }),
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: ({ cueId, decision, note }: { cueId: string; decision: 'approve' | 'reject'; note?: string }) =>
      api.post(`/sound-cues/${cueId}/review`, { decision, note }),
    onSuccess: refresh,
  })
  const approveAll = useMutation({ mutationFn: () => api.post<{ approved: number }>(`/episodes/${episodeId}/sound/approve-all`), onSuccess: refresh })
  const applyFit = useMutation({ mutationFn: () => api.post(`/episodes/${episodeId}/sound/apply-fit`, {}), onSuccess: refresh })
  const subtitles = useMutation({ mutationFn: () => api.post(`/episodes/${episodeId}/subtitles/build`), onSuccess: refresh })
  return { generate, review, approveAll, applyFit, subtitles }
}
