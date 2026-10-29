from app.providers.llm_base import LLMAnalysisRequest, LLMAnalysisResponse


class MockLLMProvider:
    """Schema-compatible placeholder until a real LLM adapter is configured."""

    def analyze(self, request: LLMAnalysisRequest) -> LLMAnalysisResponse:
        return LLMAnalysisResponse(
            provider="mock",
            model="mock-entity-analyzer-v1",
            prompt_version="entity-extraction-v1",
            payload={
                "characters": [],
                "locations": [],
                "objects": [],
                "events": [],
                "relationships": [],
                "analysis_notes": [
                    "Mock provider returned no extracted entities.",
                    f"Context chunks supplied: {len(request.context_chunks)}",
                ],
            },
            usage_metadata={"mode": "development_placeholder"},
        )
