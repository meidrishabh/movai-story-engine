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


def _mock_timeline(request: LLMAnalysisRequest) -> dict:
    events = request.task_input.get("events", [])
    return {"anchors": [{"label": "Story", "description": "Mock: single anchor"}],
            "events": [{"id": e["id"], "anchor": "Story", "narrative_layer": "main"} for e in events]}


def _mock_continuity(request: LLMAnalysisRequest) -> dict:
    return {"character_states": [], "object_states": [], "conflicts": []}


def _mock_continuity_check(request: LLMAnalysisRequest) -> dict:
    return {"conflicts": []}


def _mock_master_script(request: LLMAnalysisRequest) -> dict:
    units = []
    for index, chunk in enumerate(request.context_chunks):
        words = len(chunk["text"].split())
        units.append({
            "title": chunk.get("chapter_title") or f"Passage {chunk['narrative_position']}",
            "synopsis": chunk["text"][:200].strip(), "beats": [chunk["text"][:80].strip()],
            "characters": [], "locations": [], "screen_seconds": max(20, words // 3),
            "source_references": [chunk_reference(chunk)],
        })
    return {"units": units, "running_summary": ""}


def _mock_episode_plan(request: LLMAnalysisRequest) -> dict:
    units = request.task_input.get("units", [])
    target = max(60, int(request.task_input.get("target_episode_seconds") or 600))
    episodes, start, seconds = [], 1, 0
    for unit in units:
        seconds += unit.get("screen_seconds") or 0
        if seconds >= target:
            episodes.append((start, unit["number"]))
            start, seconds = unit["number"] + 1, 0
    if units and start <= units[-1]["number"]:
        episodes.append((start, units[-1]["number"]))
    return {"seasons": [{"title": "Season 1", "synopsis": "Mock plan", "episodes": [
        {"title": f"Episode {i}", "synopsis": "", "unit_from": a, "unit_to": b}
        for i, (a, b) in enumerate(episodes, start=1)]}]}


def _mock_scene_breakdown(request: LLMAnalysisRequest) -> dict:
    scenes = []
    for unit in request.task_input.get("units", []):
        scenes.append({"title": unit.get("title"), "description": unit.get("synopsis") or unit.get("title") or "Scene",
                       "shots": [{"description": unit.get("synopsis") or "Shot", "camera": "wide", "duration_seconds": 5}]})
    return {"scenes": scenes}


def _mock_filler(request: LLMAnalysisRequest) -> dict:
    return {"removals": []}


def _mock_filler_judge(request: LLMAnalysisRequest) -> dict:
    return {"verdicts": [{"id": c["id"], "verdict": "keep", "reason": "mock"} for c in request.task_input.get("candidates", [])]}


def _mock_episode_repair(request: LLMAnalysisRequest) -> dict:
    return {"episodes": [{"number": e["number"], "synopsis": e["synopsis"] if e.get("changed") else None,
                          "opening_note": None, "closing_note": None} for e in request.task_input.get("episodes", [])]}


def _mock_highlight(request: LLMAnalysisRequest) -> dict:
    target = int(request.task_input.get("target_seconds") or 60)
    units = request.task_input.get("units", [])[:4]
    each = max(3, target // max(1, len(units)))
    return {"title": "Mock", "logline": "", "segments": [
        {"unit": u["number"], "description": u.get("synopsis") or u.get("title") or "Segment", "seconds": each} for u in units]}


_STAGE_MOCKS = {
    "filler": _mock_filler, "filler_judge": _mock_filler_judge, "episode_repair": _mock_episode_repair,
    "highlight": _mock_highlight,
    "timeline": _mock_timeline, "continuity": _mock_continuity, "continuity_check": _mock_continuity_check, "master_script": _mock_master_script,
    "episode_plan": _mock_episode_plan, "scene_breakdown": _mock_scene_breakdown,
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
        if request.task in _STAGE_MOCKS:
            return LLMAnalysisResponse(
                provider="mock", model="mock-entity-analyzer-v2", prompt_version=f"{request.task}-mock-v1",
                payload=_STAGE_MOCKS[request.task](request), usage_metadata={"mode": "development_placeholder", "calls": 1},
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
