# MovAI Roadmap

Status as of 2026-11-01. MovAI turns a complete story into a consistent series: story understanding first, then references, snapshots, sound, video and a final export. Each phase builds on the one before it, and creators review by exception: the system flags only what it is unsure about.

## Where we are

Done and merged:

- Story upload and processing: Markdown, pasted text and text PDFs are parsed, chunked, embedded and retrievable.
- Background job runner with retries, resume and stale-job recovery.
- Entity extraction over the whole story with a configurable LLM (Gemini flash-lite tested): characters, locations, objects, events and relationships, with quotes checked against the source, stable entity ids, same-name handling and a resolution pass.
- Saved entities with aliases, quote mentions and relationships; reversible merges; hand edits and approvals kept across re-runs.
- Entity review API and page, a cost estimate and call limit per run, one active analysis per series.

Also merged since then: the whole story pipeline (timeline, continuity, master script, filler review, adaptations, episode plans and repair, scene and shot breakdown with verbatim dialogue, look sheets), a migration runner and the web UI for every step.

Built on the generation branch, running only against mock providers (placeholder files, no cost): the style bible, an asset store, the image, video, voice and music provider interfaces, a request queue with dependencies, reference images with a drift check, keyframes per shot, voices and sound with subtitles, video clips per shot, the animatic, and draft and final renders with an ffmpeg media package, plus per-episode budgets and a series-wide pause. The pipeline page lists what needs a person across all stages.

Known gaps in what exists: no real image, video or voice provider is connected; the drift check is a colour-only mock until a vision model is configured; the generation pages have been checked only through the API and a type check, not clicked through in a browser; the second judge model for filler is configured through `JUDGE_LLM_MODEL` and has not had its own vendor key; a long novel has not been run end to end; tests and CI were intentionally skipped.

## The end-to-end flow

| Phase | Covers | Status |
|---|---|---|
| 1. Upload and process | Ingest, parse, chunk, embed | Done (long-story test pending) |
| 2. Story understanding | Characters and entities, timeline, continuity, master script, duration, season and episode plans, scene and shot breakdown, dialogue | Done and merged; verified on two short stories |
| 3. Look and references | Style bible, character images, costumes and artifacts, location references | Built with mock providers; needs a real image provider and a browser check |
| 4. Episode snapshots | One still per shot, regenerate and edit | Built with mock providers (keyframes with continuity and review) |
| 5. Sound and low-res video | Voices, music, effects, subtitles, animatic, low-res clips | Built with mock providers; voice consent recorded, real voices pending |
| 6. Final output | High-res video, assembly, final mix, export | Built: trim, normalize, stitch, audio mix, soft subtitles, 1080p upscale and final export with ffmpeg; real clips pending |

## Milestones

### M1. Story understanding (finish phase 2)

1. **Timeline:** save events with narrative and chronological order; handle flashbacks; link events to entities.
2. **Continuity:** character and object states over time, with conflicts flagged for review.
3. **Master script and duration:** generated from events; per-unit duration estimates.
4. **Season and episode plans:** split along the story, not by page count; user picks season count and episode length; plans are reviewed and approved before episodes exist (episodes stay system-generated).
5. **Scene and shot breakdown with dialogue:** per episode, with who is present, action, camera and duration.
6. **Adaptation options:** after processing, the user picks one main adaptation (full, or concentrated with only filler removed) and optionally a trailer (1-4 min) and a teaser (under 1 min). Each option reports whether it already exists; episode plans follow the chosen adaptation.
7. **Long-story test:** run a full novel through the pipeline and measure calls, time and merge quality against free-tier limits.

Done when a real story goes from upload to approved episode plans and shot lists with no manual database work, and the review page shows only items that need a decision.

### M2. Foundations (before anything is generated)

