"""`yertle branches` — work with a node's branches.

Branches belong to a node, not to an organization, so every verb here takes
a node id. That is why the node is the first positional argument rather than
an option: it is the subject of the command, the way a repository is for
`git branch`.
"""

from typing import Annotated

import typer
from rich.console import Console
from yertle_client.models import BranchResponse
from yertle_client.types import Unset

import yertle
from yertle.cli._context import NodeIdArgument, SingleOrgOption, resolve_one_org
from yertle.cli._errors import api_errors
from yertle.cli._render import (
    FORMAT_EPILOG,
    Column,
    Format,
    FormatOption,
    dump_json,
    render,
)

app = typer.Typer(
    name="branches",
    help="Work with a node's branches.",
    no_args_is_help=True,
    epilog=FORMAT_EPILOG,
)


def _optional(value: object) -> str:
    """Render a field the backend may not have populated."""
    if value is None or isinstance(value, Unset):
        return "—"
    return str(value)


def _short(commit: str) -> str:
    """Abbreviate a commit id the way git does in a listing.

    The full id is 36 characters and this table already carries a branch
    name and a message; `--format json` keeps the whole thing for anyone who
    needs to pass it back.
    """
    return commit[:8] if commit else "—"


COLUMNS: list[Column[BranchResponse]] = [
    Column("Branch", lambda b: b.name, style="cyan", no_wrap=True),
    Column("Head", lambda b: _short(b.head_commit), no_wrap=True),
    Column("Base", lambda b: _optional(b.base_branch)),
    Column("Last commit", lambda b: _optional(b.head_commit_message)),
]


@app.command("list")
def list_branches(
    node_id: NodeIdArgument, org: SingleOrgOption = None, fmt: FormatOption = Format.TABLE
) -> None:
    """List the branches on a node."""
    org_id = resolve_one_org(org, command="branches list")

    with api_errors():
        branches = yertle.branches.list(node_id, org_id=org_id)

    render(
        branches,
        fmt=fmt,
        columns=COLUMNS,
        title=f"Branches on {node_id} ({len(branches)})",
    )


@app.command("create")
def create_branch(
    node_id: NodeIdArgument,
    name: Annotated[str, typer.Argument(help="Name for the new branch.")],
    org: SingleOrgOption = None,
    base: Annotated[
        str,
        typer.Option("--base", "-b", help="Branch to fork from."),
    ] = yertle.nodes.DEFAULT_BRANCH,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Create a branch on a node.

    The branch starts at the base's head commit, so it is identical to the
    base until something is pushed to it.
    """
    org_id = resolve_one_org(org, command="branches create")

    with api_errors():
        branch = yertle.branches.create(name, node_id=node_id, org_id=org_id, base_branch=base)

    if fmt is Format.JSON:
        dump_json(branch)
        return

    console = Console()
    console.print(f"[green]✓[/green] Created branch [bold]{branch.name}[/bold] from {base}")
    console.print(f"[dim]  at {branch.head_commit}[/dim]")


@app.command("delete")
def delete_branch(
    node_id: NodeIdArgument,
    name: Annotated[str, typer.Argument(help="Branch to delete.")],
    org: SingleOrgOption = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Delete even if the branch has open pull requests.",
        ),
    ] = False,
) -> None:
    """Delete a branch.

    Unlike `git branch -d`, this does NOT check whether the branch was
    merged. The backend gates only on open pull requests, and `--force`
    overrides that one check. A branch holding commits that exist nowhere
    else will be deleted without complaint.

    `main` cannot be deleted.
    """
    org_id = resolve_one_org(org, command="branches delete")

    with api_errors():
        message = yertle.branches.delete(name, node_id=node_id, org_id=org_id, force=force)

    Console().print(f"[green]✓[/green] {message}")
