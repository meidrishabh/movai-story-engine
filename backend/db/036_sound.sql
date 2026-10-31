-- Sound for an episode: who speaks with which voice, every dialogue / narration / effect / music cue, and how the
-- spoken audio fits each shot. The audio files themselves are generation_requests and assets (see 030).

-- One voice per character, plus one narrator (character_id NULL). `consent_given` records that the person or rights
-- holder behind a cloned or modelled voice agreed; the board warns when a cast voice has no recorded consent.
CREATE TABLE IF NOT EXISTS voice_casts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'character' CHECK (role IN ('character', 'narrator')),
    voice TEXT NOT NULL DEFAULT '',          -- a provider voice id, or a description ("older man, low, tired")
    language TEXT NOT NULL DEFAULT 'en',
    style TEXT NOT NULL DEFAULT '',          -- default delivery for this voice
    speed NUMERIC(4, 2) NOT NULL DEFAULT 1.0 CHECK (speed > 0),
    consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    consent_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((role = 'narrator') = (character_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_casts_character ON voice_casts (series_id, character_id) WHERE character_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_casts_narrator ON voice_casts (series_id) WHERE role = 'narrator';

-- One row per sound to make. The latest generation_request with target_type = 'sound_cue' and target_id = this id
-- is its current attempt; audio_asset_id / audio_duration are the measured result of the accepted attempt.
-- Dialogue lines are copied from scenes.dialogue (verbatim); narration, effects, ambience and music come from the
-- sound design step. shot_id / start_seconds are where the line sits, recomputed whenever timings change.
CREATE TABLE IF NOT EXISTS sound_cues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_id UUID REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id UUID REFERENCES scenes(id) ON DELETE CASCADE,
    shot_id UUID REFERENCES shots(id) ON DELETE SET NULL,
    cue_type TEXT NOT NULL CHECK (cue_type IN ('dialogue', 'narration', 'sfx', 'ambience', 'music')),
    role TEXT NOT NULL DEFAULT 'scene' CHECK (role IN ('scene', 'theme')),
    position INTEGER NOT NULL DEFAULT 1,
    character_id UUID REFERENCES characters(id) ON DELETE SET NULL,
    speaker TEXT,
    text TEXT NOT NULL,                      -- the spoken words, or the prompt for an effect / ambience / music cue
    delivery TEXT,
    start_seconds NUMERIC(7, 2),             -- seconds after the start of its shot
    duration_hint NUMERIC(7, 2),             -- requested length for effects, ambience and music
    audio_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    audio_duration NUMERIC(7, 2),
    source_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sound_cues_scene ON sound_cues (scene_id, cue_type, position) WHERE scene_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sound_cues_theme ON sound_cues (series_id) WHERE role = 'theme';
CREATE INDEX IF NOT EXISTS idx_sound_cues_episode ON sound_cues (episode_id, cue_type);

-- Spoken audio against shot length. `suggested_seconds` is what the shot would need to hold its speech; nothing
-- changes shots.duration_seconds until the user applies it. `measured` is false while any line is still an estimate.
CREATE TABLE IF NOT EXISTS sound_shot_fits (
    shot_id UUID PRIMARY KEY REFERENCES shots(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    audio_seconds NUMERIC(7, 2) NOT NULL DEFAULT 0,
    shot_seconds NUMERIC(7, 2),
    suggested_seconds NUMERIC(7, 2),
    status TEXT NOT NULL DEFAULT 'empty' CHECK (status IN ('empty', 'ok', 'overflow')),
    measured BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sound_shot_fits_episode ON sound_shot_fits (episode_id);
