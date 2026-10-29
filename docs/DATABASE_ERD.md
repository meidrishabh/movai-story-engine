# MovAI Database ERD

```mermaid
erDiagram
    users ||--o{ projects : owns
    projects ||--o{ series : contains
    series ||--o{ seasons : contains
    seasons ||--o{ episodes : contains
    series ||--o{ story_sources : owns
    seasons ||--o{ story_sources : receives
    story_sources ||--o{ source_documents : has
    source_documents ||--o{ document_pages : has
    document_pages ||--o{ document_elements : has
    story_sources ||--o{ story_chunks : produces
    story_chunks ||--o{ story_embeddings : has
    series ||--o{ analysis_runs : analyzed
    analysis_runs ||--o{ analysis_run_stages : has
    analysis_runs ||--o{ analysis_outputs : produces
    series ||--o{ characters : contains
    characters ||--o{ character_versions : has
    characters ||--o{ costumes : has
    series ||--o{ continuity_objects : contains
    series ||--o{ story_events : contains
    story_events ||--o{ character_states : changes
    continuity_objects ||--o{ artifact_states : changes
    seasons ||--o{ episode_plans : plans
    episodes ||--o{ scenes : contains
    scenes ||--o{ storyboard_frames : contains
    generation_jobs ||--o{ approvals : supports
```

## Main ownership rules

- Projects belong to users.
- Series belong to projects.
- Characters and continuity objects belong to series.
- Seasons belong to series.
- Episodes belong to seasons and series.
- Sources may belong directly to a series or to a season.
- Analysis runs belong to a series and source.

## Important polymorphic relationships

`continuity_assignments` maps characters, costumes, and continuity objects to seasons, episodes, scenes, and story units using `entity_type` and `entity_id`.

`analysis_outputs` stores versioned JSON payloads with source references for auditability.
