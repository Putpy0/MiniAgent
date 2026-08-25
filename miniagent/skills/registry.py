"""Skill registry for managing loaded skills and injecting into system prompt."""

import logging
from typing import Optional

from miniagent.skills.loader import SkillInfo, SkillLoader

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Registry for managing loaded skills.

    Provides methods to:
    - Load and cache skills from disk
    - Query skills by name or trigger
    - Generate skill summaries for LLM context
    - Enable/disable skills dynamically
    """

    def __init__(self, skills_dir: str, auto_load: bool = True):
        """
        Initialize the skill registry.

        Args:
            skills_dir: Path to the skills directory
            auto_load: Whether to automatically load skills on init
        """
        self.skills_dir = skills_dir
        self._loader = SkillLoader(skills_dir)
        self._skills: dict[str, SkillInfo] = {}

        if auto_load:
            self.reload()

    def reload(self) -> None:
        """Reload all skills from disk."""
        skills_list = self._loader.load_all_skills()
        self._skills = {s.name: s for s in skills_list}
        logger.info(f"Registry loaded with {len(self._skills)} skills")

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """
        Get a skill by name.

        Args:
            name: Name of the skill

        Returns:
            SkillInfo if found, None otherwise
        """
        return self._skills.get(name)

    def get_enabled_skills(self) -> list[SkillInfo]:
        """Get list of all enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    def get_all_skills(self) -> list[SkillInfo]:
        """Get list of all skills (including disabled)."""
        return list(self._skills.values())

    def find_skill_by_trigger(self, trigger_phrase: str) -> Optional[SkillInfo]:
        """
        Find a skill that matches a trigger phrase.

        Args:
            trigger_phrase: User's input or query

        Returns:
            Matching SkillInfo if found, None otherwise
        """
        trigger_lower = trigger_phrase.lower()

        for skill in self._skills.values():
            if not skill.enabled:
                continue

            # Check if any trigger keyword is in the phrase
            for trigger in skill.triggers:
                if trigger.lower() in trigger_lower:
                    return skill

        return None

    def find_relevant_skills(self, query: str, max_results: int = 3) -> list[SkillInfo]:
        """
        Find skills relevant to a query using simple keyword matching.

        Args:
            query: User's query or task description
            max_results: Maximum number of skills to return

        Returns:
            List of relevant skills
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored_skills = []

        for skill in self._skills.values():
            if not skill.enabled:
                continue

            score = 0

            # Check description match
            if skill.name.lower() in query_lower:
                score += 5
            # Word-overlap between description and query, capped so it can
            # never outweigh more precise name/trigger matches
            description_words = set(skill.description.lower().split())
            overlap = len(description_words & query_words)
            score += min(overlap, 3)

            # Check trigger matches
            for trigger in skill.triggers:
                if trigger.lower() in query_lower:
                    score += 2

            # Check tags
            for tag in skill.tags:
                if tag.lower() in query_words:
                    score += 1

            if score > 0:
                scored_skills.append((score, skill))

        # Sort by score descending
        scored_skills.sort(key=lambda x: x[0], reverse=True)

        return [skill for _, skill in scored_skills[:max_results]]

    def enable_skill(self, name: str) -> bool:
        """
        Enable a skill.

        Args:
            name: Name of the skill to enable

        Returns:
            True if skill was found and enabled, False otherwise
        """
        skill = self._skills.get(name)
        if skill:
            skill.enabled = True
            logger.info(f"Enabled skill: {name}")
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        """
        Disable a skill.

        Args:
            name: Name of the skill to disable

        Returns:
            True if skill was found and disabled, False otherwise
        """
        skill = self._skills.get(name)
        if skill:
            skill.enabled = False
            logger.info(f"Disabled skill: {name}")
            return True
        return False

    def generate_system_prompt_section(self) -> str:
        """
        Generate a section for the system prompt describing available skills.

        Returns:
            Formatted string for injection into system prompt
        """
        enabled = self.get_enabled_skills()

        if not enabled:
            return ""

        lines = [
            "",
            "## Available Skills",
            "",
            "You have access to the following specialized skills:",
            "",
        ]

        for skill in enabled:
            trigger_examples = ", ".join(f'"{t}"' for t in skill.triggers[:3])
            if skill.triggers:
                lines.append(
                    f"### {skill.name}\n"
                    f"**Description**: {skill.description}\n"
                    f"**Triggers**: {trigger_examples}\n"
                    f"**Requires Executor**: {'Yes' if skill.requires_executor else 'No'}\n"
                )

        lines.extend([
            "### Using Skills",
            "- When a user request matches a skill's triggers, consider using that skill",
            "- Skills may provide additional capabilities beyond your base functions",
            "- Reference skills by name when explaining your approach",
        ])

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Convert registry to dictionary representation."""
        return {
            "skills_dir": self.skills_dir,
            "skill_count": len(self._skills),
            "enabled_count": len(self.get_enabled_skills()),
            "skills": [s.to_dict() for s in self._skills.values()],
        }
