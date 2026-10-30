# MovAI API Reference

Base URL: `http://127.0.0.1:8000/api/v1`

## System

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | API health |
| GET | `/health/db` | Database health |
| GET | `/demo/overview` | Development demo overview |

## Projects and series

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/projects` | List projects |
| POST | `/projects` | Create project |
| GET | `/projects/{project_id}` | Get project |
| PATCH | `/projects/{project_id}` | Update project |
| GET | `/projects/{project_id}/series` | List project series |
| POST | `/projects/{project_id}/series` | Create series |
| GET | `/series` | List series |
| POST | `/series` | Create default-studio series |
| GET | `/series/{series_id}` | Get series |
| PATCH | `/series/{series_id}` | Update series |

## Story sources

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/series/{series_id}/sources` | Submit text source |
| POST | `/series/{series_id}/sources/upload` | Upload Markdown/PDF |
| GET | `/seasons/{season_id}/sources` | List season sources |
| POST | `/seasons/{season_id}/sources` | Submit season source |
| POST | `/seasons/{season_id}/sources/upload` | Upload season Markdown/PDF |

Supported uploads: Markdown and text-layer PDF. OCR is rejected.

## Analysis and planning

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/series/{series_id}/pipeline` | Series story status |
| GET | `/series/{series_id}/analysis-estimate` | Estimated LLM calls, tokens and minimum time for the latest source |
| GET | `/series/{series_id}/timeline` | Timeline anchors (in story order) and events with their chronological position |
| GET | `/series/{series_id}/continuity` | Characters, costumes and continuity objects (catalogue) |
| GET | `/series/{series_id}/continuity/states` | Character/object states per event and detected continuity conflicts |
| GET | `/series/{series_id}/master-script` | Latest master script with its ordered story units and screen-time estimates |
| GET | `/series/{series_id}/episode-plans` | Draft episode plans (season, title, synopsis, duration, characters) |
| PATCH | `/episode-plans/{plan_id}` | Edit a draft plan (title, synopsis, hook, climax, ending, note) |
| POST | `/episode-plans/{plan_id}/approve` | Approve one plan; creates the episode |
| POST | `/series/{series_id}/episode-plans/approve-all` | Approve every draft plan |
| POST | `/episode-plans/{plan_id}/reject` | Reject a draft plan (optional `review_note`) |
| GET | `/series/{series_id}/breakdown` | Every episode with its breakdown state: `scene_count`, `shot_seconds` against `target_duration_seconds`, `breakdown_stale`, and the latest breakdown `job_status` / `job_error` |
| POST | `/series/{series_id}/breakdown` | Queue a breakdown for every episode that has none or is stale and has no job running (202, `{queued}`) |
| GET | `/series/{series_id}/appearance` | Newest reference sheet per character (user-approved first, else the draft read from the story): description, face and body, clothing, distinctive features, colours, voice, `costumes`, and `change_notes` with the evidence quotes. Fields the story does not state are null |
| PUT | `/characters/{character_id}/appearance` | Save the user's sheet. It becomes the approved version, so re-analysis never overwrites it |
| POST | `/series/{series_id}/appearance/generate` | Read the story again for how characters look (202, a queued job). Approved sheets are kept |
| POST | `/episodes/{episode_id}/breakdown` | Queue a scene/shot/dialogue breakdown job (202) |
| GET | `/episodes/{episode_id}/breakdown` | Scenes with dialogue and shots for an episode, `stale` (the cut changed since it was built) and the episode's bridge `continuity_notes` |
| GET | `/series/{series_id}/adaptations` | Full, concentrated, trailer and teaser options: duration, status, `available` (already generated and current), `selected`, `removed` beats (proposed, judged and not reused later), `disputed` beats (kept in the story, with reasons), trailer/teaser summary |
| PUT | `/series/{series_id}/adaptation-selection` | Not used by the UI: episodes always plan from the concentrated cut when one is ready. Saves `main` (`full` or `concentrated`), optional `trailer_seconds` (60-240) and `teaser_seconds` (10-59). Returns `to_generate` for extras that do not exist yet |
| PUT | `/series/{series_id}/adaptations/concentrated/beats` | Body `unit`, `beat`, `action`: `keep` restores a removed beat, `cut` removes a disputed (or earlier restored) beat. Logged as a user decision that survives regeneration. Returns the updated lists, `affected_episodes` (approved episodes whose length changed) and `repair_job`: a queued job that rewrites those episodes' synopses and length, writes bridge notes for them and their neighbours, and marks existing breakdowns stale. 404 if the beat is not in the list it would move from |
| POST | `/series/{series_id}/adaptations/{kind}/generate` | Queue generation (`concentrated`, `trailer` or `teaser`, optional `target_seconds`); regenerates when it already exists (202) |
| POST | `/series/{series_id}/episode-plans/generate` | Re-plan seasons and episodes for the selected main adaptation (202); refused if episodes are approved for a different adaptation |
| POST | `/series/{series_id}/analyze` | Queue series analysis (409 if one is already queued or running; 400 above the call limit). The response includes the estimate. |
| POST | `/series/{series_id}/plan-seasons` | Plan seasons |
| POST | `/seasons/{season_id}/analyze` | Start season analysis |
| POST | `/seasons/{season_id}/plan-episodes` | Queue episode planning |
| POST | `/internal/seasons/{season_id}/analysis-result` | Commit structured result |

## Entities and review

Characters, locations and objects found by analysis. `kind` is `character`, `location` or `object`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/series/{series_id}/entities` | List entities with review status, aliases and quote counts |
| PATCH | `/entities/{kind}/{entity_id}` | Edit name, label, description; approve or flag. Any edit locks the entry against re-analysis. |
| POST | `/entities/{kind}/{entity_id}/merge` | Merge into another entry (`{"into_id": "..."}`); reversible |
| POST | `/entities/{kind}/{entity_id}/unmerge` | Undo a merge |

The same name may appear more than once in a series when entries carry different `disambiguation` labels.

## Jobs

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/jobs/{job_id}` | Get job status |
| POST | `/jobs/{job_id}/run-mock` | Run a mock-provider job inline (development only). Real jobs are run by the job runner. |
| POST | `/jobs/{job_id}/cancel` | Cancel queued/running job |

## Response conventions

```json
{"count": 1, "items": []}
```

Errors use HTTP status codes 400, 404, 405, 409, 422, and 500 with a `detail` field.
