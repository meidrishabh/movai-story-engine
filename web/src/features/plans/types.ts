export type PlanStatus = 'draft' | 'approved' | 'rejected'

export interface EpisodePlan {
  id: string
  season_id: string
  season_number: number
  season_title: string | null
  episode_number: number
  title: string
  synopsis: string | null
  target_duration_seconds: number | null
  opening_hook: string | null
  climax_notes: string | null
  ending_notes: string | null
  status: PlanStatus
  review_note: string | null
  unit_count: number
  characters: string[]
}
