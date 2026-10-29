# MovAI Low-Level Design

Version: 0.1  
Scope: story ingestion, embeddings, retrieval, analysis jobs, continuity, and season/episode planning.

## 1. Architecture

```text
HTTP Router
  -> Pydantic Schema
  -> Application Service
  -> Repository
  -> PostgreSQL / pgvector
```

Long-running work follows:

```text
HTTP Router -> generation_jobs -> Worker -> Provider -> Repository
```

`backend/app/main.py` is only the FastAPI bootstrap. New business logic must not be added there.

## 2. Modules

```text
app/
├── main.py                  # FastAPI bootstrap
├── db.py                    # SQLAlchemy engine/session
├── core/                    # Configuration
├── api/v1/                  # HTTP routers
├── schemas/                 # Pydantic contracts
├── repositories/            # SQL and persistence
├── services/                # Business workflows
├── providers/               # LLM, embedding, and media adapters
└── workers/                 # Long-running job boundaries
```

## 3. Story input flow

```text
Text/Markdown/PDF upload
  -> source validation
  -> document parser
  -> text normalization
  -> document/page/element persistence
  -> page-aware chunking
  -> embedding job
```

Supported sources:

- Pasted text
- Markdown
- Text-based PDF

Scanned PDFs and OCR are rejected.

Upload endpoints:

```text
POST /api/v1/series/{series_id}/sources
POST /api/v1/series/{series_id}/sources/upload
POST /api/v1/seasons/{season_id}/sources
POST /api/v1/seasons/{season_id}/sources/upload
```

## 4. Validation and parsing

`source_validation.py` returns:

```python
ValidatedStorySource(
    source_type,
    input_format,
    parser_name,
    parser_version,
    text_layer_detected,
    ocr_used,
)
```

`document_parsers.py` returns:

```python
ParsedDocument(
    text,
    page_texts,
    parser_name,
    parser_version,
    text_layer_detected,
    ocr_used,
)
```

Invalid content returns HTTP 422.

## 5. Document persistence

```text
story_sources
  └── source_documents
        └── document_pages
              └── document_elements
```

`source_documents` stores file hash, parser metadata, page count, extraction status, and OCR flags.

`document_pages` stores page number, extracted text, text length, and extraction status.

`document_elements` currently stores paragraph elements with page-local ordering.

## 6. Chunking

The current chunker uses approximately 900 words with 100 words of overlap.

Each `story_chunks` record contains:

- Source and document IDs
- Narrative position
- Chapter title
- Page start/end
- Text content
- Estimated token count
- Metadata

Page ranges are calculated against normalized page offsets. This preserves source provenance for later analysis.

## 7. Embedding architecture

```text
EmbeddingService
  -> EmbeddingProvider
       ├── MockEmbeddingProvider
       └── LocalSentenceTransformerProvider
```

Provider output:

```python
EmbeddingResult(
    vector=[...],
    provider="sentence-transformers",
    model="sentence-transformers/all-MiniLM-L6-v2",
    version="v1",
    dimensions=384,
)
```

Configuration:

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

Retrieval always filters by active model, version, and `generation_status = 'complete'`. Old vectors are marked `obsolete` during re-embedding.

## 8. Embedding job flow

```text
Create chunks
  -> create embedding_generation job
  -> worker reads pending chunks
  -> provider generates batch vectors
  -> repository persists vectors
  -> repeat until complete
  -> source becomes ready_for_analysis
```

Current development execution uses:

```text
POST /api/v1/jobs/{job_id}/run-mock
```

The production worker still needs queue claiming, retries, backoff, and restart recovery.

## 9. Retrieval flow

```text
Analysis query
  -> EmbeddingService embeds query
  -> pgvector similarity search
  -> direct matching chunks
  -> neighboring narrative chunks
  -> ordered context package
```

Retrieval context includes chunk ID, narrative position, chapter, page range, text, and direct-match status.

## 10. Complexity analysis

The deterministic analyzer measures:

- Word count
- Paragraph count
- Heading count
- Dialogue density
- Timeline markers
- Multi-world markers

Profiles:

```text
standard | complex | temporal | multi_world
```

Results are stored in:

```text
series.analysis_profile
series.analysis_complexity
analysis_run_stages
analysis_outputs
```

## 11. Analysis runs

`analysis_runs` represents one complete attempt.

`analysis_run_stages` tracks:

```text
validate_input
parse_document
chunk_story
generate_embeddings
complexity_analysis
entity_extraction
timeline_construction
continuity_analysis
master_script_generation
duration_estimation
```

Stage state machine:

```text
queued -> running -> succeeded
queued -> running -> failed
queued -> cancelled
```

`analysis_outputs` stores versioned JSON payloads and source references.

## 12. Structured LLM boundary

The provider boundary is:

```python
LLMAnalysisRequest(
    task,
    profile,
    context_chunks,
    known_entities,
)
```

```python
LLMAnalysisResponse(
    provider,
    model,
    prompt_version,
    payload,
    usage_metadata,
)
```

The first task is `entity_extraction`. Its validated output supports:

- Characters
- Locations
- Objects/artifacts
- Events
- Relationships
- Source references
- Confidence values

The current implementation uses a schema-compatible mock provider.

## 13. Entity extraction flow

```text
Analysis job
  -> retrieve relevant chunks
  -> provider receives structured request
  -> validate JSON with EntityExtractionResult
  -> persist analysis_run_stages row
  -> persist analysis_outputs row
```

The next implementation must persist validated entities into domain tables and resolve aliases.

## 14. Continuity model

```text
characters
character_versions
costumes
continuity_objects
  -> continuity_assignments
  -> character_states / artifact_states
  -> continuity_conflicts
```

Timeline support includes:

- Timeline anchors
- Story events
- Timeline relations
- Narrative and chronological positions
- World IDs
- Character states
- Artifact states
- World rules
- Entity aliases

## 15. Season and episode flow

```text
Processed series story
  -> duration estimate
  -> user season preferences
  -> season plan
  -> episode segmentation job
  -> episode_plans
  -> review/approval
  -> final episodes
```

Episodes and characters are not manually created under current product rules.

## 16. Database groups

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

## 17. Error handling

```text
400  Invalid workflow request
404  Resource not found or not owned
405  Product-forbidden manual operation
409  Invalid state transition/conflict
422  Invalid input or structured output
500  Unexpected provider/persistence failure
```

Mutating services must commit only after all writes succeed and roll back on failure.

## 18. Immediate next milestone

Connect a real structured-output LLM provider behind `LLMProvider` and implement entity persistence:

```text
Retrieved context
  -> real LLM JSON
  -> Pydantic validation
  -> entity resolution
  -> characters/locations/objects/events
  -> analysis_outputs provenance
```

## 19. Current limitations

- Real LLM provider is not connected.
- Mock entity extraction returns placeholder results.
- Full entity resolution is not implemented.
- Timeline and causal extraction is not implemented.
- Master-script generation is not implemented.
- AI season/episode segmentation is not implemented.
- Production queue/retry infrastructure is not implemented.
- Authentication and automated tests are deferred.

