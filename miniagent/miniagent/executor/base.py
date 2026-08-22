"""Abstract base class for command executors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExecutionResult:
    """Result of a command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    cwd: str
    timed_out: bool = False
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.exit_code == 0 and not self.timed_out and self.error is None

    def __str__(self) -> str:
        """String representation of execution result."""
        status = "✓" if self.success else "✗"
        return (
            f"{status} Command: {self.command}\n"
            f"  Exit Code: {self.exit_code}\n"
            f"  Duration: {self.duration_ms}ms\n"
            f"  Stdout: {self.stdout[:200]}{'...' if len(self.stdout) > 200 else ''}\n"
            f"  Stderr: {self.stderr[:200]}{'...' if len(self.stderr) > 200 else ''}"
        )


class Executor(ABC):
    """
    Abstract base class for command and file operation executors.

    Implementations must provide sandboxed execution with proper
    security measures including path validation and command restrictions.
    """

    def __init__(self, workspace_root: str, timeout: int = 30):
        """
        Initialize the executor.

        Args:
            workspace_root: Root directory for restricted file operations
            timeout: Default timeout in seconds for command execution
        """
        self.workspace_root = workspace_root
        self.timeout = timeout

    @abstractmethod
    def run_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        shell: bool = False,
    ) -> ExecutionResult:
        """
        Execute a shell command in a sandboxed environment.

        Args:
            command: Command to execute (as string or list of args)
            cwd: Working directory (must be within workspace_root)
            timeout: Timeout in seconds (overrides default)
            shell: Whether to run through shell (default False for safety)

        Returns:
            ExecutionResult with stdout, stderr, exit code, and metadata

        Raises:
            ValueError: If cwd is outside workspace_root
            TimeoutError: If command exceeds timeout
            PermissionError: If command is not allowed
        """
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """
        Read contents of a file within the workspace.

        Args:
            path: Path to file (relative or absolute, must be within workspace)

        Returns:
            File contents as string

        Raises:
            ValueError: If path is outside workspace_root
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read
        """
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, mode: str = "w") -> None:
        """
        Write content to a file within the workspace.

        Args:
            path: Path to file (relative or absolute, must be within workspace)
            content: Content to write
            mode: File mode ('w' for write, 'a' for append)

        Raises:
            ValueError: If path is outside workspace_root
            PermissionError: If file cannot be written
        """
        pass

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists within the workspace.

        Args:
            path: Path to check

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    def list_directory(self, path: str) -> list[str]:
        """
        List contents of a directory within the workspace.

        Args:
            path: Directory path to list

        Returns:
            List of file/directory names

        Raises:
            ValueError: If path is outside workspace_root
            NotADirectoryError: If path is not a directory
        """
        pass

    def validate_path(self, path: str) -> str:
        """
        Validate that a path is within the workspace root.

        Args:
            path: Path to validate (can be relative or absolute)

        Returns:
            Absolute normalized path

        Raises:
            ValueError: If path resolves outside workspace_root
        """
        import os
        from pathlib import Path

        # Convert to Path object
        path_obj = Path(path)

        # If relative, make it absolute relative to workspace
        if not path_obj.is_absolute():
            path_obj = Path(self.workspace_root) / path_obj

        # Resolve to get canonical path (resolves symlinks, .., etc.)
        resolved_path = path_obj.resolve()
        workspace_resolved = Path(self.workspace_root).resolve()

        # Check if resolved path starts with workspace root
        try:
            resolved_path.relative_to(workspace_resolved)
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves to '{resolved_path}' which is "
                f"outside workspace '{workspace_resolved}'. "
                f"Path traversal is not allowed."
            )

        return str(resolved_path)
