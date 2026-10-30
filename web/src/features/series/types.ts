export interface Series {
  id: string
  project_id: string
  title: string
  premise: string | null
  genre: string | null
  language_code: string
  episode_count?: number
  estimated_duration_seconds?: number | null
}

export interface SourceInfo {
  id: string
  title: string
  original_filename: string | null
  source_type: string
  validation_status: string
  status: string
  created_at: string
}

/** What a run will cost before it starts. */
export interface Estimate {
  chunks: number
  words: number
  batches: number
  llm_calls: number
  estimated_prompt_tokens: number
  estimated_output_tokens: number
  minimum_seconds: number
  max_calls_allowed: number
  within_call_limit: boolean
}
