"""MiniAgent command-line interface.

Minimal, dependency-light CLI built on typer + rich. Provides:
- version: print the installed miniagent version
- doctor:  validate configuration and environment readiness
- skills:  list skills discovered in a skills directory
- chat:    interactive agent REPL with sandboxed tool execution
- pipeline: run the staged reasoning pipeline on a task

The LLM commands never print the API key; the executor is always gated by
the PermissionChecker.
"""

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="miniagent",
    help="MiniAgent - staged reasoning AI agent framework.",
    no_args_is_help=True,
)
console = Console()


def _get_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("miniagent")
    except Exception:
        return "0.1.0 (not installed)"


@app.command()
def version() -> None:
    """Print the installed miniagent version."""
    console.print(f"miniagent {_get_version()}")


@app.command()
def doctor(
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.yaml (default: $MINIAGENT_CONFIG or ./config.yaml)",
    ),
) -> None:
    """Validate configuration and report environment readiness."""
    from miniagent.config import MiniAgentConfig

    table = Table(title="MiniAgent Doctor", show_header=False)
    table.add_column("Check", style="bold")
    table.add_column("Result")

    try:
        cfg = MiniAgentConfig.load_from_yaml(str(config_path) if config_path else None)
        table.add_row("config", "[green]loaded OK[/green]")
    except Exception as e:
        console.print(table)
        console.print(f"[red]Config failed to load: {type(e).__name__}: {e}[/red]")
        raise typer.Exit(code=1)

    table.add_row("primary model", cfg.llm.primary)
    table.add_row("fallback models", ", ".join(cfg.llm.fallback) or "-")

    missing_keys = [
        provider
        for provider in {cfg.llm.primary.split("/")[0], *[p.split("/")[0] for p in cfg.llm.fallback]}
        if not cfg.llm.api_keys.get(provider)
    ]
    if missing_keys:
        table.add_row(
            "api keys",
            f"[yellow]missing/empty for: {', '.join(sorted(missing_keys))}[/yellow]",
        )
    else:
        table.add_row("api keys", "[green]all providers covered[/green]")

    try:
        import litellm  # noqa: F401

        table.add_row("litellm", "[green]importable[/green]")
    except Exception as e:
        table.add_row("litellm", f"[red]import failed: {e}[/red]")

    workspace = Path(cfg.executor.workspace)
    table.add_row(
        "workspace dir",
        str(workspace.resolve()) if workspace.exists() else f"{workspace} [yellow](not created yet)[/yellow]",
    )
    skills_dir = Path(cfg.skills_dir)
    table.add_row(
        "skills dir",
        str(skills_dir.resolve()) if skills_dir.exists() else f"{skills_dir} [yellow](not created yet)[/yellow]",
    )

    console.print(table)


@app.command()
def skills(
    skills_dir: Path = typer.Argument(Path("./skills"), help="Skills directory to scan"),
) -> None:
    """List skills found in a skills directory."""
    from miniagent.skills.loader import SkillLoader

    loader = SkillLoader(str(skills_dir))
    loaded = loader.load_all_skills()

    if not loaded:
        console.print(f"[yellow]No skills found in {skills_dir}[/yellow]")
        return

    table = Table(title=f"Skills in {skills_dir}")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Triggers")
    table.add_column("Executor")
    for s in loaded:
        table.add_row(
            s.name,
            s.description,
            ", ".join(s.triggers[:3]),
            "yes" if s.requires_executor else "no",
        )
    console.print(table)


@app.command()
def chat(
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.yaml (default: $MINIAGENT_CONFIG or ./config.yaml)",
    ),
    workspace: Path = typer.Option(
        None, "--workspace", help="Override the sandboxed workspace directory"
    ),
    model: str = typer.Option(
        None, "--model", help="Model id override (falls back to config.llm.primary)"
    ),
) -> None:
    """Interactive agent chat (REPL). The model can propose shell commands;
    SAFE ones run automatically, DANGEROUS ask y/N, BLOCKED always refused."""
    from miniagent.cli_chat import ChatSession

    session = ChatSession(config_path=config_path, workspace=workspace, model=model)
    session.run_repl()


