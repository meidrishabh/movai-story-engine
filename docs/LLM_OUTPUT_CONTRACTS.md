# LLM Output Contracts

All provider responses must be JSON-compatible and validated with Pydantic before persistence.

## Entity extraction

```json
{
  "characters": [],
  "locations": [],
  "objects": [],
  "events": [],
  "relationships": [],
  "analysis_notes": []
}
```

## Character contract

```json
{
  "name": "Maya",
  "role": "scientist",
  "personality": "cautious and analytical",
  "story_role": "protagonist",
  "aliases": ["Dr. Maya"],
  "source_references": [],
  "confidence": 0.91
}
```

## Event contract

```json
{
  "title": "The signal appears",
  "description": "Maya detects the repeating signal.",
  "event_type": "inciting_incident",
  "narrative_position": 4,
  "chronological_position": 2,
  "timeline_label": "primary",
  "source_references": [],
  "confidence": 0.88
}
```

## Rules

- Unknown values must be `null`, empty arrays, or empty strings according to the schema.
- Do not invent source references.
- Reject malformed JSON.
- Persist provider/model/prompt version.
- Store the raw validated payload in `analysis_outputs`.
- Store confidence separately from approval status.
