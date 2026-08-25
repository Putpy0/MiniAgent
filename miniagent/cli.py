"""MiniAgent command-line interface.

Minimal, dependency-light CLI built on typer + rich. Provides:
- version: print the installed miniagent version
- doctor:  validate configuration and environment readiness
- skills:  list skills discovered in a skills directory

No command performs network access or executes shell commands; the LLM
client and executor are intentionally NOT wired into the CLI yet.
"""

from pathlib import Path

import typer
from rich.console import Console
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


def main() -> None:  # entry point target
    app()


if __name__ == "__main__":
    main()