@app.command()
def pipeline(
    task: str = typer.Argument(..., help="Task description for the reasoning pipeline"),
    config_path: Path = typer.Option(
        None, "--config", help="Path to config.yaml"
    ),
    workspace: Path = typer.Option(
        None, "--workspace", help="Sandboxed workspace for the Execution stage"
    ),
    model: str = typer.Option(None, "--model", help="Model id override"),
) -> None:
    """Run the 10-stage reasoning pipeline on a task.

    Routes stages by complexity (simple=[1,6,10], complex=all), executes
    stage-8 commands through the sandboxed executor, prints a per-stage
    summary.
    """
    from miniagent.config import MiniAgentConfig
    from miniagent.pipeline import ReasoningPipeline
    from miniagent.pipeline.context import PipelineContext

    cfg = MiniAgentConfig.load_from_yaml(str(config_path) if config_path else None)
    ws = Path(workspace) if workspace else Path(cfg.executor.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    if model:
        cfg.llm.primary = model

    from miniagent.cli_chat import load_api_key

    key, source = load_api_key(config_path)
    if not key:
        console.print("[red]OPENROUTER_API_KEY tidak ditemukan (env / .openrouter_key)[/red]")
        raise typer.Exit(code=1)
    os.environ.setdefault("OPENROUTER_API_KEY", key)

    from miniagent.llm.client import LLMClient
    from miniagent.executor.subprocess_executor import SubprocessExecutor

    client = LLMClient(config=cfg.llm)

    def confirm(cmd: str, reason: str) -> bool:
        console.print(f"[yellow]DANGEROUS:[/yellow] {reason}\ncommand: {cmd}")
        try:
            return input("Jalankan? [y/N] ").strip().lower() == "y"
        except EOFError:
            return False

    executor = SubprocessExecutor(
        workspace_root=str(ws),
        timeout=cfg.executor.timeout,
        confirmation_callback=confirm,
    )

    status_map = {"ok": "green", "_error": "red"}

    def on_stage(sid: int, data: dict) -> None:
        name = f"stage {sid:>2}"
        style = status_map["ok"] if "_error" not in data else status_map["_error"]
        headline = data.get("intent") or data.get("summary") or data.get("verdict") or ""
        if not headline and isinstance(data.get("code"), str):
            headline = "(implementation produced)"
        err = (" ERROR: " + str(data["_error"])[:60]) if "_error" in data else ""
        console.print(f"[{style}]{name}[/{style}] {_safe(headline)[:90]}{err}")

    def _safe(text):
        return str(text or "").encode("ascii", "backslashreplace").decode("ascii")

    pipe = ReasoningPipeline(client, executor=executor, confirmation_callback=confirm, on_stage=on_stage)
    try:
        with console.status("[dim]pipeline berjalan...[/dim]"):
            ctx = pipe.run(task)
    except Exception:
        from miniagent.cli_chat import find_working_free_model

        console.print("[yellow]Model utama gagal - mencoba kandidat model gratis...[/yellow]")
        winner = find_working_free_model(cfg.llm)
        if not winner:
            console.print(
                "[red]Tidak ada model gratis yang bisa dipakai. "
                "Cek https://openrouter.ai/settings/privacy (data policy) atau pakai model berbayar.[/red]"
            )
            raise typer.Exit(code=1)
        console.print(f"[green]Menggunakan model gratis:[/green] {winner}")
        cfg.llm.primary = winner
        client = LLMClient(config=cfg.llm)
        pipe = ReasoningPipeline(client, executor=executor, confirmation_callback=confirm, on_stage=on_stage)
        with console.status("[dim]pipeline berjalan ulang dengan model pengganti...[/dim]"):
            ctx = pipe.run(task)

    if ctx.stopped_reason == "needs_clarification":
        ambig = ctx.get_output(1).get("ambiguities", [])
        console.print(Panel.fit(
            "[yellow]Butuh klarifikasi Anda:[/yellow]\n- " + "\n- ".join(_safe(a) for a in ambig),
            title="pipeline terhenti",
        ))
        return

    if ctx.execution_results:
        table = Table(title="Execution results")
        for col in ("command", "risk", "status", "exit"):
            table.add_column(col)
        for r in ctx.execution_results:
            table.add_row(_safe(r.get("command", ""))[:50], r.get("risk", ""), r.get("status", ""), str(r.get("exit_code", "-")))
        console.print(table)

    fin = ctx.get_output(10)
    summary = fin.get("summary") or json.dumps(fin, ensure_ascii=False)[:400]
    console.print(Panel.fit(_safe(summary), title=f"selesai | {len(ctx.stage_outputs)} stage", border_style="cyan"))


def main() -> None:  # entry point target
    app()


if __name__ == "__main__":
    main()
