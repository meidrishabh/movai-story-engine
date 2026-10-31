export interface StyleOverride {
  when: string | null
  change: string | null
}

export interface StyleBible {
  id: string
  series_id: string
  version: number
  status: 'draft' | 'approved' | 'superseded'
  theme_tone: string | null
  medium: string | null
  art_style: string | null
  palette: string | null
  lighting: string | null
  camera_language: string | null
  negative_style: string | null
  per_act_overrides: StyleOverride[]
  approved_at: string | null
  updated_at: string
}

export interface StyleBibleResponse {
  bible: StyleBible | null
  approved: boolean
  /** The text every image prompt for this series starts with. */
  style_block: string | null
}

export type StyleFields = Pick<
  StyleBible,
  'theme_tone' | 'medium' | 'art_style' | 'palette' | 'lighting' | 'camera_language' | 'negative_style' | 'per_act_overrides'
>
