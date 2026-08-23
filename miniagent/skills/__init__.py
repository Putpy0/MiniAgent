"""MiniAgent skills module for extensible capabilities."""

from miniagent.skills.loader import SkillLoader, SkillInfo
from miniagent.skills.registry import SkillRegistry
from miniagent.skills.installer import SkillInstaller

__all__ = ["SkillLoader", "SkillInfo", "SkillRegistry", "SkillInstaller"]