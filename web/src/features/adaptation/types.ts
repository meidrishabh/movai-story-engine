export type AdaptationKind = 'full' | 'concentrated' | 'trailer' | 'teaser'
export type MainKind = 'full' | 'concentrated'
export type AdaptationStatus = 'not_generated' | 'generating' | 'ready' | 'failed'

/** One beat the filler review looked at. `why` explains why a disputed beat stayed in. */
export interface BeatItem {
  unit: number
  unit_title: string
  beat: number | null
  beat_text: string | null
  reason: string
  judge_reason: string
  seconds: number
  reused_later: string[]
  why?: 'reused_later' | 'judge_keep' | 'judge_missing'
  by?: 'user'
}

export interface AdaptationItem {
  kind: AdaptationKind
  label: string
  group: 'main' | 'extra'
  status: AdaptationStatus
  available: boolean
  stale: boolean
  selected: boolean
  duration_seconds: number | null
  target_seconds: number | null
  error: string | null
  min_seconds?: number
  max_seconds?: number
  default_seconds?: number
  summary?: { title: string | null; logline: string | null; segments: number } | null
  removed?: BeatItem[]
  disputed?: BeatItem[]
  restored?: BeatItem[]
  saved_seconds?: number | null
}

export interface BeatDecisionResult {
  duration_seconds: number
  affected_episodes: string[]
  repair_job: string | null
}

export type BeatAction = 'keep' | 'cut'
