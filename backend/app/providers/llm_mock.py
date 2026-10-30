import re
from collections import Counter

from app.providers.llm_base import LLMAnalysisRequest, LLMAnalysisResponse, chunk_reference

# Words that start sentences or appear capitalised without naming anyone.
_COMMON = {
    "The", "A", "An", "And", "But", "Or", "He", "She", "It", "They", "We", "I", "You",
    "His", "Her", "Their", "Its", "This", "That", "These", "Those", "There", "Then",
    "When", "While", "As", "At", "In", "On", "Of", "To", "For", "With", "From", "By",
    "If", "So", "Not", "No", "Yes", "What", "Who", "Why", "How", "Where", "After",
    "Before", "Chapter", "Page", "One", "Two", "Three", "Now", "Once", "Still",
}


class MockLLMProvider:
    """Offline stand-in that guesses entities from capitalised words.

    It is deliberately crude: it exists so the whole pipeline can be exercised
    without an API key. Real analysis needs a configured LLM provider.
    """

    def analyze(self, request: LLMAnalysisRequest) -> LLMAnalysisResponse:
        if request.task == "entity_resolution":
            return LLMAnalysisResponse(
                provider="mock", model="mock-entity-analyzer-v2",
                prompt_version="entity-resolution-mock-v1",
                payload={"groups": []}, usage_metadata={"mode": "development_placeholder", "calls": 1},
            )
        counts: Counter[str] = Counter()
        refs_by_name: dict[str, list[dict]] = {}
        for chunk in request.context_chunks:
            # Skip a capital that merely starts a sentence.
            for match in re.finditer(r"(?<![.!?\"“]\s)(?<!^)\b([A-Z][a-z]{2,})\b", chunk["text"]):
                word = match.group(1)
                if word in _COMMON:
                    continue
                counts[word] += 1
                refs = refs_by_name.setdefault(word, [])
                reference = chunk_reference(chunk)
                if reference not in refs:
                    refs.append(reference)

        characters = [
            {"name": name, "role": None, "aliases": [], "confidence": 0.3, "evidence": name,
             "source_references": refs_by_name[name]}
            for name, count in counts.most_common(8)
            if count >= 2
        ]
        events = [
            {
                "title": chunk.get("chapter_title") or f"Passage {chunk['narrative_position']}",
                "description": chunk["text"][:160].strip(),
                "event_type": "scene",
                "evidence": chunk["text"][:60].strip(),
                "narrative_position": chunk["narrative_position"],
                "confidence": 0.2,
                "source_references": [chunk_reference(chunk)],
            }
            for chunk in request.context_chunks
        ]
        return LLMAnalysisResponse(
            provider="mock",
            model="mock-entity-analyzer-v2",
            prompt_version="entity-extraction-mock-v2",
            payload={
                "characters": characters,
                "locations": [],
                "objects": [],
                "events": events,
                "relationships": [],
                "analysis_notes": ["Mock provider: entities guessed from capitalised words."],
            },
            usage_metadata={"mode": "development_placeholder", "calls": 1},
        )
