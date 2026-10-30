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

export interface Pipeline {
  series: Series
  source: SourceInfo | null
  master_script: { id: string; version_number: number; summary: string | null } | null
  analysis_run: AnalysisRun | null
  story_status: string
}
