# MovAI — Claude Handoff Checkpoint

Date: 2026-10-30  
Workspace: `C:\MovAi`

## Purpose

This document captures the current MovAI state so development can continue in Claude without repeating previous discussions or refactoring work.

## Product hierarchy

The intended user hierarchy is:

```text
Project
└── Series
    ├── Characters and continuity assets
    ├── Seasons
    │   └── Episodes
    └── Series-level story context
```

The user provides the complete story first. The system processes it, estimates duration, extracts story structure and continuity information, and only then allows season and episode planning.

## Current story workflow

Supported input types for now:

- Pasted text
- Markdown (`.md`)
- Text-based novel PDF

Scanned PDFs and OCR are not supported at this stage.

Current intended flow:

1. User creates or opens a project.
2. User creates or opens a series.
3. User submits the complete story at the series level.
4. The system stores the source document, pages/elements, normalized chunks, and embeddings.
5. The system analyzes the story and estimates total duration.
6. The user selects approximate season count and episode duration.
7. The system creates/plans seasons and later segments the master story into episodes.
8. Characters, costumes, possessions, and continuity objects are generated from story analysis rather than manually added.
9. Users may later add character versions, reference images, and generation assets.

Important product rules:

- The first season is created through planning after story processing; it is not manually created first.
- Additional seasons may be created after the current season reaches an appropriate completed/processed state.
- Users cannot manually create episodes.
- Users cannot manually create characters; characters originate from approved story analysis.
- Character faces/bodies, costumes, possessions, timelines, and continuity must remain consistent across seasons and episodes.

## Backend architecture currently present

Backend location:

```text
C:\MovAi\backend
```

Current target structure:

```text
backend/app/
├── main.py                         # Minimal FastAPI bootstrap and UI mounting
├── db.py                            # SQLAlchemy engine/session dependency
├── core/
│   └── config.py                    # Shared configuration and paths
├── api/
│   ├── dependencies.py              # get_db dependency
│   └── v1/
│       ├── router.py                # Main versioned router
│       ├── analysis.py              # Analysis-run status endpoint
│       ├── analysis_results.py      # Internal extracted-result commit
│       ├── catalog.py               # Projects, series, and episodes
│       ├── characters.py             # Characters, versions, continuity
│       ├── production.py             # Scenes and storyboard frames
│       ├── seasons.py                # Seasons and season episode listing
│       ├── story.py                  # Series-level story pipeline
│       └── workflow.py               # Jobs and approvals
├── schemas/
│   ├── catalog.py
│   ├── characters.py
│   ├── production.py
│   ├── story.py
│   ├── workflow.py
│   └── analysis_results.py
├── repositories/
│   └── analysis_repository.py
├── services/
│   └── document_ingestion.py
├── providers/
│   ├── base.py
│   └── mock.py
├── workers/
└── domain/
```

Architecture notes are also documented in:

```text
C:\MovAi\backend\ARCHITECTURE.md
```

## Extracted API modules

### Catalog

File: `backend/app/api/v1/catalog.py`

Includes:

- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/series`
- `POST /api/v1/projects/{project_id}/series`
- `GET /api/v1/series`
- `POST /api/v1/series`
- `GET /api/v1/series/{series_id}`
- `PATCH /api/v1/series/{series_id}`
- `GET /api/v1/series/{series_id}/episodes`
- `POST /api/v1/series/{series_id}/episodes` — intentionally returns 405
- `PATCH /api/v1/episodes/{episode_id}`

### Seasons

File: `backend/app/api/v1/seasons.py`

Includes:

- `GET /api/v1/series/{series_id}/seasons`
- `POST /api/v1/series/{series_id}/seasons`
- `PATCH /api/v1/seasons/{season_id}`
- `PATCH /api/v1/seasons/{season_id}/pipeline`
- `GET /api/v1/seasons/{season_id}/pipeline`
- `GET /api/v1/seasons/{season_id}/episodes`
- `POST /api/v1/seasons/{season_id}/episodes` — intentionally returns 405

### Series story pipeline

File: `backend/app/api/v1/story.py`

Includes:

- `GET /api/v1/series/{series_id}/pipeline`
- `POST /api/v1/series/{series_id}/sources`
- `POST /api/v1/series/{series_id}/master-script`
- `POST /api/v1/series/{series_id}/analyze`
- `POST /api/v1/series/{series_id}/plan-seasons`

### Characters and continuity

File: `backend/app/api/v1/characters.py`

Includes:

- `GET /api/v1/series/{series_id}/characters`
- `POST /api/v1/series/{series_id}/characters` — intentionally returns 405
- `GET /api/v1/series/{series_id}/continuity`
- `GET /api/v1/characters/{character_id}/versions`
- `POST /api/v1/characters/{character_id}/versions`

### Scenes and storyboards

File: `backend/app/api/v1/production.py`

Includes:

- `GET /api/v1/episodes/{episode_id}/scenes`
- `POST /api/v1/episodes/{episode_id}/scenes`
- `GET /api/v1/scenes/{scene_id}/storyboards`
- `POST /api/v1/scenes/{scene_id}/storyboards`

Storyboard creation creates a queued mock generation job.

### Jobs, approvals, and internal analysis results

Files:

- `backend/app/api/v1/workflow.py`
- `backend/app/api/v1/analysis_results.py`

Includes:

- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/run-mock`
- `POST /api/v1/jobs/{job_id}/cancel`
- `POST /api/v1/approvals`
- `POST /api/v1/internal/seasons/{season_id}/analysis-result`

