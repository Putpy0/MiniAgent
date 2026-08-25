"""Command safety checker with whitelist/blacklist for dangerous operations."""

import re
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
class CommandRiskLevel(Enum):
    """Risk level classification for commands."""

    SAFE = "safe"  # Can run without confirmation
    CAUTION = "caution"  # Should warn user but can proceed
    DANGEROUS = "dangerous"  # Requires explicit confirmation
    BLOCKED = "blocked"  # Never allowed
@dataclass
class CommandClassification:
    """Classification result for a command."""

    risk_level: CommandRiskLevel
    reason: str
    matched_pattern: Optional[str] = None
class PermissionChecker:
    """
    Security checker for shell commands.

    Implements whitelist/blacklist approach to classify commands
    by risk level and determine if user confirmation is required.
    """

    # Patterns for extremely dangerous commands (always blocked)
    BLOCKED_PATTERNS = [
        # Fork bombs
        r":\(\)\{\s*:\|:\s*&\s*\}\s*;",
        r"\(\)\s*\{\s*:\|\:&\s*\}\s*;",
        # Direct disk destruction
        r"mkfs",
        r"mke2fs",
        r"fdisk.*-y",
        r"parted.*mklabel",
        # Kernel module manipulation (in most contexts)
        r"rmmod\s+-f",
        r"modprobe\s+-r\s+.*critical",
        # Bootloader destruction
        r"update-grub.*--recheck",
        r"grub-install.*--force",
        # dd writing to a device target (any argument order), except /dev/null
        # which is always safe to write to. Only the OUTPUT target matters:
        # reading from /dev/zero|random|urandom is harmless data generation.
        r"dd\s+.*\bof=(?!/dev/null\b)/dev/\S+",
        # dd reading from a raw block device (disk/partition imaging).
        # NOTE: /dev/zero and /dev/random source patterns were removed - they
        # caused permanent false positives on legitimate commands such as
        # "dd if=/dev/zero of=swapfile bs=1M count=1024".
        r"dd\s+.*\bif=/dev/(sd[a-z]+\d*|hd[a-z]+|vd[a-z]+|nvme\d+n\d+(p\d+)?|mmcblk\d+(p\d+)?)\b",
    ]

    # Patterns for dangerous commands (require confirmation)
    DANGEROUS_PATTERNS = [
        # Recursive force remove
        r"rm\s+(-[rf]+\s+)*(/|~|\$HOME)",
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+\*",
        r"rm\s+-rf\s+\.\.",
        # Force remove common directories
        r"rm\s+-rf\s+(bin|etc|usr|var|home|boot|opt|sbin)",
        # Sudo with dangerous commands
        r"sudo\s+rm\s+-rf",
        r"sudo\s+chmod\s+-R\s+777",
        r"sudo\s+chown\s+-R",
        # Overwrite files
        r">\s*/",
        r"cat\s+/dev/null\s*>\s*/",
        # Network download and execute (potentially dangerous)
        r"curl.*\|\s*(ba)?sh",
        r"wget.*-O\s*-.*\|\s*(ba)?sh",
        r"curl.*\|\s*python",
        r"wget.*\|\s*python",
        # Changing permissions recursively
        r"chmod\s+-R\s+777",
        r"chmod\s+-R\s+a\+rwx",
        # History clearing (often malicious)
        r"history\s+-c",
        r"rm\s+.*\.bash_history",
        r"shred\s+.*\.bash_history",
        # Stopping critical services
        r"systemctl\s+stop\s+(ssh|sshd|firewalld|ufw|iptables)",
        r"service\s+(ssh|sshd|firewalld|ufw|iptables)\s+stop",
        # Disabling security
        r"setenforce\s+0",
        r"ufw\s+disable",
        r"iptables\s+-F",
        r"iptables\s+-X",
        # ADDITIONAL DANGEROUS PATTERNS:
        r"wget\s+.*\|.*bash",
        r"curl\s+.*\|.*bash",
        r"ssh\s+.*\|.*sh",
        r"scp\s+.*\|.*sh",
        r"rsync\s+.*\|.*sh",
        r"docker\s+run.*-v.*:/.*",
        r"docker\s+run.*--privileged",
        r"kubectl\s+delete.*namespace",
        r"kubectl\s+delete.*pod",
        r"docker-compose\s+down\s+--remove-orphans",
        r"docker\s+rm.*-f.*--all",
        r"docker\s+image\s+rm.*--all",
        r"rmdir\s+/",
        r"echo.*>/dev/sda",
        r"echo.*>/dev/(sda1|sdb1|hda)",
        r"mkfs\.ext4.*\/dev\/sda",
        r"fsck\.ext4.*\/dev\/sda",
        r"fdisk\/dev\/sda",
        r"parted.*\/dev\/sda",
    ]

    # SAFE commands - only truly safe commands are allowed without confirmation
    # WARNING: Even these should be reviewed carefully for safety
    SAFE_COMMANDS = [
        # File operations (safe when used carefully)
        "ls", "dir", "pwd", "echo", "cat", "head", "tail", "less", "more",
        # System info
        "uname", "hostname", "whoami", "date", "time", "uptime", "free",
        # Network operations (mostly safe)
        "ping", "traceroute", "netstat", "ss", "dig", "nslookup", "host",
        # Programming languages (only if the code itself is safe)
        "python", "python3", "node", "npm", "yarn", "gcc", "g++", "clang",
        "rustc", "cargo", "go", "javac", "java", "javac",
        # Build tools
        "make", "cmake", "pip", "pip3", "npm", "yarn",
        # Development tools
        "vim", "nano", "emacs", "code", "bat", "ripgrep", "rg", "ag",
        # Data processing
        "jq", "yq", "sed", "awk", "sort", "uniq", "cut", "paste", "tr",
        # Cryptography and data encoding
        "md5sum", "sha1sum", "sha256sum", "sha512sum", "openssl", "base64", "xxd",
        "hexdump", "od", "strings", "test", "[", "true", "false",
        # Additional safe commands
        # NOTE: network/infra tools (ssh, scp, rsync, curl, wget, docker,
        # docker-compose, kubectl, helm, terraform, ansible) are intentionally
        # NOT here - they belong to DANGEROUS_BASE_COMMANDS and always require
        # confirmation. Listing them as safe would be contradictory.
        "git",
    ]

    # Set of base commands that are dangerous and require confirmation
    # These are separated from CAUTION_COMMANDS to ensure they are always DANGEROUS
    DANGEROUS_BASE_COMMANDS = {
        "rm", "find", "curl", "wget", "ssh", "scp", "rsync", "docker",
        "docker-compose", "kubectl", "helm", "terraform", "ansible", "chmod",
        "chown", "mv", "cp", "mkdir", "touch", "rmdir", "dd", "mkfs", "fdisk",
        "parted", "iptables", "systemctl", "service", "apt", "yum", "dnf",
        "pacman", "zypper", "env", "printenv",
    }

    # CAUTION commands
    CAUTION_COMMANDS = [
        "git reset --hard",
        "git clean -fd",
        "docker rm -f",
        "docker rmi -f",
        "docker system prune",
        "npm uninstall",
        "pip uninstall",
        "cargo clean",
        "make clean",
        "truncate -s 0",
        ": > largefile",
    ]

    def __init__(self, allow_dangerous: bool = False):
        """
        Initialize the permission checker.

        Args:
            allow_dangerous: If True, skip confirmation for dangerous commands
                (USE WITH EXTREME CAUTION - only for trusted environments)
        """
        self.allow_dangerous = allow_dangerous
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficiency."""
        self._blocked_regexes = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.BLOCKED_PATTERNS
        ]
        self._dangerous_regexes = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS
        ]

    def _split_compound_command(self, command: str) -> list[str]:
        """
        Split a compound command into individual sub-commands.

        FIX 3: This function detects command chaining operators (&&, ;, |, ||)
        and shell substitution ($(), backticks) to split the command into
        individual parts for separate safety classification.

        This prevents bypass attempts like:
          "ls && rm -rf /" or "echo $(cat /etc/passwd)"

        The function carefully handles quoted strings to avoid splitting
        inside quoted content. It also tracks brace depth for function
        definitions like fork bombs :(){:|:&};:

        Args:
            command: The shell command string to split

        Returns:
            List of individual sub-command strings
        """
        if not command:
            return []

        sub_commands = []
        current = []
        i = 0
        in_single_quote = False
        in_double_quote = False
        in_backtick = False  # FIX 3: Changed from backtick_depth counter to boolean toggle
        paren_depth = 0
        brace_depth = 0  # Track {} for function definitions

        while i < len(command):
            char = command[i]

            # Handle quote state tracking
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
            # Handle backticks - FIX 3: Use boolean toggle instead of counter
            elif char == "`" and not in_single_quote and not in_double_quote:
                in_backtick = not in_backtick
                current.append(char)
            # Handle $() nesting
            elif (
                char == "$"
                and i + 1 < len(command)
                and command[i + 1] == "("
                and not in_single_quote
                and not in_double_quote
            ):
                paren_depth += 1
                current.append("$(")
                i += 1  # Skip the next (
            elif (
                char == ")"
                and paren_depth > 0
                and not in_single_quote
                and not in_double_quote
            ):
                paren_depth -= 1
                current.append(char)
            # Track brace depth for function definitions (fork bombs)
            elif char == "{" and not in_single_quote and not in_double_quote:
                brace_depth += 1
                current.append(char)
            elif char == "}" and not in_single_quote and not in_double_quote:
                brace_depth -= 1
                current.append(char)
            # Check for command separators (only when not in quotes or nested)
            elif (
                not in_single_quote
                and not in_double_quote
                and paren_depth == 0
                and not in_backtick  # FIX 3: Changed from backtick_depth == 0
                and brace_depth == 0  # Don't split inside function body
            ):
                # Check for &&
                if char == "&" and i + 1 < len(command) and command[i + 1] == "&":
                    if current:
                        sub_commands.append("".join(current).strip())
                        current = []
                    i += 2  # Skip both &
                    continue
                # Check for ||
                elif char == "|" and i + 1 < len(command) and command[i + 1] == "|":
                    if current:
                        sub_commands.append("".join(current).strip())
                        current = []
                    i += 2  # Skip both |
                    continue
                # Check for single | (pipe)
                elif char == "|":
                    if current:
                        sub_commands.append("".join(current).strip())
                        current = []
                    i += 1
                    continue
                # Check for ; (semicolon)
                elif char == ";":
                    if current:
                        sub_commands.append("".join(current).strip())
                        current = []
                    i += 1
                    continue
                else:
                    current.append(char)
            else:
                current.append(char)

            i += 1

        # Add remaining content
        if current:
            remaining = "".join(current).strip()
            if remaining:
                sub_commands.append(remaining)

        return sub_commands

    def classify_command(self, command: str) -> CommandClassification:
        """
        Classify a command by risk level.

        FIX 1 & FIX 3: This method now handles compound commands by splitting them
        and checking each sub-command individually. If ANY sub-command is BLOCKED,
        the entire command is classified as BLOCKED (cannot be bypassed).

        IMPORTANT: Before splitting, we first check if the full command matches any
        BLOCKED pattern directly. This ensures fork bombs and similar attacks that
        might get incorrectly split are still caught.

        Args:
            command: The shell command to classify

        Returns:
            CommandClassification with risk level and reason
        """
        command_stripped = command.strip()

        # FIX 1: First check if the FULL command matches any BLOCKED pattern directly
        # This catches fork bombs and other attacks before any splitting occurs
        for regex in self._blocked_regexes:
            if regex.search(command_stripped):
                return CommandClassification(
                    risk_level=CommandRiskLevel.BLOCKED,
                    reason="Command matches blocked pattern (potentially destructive)",
                    matched_pattern=regex.pattern,
                )

        # FIX 3: Split compound commands and check each sub-command
        sub_commands = self._split_compound_command(command_stripped)

        # If we have multiple sub-commands, check each one
        if len(sub_commands) > 1:
            highest_risk = CommandRiskLevel.SAFE
            highest_reason = ""
            highest_pattern = None

            for sub_cmd in sub_commands:
                sub_result = self._classify_single_command(sub_cmd)

                # BLOCKED always wins - if any sub-command is blocked, whole command is blocked
                if sub_result.risk_level == CommandRiskLevel.BLOCKED:
                    return CommandClassification(
                        risk_level=CommandRiskLevel.BLOCKED,
                        reason=f"Compound command contains blocked sub-command: {sub_cmd}",
                        matched_pattern=sub_result.matched_pattern,
                    )

                # Track highest risk level for non-blocked commands
                risk_order = {
                    CommandRiskLevel.SAFE: 0,
                    CommandRiskLevel.CAUTION: 1,
                    CommandRiskLevel.DANGEROUS: 2,
                }
                if risk_order.get(sub_result.risk_level, 0) > risk_order.get(highest_risk, 0):
                    highest_risk = sub_result.risk_level
                    highest_reason = sub_result.reason
                    highest_pattern = sub_result.matched_pattern

            return CommandClassification(
                risk_level=highest_risk,
                reason=highest_reason,
                matched_pattern=highest_pattern,
            )

        # Single command - use direct classification
        return self._classify_single_command(command_stripped)

    def _classify_single_command(self, command: str) -> CommandClassification:
        """
        Classify a single (non-compound) command by risk level.

        This is the internal classification logic that checks patterns
        without compound command splitting.

        Args:
            command: A single command string (no &&, ;, |, etc.)

        Returns:
            CommandClassification with risk level and reason
        """
        command_stripped = command.strip()

        # Check blocked patterns first (FIX 1: BLOCKED always checked first)
        for regex in self._blocked_regexes:
            if regex.search(command_stripped):
                return CommandClassification(
                    risk_level=CommandRiskLevel.BLOCKED,
                    reason="Command matches blocked pattern (potentially destructive)",
                    matched_pattern=regex.pattern,
                )

        # Check dangerous patterns
        for regex in self._dangerous_regexes:
            if regex.search(command_stripped):
                return CommandClassification(
                    risk_level=CommandRiskLevel.DANGEROUS,
                    reason="Command may be destructive and requires confirmation",
                    matched_pattern=regex.pattern,
                )

        # Check for base commands that are always dangerous
        base_cmd = self._extract_base_command(command_stripped)
        if base_cmd in self.DANGEROUS_BASE_COMMANDS:
            return CommandClassification(
                risk_level=CommandRiskLevel.DANGEROUS,
                reason=f"Command '{base_cmd}' is in the dangerous commands list and requires confirmation",
                matched_pattern=base_cmd,
            )

        # Check caution commands
        for caution_cmd in self.CAUTION_COMMANDS:
            if caution_cmd in command_stripped.lower():
                return CommandClassification(
                    risk_level=CommandRiskLevel.CAUTION,
                    reason=f"Command '{caution_cmd}' should be used with care",
                    matched_pattern=caution_cmd,
                )

        # Check if base command is in safe list
        if base_cmd in self.SAFE_COMMANDS:
            return CommandClassification(
                risk_level=CommandRiskLevel.SAFE,
                reason=f"'{base_cmd}' is a safe command",
            )

        # Default to caution for unknown commands
        return CommandClassification(
            risk_level=CommandRiskLevel.CAUTION,
            reason=f"Unknown command '{base_cmd}', proceeding with caution",
        )

    def _extract_base_command(self, command: str) -> str:
        """
        Extract the base command from a command string.

        Args:
            command: Full command string

        Returns:
            Base command name
        """
        import shlex

        try:
            # Try to parse with shlex for proper handling of quotes
            tokens = shlex.split(command)
            if tokens:
                # Handle pipes and redirects - get first command
                first_cmd = tokens[0]
                # Remove path prefix if present
                return first_cmd.split("/")[-1]
        except ValueError:
            # Fallback to simple split
            parts = command.split()
            if parts:
                return parts[0].split("/")[-1]

        return ""

    def extract_path_like_arguments(self, command: str) -> list[str]:
        """
        Extract path-like arguments from a command for validation.

        Args:
            command: The command to analyze

        Returns:
            List of path-like arguments found in the command
        """
        import shlex

        paths = []
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()

        # Common flags that take path arguments
        path_flags = {
            '-o', '--output', '-O', '-C', '--output-directory', '--file',
            '--if', '-if', '--of', '-of', '--input', '--dest', '--target',
            '--path', '--directory', '--workspace', '--working-directory'
        }

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Check if token is a path flag
            if token in path_flags or (token.startswith('-') and len(token) > 1):
                if i + 1 < len(tokens):
                    next_token = tokens[i + 1]
                    # Skip if next token is a flag (starts with -)
                    if not next_token.startswith('-'):
                        # Check if it looks like a path
                        if ('/' in next_token) or ('\\' in next_token) or (
                                next_token.startswith('~')) or (next_token.startswith('.')):
                            paths.append(next_token)
                            i += 2
                            continue

            # Check for token that contains a path (e.g., "file.txt", "/path/to/file")
            if ('/' in token) or ('\\' in token) or (token.startswith('~')) or (
                    token.startswith('.')):
                # Exclude common safe paths
                if not token in ['..', '.', './', '../']:
                    paths.append(token)

            i += 1

        return paths

    def requires_confirmation(self, command: str) -> bool:
        """
        Check if a command requires user confirmation before execution.

        Args:
            command: The command to check

        Returns:
            True if confirmation is required, False otherwise
        """
        classification = self.classify_command(command)

        # If dangerous mode is enabled, skip confirmation for non-blocked
        if self.allow_dangerous:
            return classification.risk_level == CommandRiskLevel.BLOCKED

        return classification.risk_level in (
            CommandRiskLevel.DANGEROUS,
            CommandRiskLevel.BLOCKED,
        )

    def is_allowed(self, command: str) -> bool:
        """
        Check if a command is allowed to run at all.

        Args:
            command: The command to check

        Returns:
            True if command can potentially run, False if blocked
        """
        classification = self.classify_command(command)
        return classification.risk_level != CommandRiskLevel.BLOCKED

    def get_safety_message(self, command: str) -> str:
        """
        Get a safety message for a command.

        Args:
            command: The command to get message for

        Returns:
            Safety message or empty string if safe
        """
        classification = self.classify_command(command)

        if classification.risk_level == CommandRiskLevel.BLOCKED:
            return (
                f"\u26a0\ufe0f BLOCKED: This command is not allowed for safety reasons.\n"
                f"   Reason: {classification.reason}"
            )
        elif classification.risk_level == CommandRiskLevel.DANGEROUS:
            return (
                f"\u26a0\ufe0f WARNING: This command may be dangerous.\n"
                f"   Reason: {classification.reason}\n"
                f"   Command: {command}\n"
                f"   Are you sure you want to proceed? (y/n)"
            )
        elif classification.risk_level == CommandRiskLevel.CAUTION:
            return (
                f"\u26a0\ufe0f Caution: {classification.reason}\n"
                f"   Command: {command}"
            )
        return ""