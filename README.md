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

Real LLM story analysis is not connected yet. The structured LLM interface and mock provider are available for pipeline testing.

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
└── README.md
```

## Database

The local database is PostgreSQL:

```text
Database: MovAI
Port: 5432
```

The database uses pgvector for story embeddings.

Migrations currently exist through:

```text
020_embedding_generation_jobs.sql
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

The database password should not be committed to source control.

## Running the backend

From `C:\MovAi\backend`:

```powershell
uvicorn app.main:app --reload
```

The application is available at:

- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/ui/`
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

Development job execution is currently exposed through:

```text
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/run-mock
POST /api/v1/jobs/{job_id}/cancel
```

Embedding jobs use the `embedding_generation` job type.

Story analysis jobs use the `story_analysis` job type.

The current job runner is development-only. A real persistent worker queue is still needed for production.

## Structured story analysis

The first structured analysis stage is entity extraction. Its provider contract supports:

- Characters
- Locations
- Objects/artifacts
- Events
- Relationships
- Source references
- Confidence values

Current mock analysis returns schema-valid placeholder output. A real LLM provider must be connected before meaningful story analysis can be generated.

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
- Structured LLM provider interface
- Mock entity-extraction stage

Not completed:

- Real LLM provider
- Full entity persistence pipeline
- Entity resolution and alias merging
- Timeline and causal graph generation
- Continuity extraction and conflict resolution
- Master-script generation
- Duration generation from analyzed story
- Season and episode AI segmentation
- Production-grade worker queue
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

