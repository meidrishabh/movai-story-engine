# MovAI Deployment and Operations

## Current local deployment

```text
Windows
├── FastAPI/Uvicorn
├── PostgreSQL 13
├── pgvector
└── Local Sentence Transformer model
```

## Start backend

```powershell
cd C:\MovAi\backend
python -m pip install -r requirements.txt
python -m app.migrate
powershell -File .\dev.ps1     # the API and the job runner, each in its own window
```

Run one API and one job runner per checkout, from the same folder. They share the asset folder (`STORAGE_DIR`), and a
runner started from another checkout writes its files where this API cannot see them. Restart the job runner after
pulling new code: a running runner keeps the old code and will not claim newer job types (`generation_request`,
`sound_generation`, `episode_render`).

Start the web app separately: `cd C:\MovAi\web; npm install; npm run dev` (http://localhost:5173).

## Configuration

```env
DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/MovAI
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

## Media generation

- Providers are `mock` by default (`IMAGE_PROVIDER`, `VIDEO_PROVIDER`, `VOICE_PROVIDER`, `MUSIC_PROVIDER`); the whole
  flow runs without any paid service. See `backend/.env.example`.
- ffmpeg is required for clips, the animatic, stitching and the final export: `winget install Gyan.FFmpeg`, or set
  `FFMPEG_PATH`. After installing, open a new shell so PATH updates.
- Generated and uploaded files live in `backend/storage/` (git-ignored). Back this folder up with the database.
- Pause switch: `POST /api/v1/series/{id}/generation/pause` holds every queued request for a series, and `/resume`
  queues them again. Per-episode retry limits, cost caps and pause are on the Video page.
- Next provider: a manual adapter for development. It leaves requests `awaiting_input`, shows the prompt and
  references in the UI, and takes the result through `POST /api/v1/generation-requests/{id}/result`.

## Database operations

- Apply migrations in numeric order.
- Back up before schema changes.
- Verify pgvector is enabled.
- Do not mix embedding models in retrieval.

## Operational checks

```text
/health
/health/db
```

## Future production requirements

- Process manager/container deployment
- Object storage for uploads and media
- Persistent job queue
- Worker fleet
- Secret manager
- Centralized logs
- Metrics and alerts
- Database backups
- Authentication and authorization
