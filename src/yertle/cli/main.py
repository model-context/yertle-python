"""Entry point for the `yertle` command.

This module is the composition root and nothing else: it builds the Typer app
and mounts the command modules from `cli/commands/`. Behaviour lives in those
modules, presentation helpers in `cli/_render.py`, failure paths in
`cli/_errors.py`.

Commands are noun-then-verb, like `gh` and the AWS CLI — `yertle orgs list`,
not `yertle orgs`. A bare noun prints help.
"""

import typer

from yertle.cli.commands import auth, login, nodes, orgs, version

app = typer.Typer(
    name="yertle",
    help="CLI for Yertle — the architecture-graph platform.",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """CLI for Yertle — the architecture-graph platform."""


app.command(name="version")(version.version)
app.command(name="login")(login.login)
app.add_typer(orgs.app)
app.add_typer(nodes.app)
app.add_typer(auth.app)


if __name__ == "__main__":
    app()