## Document ingestion and embeddings

File: `backend/app/services/document_ingestion.py`

Current development behavior:

- Accepts normalized text from the source payload.
- Creates a `source_documents` row.
- Creates one document page for text input.
- Creates paragraph-level `document_elements`.
- Splits text into overlapping story chunks.
- Creates or queues `story_embeddings` rows through the embedding job flow.
- Uses the configured embedding provider; local Sentence Transformers is the current default.
- Active local embedding dimension is 384.
- Mock vectors may still exist as obsolete historical rows and must not be mixed with active vectors.

The application does not send embeddings directly to an LLM. Embeddings are used for retrieval/context selection; the retrieved text and structured data are sent to the LLM.

## Database state

Database:

```text
PostgreSQL 13
Database: MovAI
```

pgvector is installed and enabled. The local build used pgvector `0.8.7`.

Applied/created migrations include:

- `backend/db/006_add_seasons.sql`
- `backend/db/007_story_pipeline.sql`
- `backend/db/008_analysis_derived_entities.sql`
- `backend/db/009_series_level_story_pipeline.sql`
- `backend/db/010_series_story_planning.sql`
- `backend/db/011_document_analysis.sql`
- `backend/db/012_continuity_analysis.sql`
- `backend/db/013_document_ingestion_metadata.sql`
- `backend/db/014_analysis_run_stages.sql`
- `backend/db/015_analysis_outputs.sql`
- `backend/db/016_story_integrity_indexes.sql`
- `backend/db/017_embedding_metadata.sql`
- `backend/db/018_continuity_assignment_metadata.sql`
- `backend/db/019_episode_plans.sql`
- `backend/db/020_embedding_generation_jobs.sql`

Migration `013_document_ingestion_metadata.sql` was applied successfully. It adds:

- `source_documents.extraction_status`
- `source_documents.parser_name`
- `source_documents.parser_version`
- `source_documents.text_layer_detected`
- `source_documents.ocr_used`

The database contains the story-analysis tables for sources, documents, pages, elements, chunks, embeddings, analysis runs, timeline/continuity data, characters, costumes, and continuity objects.

The latest migrations add per-stage analysis tracking, versioned analysis outputs, series story indexes, embedding provider/dimension metadata, richer continuity assignments, and reviewable episode plans.

Migration `020` adds the `embedding_generation` job type. New source ingestion now creates chunks and queues an embedding job; the embedding worker persists vectors in batches and marks the source `ready_for_analysis` after completion.

## Latest story-processing update

The pre-LLM story pipeline is now substantially implemented:

- Direct multipart Markdown/PDF uploads are supported.
- `pypdf` and `python-multipart` are installed.
- Scanned/image-only PDFs are rejected; OCR is not used.
- PDF page boundaries are preserved in `document_pages`.
- Story chunks store `chapter_title`, `page_start`, and `page_end`.
- Local Sentence Transformers embeddings are installed and verified.
- Selected local model: `sentence-transformers/all-MiniLM-L6-v2`.
- Real vector dimension: 384.
- Existing mock vectors can be marked obsolete and replaced safely.
- Retrieval filters by active embedding model and version.
- Real similarity retrieval was verified against a re-embedded source.
- A deterministic complexity analyzer is persisted into `analysis_outputs`.
- A structured LLM provider interface has been added.
- A schema-validated mock entity-extraction stage has been added.

Current local embedding configuration:

