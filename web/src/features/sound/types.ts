export interface AudioFile {
  id: string
  url: string
  mime_type: string
  duration_seconds: number | null
}

export interface CastVoice {
  voice: string
  language: string
  style: string
  speed: number
  consent_given: boolean
  consent_note: string | null
  preview: { request_id: string; status: string; error: string | null; url: string | null } | null
}

export interface CastCharacter {
  character_id: string
  name: string
  role: string | null
  lines: number
  suggested_voice: string
  cast: CastVoice | null
}

export interface CastList {
  narrator: { cast: CastVoice | null }
  characters: CastCharacter[]
  uncast_speaking: number
  without_consent: number
}

export interface VoiceFields {
  voice: string
  language: string
  style: string
  speed: number
  consent_given: boolean
  consent_note: string
}

export type CueType = 'dialogue' | 'narration' | 'sfx' | 'ambience' | 'music'
export type CueStatus = 'planned' | 'queued' | 'blocked' | 'running' | 'awaiting_input' | 'ready' | 'failed' | 'rejected'

export interface Cue {
  id: string
  cue_type: CueType
  role: 'scene' | 'theme'
  position: number
  speaker: string | null
  character_id: string | null
  text: string
  delivery: string | null
  shot_id: string | null
  start_seconds: number | null
  duration_hint: number | null
  audio_duration: number | null
  status: CueStatus
  review_status: 'pending' | 'approved' | 'rejected' | null
  review_note: string | null
  error: string | null
  request_id: string | null
  attempts: number
  audio: (AudioFile & { kind: string }) | null
}

export interface ShotFit {
  status: 'empty' | 'ok' | 'overflow'
  audio_seconds: number
  suggested_seconds: number | null
  measured: boolean
}

export interface BoardShot {
  id: string
  shot_number: number
  description: string
  duration_seconds: number
  fit: ShotFit | null
}

export interface BoardScene {
  id: string
  scene_number: number
  title: string | null
  shots: BoardShot[]
  cues: Cue[]
}

export interface SoundBoard {
  episode: { id: string; episode_number: number; title: string }
  job: { status: 'queued' | 'running' | 'succeeded' | 'failed'; error_summary: string | null } | null
  theme: Cue | null
  scenes: BoardScene[]
  counts: Partial<Record<CueStatus, number>>
  overflow_shots: number
  warnings: string[]
  subtitles: { episode: AudioFile | null; scenes: number; shots: number }
}

export interface SubtitlePreview {
  files: { episode: AudioFile | null; scenes: number; shots: number }
  srt: string | null
}
