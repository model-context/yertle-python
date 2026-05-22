"""Entry point for the `yertle` command."""

import typer

from yertle import __version__

app = typer.Typer(
    name="yertle",
    help="CLI for Yertle — the architecture-graph platform.",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """CLI for Yertle — the architecture-graph platform."""


@app.command()
def version() -> None:
    """Print the installed yertle version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
