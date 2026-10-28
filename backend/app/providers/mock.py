from .base import GenerationRequest, ProviderResult


class MockStoryboardProvider:
    """Deterministic provider used until a real GenAI adapter is selected."""

    def generate(self, request: GenerationRequest) -> ProviderResult:
        return ProviderResult(
            provider="mock",
            model="mock-storyboard-v1",
            output_metadata={
                "kind": "placeholder",
                "prompt": request.prompt,
                "message": "Replace this adapter with a real storyboard provider.",
            },
            output_bytes=None,
        )
