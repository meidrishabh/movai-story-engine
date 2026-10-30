# MovAI web

React + TypeScript UI for MovAI. It is a separate app from the API: it runs on port 5173 and calls the API over HTTP.

## Run

```
cd web
npm install
cp .env.example .env.local     # only if the API is not at http://127.0.0.1:8000
npm run dev                    # http://localhost:5173
```

The API must be running and must allow this origin (`CORS_ORIGINS` in `backend/.env`, default `http://localhost:5173`).

Other scripts: `npm run typecheck`, `npm run build`, `npm run preview`.

## Structure

```
src/
  app/            providers, router, layouts, error boundary
  config/         environment (the only place that reads import.meta.env)
  shared/
    api/          fetch client, ApiError, list envelope
    lib/          formatting and error helpers
    ui/           buttons, cards, badges, notices, states
  features/       one folder per feature
    <feature>/types.ts   response types (hand-written; see below)
    <feature>/api.ts     query keys, queries and mutations (TanStack Query)
    <feature>/*Page.tsx  screens, lazy-loaded from app/router.tsx
  styles/         tokens.css (theme), base.css, components.css
```

Adding a screen: create `features/<name>/`, add its types and hooks, and add one lazy route in `app/router.tsx`
(and a step in `app/layouts/SeriesLayout.tsx` if it belongs to a series).

## Conventions

- Components never call `fetch`; they use hooks from a feature's `api.ts`.
- Every query shows loading, empty and error states (`shared/ui`).
- Colours, spacing and fonts come from `styles/tokens.css` only.
- Polling (pipeline, generation) is configured next to the query with `refetchInterval` and stops when the work is done.

## Response types

Most API endpoints return plain dictionaries without OpenAPI response models, so generated types would be empty. The
types in `features/*/types.ts` are written by hand to match the API. When the backend gains response models, generate
them with `openapi-typescript` and replace these files one feature at a time.
