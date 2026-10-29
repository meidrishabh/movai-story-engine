# MovAI Testing Strategy

## Unit tests

Test pure functions:

- Source validation
- Markdown detection
- Text normalization
- PDF rejection
- Chunk boundaries
- Page provenance
- Complexity analysis
- Embedding provider output
- LLM schema validation

## Repository tests

Use a test database to verify:

- Ownership filtering
- Source/document persistence
- Chunk and embedding writes
- Analysis output versioning
- Episode-plan uniqueness
- Continuity assignments

## Service tests

Test:

- Project/series workflows
- Season readiness rules
- Embedding reprocessing
- Model obsolescence
- Retrieval context construction
- Job transitions
- Analysis-stage persistence

## API tests

Verify:

- Request validation
- Error status codes
- Upload endpoints
- Manual character/episode rejection
- Job status responses
- Ownership isolation

## Integration tests

Recommended flow:

```text
Create project
→ Create series
→ Upload Markdown
→ Parse and chunk
→ Generate embeddings
→ Retrieve context
→ Start analysis job
→ Validate analysis output
→ Create season plan
→ Create episode plan
```

## Regression requirements

Every database migration must be tested against an existing database snapshot. Every provider adapter must be testable through the common provider interface.
