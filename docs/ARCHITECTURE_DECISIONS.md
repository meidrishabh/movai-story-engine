# MovAI Architecture Decisions

## ADR-001: FastAPI and Python

Decision: Use Python/FastAPI for the initial backend.

Reason: Strong document, NLP, embedding, and AI-provider ecosystem with fast iteration.

## ADR-002: PostgreSQL and pgvector

Decision: Use PostgreSQL as the primary database and pgvector for embeddings.

Reason: Relational ownership/transaction support plus vector retrieval in one system.

## ADR-003: Series-first story ingestion

Decision: Accept the complete story before requiring season creation.

Reason: Total duration, narrative arcs, characters, and continuity need whole-series context.

## ADR-004: No OCR initially

Decision: Reject scanned/image-only PDFs.

Reason: OCR adds accuracy, cost, and review complexity; it is outside the current MVP scope.

## ADR-005: Provider interfaces

Decision: Hide embedding, LLM, and media vendors behind provider interfaces.

Reason: Models and vendors can change without rewriting routes or business services.

## ADR-006: System-generated episodes

Decision: Users configure preferences but do not manually create episodes.

Reason: Episodes must preserve story arcs, climax placement, and continuity.

## ADR-007: Local embeddings for development

Decision: Use Sentence Transformers locally during development.

Reason: No per-request vendor cost and suitable for single-user testing.

## ADR-008: Postgres-backed job runner

Decision: Run background work with a polling worker (`python -m app.workers.job_runner`) that claims rows from `generation_jobs` using `FOR UPDATE SKIP LOCKED`, with retries, backoff and stale-job recovery.

Reason: No extra infrastructure while keeping job state in one place. A Redis or Celery queue can replace it later without changing job rows.

## ADR-009: One OpenAI-compatible LLM adapter, provider chosen by configuration

Decision: Reach hosted and local models through a single OpenAI-style `/chat/completions` adapter configured by `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`, with optional fallback models. For the MVP the default is a Gemini flash-lite model on the free tier.

Reason: Free-tier and local options change often. One adapter lets the model be swapped from `.env`. Large Gemini Flash models were frequently overloaded, so the smaller model is the default. Free tiers may use prompts to improve the vendor's products, so they are suitable for test stories only.

## ADR-010: Entities have ids; names are not unique

Decision: Characters, locations and objects are identified by id. The same name may repeat in a series when `disambiguation` labels differ. Merges are reversible (`merged_into_id`), hand edits set `locked`, and entries not seen in the latest run are marked `stale`, never deleted.

Reason: Novels reuse names (generations, titles). Name-unique storage silently merged different people, and re-analysis must never overwrite reviewed work.

## ADR-011: Extraction keeps stable ids, verifies quotes and stores every call

Decision: Entities get stable ids (E/L/O) that are fed back to the model on later calls together with descriptions and relationships. The model must quote the source; quotes are checked against the text. Each LLM reply is stored in `analysis_batches`, so a failed run resumes without new calls and merge logic can be re-run for free. A final resolution call proposes merges of entries that are the same entity.

Reason: Keeps names consistent across a long story, catches invented details, and bounds cost on rate-limited free tiers. Uncertain cases are flagged for review instead of decided silently.
