"""Subprocess-based executor with sandboxing and security features."""

import logging
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from miniagent.executor.base import Executor, ExecutionResult
from miniagent.executor.permission import PermissionChecker, CommandRiskLevel

logger = logging.getLogger(__name__)
class SubprocessExecutor(Executor):
    """
    Subprocess-based command executor with security features.

    Features:
    - Path validation to prevent escaping workspace
    - Command safety classification
    - Timeout enforcement
    - Execution logging for audit trail
    - User confirmation for dangerous commands via callback
    """

    def __init__(
        self,
        workspace_root: str,
        timeout: int = 30,
        log_file: Optional[str] = None,
        confirmation_callback: Optional[Callable[[str, str], bool]] = None,
        env_denylist_patterns: Optional[list[str]] = None,
        strict_path_checking: bool = True,
    ):
        """
        Initialize the subprocess executor.

        Args:
            workspace_root: Root directory for restricted file operations
            timeout: Default timeout in seconds for command execution
            log_file: Path to execution log file
            confirmation_callback: Callback for dangerous command confirmation.
                Signature: callback(command: str, reason: str) -> bool
                Returns True to allow, False to deny.
                If None, dangerous commands will fail closed (denied by default).
            env_denylist_patterns: List of regex patterns for environment variables
                that should be filtered from subprocess environment.
                Defaults to blocking API keys and tokens.
            strict_path_checking: If True (default), path-like arguments in commands
                are resolved and verified to stay inside workspace_root before
                execution. Commands referencing paths outside the workspace are
                rejected with PermissionError.
        """
        super().__init__(workspace_root, timeout, confirmation_callback)
        self.permission_checker = PermissionChecker()
        self.log_file = log_file
        self.strict_path_checking = strict_path_checking
        self._ensure_workspace_exists()

        # Environment denylist patterns
        if env_denylist_patterns is None:
            env_denylist_patterns = [
                r".*_API_KEY$",
                r".*_TOKEN$",
                r".*_SECRET$",
                r".*_PASSWORD$",
                r".*KEY$",
            ]
        self.env_denylist_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in env_denylist_patterns]

    def _ensure_workspace_exists(self) -> None:
        """Ensure workspace directory exists."""
        Path(self.workspace_root).mkdir(parents=True, exist_ok=True)

    def _get_filtered_environment(self) -> dict:
        """
        Get a filtered copy of the environment for subprocess execution.

        Returns:
            Filtered environment dictionary with sensitive variables removed.
        """
        # Start with a copy of the current environment
        env = os.environ.copy()

        # Filter out variables matching denylist patterns
        keys_to_remove = []
        for key in env.keys():
            for pattern in self.env_denylist_patterns:
                if pattern.match(key):
                    keys_to_remove.append(key)
                    break

        for key in keys_to_remove:
            del env[key]

        return env

    def _log_execution(self, result: ExecutionResult) -> None:
        """Log execution result to file for audit trail."""
        if not self.log_file:
            return

        try:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().isoformat()
            log_entry = (
                f"[{timestamp}] Command: {result.command}\n"
                f"  Exit Code: {result.exit_code}\n"
                f"  Duration: {result.duration_ms}ms\n"
                f"  CWD: {result.cwd}\n"
                f"  Timed Out: {result.timed_out}\n"
                f"  Error: {result.error or 'None'}\n"
                f"  Stdout (first 500 chars): {result.stdout[:500]}\n"
                f"  Stderr (first 500 chars): {result.stderr[:500]}\n"
                f"  {'=' * 80}\n"
            )

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            logger.warning(f"Failed to write execution log: {e}")

    def run_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        shell: bool = False,
    ) -> ExecutionResult:
        """
        Execute a shell command with security checks.

        FIX 1 & FIX 2: This method now properly handles BLOCKED vs DANGEROUS commands:
        - BLOCKED commands always raise PermissionError (cannot be bypassed)
        - DANGEROUS commands use the confirmation_callback for user approval
          If no callback is set, dangerous commands fail closed (denied by default)

        Args:
            command: Command to execute
            cwd: Working directory (must be within workspace_root)
            timeout: Timeout in seconds (overrides default)
            shell: Whether to run through shell (default False for safety)

        Returns:
            ExecutionResult with output and metadata

        Raises:
            ValueError: If path validation fails
            PermissionError: If command is blocked or denied by confirmation callback
            TimeoutError: If command exceeds timeout
        """
        # Validate working directory
        if cwd:
            try:
                validated_cwd = self.validate_path(cwd)
            except ValueError as e:
                raise ValueError(f"Invalid working directory: {e}")
        else:
            validated_cwd = self.workspace_root

        # FIX 1: Check command safety - BLOCKED always checked first, regardless of flags
        classification = self.permission_checker.classify_command(command)

        # BLOCKED commands are ALWAYS rejected - no bypass possible
        if classification.risk_level == CommandRiskLevel.BLOCKED:
            raise PermissionError(
                f"Command blocked for safety: {classification.reason}"
            )

        # DANGEROUS commands require confirmation via callback
        if classification.risk_level == CommandRiskLevel.DANGEROUS:
            # FIX 2: Use callback-based confirmation instead of direct input()
            if self.confirmation_callback is not None:
                # Call the injected callback
                reason = classification.reason
                confirmed = self.confirmation_callback(command, reason)
                if not confirmed:
                    raise PermissionError(
                        f"Command denied by user: {classification.reason}\n"
                        f"Command: {command}"
                    )
            else:
                # No callback provided - fail closed (deny by default)
                # This is the safe default for non-interactive/testing scenarios
                raise PermissionError(
                    f"Command requires confirmation but no callback provided: "
                    f"{classification.reason}\nCommand: {command}"
                )

        # CAUTION commands can proceed with just a log warning
        if classification.risk_level == CommandRiskLevel.CAUTION:
            logger.info(f"Caution: {classification.reason} - Command: {command}")

        # FIX 3: Verify all path-like arguments stay inside the workspace
        if getattr(self, "strict_path_checking", True):
            path_candidates = self.permission_checker.extract_path_like_arguments(command)
            # Windows-style absolute paths (drive letters) use backslashes, which
            # POSIX shlex strips as escape characters. Scan the raw command so
            # they cannot bypass the workspace containment check.
            for match in re.findall(r"[A-Za-z]:[\\/][^\s\"']*", command):
                if match not in path_candidates:
                    path_candidates.append(match)
            for candidate in path_candidates:
                candidate_expanded = os.path.expanduser(candidate)
                if os.path.isabs(candidate_expanded):
                    resolved = os.path.realpath(candidate_expanded)
                else:
                    resolved = os.path.realpath(os.path.join(validated_cwd, candidate_expanded))
                try:
                    workspace_real = os.path.realpath(self.workspace_root)
                    if os.path.commonpath([resolved, workspace_real]) != workspace_real:
                        raise PermissionError(
                            f"Command references path outside workspace: {candidate} "
                            f"(resolved to {resolved}, workspace is {workspace_real})"
                        )
                except ValueError:
                    raise PermissionError(
                        f"Command references path outside workspace (cannot verify containment): {candidate}"
                    )

        # Prepare command execution
        exec_timeout = timeout if timeout is not None else self.timeout
        start_time = time.time()

        try:
            # Parse command for non-shell execution (safer)
            if not shell:
                try:
                    args = shlex.split(command)
                except ValueError as e:
                    return ExecutionResult(
                        command=command,
                        exit_code=-1,
                        stdout="",
                        stderr=f"Failed to parse command: {e}",
                        duration_ms=0,
                        cwd=validated_cwd,
                        error=str(e),
                    )
            else:
                args = command

            logger.info(f"Executing command: {command} (cwd={validated_cwd})")

            # Get filtered environment for subprocess
            filtered_env = self._get_filtered_environment()

            result = subprocess.run(
                args if shell else args,
                cwd=validated_cwd,
                capture_output=True,
                text=True,
                timeout=exec_timeout,
                shell=shell,
                env=filtered_env,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            execution_result = ExecutionResult(
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
                cwd=validated_cwd,
                timed_out=False,
            )

        except subprocess.TimeoutExpired as e:
            duration_ms = int((time.time() - start_time) * 1000)
            execution_result = ExecutionResult(
                command=command,
                exit_code=-1,
                stdout=e.stdout.decode() if e.stdout else "",
                stderr=e.stderr.decode() if e.stderr else "",
                duration_ms=duration_ms,
                cwd=validated_cwd,
                timed_out=True,
                error=f"Command timed out after {exec_timeout}s",
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            execution_result = ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                cwd=validated_cwd,
                error=str(e),
            )

        # Log execution
        self._log_execution(execution_result)

        return execution_result

    def read_file(self, path: str) -> str:
        """
        Read contents of a file within the workspace.

        Args:
            path: Path to file (relative or absolute)

        Returns:
            File contents as string

        Raises:
            ValueError: If path is outside workspace
            FileNotFoundError: If file does not exist
        """
        validated_path = self.validate_path(path)

        if not os.path.isfile(validated_path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(validated_path, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, path: str, content: str, mode: str = "w") -> None:
        """
        Write content to a file within the workspace.

        Args:
            path: Path to file (relative or absolute)
            content: Content to write
            mode: File mode ('w' for write, 'a' for append)

        Raises:
            ValueError: If path is outside workspace
        """
        validated_path = self.validate_path(path)

        # Ensure parent directory exists
        Path(validated_path).parent.mkdir(parents=True, exist_ok=True)

        with open(validated_path, mode, encoding="utf-8") as f:
            f.write(content)

    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists within the workspace.

        Args:
            path: Path to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            validated_path = self.validate_path(path)
            return os.path.isfile(validated_path)
        except ValueError:
            return False

    def list_directory(self, path: str) -> list[str]:
        """
        List contents of a directory within the workspace.

        Args:
            path: Directory path to list

        Returns:
            List of file/directory names

        Raises:
            ValueError: If path is outside workspace
            NotADirectoryError: If path is not a directory
        """
        validated_path = self.validate_path(path)

        if not os.path.isdir(validated_path):
            raise NotADirectoryError(f"Not a directory: {path}")

        return os.listdir(validated_path)