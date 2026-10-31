export interface AssetSummary {
  id: string
  kind: 'image' | 'video' | 'audio' | 'subtitle' | 'other'
  mime_type: string
  width: number | null
  height: number | null
  duration_seconds: number | null
  provider: string | null
  url: string
}

export interface KeyframeReference {
  asset_id: string
  label: string
}

export interface ConsistencyCheck {
  status?: 'passed' | 'flagged' | 'skipped'
  score?: number | null
  notes?: string
}

export type KeyframeStatus = 'queued' | 'blocked' | 'running' | 'awaiting_input' | 'succeeded' | 'failed' | 'rejected'

export interface Keyframe {
  id: string
  status: KeyframeStatus
  review_status: 'pending' | 'approved' | 'rejected'
  review_note: string | null
  prompt: string
  negative_prompt: string | null
  references: KeyframeReference[]
  warnings: string[]
  checks: ConsistencyCheck
  error_summary: string | null
  attempts: number
  provider: string | null
  result: AssetSummary | null
}

export interface KeyframeShot {
  id: string
  shot_number: number
  description: string
  camera: string | null
  duration_seconds: number | null
  characters: string[]
  keyframe: Keyframe | null
}

export interface KeyframeScene {
  id: string
  scene_number: number
  title: string | null
  location: string | null
  time_of_day: string | null
  shots: KeyframeShot[]
}

export interface KeyframeTotals {
  shots: number
  not_generated: number
  working: number
  needs_review: number
  approved: number
  failed: number
  flagged: number
}

export interface EpisodeKeyframes {
  episode: { id: string; episode_number: number; title: string }
  style_approved: boolean
  totals: KeyframeTotals
  scenes: KeyframeScene[]
}

export interface EpisodeKeyframeSummary {
  id: string
  episode_number: number
  title: string
  shots: number
  generated: number
  approved: number
  needs_review: number
  working: number
  failed: number
}

export interface KeyframeOverview {
  style_approved: boolean
  count: number
  items: EpisodeKeyframeSummary[]
}

export interface GenerateResult {
  created: number
  skipped: number
  request_ids: string[]
  warnings: Record<string, string[]>
}
