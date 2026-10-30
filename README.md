# MovAI

MovAI is an AI-assisted drama and story production platform. It accepts a complete story, processes the source into structured narrative data, and prepares the story for character, continuity, season, episode, storyboard, image, and video generation.

## Current product hierarchy

```text
Project
└── Series
    ├── Characters and continuity
    ├── Seasons
    │   └── Episodes
    └── Series-level story source and master script
```

## Current story flow

```text
Upload or paste story
→ Validate input
→ Parse Markdown or text-based PDF
→ Reject scanned/OCR-only PDF
→ Preserve pages and sections
→ Create page-aware story chunks
→ Generate embeddings
→ Store vectors in pgvector
→ Retrieve relevant context
→ Analyze deterministic complexity
→ Run structured LLM analysis
→ Generate master script
→ Estimate duration
→ Plan seasons
→ Plan episodes
```

Entity extraction runs through a configurable LLM (see [LLM configuration](#llm-configuration)). The later stages (timeline, continuity, master script, duration, season and episode planning) are not built yet.

## Technology

- Python
- FastAPI
- PostgreSQL 13
- pgvector
- SQLAlchemy
- Pydantic
- Sentence Transformers
- PyTorch
- pypdf
- Vanilla HTML/CSS/JavaScript UI currently served by FastAPI

## Project structure

```text
MovAi/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI bootstrap only
│   │   ├── db.py                      # SQLAlchemy database setup
│   │   ├── core/                      # Shared configuration
│   │   ├── api/v1/                    # Versioned HTTP routers
│   │   ├── schemas/                   # Request/output contracts
│   │   ├── repositories/              # Database access
│   │   ├── services/                  # Business workflows
│   │   ├── providers/                 # LLM, embedding, and media adapters
│   │   └── workers/                   # Long-running processing boundaries
│   ├── db/                            # SQL migrations
│   ├── requirements.txt
│   └── ARCHITECTURE.md
├── frontend/                          # Current UI
├── docs/                               # Design, API, operations, and project documentation
└── README.md
```

## Documentation

- [Product Pitch](pitch.md)
- [High-Level Design](docs/HLD.md)
- [Low-Level Design](docs/LLD.md)
- [API Reference](docs/API_REFERENCE.md)
- [Database ERD](docs/DATABASE_ERD.md)
- [Story Processing Specification](docs/STORY_PROCESSING_SPEC.md)
- [Testing Strategy](docs/TESTING_STRATEGY.md)
- [Deployment and Operations](docs/DEPLOYMENT_OPERATIONS.md)
- [Architecture Decisions](docs/ARCHITECTURE_DECISIONS.md)
- [Claude Handoff Checkpoint](docs/MOVAI_CLAUDE_HANDOFF_CHECKPOINT.md)

## Database

The local database is PostgreSQL:

```text
Database: MovAI
Port: 5432
```

The database uses pgvector for story embeddings.

Migrations currently exist through:

```text
022_entity_identity.sql
```

Important database areas:

```text
projects, series, seasons, episodes
story_sources, source_documents, document_pages, document_elements
story_chunks, story_embeddings
analysis_runs, analysis_run_stages, analysis_outputs
timeline_anchors, story_events, timeline_relations
characters, character_versions, costumes
continuity_objects, continuity_assignments
character_states, artifact_states, continuity_conflicts
episode_plans, generation_jobs, approvals
```

## Backend setup

From the backend directory:

```powershell
cd C:\MovAi\backend
```

Create or activate the virtual environment if needed:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a `.env` file in `backend/`:

```env
DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/MovAI
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

Copy `backend/.env.example` to start. All settings (including the LLM ones below) are read from this file. The database password and API keys should not be committed to source control.

## Running the backend

Analysis runs as background jobs, so two processes are needed: the API and the job runner. From `C:\MovAi\backend`:

```powershell
powershell -File .\dev.ps1     # opens both in separate windows
```

Or by hand, in two terminals:

```powershell
uvicorn app.main:app --reload
python -m app.workers.job_runner
```

Without the job runner, uploaded stories stay "queued". `python -m app.workers.job_runner --once` processes the queue and exits.

The application is available at:

- API: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`
- UI: a separate app on its own port (being rebuilt in React + TypeScript); the API only serves JSON.
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`
- Database health: `http://127.0.0.1:8000/health/db`

## Applying migrations

PostgreSQL 13 `psql.exe` is expected at the default Windows installation path. Apply migrations in numeric order:

```powershell
$env:PGPASSWORD = "<password>"
Get-ChildItem .\db -Filter "*.sql" | Sort-Object Name | ForEach-Object {
    & "C:\Program Files\PostgreSQL\13\bin\psql.exe" `
        -v ON_ERROR_STOP=1 `
        -U postgres `
        -d MovAI `
        -h localhost `
        -f $_.FullName
}
```

Do not reapply migrations casually against a production database. Use migration tracking before production deployment.

## Story upload endpoints

JSON text source:

```text
POST /api/v1/series/{series_id}/sources
POST /api/v1/seasons/{season_id}/sources
```

Multipart file upload:

```text
POST /api/v1/series/{series_id}/sources/upload
POST /api/v1/seasons/{season_id}/sources/upload
```

Supported files:

- `.md`
- `.markdown`
- Text-based `.pdf`

Scanned PDFs and OCR-based extraction are rejected.

## Embeddings

The local provider uses:

```text
sentence-transformers/all-MiniLM-L6-v2
```

Its vectors have 384 dimensions.

Enable local embeddings:

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

The mock provider remains available for development:

```env
EMBEDDING_PROVIDER=mock
```

Do not mix vectors from different models in retrieval. The application stores model/version metadata and marks old vectors as obsolete during re-embedding.

## Processing jobs

Jobs live in `generation_jobs` and are run by the job runner (`python -m app.workers.job_runner`), which claims queued jobs safely, retries failures with a growing delay, fails permanent errors (bad API key, call limit reached) at once, and requeues jobs whose worker went silent.

```text
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/run-mock      # development only, mock-provider jobs
```

Job types handled by the runner: `embedding_generation` and `story_analysis`.

## LLM configuration

Set in `backend/.env` (see `backend/.env.example`):

```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=<model name>
LLM_API_KEY=<your key>
LLM_MIN_INTERVAL_SECONDS=6
```

Any OpenAI-style endpoint works (Gemini, OpenRouter, Ollama). With `LLM_PROVIDER=mock` (the default) a crude offline guesser is used. Free-tier models may use prompts for training, so use them with test stories only. Before queueing, `GET /api/v1/series/{id}/analysis-estimate` shows the expected number of calls.

A sample story for trying the pipeline is in `docs/samples/happy_flow_story.md`.

## Structured story analysis

Entity extraction reads the whole story in batches and produces characters, locations, objects, events and relationships, each with a quoted piece of evidence checked against the source text. Entities keep stable ids across batches, same-named characters are kept apart by a disambiguation label, and a final pass looks for entries that are the same entity under different names. Results are saved to the database, and uncertain items are marked `needs_review`.

Review them through the entities API (a review screen is part of the new UI): approve, edit, merge or unmerge. Hand edits and approvals are kept when the story is analysed again. Details are in [Story Processing Specification](docs/STORY_PROCESSING_SPEC.md).

## Current status

Completed:

- Modular FastAPI routers
- Modular schemas
- Repository/service structure started
- Project/series catalog services
- Season service
- Text and Markdown ingestion
- PDF text-layer parsing
- OCR/scanned-PDF rejection
- Page-aware chunks
- Local embeddings
- Model-aware retrieval
- Complexity analysis
- Analysis stage/output persistence
- Structured LLM provider interface and an OpenAI-compatible adapter
- Postgres-backed job runner with retries and resume
- Whole-story entity extraction with quote verification
- Entity resolution, alias merging, and persistence of characters, locations and objects
- Entity review API and page

Not completed:

- Timeline and causal graph generation
- Continuity extraction and conflict resolution
- Master-script generation
- Duration generation from analyzed story
- Season and episode AI segmentation
- Production authentication
- Automated test suite

## Development principles

New backend changes should follow:

```text
Router
→ Schema validation
→ Service/use-case
→ Repository/database access
→ Provider or worker
```

Keep raw SQL out of routers, keep provider-specific logic behind interfaces, and keep long-running processing outside request handlers.

