"""Skill loader for parsing SKILL.md files with YAML frontmatter."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """Information about a loaded skill."""

    name: str
    description: str
    folder_path: str
    triggers: list[str] = field(default_factory=list)
    requires_executor: bool = False
    entrypoint: str = "run.py"
    author: Optional[str] = None
    version: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    raw_content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_summary(self) -> str:
        """Generate a concise summary for system prompt injection."""
        trigger_str = ", ".join(self.triggers[:3])
        if len(self.triggers) > 3:
            trigger_str += ", ..."
        return f"- **{self.name}**: {self.description} (triggers: {trigger_str})"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "folder_path": self.folder_path,
            "triggers": self.triggers,
            "requires_executor": self.requires_executor,
            "entrypoint": self.entrypoint,
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
            "enabled": self.enabled,
        }


class SkillLoader:
    """
    Loader for skills from the skills directory.

    Scans skill folders, parses SKILL.md files with YAML frontmatter,
    and returns structured SkillInfo objects.
    """

    SKILL_FILE = "SKILL.md"
    TEMPLATE_FOLDER = "_template"

    def __init__(self, skills_dir: str):
        """
        Initialize the skill loader.

        Args:
            skills_dir: Path to the skills directory
        """
        self.skills_dir = Path(skills_dir)

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """
        Parse YAML frontmatter from markdown content.

        Args:
            content: Full content of SKILL.md file

        Returns:
            Tuple of (frontmatter dict, body content)
        """
        if not content.startswith("---"):
            return {}, content

        # Find the end of frontmatter
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        frontmatter_str = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""

        try:
            frontmatter = yaml.safe_load(frontmatter_str) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            frontmatter = {}

        return frontmatter, body

    def load_skill(self, skill_folder: str) -> Optional[SkillInfo]:
        """
        Load a single skill from its folder.

        Args:
            skill_folder: Name of the skill folder (relative to skills_dir)

        Returns:
            SkillInfo if successfully loaded, None otherwise
        """
        folder_path = self.skills_dir / skill_folder

        # Skip template and disabled folders
        if skill_folder.startswith("_") or skill_folder.startswith("."):
            return None

        skill_file = folder_path / self.SKILL_FILE

        if not skill_file.exists():
            logger.warning(f"Skill '{skill_folder}' missing {self.SKILL_FILE}")
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {skill_file}: {e}")
            return None

        frontmatter, body = self._parse_frontmatter(content)

        # Validate required fields
        if "name" not in frontmatter:
            logger.warning(f"Skill '{skill_folder}' missing 'name' in frontmatter")
            return None

        if "description" not in frontmatter:
            logger.warning(f"Skill '{skill_folder}' missing 'description' in frontmatter")
            frontmatter["description"] = "No description provided"

        return SkillInfo(
            name=frontmatter.get("name", skill_folder),
            description=frontmatter.get("description", ""),
            folder_path=str(folder_path),
            triggers=frontmatter.get("triggers", []),
            requires_executor=frontmatter.get("requires_executor", False),
            entrypoint=frontmatter.get("entrypoint", "run.py"),
            author=frontmatter.get("author"),
            version=frontmatter.get("version"),
            tags=frontmatter.get("tags", []),
            enabled=not skill_folder.startswith("."),
            raw_content=body,
            metadata=frontmatter,
        )

    def load_all_skills(self) -> list[SkillInfo]:
        """
        Load all skills from the skills directory.

        Returns:
            List of successfully loaded SkillInfo objects
        """
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory does not exist: {self.skills_dir}")
            return []

        skills = []
        for item in self.skills_dir.iterdir():
            if item.is_dir():
                skill_info = self.load_skill(item.name)
                if skill_info:
                    skills.append(skill_info)
                    logger.info(f"Loaded skill: {skill_info.name}")

        logger.info(f"Loaded {len(skills)} skills")
        return skills

    def get_enabled_skills(self, skills: Optional[list[SkillInfo]] = None) -> list[SkillInfo]:
        """
        Filter to only enabled skills.

        Args:
            skills: List of skills to filter (loads all if None)

        Returns:
            List of enabled skills
        """
        if skills is None:
            skills = self.load_all_skills()
        return [s for s in skills if s.enabled]

    def generate_skill_summary(self, skills: Optional[list[SkillInfo]] = None) -> str:
        """
        Generate a concise summary of all skills for system prompt injection.

        Args:
            skills: List of skills to summarize (loads all if None)

        Returns:
            Formatted string summarizing available skills
        """
        if skills is None:
            skills = self.get_enabled_skills()

        if not skills:
            return "No skills currently available."

        lines = [
            "# Available Skills",
            "",
            "The following skills are available for use:",
            "",
        ]

        for skill in skills:
            lines.append(skill.to_summary())

        lines.extend([
            "",
            "## Usage Notes",
            "- Skills are automatically triggered based on user intent",
            "- Use skill names when you need specific capabilities",
            "- Each skill has its own entry point and may require executor access",
        ])

        return "\n".join(lines)

    def create_template_skill(self, skill_name: str) -> Path:
        """
        Create a new skill folder from the template.

        Args:
            skill_name: Name for the new skill folder

        Returns:
            Path to the created skill folder

        Raises:
            FileExistsError: If skill folder already exists
            FileNotFoundError: If template folder not found
            ValueError: If skill_name is invalid or escapes the skills dir
        """
        # Validate the name first: a plain folder token, no traversal,
        # no git-ref-forbidden shapes.
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", skill_name)
            or ".." in skill_name
            or skill_name.endswith(".")
            or skill_name.endswith(".lock")
        ):
            raise ValueError(f"Invalid skill name: {skill_name!r}")

        template_path = self.skills_dir / self.TEMPLATE_FOLDER
        if not template_path.exists():
            raise FileNotFoundError(
                f"Template folder not found: {template_path}. "
                "Please ensure the _template folder exists in skills directory."
            )

        new_skill_path = self.skills_dir / skill_name

        # Defense-in-depth: the resolved path must stay inside skills_dir
        try:
            new_skill_path.resolve().relative_to(self.skills_dir.resolve())
        except ValueError:
            raise ValueError(f"Skill path escapes skills directory: {skill_name!r}")

        if new_skill_path.exists():
            raise FileExistsError(f"Skill folder already exists: {new_skill_path}")

        # Copy template files
        import shutil
        shutil.copytree(template_path, new_skill_path)

        logger.info(f"Created skill template at: {new_skill_path}")
        return new_skill_path
