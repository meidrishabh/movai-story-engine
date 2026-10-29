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
uvicorn app.main:app --reload
```

## Configuration

```env
DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/MovAI
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

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
