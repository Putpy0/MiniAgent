"""Shared state threaded through the reasoning pipeline."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PipelineContext:
    """Carries the user request and every stage output downstream."""

    user_request: str
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    stage_outputs: dict[int, dict[str, Any]] = field(default_factory=dict)
    execution_results: list[dict[str, Any]] = field(default_factory=list)
    stopped_reason: Optional[str] = None

    def previous_context_json(self, limit_chars: int = 6000) -> str:
        """Compact JSON of all stage outputs so far, for prompt injection."""
        import json

        if not self.stage_outputs:
            return "{}"
        text = json.dumps(self.stage_outputs, ensure_ascii=False, default=str)
        return text[:limit_chars]

    def get_output(self, stage_id: int) -> dict[str, Any]:
        return self.stage_outputs.get(stage_id, {})
