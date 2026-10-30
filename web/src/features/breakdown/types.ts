export interface EpisodeBreakdownStatus {
  id: string
  episode_number: number
  title: string
  target_duration_seconds: number | null
  breakdown_stale: boolean
  scene_count: number
  shot_seconds: number
  job_status: 'queued' | 'running' | 'succeeded' | 'failed' | null
  job_error: string | null
}

export interface Shot {
  shot_number: number
  description: string
  camera: string | null
  duration_seconds: number | null
}

export interface Scene {
  id: string
  scene_number: number
  title: string
  description: string | null
  dialogue: string | null
  environment_notes: string | null
  shots: Shot[]
}

export interface Breakdown {
  count: number
  stale: boolean
  continuity_notes: Record<string, unknown>
  items: Scene[]
}
