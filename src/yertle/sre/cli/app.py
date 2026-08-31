"""Typer-based command-line interface."""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from yertle.sre import __version__
from yertle.sre.agent import build_agent
from yertle.sre.cli.status import probe_all
from yertle.sre.config import Settings

# Load .env into os.environ so:
#   - probes in cli.status see ANTHROPIC_API_KEY
#   - subprocess shell-outs (aws / gh / yertle) inherit AWS_PROFILE,
#     AWS_REGION, YERTLE_ORG, etc. from the user's .env
# Existing shell env vars take precedence — load_dotenv does not override.
load_dotenv()

app = typer.Typer(
    name="yertle-sre",
    help="Natural-language SRE agent for systems modeled in Yertle.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="The question to ask, in plain English.")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override the Claude model name."),
    ] = None,
    max_iterations: Annotated[
        int | None,
        typer.Option(
            "--max-iterations",
            help="Cap the number of agent steps. Cost guardrail.",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream tool calls as they happen."),
    ] = False,
) -> None:
    """Ask the agent a one-shot question and print the answer."""
    if not question.strip():
        err_console.print(
            '[red]Error:[/red] question cannot be empty. Usage: yertle-sre ask "your question"',
        )
        sys.exit(2)

    settings = _load_settings(model=model, max_iterations=max_iterations)
    agent = build_agent(settings)

    inputs = {"messages": [{"role": "user", "content": question}]}
    config = {"recursion_limit": settings.max_iterations}

    if verbose:
        _stream(agent, inputs, config)
    else:
        with console.status("[dim]thinking…[/dim]", spinner="dots"):
            result = agent.invoke(inputs, config=config)
        _print_final(result)


@app.command()
def repl(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override the Claude model name."),
    ] = None,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Cap per-question agent steps."),
    ] = None,
) -> None:
    """Start an interactive session. Context is preserved across questions."""
    settings = _load_settings(model=model, max_iterations=max_iterations)
    agent = build_agent(settings, enable_memory=True)

    thread_id = "repl"
    config = {
        "recursion_limit": settings.max_iterations,
        "configurable": {"thread_id": thread_id},
    }

    console.print(
        Panel.fit(
            "yertle-sre REPL — ask SRE questions about your system.\n"
            "Type [bold]exit[/bold] or press Ctrl-D to quit.",
            border_style="cyan",
        ),
    )

    while True:
        try:
            question = console.input("[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            return

        inputs = {"messages": [{"role": "user", "content": question}]}
        console.print()  # blank line between the user's question and the answer
        # Stream by default in the REPL so tool calls show up live during long
        # investigations — the wall-clock time is the same, but watching
        # progress is far less painful than staring at "thinking…" for a
        # minute. The final assistant message renders as Markdown.
        _stream(agent, inputs, config)
        console.print()  # blank line between the answer and the next prompt


@app.command()
def version() -> None:
    """Print the installed yertle-sre version."""
    console.print(f"yertle-sre {__version__}")


@app.command()
def status() -> None:
    """Show auth/connection status for all underlying CLIs.

    Probes each prerequisite (Anthropic key, yertle, aws, gh) and reports
    what's wired up. Diagnostic only — does not change agent behavior.
    Always exits 0; failures are information, not errors.
    """
    for result in probe_all():
        icon = "[green]✓[/green]" if result.ok else "[red]✗[/red]"
        console.print(f"  {icon} [bold]{result.name:<22}[/bold] {result.detail}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_settings(*, model: str | None, max_iterations: int | None) -> Settings:
    overrides: dict[str, Any] = {}
    if model is not None:
        overrides["model"] = model
    if max_iterations is not None:
        overrides["max_iterations"] = max_iterations
    try:
        return Settings(**overrides)
    # BLE001 suppressed deliberately, not incidentally: this is a CLI entry
    # boundary whose job is to turn *any* settings-construction failure into a
    # one-line message and exit 2, rather than a traceback. pydantic-settings
    # raises ValidationError for bad values but other types for a malformed
    # .env, and the user-facing behavior should not depend on which. The error
    # is reported, never swallowed — that is what the rule exists to prevent.
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(2)


def _print_final(result: dict[str, Any]) -> None:
    messages = result.get("messages", [])
    if not isinstance(messages, list) or not messages:
        err_console.print("[red]Agent returned no messages.[/red]")
        sys.exit(1)
    final = messages[-1]
    content = getattr(final, "content", final)
    if isinstance(content, list):
        # Anthropic content blocks — concatenate text blocks.
        parts = [block.get("text", "") for block in content if isinstance(block, dict)]
        text = "".join(parts)
    else:
        text = str(content)
    # Render Markdown so headers, bold, lists, code fences, and tables
    # display properly instead of leaking literal `**` / `##` / backticks.
    console.print(Markdown(text))


def _stream(agent: Any, inputs: dict[str, Any], config: dict[str, Any]) -> None:
    """Verbose streaming: print tool calls + final answer as they arrive.

    A `console.status` spinner stays pinned to the bottom of the terminal so
    the gaps between tool calls (when Claude is reasoning, which is most of
    the wall-clock time) don't feel frozen. Tool-call lines scroll above
    the spinner via Rich's live-rendering layer.
    """
    last_text = ""
    with console.status("[dim]thinking…[/dim]", spinner="dots"):
        for chunk in agent.stream(inputs, config=config, stream_mode="values"):  # type: ignore[attr-defined]
            messages = chunk.get("messages", [])
            if not messages:
                continue
            latest = messages[-1]
            tool_calls = getattr(latest, "tool_calls", None)
            if tool_calls:
                for call in tool_calls:
                    name = (
                        call.get("name") if isinstance(call, dict) else getattr(call, "name", "?")
                    )
                    args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                    console.print(f"[dim]→ {name}({args})[/dim]")
                continue
            content = getattr(latest, "content", "")
            if isinstance(content, str) and content and content != last_text:
                last_text = content
    if last_text:
        console.print(Markdown(last_text))


if __name__ == "__main__":
    app()
