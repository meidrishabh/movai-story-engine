export type PromoKind = 'teaser' | 'trailer'
export type PromoRenderKind = 'animatic' | 'draft' | 'final'
export type ItemType = 'shot' | 'title_card' | 'narration'

export interface Asset {
  id: string
  url: string
}

export interface RequestView {
  request_id: string
  status: 'queued' | 'blocked' | 'running' | 'awaiting_input' | 'succeeded' | 'failed' | 'rejected'
  review_status: 'pending' | 'approved' | 'rejected'
  error_summary: string | null
  asset: Asset | null
}

export interface PromoItem {
  id: string
  position: number
  type: ItemType
  text: string | null
  seconds: number | null
  trim_seconds: number | null
  start_offset: number
  style: { subtitle?: string }
  reason: string | null
  shot_id: string | null
  shot?: { episode_number: number; scene_number: number; shot_number: number; description: string; camera: string | null; duration_seconds: number | null } | null
  keyframe?: RequestView | null
  clip?: RequestView | null
  voice?: RequestView | null
}

export interface PromoProgress {
  shots: number
  with_keyframe: number
  with_clip: number
  approved_clips: number
  working: number
  narration: number
  narration_ready: number
}

export interface PromoRender {
  id: string
  kind: PromoRenderKind
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  duration_seconds: number | null
  error_summary: string | null
  asset: Asset | null
  download_url: string | null
}

export interface Promo {
  id: string
  series_id: string
  kind: PromoKind
  title: string
  target_duration_seconds: number
  status: 'draft' | 'planned'
  notes: string | null
  hook: string | null
  music_mood: string | null
  items: PromoItem[]
  music: RequestView | null
  seconds: number
  within_target: boolean
  progress: PromoProgress
  renders?: Partial<Record<PromoRenderKind, PromoRender>>
}

export interface MissingResult {
  keyframes_requested: number
  clips_requested: number
  clips_waiting_on_keyframe: number
  voice_lines_requested: number
  music_requested: number
  reused_keyframes: number
  reused_clips: number
  problems: string[]
}

export interface NewItem {
  type: ItemType
  text?: string
  seconds?: number
  shot_id?: string
  trim_seconds?: number
  subtitle?: string
}

export interface ItemChanges {
  trim_seconds?: number
  start_offset?: number
  seconds?: number
  text?: string
  subtitle?: string
}
