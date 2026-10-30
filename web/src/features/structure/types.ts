export interface Anchor {
  id: string
  label: string
  description: string | null
  timeline_type: string | null
  sort_order: number | null
}

export interface StoryEvent {
  id: string
  title: string
  description: string | null
  narrative_position: number | null
  chronological_position: number | null
  narrative_layer: string | null
  timeline_anchor_id: string | null
}

export interface Timeline {
  anchors: Anchor[]
  events: StoryEvent[]
}

export interface Conflict {
  id: string
  entity_type: string
  conflict_type: string
  description: string
  severity: string
  status: string
}

export interface Continuity {
  conflicts: Conflict[]
}

export interface StoryUnit {
  id: string
  sequence_number: number
  title: string
  synopsis: string | null
  character_names: string[] | null
  location_names: string[] | null
  estimated_seconds: number | null
}

export interface MasterScript {
  id: string
  version_number: number
  title: string
  summary: string | null
  units: StoryUnit[]
}
