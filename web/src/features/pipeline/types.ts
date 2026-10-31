import type { Series, SourceInfo } from '../series/types'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface AnalysisRun {
  id: string
  status: RunStatus
  current_stage: string | null
  progress: number
  model_name: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

/** What the pipeline finished but wants a person to look at. */
export interface Attention {
  entities_to_review: number
  open_conflicts: number
  disputed_beats: number
  draft_plans: number
  /** Items from the image, sound and video stages; `to` is a route relative to the series page. */
  generation: GenerationAttention[]
}

export interface GenerationAttention {
  key: string
  count: number
  label: string
  to: string
}

export interface EpisodeBudgetState {
  max_retries_per_shot: number
  max_cost: number | null
  paused: boolean
  cost_total: number
  over_cost: boolean
}

export interface GenerationOverview {
  paused: boolean
  spend: number
  requests: number
  held: number
  awaiting_input: number
  by_kind: { kind: string; requests: number; spend: number }[]
  providers: Record<string, string>
  episodes: {
    episode_id: string
    episode_number: number
    title: string
    spend: number
    requests: number
    failed: number
    open: number
    budget: EpisodeBudgetState
  }[]
}

export interface Pipeline {
  attention: Attention
  series: Series
  source: SourceInfo | null
  master_script: { id: string; version_number: number; summary: string | null } | null
  analysis_run: AnalysisRun | null
  story_status: string
}
