# MovAI backend structure

The backend is being migrated from a monolithic FastAPI module to layered modules.

```text
app/
  main.py                 # application entry point and compatibility wiring
  core/                   # configuration and cross-cutting infrastructure
  api/                    # HTTP routers, dependencies, and versioning
  schemas/                # Pydantic request/response contracts
  domain/                 # domain rules, independent of HTTP and SQL
  repositories/           # PostgreSQL access and query composition
  services/               # use cases and orchestration
  workers/                # background job execution
  providers/              # LLM, embedding, and media provider adapters
  db.py                   # database engine and session lifecycle
```

## Boundaries

- Routers validate HTTP input and return HTTP responses.
- Services coordinate a use case and contain business decisions.
- Repositories own SQL and database persistence.
- Schemas define API contracts; they are not database models.
- Providers isolate external AI/media integrations behind interfaces.
- Workers execute long-running jobs outside request handlers.

The existing raw SQL is intentional during the first migration. Repositories will
be introduced around the existing queries before any ORM conversion is considered.
This keeps the refactor behavior-preserving and makes each vertical slice testable.

## Generation pipeline (images, sound, video)

Everything generated is a row in `generation_requests`, made by a provider, stored as an `assets` file and reviewed
by a person. All providers default to `mock` (placeholder files, no cost), so the whole pipeline runs offline.

```text
style bible -> style anchor -> character / place / object images -> keyframe per shot -> video clip per shot
                               sound cues (voices, effects, music) -> audio plan
                               clips + audio plan + subtitles -> animatic / draft / final render
```

- **Request queue** (`services/generation_service.py`, table `generation_requests`): one request per image, clip,
  voice line and so on. Fields: `kind`, `target_type`/`target_id`, `prompt`, `negative_prompt`, `params`,
  `reference_asset_ids`, `depends_on`, `result_asset_id`, `review_status`, `cost`. A request is `blocked` until its
  `depends_on` requests succeed (or are approved, with `params.deps_need_approval`). Statuses: queued, blocked,
  running, awaiting_input, succeeded, failed, rejected. Reject-with-note queues a new attempt with the note
  appended to the prompt. The job runner claims `generation_request` jobs and calls `run_request`.
- **Providers** (`providers/media_base.py`, `media_factory.py`, `media_mock.py`): `ImageProvider`, `VideoProvider`,
  `VoiceProvider` and `MusicProvider`, each `generate(request) -> GeneratedMedia`. Chosen by `IMAGE_PROVIDER`,
  `VIDEO_PROVIDER`, `VOICE_PROVIDER`, `MUSIC_PROVIDER`. A provider that cannot answer immediately raises
  `MediaPending`; the request becomes `awaiting_input` and a result is attached with
  `POST /api/v1/generation-requests/{id}/result`. This is the seam for the manual (Muse sandbox) adapter.
- **Asset store** (`services/asset_store.py`): `AssetStorage` interface with a local-disk backend under
  `STORAGE_DIR` (default `backend/storage/`, git-ignored). `storage_root()` is the one place that resolves the
  folder; files are served by `GET /api/v1/assets/{id}/file`. The API and the job runner must run from the same
  checkout so they read the same folder.
- **Style bible** (`services/style_bible_service.py`): one approved bible per series (medium, art style, palette,
  lighting, camera language, negative style, per-act overrides). Prompts use `style_block(bible)` in full for images
  and `style_block(bible, short=True)` for video.
- **References** (`services/reference_service.py`): style anchor frames, per-view images of characters (per
  version and costume), places and objects, and a drift check (`CONSISTENCY_JUDGE`). An approved reference is a
  request with `review_status = 'approved'`; `approved_asset_ids` and `get_approved_references` are what other
  stages read.
- **Keyframes** (`services/keyframe_service.py`, `prompt_builder.py`, `reference_adapter.py`): one keyframe per
  shot, in scene order, carrying the style anchor, place, character and previous-shot references (capped at 8).
  `build_video_prompt` makes the short motion prompt for the clip. Keyframes use the same drift judge as the
  reference images (`consistency_check.py`).
- **Sound** (`services/sound_service.py`, `voice_cast_service.py`): voice casting with consent, cues copied from the
  breakdown's dialogue plus designed narration, effects, ambience and music, measured audio length per shot
  (`sound_shot_fits`), subtitles, and `build_audio_plan`, which returns each shot's tracks in the shape
  `assemble_episode` takes.
- **Video and renders** (`services/video_service.py`, `render_service.py`): one clip per shot, image-to-video from
  the approved keyframe. The real clip length is recorded; a short clip is flagged, not padded, unless the last
  frame is held. Per-episode budgets (`generation_budgets`: retry limit, cost cap, pause) and a series-wide pause
  (`generation_controls`) hold requests as `blocked` with `params.held_reason`. Renders (`episode_renders`) are the
  animatic, a draft and the 1080p final, built by the job runner with `assemble_episode`.
- **Media package** (`app/media/`): pure ffmpeg functions on file paths, no database: `probe`, `normalize`, `trim`,
  `concat`, `mix_audio`, `add_subtitles`, `upscale`, frame extraction and `assemble_episode`, which caches scenes and
  rebuilds only those whose inputs changed. ffmpeg is found from `FFMPEG_PATH`, then PATH, then the winget install.
- **Pipeline view** (`services/generation_overview.py`): `generation_attention` adds the generation stages to the
  pipeline page's "needs your attention" list; `overview` gives spend, request counts and episode budgets.

Review pages per stage: style bible, reference images, keyframes, voices, sound, video, and the pipeline page.
