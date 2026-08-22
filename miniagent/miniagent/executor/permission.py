"""Command safety checker with whitelist/blacklist for dangerous operations."""

import re
from dataclasses import dataclass
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
        r"dd\s+if=/dev/zero",
        r"dd\s+if=/dev/random",
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
    ]

    # Commands that require caution but are commonly needed
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
        ": > largefile",  # Truncate via redirect
    ]

    # Safe commands that don't need confirmation (whitelist)
    SAFE_COMMANDS = [
        "ls",
        "dir",
        "pwd",
        "echo",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "wc",
        "grep",
        "find",
        "which",
        "whereis",
        "man",
        "help",
        "type",
        "stat",
        "file",
        "uname",
        "hostname",
        "whoami",
        "date",
        "time",
        "uptime",
        "free",
        "df",
        "du",
        "top",
        "ps",
        "pgrep",
        "pidof",
        "env",
        "printenv",
        "export",
        "alias",
        "unalias",
        "set",
        "shopt",
        "cd",
        "mkdir",
        "touch",
        "cp",
        "mv",
        "ln",
        "chmod",
        "chown",
        "tar",
        "gzip",
        "gunzip",
        "zip",
        "unzip",
        "bzip2",
        "xz",
        "python",
        "python3",
        "pip",
        "pip3",
        "npm",
        "npx",
        "node",
        "yarn",
        "git",
        "ssh",
        "scp",
        "rsync",
        "curl",
        "wget",
        "ping",
        "traceroute",
        "netstat",
        "ss",
        "dig",
        "nslookup",
        "host",
        "make",
        "cmake",
        "gcc",
        "g++",
        "clang",
        "rustc",
        "cargo",
        "go",
        "javac",
        "java",
        "docker",
        "docker-compose",
        "kubectl",
        "helm",
        "terraform",
        "ansible",
        "vim",
        "nano",
        "emacs",
        "code",
        "bat",
        "ripgrep",
        "rg",
        "ag",
        "jq",
        "yq",
        "sed",
        "awk",
        "sort",
        "uniq",
        "cut",
        "paste",
        "tr",
        "diff",
        "patch",
        "cmp",
        "comm",
        "md5sum",
        "sha1sum",
        "sha256sum",
        "sha512sum",
        "openssl",
        "base64",
        "xxd",
        "hexdump",
        "od",
        "strings",
        "test",
        "[",
        "true",
        "false",
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
        paren_depth = 0
        backtick_depth = 0
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
            # Handle backticks
            elif char == "`" and not in_single_quote and not in_double_quote:
                backtick_depth += 1
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
                and backtick_depth == 0
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

        # Check caution commands
        for caution_cmd in self.CAUTION_COMMANDS:
            if caution_cmd in command_stripped.lower():
                return CommandClassification(
                    risk_level=CommandRiskLevel.CAUTION,
                    reason=f"Command '{caution_cmd}' should be used with care",
                    matched_pattern=caution_cmd,
                )

        # Extract base command for whitelist check
        base_cmd = self._extract_base_command(command_stripped)

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
                f"⛔ BLOCKED: This command is not allowed for safety reasons.\n"
                f"   Reason: {classification.reason}"
            )
        elif classification.risk_level == CommandRiskLevel.DANGEROUS:
            return (
                f"⚠️  WARNING: This command may be dangerous.\n"
                f"   Reason: {classification.reason}\n"
                f"   Command: {command}\n"
                f"   Are you sure you want to proceed? (y/n)"
            )
        elif classification.risk_level == CommandRiskLevel.CAUTION:
            return (
                f"ℹ️  Caution: {classification.reason}\n"
                f"   Command: {command}"
            )
        return ""
