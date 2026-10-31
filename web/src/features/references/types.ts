export interface AssetSummary {
  id: string
  kind: 'image' | 'video' | 'audio' | 'subtitle' | 'other'
  mime_type: string
  width: number | null
  height: number | null
  /** Path of the file on the API, for example /api/v1/assets/<id>/file. */
  url: string
}

export type RequestStatus = 'queued' | 'blocked' | 'running' | 'awaiting_input' | 'succeeded' | 'failed' | 'rejected'

/** One generation request as the gallery needs it. */
export interface RefRequest {
  id: string
  kind: string
  status: RequestStatus
  review_status: 'pending' | 'approved' | 'rejected'
  review_note: string | null
  prompt: string
  error_summary: string | null
  params: { view?: string; subject?: string; [key: string]: unknown }
  result: AssetSummary | null
  drift_score: number | null
  drift_flag: boolean
  drift_notes: string | null
  drift_judge: string | null
  created_at: string
}

export interface RefView {
  view: string
  label: string
  /** The newest attempt that was not rejected, or null when nothing was requested yet. */
  request: RefRequest | null
  attempts: number
}

export type TargetType = 'character_version' | 'costume' | 'entity_look'

export interface RefCostume {
  target_type: 'costume'
  target_id: string
  name: string
  description: string
  views: RefView[]
}

export interface RefTarget {
  target_type: TargetType
  target_id: string
  name: string
  description: string
  role?: string | null
  version_number?: number
  views: RefView[]
  costumes?: RefCostume[]
}

export interface ReferenceOverview {
  style_bible_approved: boolean
  style_anchor_asset_id: string | null
  style_anchors: RefRequest[]
  characters: RefTarget[]
  places: RefTarget[]
  objects: RefTarget[]
  flagged_count: number
}

export interface GenerateAllResult {
  characters: number
  costumes: number
  places: number
  objects: number
  requests_created: number
}
