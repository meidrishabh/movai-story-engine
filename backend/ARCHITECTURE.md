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
