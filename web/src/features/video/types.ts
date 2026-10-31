export interface AssetView {
  id: string
  kind: 'image' | 'video' | 'audio' | 'subtitle' | 'other'
  mime_type: string
  byte_size: number
  width: number | null
  height: number | null
  duration_seconds: number | null
  provider: string | null
  url: string
}

/** How the clip compares with its shot: exact, too long (will be trimmed), short (flagged), short with the last frame held. */
export type TrimState = 'exact' | 'trim' | 'short' | 'hold' | 'unknown' | 'unplayable'

export interface ClipView {
  request_id: string
  status: 'queued' | 'blocked' | 'running' | 'awaiting_input' | 'succeeded' | 'failed' | 'rejected'
  review_status: 'pending' | 'approved' | 'rejected'
  review_note: string | null
  error_summary: string | null
  cost: number
  provider: string | null
  asset: AssetView | null
  needed_seconds: number
  actual_seconds: number | null
  trim: TrimState
  hold_last_frame: boolean
  attempts: number
  held_reason: 'paused' | 'budget' | null
  prompt: string
}

export interface KeyframeView {
  request_id: string
  review_status: 'pending' | 'approved' | 'rejected'
  asset: AssetView | null
}

export interface ShotRow {
  shot_id: string
  scene_id: string
  scene_number: number
  scene_title: string
  shot_number: number
  description: string
  camera: string | null
  duration_seconds: number
  keyframe: KeyframeView | null
  clip: ClipView | null
}

export interface Budget {
  max_retries_per_shot: number
  max_cost: number | null
  paused: boolean
  cost_total: number
  over_cost: boolean
}

export type RenderKind = 'animatic' | 'draft' | 'final'

export interface RenderSceneInfo {
  scene_id: string
  scene_number: number | null
  title: string | null
  duration: number
  asset_id: string
  cached: boolean
}

export interface RenderView {
  id: string
  kind: RenderKind
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  error_summary: string | null
  duration_seconds: number | null
  asset: AssetView | null
  subtitle_asset: AssetView | null
  download_url: string | null
  created_at: string
  completed_at: string | null
  details: {
    scenes?: RenderSceneInfo[]
    stills?: string[]
    auto_hold?: string[]
    rebuilt_shots?: number
    rebuilt_scenes?: number
    unchanged?: boolean
    profile?: { width: number; height: number; fps: number }
  }
}

export interface VideoBoard {
  episode: { id: string; series_id: string; episode_number: number; title: string }
  budget: Budget
  shots: ShotRow[]
  summary: {
    shots: number
    with_keyframe: number
    approved: number
    pending_review: number
    failed: number
    in_progress: number
    no_clip: number
    attention: number
  }
  renders: Partial<Record<RenderKind, RenderView>>
}

export interface PlanResult {
  created: number
  already_planned: number
  failed: number
  skipped_no_keyframe: number
}
