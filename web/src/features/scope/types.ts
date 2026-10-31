export interface ScopeScene {
  id: string
  scene_number: number
  title: string
  shots: number
  seconds: number
  selected: boolean
}

/** The scenes an episode's pages work on. `all_scenes` means nothing is narrowed down. */
export interface WorkingScenes {
  episode_id: string
  all_scenes: boolean
  scene_ids: string[]
  selected_shots: number
  scenes: ScopeScene[]
}

export interface ChecklistStage {
  key: string
  label: string
  total: number
  done: number
  missing: string[]
  missing_count: number
  complete: boolean
  hint: string
}

export interface ScopeChecklist {
  episode_id: string
  scene_ids: string[]
  shots: number
  ready_to_render: boolean
  stages: ChecklistStage[]
}

export interface ReferenceScope {
  limited: boolean
  characters: string[]
  costumes: string[]
  places: string[]
  objects: string[]
}

export interface PrepareResult {
  working: WorkingScenes
  needed: { shots: number; characters: { id: string; name: string }[]; places: { id: string; name: string }[]; objects: { id: string; name: string }[] }
  reference_scope: ReferenceScope
  references_requested: { requests_created?: number; error?: string } | null
  checklist: ScopeChecklist
}
