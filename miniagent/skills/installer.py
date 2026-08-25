"""Skill installer for cloning skills from Git repositories."""

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

from miniagent.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillInstaller:
    """
    Installer for skills from Git repositories.

    Supports:
    - Cloning from GitHub, GitLab, etc.
    - Validating skill structure after install
    - Installing to the skills directory
    """

    def __init__(self, skills_dir: str):
        """
        Initialize the skill installer.

        Args:
            skills_dir: Path to the skills directory
        """
        self.skills_dir = Path(skills_dir)
        self._loader = SkillLoader(skills_dir)

    def _validate_git_url(self, url: str) -> bool:
        """
        Validate a Git repository URL.

        Args:
            url: Git repository URL

        Returns:
            True if URL appears valid, False otherwise
        """
        # Basic validation - should start with http/https/git@ or be a short GitHub name
        valid_prefixes = [
            "https://",
            "http://",
            "git@",
            "ssh://",
        ]

        url_lower = url.lower()

        # Check for valid prefixes
        if any(url_lower.startswith(prefix) for prefix in valid_prefixes):
            return True

        # Allow short GitHub names (user/repo format)
        if "/" in url and not url.startswith("/"):
            parts = url.split("/")
            if len(parts) == 2 and all(p.isalnum() or p in "-_" for p in parts):
                return True

        return False

    def _validate_branch(self, branch: str) -> bool:
        """
        Validate a git branch/ref name before passing it to subprocess.

        Prevents argument injection (e.g. a branch starting with '-' being
        interpreted as a git option such as --upload-pack=...).

        Args:
            branch: Branch name to validate

        Returns:
            True if the branch name is safe, False otherwise
        """
        if not branch or not branch.strip():
            return False

        branch = branch.strip()

        # Never allow options - a leading '-' would be parsed by git as flags
        if branch.startswith("-"):
            return False

        # Only allow characters valid in git ref names
        return bool(re.match(r"^[A-Za-z0-9_./-]+$", branch))

    def _normalize_git_url(self, url: str) -> str:
        """
        Normalize a Git URL to full HTTPS format.

        Args:
            url: Git URL (can be short GitHub name)

        Returns:
            Full HTTPS URL
        """
        # If it's a short GitHub name, expand it
        if "/" in url and not url.startswith("http") and not url.startswith("git@"):
            parts = url.split("/")
            if len(parts) == 2:
                return f"https://github.com/{url}.git"

        # Add .git suffix if missing and it's an HTTPS URL
        if url.startswith("https://") and not url.endswith(".git"):
            return url + ".git"

        return url

    def _extract_skill_name(self, url: str, name_override: Optional[str] = None) -> str:
        """
        Extract skill name from Git URL.

        Args:
            url: Git repository URL
            name_override: Optional override for skill name

        Returns:
            Skill folder name
        """
        if name_override:
            return name_override

        # Extract from URL
        normalized = self._normalize_git_url(url)

        # Handle GitHub/GitLab URLs
        if "github.com" in normalized or "gitlab.com" in normalized:
            # Format: https://github.com/user/repo.git
            parts = normalized.rstrip(".git").split("/")
            if len(parts) >= 2:
                return parts[-1]

        # Fallback: use last part of URL
        name = normalized.rstrip("/").split("/")[-1]
        return name.rstrip(".git")

    def install(
        self,
        git_url: str,
        name: Optional[str] = None,
        branch: Optional[str] = None,
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        Install a skill from a Git repository.

        Args:
            git_url: Git repository URL (full URL or user/repo shorthand)
            name: Optional name for the skill folder (default: repo name)
            branch: Optional branch to checkout (default: default branch)
            force: Whether to overwrite existing skill folder

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Validate URL
        if not self._validate_git_url(git_url):
            return False, f"Invalid Git URL format: {git_url}"

        # Validate branch BEFORE it reaches the subprocess (argument injection)
        if branch and not self._validate_branch(branch):
            return False, f"Invalid branch name: {branch}"

        # Normalize URL
        normalized_url = self._normalize_git_url(git_url)

        # Determine skill name
        skill_name = self._extract_skill_name(git_url, name)

        # Validate skill name
        if not skill_name.replace("-", "").replace("_", "").isalnum():
            return False, f"Invalid skill name derived from URL: {skill_name}"

        skill_path = self.skills_dir / skill_name

        # Check if already exists
        if skill_path.exists():
            if force:
                logger.info(f"Removing existing skill folder: {skill_path}")
                import shutil
                shutil.rmtree(skill_path)
            else:
                return False, (
                    f"Skill folder already exists: {skill_path}. "
                    f"Use --force to overwrite."
                )

        # Ensure skills directory exists
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        # Build git clone command
        clone_cmd = ["git", "clone", "--depth", "1"]

        if branch:
            clone_cmd.extend(["--branch", branch])

        # "--" separator: git must treat everything after it as positional
        # arguments (defense-in-depth against option injection)
        clone_cmd.extend(["--", normalized_url, str(skill_path)])

        try:
            logger.info(f"Cloning skill from: {normalized_url}")
            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode != 0:
                return False, f"Git clone failed: {result.stderr.strip()}"

            # Validate the cloned skill
            validation_result = self._validate_installed_skill(skill_path)
            if not validation_result[0]:
                # Rollback on validation failure
                import shutil
                shutil.rmtree(skill_path)
                return False, validation_result[1]

            logger.info(f"Successfully installed skill: {skill_name}")
            return True, f"Skill '{skill_name}' installed successfully from {git_url}"

        except subprocess.TimeoutExpired:
            return False, "Git clone timed out after 60 seconds"
        except Exception as e:
            logger.error(f"Failed to install skill: {e}")
            return False, f"Installation error: {str(e)}"

    def _validate_installed_skill(self, skill_path: Path) -> tuple[bool, str]:
        """
        Validate an installed skill has required files.

        Args:
            skill_path: Path to the installed skill folder

        Returns:
            Tuple of (valid: bool, message: str)
        """
        # Check for SKILL.md
        skill_file = skill_path / SkillLoader.SKILL_FILE
        if not skill_file.exists():
            return False, f"Missing required file: {SkillLoader.SKILL_FILE}"

        # Try to load the skill to validate frontmatter
        loader = SkillLoader(str(self.skills_dir))
        skill_info = loader.load_skill(skill_path.name)

        if skill_info is None:
            return False, "Failed to parse skill metadata"

        if not skill_info.name:
            return False, "Skill metadata missing 'name' field"

        return True, "Validation passed"

    def uninstall(self, skill_name: str) -> tuple[bool, str]:
        """
        Uninstall a skill by removing its folder.

        Args:
            skill_name: Name of the skill to remove

        Returns:
            Tuple of (success: bool, message: str)
        """
        skill_path = self.skills_dir / skill_name

        if not skill_path.exists():
            return False, f"Skill not found: {skill_name}"

        # Prevent removing template folder
        if skill_name == SkillLoader.TEMPLATE_FOLDER:
            return False, "Cannot uninstall the template folder"

        try:
            import shutil
            shutil.rmtree(skill_path)
            logger.info(f"Uninstalled skill: {skill_name}")
            return True, f"Skill '{skill_name}' uninstalled successfully"
        except Exception as e:
            logger.error(f"Failed to uninstall skill: {e}")
            return False, f"Failed to uninstall: {str(e)}"

    def update(self, skill_name: str) -> tuple[bool, str]:
        """
        Update a skill from its Git repository.

        Args:
            skill_name: Name of the skill to update

        Returns:
            Tuple of (success: bool, message: str)
        """
        skill_path = self.skills_dir / skill_name

        if not skill_path.exists():
            return False, f"Skill not found: {skill_name}"

        # Check if it's a git repository
        git_dir = skill_path / ".git"
        if not git_dir.exists():
            return False, "Not a Git-installed skill, cannot update"

        try:
            logger.info(f"Updating skill: {skill_name}")
            result = subprocess.run(
                ["git", "pull"],
                cwd=str(skill_path),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode != 0:
                return False, f"Git pull failed: {result.stderr.strip()}"

            logger.info(f"Updated skill: {skill_name}")
            return True, f"Skill '{skill_name}' updated successfully"

        except subprocess.TimeoutExpired:
            return False, "Update timed out after 60 seconds"
        except Exception as e:
            logger.error(f"Failed to update skill: {e}")
            return False, f"Update error: {str(e)}"
