"""Subprocess-based executor with sandboxing and security features."""

import logging
import os
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from miniagent.executor.base import Executor, ExecutionResult
from miniagent.executor.permission import PermissionChecker

logger = logging.getLogger(__name__)


class SubprocessExecutor(Executor):
    """
    Subprocess-based command executor with security features.

    Features:
    - Path validation to prevent escaping workspace
    - Command safety classification
    - Timeout enforcement
    - Execution logging for audit trail
    - User confirmation for dangerous commands
    """

    def __init__(
        self,
        workspace_root: str,
        timeout: int = 30,
        allow_dangerous: bool = False,
        log_file: Optional[str] = None,
    ):
        """
        Initialize the subprocess executor.

        Args:
            workspace_root: Root directory for restricted file operations
            timeout: Default timeout in seconds for command execution
            allow_dangerous: Skip confirmation for dangerous commands (USE WITH CAUTION)
            log_file: Path to execution log file
        """
        super().__init__(workspace_root, timeout)
        self.permission_checker = PermissionChecker(allow_dangerous=allow_dangerous)
        self.log_file = log_file
        self._ensure_workspace_exists()

    def _ensure_workspace_exists(self) -> None:
        """Ensure workspace directory exists."""
        Path(self.workspace_root).mkdir(parents=True, exist_ok=True)

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
        require_confirmation: bool = True,
    ) -> ExecutionResult:
        """
        Execute a shell command with security checks.

        Args:
            command: Command to execute
            cwd: Working directory (must be within workspace)
            timeout: Timeout in seconds (overrides default)
            shell: Whether to run through shell (default False)
            require_confirmation: Whether to require user confirmation for dangerous commands

        Returns:
            ExecutionResult with output and metadata

        Raises:
            ValueError: If path validation fails
            PermissionError: If command requires confirmation
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

        # Check command safety
        if require_confirmation:
            classification = self.permission_checker.classify_command(command)

            if classification.risk_level.value == "blocked":
                raise PermissionError(
                    f"Command blocked for safety: {classification.reason}"
                )

            if classification.risk_level.value == "dangerous":
                # In non-interactive mode, we raise an error
                # Interactive CLI should handle this before calling run_command
                raise PermissionError(
                    f"Command requires confirmation: {classification.reason}\n"
                    f"Command: {command}"
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

            result = subprocess.run(
                args if shell else args,
                cwd=validated_cwd,
                capture_output=True,
                text=True,
                timeout=exec_timeout,
                shell=shell,
                env=os.environ.copy(),
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

    def request_confirmation(self, command: str) -> bool:
        """
        Request user confirmation for a dangerous command.

        This method should be called by interactive CLI before executing
        dangerous commands. For non-interactive use, raises PermissionError.

        Args:
            command: The command requiring confirmation

        Returns:
            True if user confirmed, False otherwise

        Raises:
            PermissionError: If command is blocked
        """
        classification = self.permission_checker.classify_command(command)

        if classification.risk_level.value == "blocked":
            raise PermissionError(
                f"⛔ BLOCKED: {classification.reason}"
            )

        if classification.risk_level.value != "dangerous":
            return True  # No confirmation needed

        # Print warning and ask for confirmation
        print(self.permission_checker.get_safety_message(command))

        while True:
            response = input("Proceed? (y/n): ").strip().lower()
            if response in ("y", "yes"):
                return True
            elif response in ("n", "no"):
                return False
            else:
                print("Please enter 'y' or 'n'")