1. **Migration tracking:** `schema_migrations` table, a runner command, and a baseline for the missing migrations 001 to 005.
2. **Tests and CI:** pytest with the LLM mocked, a test database, and a GitHub Actions workflow; then re-enable Dependabot.
3. **Asset storage:** local folder first, behind an interface that can move to S3-style storage; an `assets` table (file, type, version, owner).
4. **Versions and dependencies:** every generated item records the story, character and style versions it came from; changing an input marks everything downstream stale; hand-edited items are locked.
5. **Approval gates and cost ledger:** every paid step shows an estimate, respects a limit and waits for approval; spending is recorded per project.
6. **UI rewrite:** replace the one-line `app.js` with readable modules; pipeline status, review screens for each stage, and approval controls.
7. **Remote worker:** the job runner can run on another machine (for GPU work) using only database access.

### M3. Look and references (phase 3)

1. **Style bible:** one fixed look per series (art style, palette, lighting) set before any image is made.
2. **Character references:** approved reference images per character and per costume version, stored as the source of truth.
3. **Artifacts and locations:** reference images for key objects and places.
4. **Consistency checks:** automatic comparison of new images against the approved references.
5. **Provider choice** for images (see Decisions).

### M4. Episode snapshots (phase 4)

1. One still per shot, built from the shot list, the style bible and the character references.
2. Regenerate or edit a single shot; keep versions; lock approved shots.
3. Stale tracking when a character, costume or style changes.

### M5. Sound, animatic and low-res video (phase 5)

1. **Audio first (cheaper):** voices for dialogue, music, sound effects and subtitles.
2. **Animatic:** snapshots timed to the audio, to check pacing before paying for video.
3. **Low-res video:** short clips per shot at a working resolution, with regenerate and update.

### M6. Final output (phase 6)

1. High-res rendering (Wan on NVIDIA GPUs) and upscaling to 1080p.
2. Assembly: order, trim, transitions, final audio mix.
3. Export per episode and for the whole series.

### M7. Product readiness (before anyone outside your machine uses it)

1. Real authentication and project ownership.
2. Content moderation and voice-consent records.
3. Deployment: hosted database, object storage, secret management, backups.
4. Revisit the parked items below.

## Working rules

- **Review by exception:** flag uncertain items; do not ask users to check everything.
- **Cost gates:** estimate, limit, then approval for every paid step.
- **Never overwrite reviewed work:** locked and approved items survive re-runs; items that disappear are marked stale, not deleted.
- **Everything is resumable:** store each external call's result so a failure repeats nothing.
- **Free-tier LLMs are for test stories only:** prompts may be used for training.

## Parked (revisit before M7)

- **Language support:** the local embedding model is English-focused; Hindi and other languages need testing, and video prompts may need translation.
- **Rights and licensing:** rights to uploaded source material, model licence terms (Wan, image models), voice cloning rules, labelling AI-generated output.
- **User data handling:** full project deletion (rows, files, stored model replies), backups, and what logs contain.

## Decisions needed

| Decision | Needed by |
|---|---|
| First demo scope: one short episode or a full series | M1 (affects planning defaults) |
| Image provider and GPU access | M3 |
| Video provider and rented GPU | M5 |
| Voice provider (ElevenLabs planned) and consent flow | M5 |
| Object storage vendor | M2 or M7 |
| Season-level story endpoints: keep or remove | M1 |

## Main risks

- **Free-tier limits and outages** (the larger Gemini models were often overloaded): mitigated by flash-lite, fallback models, stored replies and call limits.
- **Visual consistency across episodes:** depends on approved references, a fixed style and automatic checks; the hardest quality problem in M3 to M5.
- **Video cost and iteration:** planning estimates are roughly 50,000 to 3,00,000 rupees for a 60-minute film; the animatic and cost gates exist to limit retries.
- **Long novels at scale:** untested; M1 includes a full-novel run.

## Next step

Add a manual provider for development, on its own branch. Instead of calling an image or video API it leaves the request `awaiting_input`, shows the exact prompt and reference images in the UI, and takes the result through the existing upload endpoint (`POST /api/v1/generation-requests/{id}/result`), so a person generating in the Muse AI sandbox acts as the API. Muse limits to design around: no negative prompt, seed or camera controls (fold them into the prompt text); clips come out at about 10 seconds and cannot be set, so the media layer trims them to the shot length; 4 images per chat request and 6 videos per message, so group requests in those sizes. After that: click through every generation page in a browser, connect real providers, and run one long story end to end.
