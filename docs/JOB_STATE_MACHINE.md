# MovAI Job State Machine

## States

```text
queued
running
succeeded
failed
cancelled
```

## Valid transitions

```text
queued → running
queued → cancelled
running → succeeded
running → failed
running → cancelled
failed → queued          # retry
```

## Job metadata

- Job type
- Provider
- Provider model
- Request metadata
- Progress 0–100
- Attempt count
- Maximum attempts
- Error summary
- Usage metadata
- Output references
- Start/completion timestamps

## Analysis stage states

Analysis stages use the same lifecycle, with progress and stage-specific output metadata.

## Worker requirements

Production workers must claim jobs safely, update heartbeats, retry transient failures, and avoid marking a job successful before all output persistence succeeds.
