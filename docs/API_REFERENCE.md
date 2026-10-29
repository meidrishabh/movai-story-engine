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
| POST | `/series/{series_id}/analyze` | Start series analysis |
| POST | `/series/{series_id}/plan-seasons` | Plan seasons |
| POST | `/seasons/{season_id}/analyze` | Start season analysis |
| POST | `/seasons/{season_id}/plan-episodes` | Queue episode planning |
| POST | `/internal/seasons/{season_id}/analysis-result` | Commit structured result |

## Jobs

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/jobs/{job_id}` | Get job status |
| POST | `/jobs/{job_id}/run-mock` | Run development job |
| POST | `/jobs/{job_id}/cancel` | Cancel queued/running job |

## Response conventions

```json
{"count": 1, "items": []}
```

Errors use HTTP status codes 400, 404, 405, 409, 422, and 500 with a `detail` field.