```text
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

The tested source contains both the old obsolete 1536-dimensional mock vectors and the active 384-dimensional local vectors. Retrieval uses only the active local model/version.

## Story-analysis milestone status

```text
Document intake                 complete
PDF/Markdown parsing            complete
OCR rejection                   complete
Page-aware chunking             complete
Local embeddings                complete
Embedding jobs                  complete for development flow
Similarity retrieval            complete and verified
Complexity analysis             complete for deterministic first pass
Structured LLM interface        complete
Real LLM provider               not connected
Real entity extraction          mock contract only
Timeline/continuity extraction  not complete
Master-script generation        not complete
Season/episode AI splitting     not complete
```

The mock entity-extraction provider currently validates and stores the structured output contract but intentionally returns placeholder results. Meaningful story analysis now requires connecting a real LLM provider.

## Providers

Current provider implementation:

```text
backend/app/providers/mock.py
```

The mock storyboard provider returns metadata only. No real image or video generation is connected yet.

Provider abstraction:

```text
backend/app/providers/base.py
```

Future providers should implement the provider interface instead of being added directly to route handlers.

## Validation already completed

The following checks have passed repeatedly:

- Python compilation for the refactored modules
- FastAPI app import/startup
- OpenAPI generation
- Route registration checks
- No duplicate active route decorators for extracted route groups
- Database migration `013` applied successfully

The application title currently reports:

```text
MovAI API
```

## Latest refactor update (after initial checkpoint)

Since the original checkpoint was created, the following modules were also extracted:

- `backend/app/api/v1/season_story.py`
  - Season-level source upload/listing
  - Season master-script creation/read
  - Season story analysis job creation
  - Episode segmentation planning job creation
- `backend/app/api/v1/system.py`
  - `/health`
  - `/health/db`

The extracted season-story and system routes are registered through `backend/app/api/v1/router.py`, and their active decorators were removed from `main.py`.

OpenAPI validation still reports 34 registered routes and the app imports successfully.

## Current known limitation

`backend/app/main.py` still contains inactive legacy function bodies from the original monolithic implementation. Their route decorators have been removed, so they are not registered in FastAPI. They should be deleted in the final cleanup pass after the remaining season-level story routes are extracted.

The demo overview has also been moved to `backend/app/api/v1/system.py`.

The final cleanup is now complete: `backend/app/main.py` is a minimal bootstrap containing only FastAPI creation, versioned router registration, and UI static-file mounting. The inactive legacy handlers and duplicated schemas were removed from the application entrypoint.

## Current repository and delivery status

- Repository: `https://github.com/meidrishabh/movai-story-engine`
- SSH authentication is configured for Git operations.
- `master` is protected by pull requests, deletion protection, and force-push protection.
- `SECURITY.md`, `CONTRIBUTING.md`, and `.github/dependabot.yml` are present.
- Dependabot normal update pull requests are paused until CI is available.
- Technical documents are organized under `docs/`; `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, and `pitch.md` remain at the root.
- The investor-facing future-state pitch is in `pitch.md`.

Recent branches and pull requests:

- PR #1: repository security and contribution policies — merged.
- PR #2: documentation organization — created for the docs reorganization.
- PR #3: future-state investor pitch — created and updated with the complete product scope.

## Recommended next steps

### 1. Add CI before dependency automation

Create a GitHub Actions workflow covering:

Recommended first tests:

- Project ownership isolation
- Series ownership isolation
- Story source creation
- Document/chunk/embedding creation
- Analysis job lifecycle
- Season planning readiness rules
- Manual character/episode creation rejection
- Storyboard job creation

Keep Dependabot update pull requests paused until these checks pass reliably.

### 2. Connect the real LLM provider

Implement a production provider behind the existing interface for:

- Character, location, object, event, and relationship extraction
- Timeline and causal-graph analysis
- Master-script generation
- Duration estimation
- Season and episode planning

### 3. Persist and review derived story entities

Complete entity resolution, aliases, timeline anchors, continuity assignments, conflicts, and approval flows. Preserve source references for every generated result.

### 4. Add a real job worker

The current `run-mock` endpoint is synchronous and development-only. Replace it with a worker queue before production use.

### 5. Add production authentication and authorization

Replace the development user with real user/session authentication while preserving project and series ownership checks.

### 6. Add visual-generation adapters

Keep provider credentials/configuration outside route handlers. Add provider adapters under `backend/app/providers/`.

The planned production path is cost-aware: generate video at a practical working resolution, upscale to 1080p where appropriate, and run Wan on on-demand NVIDIA GPUs. A 60-minute finished movie is expected to require substantial retry and review budget; early planning estimates are roughly ₹50,000–₹3,00,000 depending on quality, regeneration, GPU choice, and workflow automation.

ElevenLabs is planned for voice generation. The cost is expected to be materially smaller than video generation, but licensing, voice consent, storage, and regeneration must be included in production pricing.

## Important implementation conventions

- Use `apply_patch` for file edits.
- Keep SQL in repositories/services as the refactor continues.
- Keep HTTP validation in routers and Pydantic schemas.
- Keep long-running processing out of request handlers.
- Preserve owner checks using the development user until real authentication is added.
- Do not manually create episodes or characters unless the product rules are intentionally changed.
- Do not add OCR unless the product scope explicitly changes.

