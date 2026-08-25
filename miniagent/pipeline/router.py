"""Complexity-based stage routing.

Mapping (aligned with the examples embedded in 01_intent_analysis.md):
- simple  -> [1, 6, 10]           (analyze, implement, finalize)
- medium  -> [1, 2, 4, 6, 7, 9, 10]
- complex -> all ten stages

When the Intent stage supplies non-empty `suggested_stages`, that list wins
(validated against known ids and sorted).
"""

from typing import Optional

from miniagent.pipeline.stages import ALL_STAGE_IDS

ROUTE_MAP = {
    "simple": [1, 6, 10],
    "medium": [1, 2, 4, 6, 7, 9, 10],
    "complex": list(ALL_STAGE_IDS),
}


def route_stages(complexity: str = "medium", suggested: Optional[list] = None) -> list[int]:
    """Return the ordered stage id list for a task."""
    if suggested:
        valid = sorted({int(s) for s in suggested if int(s) in ALL_STAGE_IDS})
        if valid:
            return valid
    return list(ROUTE_MAP.get(str(complexity).lower(), ROUTE_MAP["medium"]))
