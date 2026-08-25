"""Interactive chat session for the MiniAgent CLI (opencode/claw-style REPL).

Protocol: the model proposes shell commands inside fenced blocks tagged
``run`` (bash/sh accepted as aliases). Each proposed command goes through
PermissionChecker classification:

- SAFE      -> executed automatically in the session workspace
- DANGEROUS -> interactive y/N confirmation, then executed if approved
- BLOCKED   -> always refused

Tool results are fed back into the conversation so the model can react to
real output instead of inventing it.
"""

import os
import re
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

RUN_BLOCK_RE = re.compile(
    r"```(?:run|shell|bash|sh)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)

MAX_TOOL_CALLS_PER_TURN = 3
MAX_HISTORY_MESSAGES = 24

# Verified free via OpenRouter /models API on 2026-08-25. The plain
# "openrouter/free" router is intentionally absent - its Stealth provider
# returned 502s during testing.
FREE_MODEL_CANDIDATES = [
    "openrouter/z-ai/glm-5.2:free",
    "openrouter/google/gemma-4-31b-it:free",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/thinkingmachines/inkling:free",
    "openrouter/poolside/laguna-s-2.1:free",
    "openrouter/cohere/north-mini-code:free",
]

SYSTEM_PROMPT_TEMPLATE = """You are MiniAgent, a careful terminal coding assistant.
You are running INSIDE a sandboxed workspace at: {workspace}

Rules:
1. Answer concisely, in the same language the user writes in.
2. When you need to run a shell command, reply with a one-line explanation and
   include EXACTLY ONE fenced block tagged `run` containing a single command:
   ```run
   <one single shell command>
   ```
3. Only propose commands whose file targets stay inside the workspace.
   Never propose destructive commands (rm -rf, dd to devices, etc).
4. Command results arrive back to you as "[tool ...]" messages. NEVER invent
   execution output; wait for the real result."""


def _safe(text: object) -> str:
    """Make arbitrary text (LLM output, provider errors) printable on any
    console encoding - non-representable chars become \\uXXXX escapes."""
    return str(text or "").encode("ascii", "backslashreplace").decode("ascii")


def parse_run_blocks(text: str) -> list[str]:
    """Extract candidate shell commands from ```run fenced blocks.

    Multi-line blocks yield one command per non-empty line. Returns at most
    MAX_TOOL_CALLS_PER_TURN commands.
    """
    commands: list[str] = []
    for match in RUN_BLOCK_RE.finditer(text or ""):
        for line in match.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
                if len(commands) >= MAX_TOOL_CALLS_PER_TURN:
                    return commands
    return commands


def load_api_key(config_path: Optional[Path]) -> tuple[Optional[str], str]:
    """Resolve the OpenRouter key: env var first, then .openrouter_key
    sitting next to the config file. Returns (key, source)."""
    env = os.getenv("OPENROUTER_API_KEY")
    if env:
        return env, "environment"
    if config_path is not None:
        sibling = Path(config_path).parent / ".openrouter_key"
        if sibling.exists():
            value = sibling.read_text(encoding="utf-8").strip()
            if value:
                return value, str(sibling)
    return None, ""


class ChatSession:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        workspace: Optional[Path] = None,
        model: Optional[str] = None,
        console: Optional[Console] = None,
    ):
        from miniagent.config import MiniAgentConfig

        self.console = console or Console()
        self.config_path = (
            Path(config_path)
            if config_path
            else Path(os.getenv("MINIAGENT_CONFIG", "config.yaml"))
        )
        self.config = MiniAgentConfig.load_from_yaml(str(self.config_path))
        self.workspace = Path(workspace) if workspace else Path(self.config.executor.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        if model:
            self.config.llm.primary = model

        self.history: list[dict[str, str]] = []
        self.client = None  # built lazily once a key/model is settled
        self._probed_fallback = False

    # ---------- setup ----------

    def _ensure_client(self) -> bool:
        """Build LLMClient; returns False when no usable API key exists."""
        if self.client is not None:
            return True

        from miniagent.llm.client import LLMClient

        key, source = load_api_key(self.config_path)
        if not key:
            self.console.print(
                Panel.fit(
                    "[red]API key OpenRouter tidak ditemukan.[/red]\n\n"
                    "Salah satu dari:\n"
                    "1. set environment variable OPENROUTER_API_KEY, atau\n"
                    f"2. taruh key di {self.config_path.parent / '.openrouter_key'}\n"
                    "(ambil gratis di https://openrouter.ai/settings/keys)",
                    title="miniagent chat",
                )
            )
            return False
        os.environ["OPENROUTER_API_KEY"] = key  # let ${...} validators resolve
        self.key_source = source
        self._build_client(self.config.llm.primary)
        return True

    def _build_client(self, primary: str) -> None:
        from miniagent.llm.client import LLMClient

        self.model = primary
        self.config.llm.primary = primary
        self.client = LLMClient(config=self.config.llm)

    def _probe_free_models(self) -> bool:
        """On total failure of the configured model, try free candidates."""
        if self._probed_fallback:
            return False
        self._probed_fallback = True
        self.console.print("[yellow]Model utama gagal - mencoba kandidat model gratis...[/yellow]")
        for candidate in FREE_MODEL_CANDIDATES:
            try:
                probe_cfg = self.config.llm.model_copy(
                    update={"primary": candidate, "fallback": [], "max_retries": 0, "max_tokens": 16}
                )
                from miniagent.llm.client import LLMClient

                probe = LLMClient(config=probe_cfg)
                r = probe.chat("Balas satu kata: siap")
                if r.content.strip():
                    self.console.print(f"[green]Menggunakan model gratis:[/green] {candidate}")
                    self._build_client(candidate)
                    return True
            except Exception as e:
                self.console.print(f"  [dim]{_safe(candidate)}: {_safe(str(e))[:80]}[/dim]")
        return False

    # ---------- tool execution ----------

    def _confirm_dangerous(self, command: str, reason: str) -> bool:
        self.console.print(f"[yellow]DANGEROUS:[/yellow] {reason}")
        try:
            answer = input(f"Jalankan '{command}'? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        return answer == "y"

    def _execute_commands(self, commands: list[str]) -> list[dict[str, str]]:
        from miniagent.executor.permission import PermissionChecker
        from miniagent.executor.subprocess_executor import SubprocessExecutor

        checker = PermissionChecker()
        executor = SubprocessExecutor(
            workspace_root=str(self.workspace),
            timeout=self.config.executor.timeout,
            confirmation_callback=self._confirm_dangerous,
        )

        results = []
        for cmd in commands:
            classification = checker.classify_command(cmd)
            risk = classification.risk_level.value
            style = {"safe": "green", "caution": "yellow", "dangerous": "red", "blocked": "red"}[risk]
            self.console.print("[" + style + "]$"
                               + _safe(cmd) + " [dim](" + risk + ")[/]")
            if risk == "blocked":
                results.append({"command": cmd, "refused": classification.reason})
                continue
            # Executor default shell=False treats '>' literally; commands with
            # shell operators need shell=True. Safety checks (classification +
            # workspace containment) already ran above, before this call.
            needs_shell = any(ch in cmd for ch in ">&|;")
            result = executor.run_command(cmd, shell=needs_shell)
            summary = (
                f"[tool exit={result.exit_code}]"
                + (f" stdout: {result.stdout[:800]}" if result.stdout else "")
                + (f" stderr: {result.stderr[:400]}" if result.stderr else "")
                + (f" error: {result.error}" if result.error else "")
            )
            results.append({"command": cmd, "result": summary})
        return results

    # ---------- repl ----------

    HELP_ROWS = [
        ("/help", "tampilkan bantuan"),
        ("/reset", "kosongkan riwayat percakapan"),
        ("/model <id>", "ganti model"),
        ("/models", "daftar kandidat model gratis"),
        ("/history", "jumlah pesan tersimpan"),
        ("/exit, /quit", "keluar"),
    ]

    def run_repl(self) -> None:
        if not self._ensure_client():
            raise SystemExit(1)

        self.console.print(
            Panel.fit(
                f"[bold]MiniAgent chat[/bold]\n"
                f"model     : {self.model}\n"
                f"workspace : {self.workspace.resolve()}\n"
                f"key       : {getattr(self, 'key_source', '?')}\n\n"
                "Ketik pesan biasa untuk mengobrol. Model boleh mengusulkan command\n"
                "(SAFE jalan otomatis, DANGEROUS diminta konfirmasi, BLOCKED selalu ditolak).\n"
                "/help untuk daftar perintah.",
                border_style="cyan",
            )
        )

        while True:
            try:
                line = self.console.input("[bold green]you ›[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]bye[/dim]")
                break

            if not line:
                continue

            action = self._dispatch_slash(line)
            if action == "exit":
                break
            if action == "continue":
                continue

            self._handle_turn(line)

    def _dispatch_slash(self, line: str) -> str:
        """Return 'exit' | 'continue' | '' (empty = bukan slash, proses normal)."""
        if not line.startswith("/"):
            return ""

        parts = line.split(maxsplit=1)
        name = parts[0].lower()

        if name in ("/exit", "/quit"):
            self.console.print("[dim]bye[/dim]")
            return "exit"
        if name == "/help":
            table = Table(show_header=False, box=None)
            table.add_column(style="cyan")
            table.add_column()
            for row in self.HELP_ROWS:
                table.add_row(*row)
            self.console.print(table)
            return "continue"
        if name == "/reset":
            self.history.clear()
            self._probed_fallback = False
            self.console.print("[dim]riwayat dikosongkan[/dim]")
            return "continue"
        if name == "/model":
            new_model = parts[1].strip() if len(parts) > 1 else ""
            if not new_model:
                self.console.print(f"model aktif: {self.model}")
            elif self.client is not None:
                self._build_client(new_model)
                self.console.print(f"[green]model diganti ke[/green] {new_model}")
            return "continue"
        if name == "/models":
            self.console.print("\n".join(FREE_MODEL_CANDIDATES))
            return "continue"
        if name == "/history":
            self.console.print(f"{len(self.history)} pesan di riwayat")
            return "continue"

        self.console.print(f"[yellow]Perintah tidak dikenal:[/yellow] {name} (/help)")
        return "continue"

    def _handle_turn(self, user_text: str) -> None:
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(workspace=self.workspace.resolve())
        trimmed = self.history[-MAX_HISTORY_MESSAGES:]

        chunks: list[str] = []
        try:
            self.console.print(f"[dim]{_safe(self.model)}[/dim]")
            for delta in self.client.chat_stream(
                user_text,
                conversation_history=trimmed,
                system_prompt=system_prompt,
            ):
                chunks.append(_safe(delta))
                self.console.out(chunks[-1], end="")
            self.console.print("\n")
        except Exception as e:
            if not chunks:
                # Nothing streamed yet - treat as a normal failure so the
                # free-model fallback logic can kick in.
                self.console.print("[red]Permintaan gagal:[/red] " + _safe(str(e))[:160])
                if self._probe_free_models():
                    return self._handle_turn(user_text)
                return
            self.console.print(
                "\n[red][stream terputus: " + _safe(str(e))[:80] + "][/red]"
            )

        content = "".join(chunks).strip()
        if not content:
            self.console.print("[yellow](jawaban kosong dari model)[/yellow]")
            return
        self.history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": content},
            ]
        )

        commands = parse_run_blocks(content)
        if not commands:
            return

        results = self._execute_commands(commands)
        tool_summary = "\n".join(
            r.get("result") or f"[refused] {r.get('refused', '')[:120]}" for r in results
        )
        # Feed real outcomes back so the model can react on its next turn.
        self.history.append(
            {
                "role": "user",
                "content": f"[tool results]\n{tool_summary}\nRingkas hasilnya untuk user.",
            }
        )
