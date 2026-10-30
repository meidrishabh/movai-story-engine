export type EntityKind = 'character' | 'location' | 'object'
export type ReviewStatus = 'approved' | 'needs_review' | 'stale' | 'pending'

export interface Entity {
  id: string
  name: string
  disambiguation: string | null
  description: string | null
  review_status: ReviewStatus
  locked: boolean
  merged_into_id: string | null
  aliases: string[]
  mention_count: number
  role?: string | null
  story_role?: string | null
  object_type?: string | null
}

export interface Entities {
  characters: Entity[]
  locations: Entity[]
  objects: Entity[]
}
