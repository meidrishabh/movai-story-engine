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
