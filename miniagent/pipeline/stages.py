"""Stage specifications, prompt loading, and template rendering.

Each prompt file (miniagent/prompts/NN_*.md) carries YAML frontmatter with
stage_id / stage_name / requires_executor / output_format and a body using
{{user_request}} / {{conversation_history}} / {{context}} placeholders.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class StageSpec:
    id: int
    name: str
    prompt_file: str
    requires_executor: bool = False


STAGES: dict[int, StageSpec] = {
    1: StageSpec(1, "Intent Analysis", "01_intent_analysis.md"),
    2: StageSpec(2, "Requirement Gathering", "02_requirement_gathering.md"),
    3: StageSpec(3, "Research", "03_research.md"),
    4: StageSpec(4, "Planning", "04_planning.md"),
    5: StageSpec(5, "Architecture", "05_architecture.md"),
    6: StageSpec(6, "Implementation", "06_implementation.md"),
    7: StageSpec(7, "Self Review", "07_self_review.md"),
    8: StageSpec(8, "Execution", "08_execution.md", requires_executor=True),
    9: StageSpec(9, "Validation", "09_validation.md"),
    10: StageSpec(10, "Finalization", "10_finalization.md"),
}

ALL_STAGE_IDS = list(STAGES.keys())


def load_stage_template(stage_id: int, prompts_dir: Optional[Path] = None) -> str:
    """Load the raw prompt body (frontmatter stripped) for a stage."""
    spec = STAGES[stage_id]
    path = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
    raw = (path / spec.prompt_file).read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return raw.strip()


def render_template(template: str, user_request: str, history_json: str, context_json: str) -> str:
    """Fill {{placeholders}}; unknown placeholders become empty strings."""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return {
            "user_request": user_request,
            "conversation_history": history_json,
            "context": context_json,
        }.get(key, "")

    return PLACEHOLDER_RE.sub(_sub, template)


def parse_frontmatter(stage_id: int, prompts_dir: Optional[Path] = None) -> dict:
    spec = STAGES[stage_id]
    path = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
    raw = (path / spec.prompt_file).read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                data = yaml.safe_load(parts[1]) or {}
                if isinstance(data, dict):
                    return data
            except yaml.YAMLError:
                pass
    return {}
