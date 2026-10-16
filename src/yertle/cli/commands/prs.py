"""`yertle prs` — pull requests on a node's branches.

Like branches, pull requests belong to a node, so the node id is the first
positional argument on every verb. PR *numbers* are per-node and restart at
1 for each, which is why `prs show 1` needs a node to mean anything.
"""

from typing import Annotated

import typer
from rich.console import Console
from yertle_client.models import PullRequestResponse
from yertle_client.types import Unset

import yertle
from yertle.cli._context import NodeIdArgument, SingleOrgOption, resolve_one_org
from yertle.cli._errors import api_errors, die
from yertle.cli._render import (
    FORMAT_EPILOG,
    Column,
    Format,
    FormatOption,
    dump_json,
    fields,
    render,
)

app = typer.Typer(
    name="prs",
    help="Work with a node's pull requests.",
    no_args_is_help=True,
    epilog=FORMAT_EPILOG,
)

NumberArgument = Annotated[int, typer.Argument(help="PR number from `yertle prs list`.")]

_STATUS_STYLE = {"open": "green", "merged": "magenta", "closed": "red"}


def _status(pr: PullRequestResponse) -> str:
    """Status, with draft called out — a draft open PR is not ready to merge."""
    colour = _STATUS_STYLE.get(pr.status, "")
    text = f"[{colour}]{pr.status}[/{colour}]" if colour else pr.status
    return f"{text} (draft)" if pr.is_draft else text


def _optional(value: object) -> str:
    """Render a field the backend may not have populated."""
    if value is None or isinstance(value, Unset):
        return "—"
    return str(value)


# Mirrors how `gh pr list` reads: the number first, because it is what every
# other verb takes, then what the PR is and where it is going.
COLUMNS: list[Column[PullRequestResponse]] = [
    Column("#", lambda pr: str(pr.number), style="cyan", no_wrap=True, justify="right"),
    Column("Title", lambda pr: pr.title),
    Column("Status", _status),
    Column("From → To", lambda pr: f"{pr.source_branch} → {pr.target_branch}"),
    Column("Author", lambda pr: _optional(pr.author_email) or pr.author),
]


@app.command("list")
def list_prs(
    node_id: NodeIdArgument,
    org: SingleOrgOption = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter: open, merged or closed."),
    ] = None,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """List a node's pull requests."""
    org_id = resolve_one_org(org, command="prs list")

    with api_errors():
        prs = yertle.prs.list(node_id, org_id=org_id, status=status)

    scope = f"{status} pull requests" if status else "Pull requests"
    render(prs, fmt=fmt, columns=COLUMNS, title=f"{scope} on {node_id} ({len(prs)})")


@app.command("show")
def show_pr(
    node_id: NodeIdArgument,
    number: NumberArgument,
    org: SingleOrgOption = None,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Show one pull request, including whether it can merge."""
    org_id = resolve_one_org(org, command="prs show")

    with api_errors():
        pr = yertle.prs.get(number, node_id=node_id, org_id=org_id)

    if fmt is Format.JSON:
        dump_json(pr)
        return

    console = Console()
    console.print(f"[bold]#{pr.number} {pr.title}[/bold]")
    console.print(f"[dim]{_status(pr)} · {pr.source_branch} → {pr.target_branch}[/dim]")
    description = (pr.description or "").strip() if not isinstance(pr.description, Unset) else ""
    if description:
        console.print(f"\n{description}")

    console.print()
    fields(
        [
            ("Author", _optional(pr.author_email) or pr.author),
            ("Commits ahead", _optional(pr.commits_ahead)),
            ("Can merge", _mergeability(pr)),
            ("Merged by", _optional(pr.merged_by_email)),
            ("Closed by", _optional(pr.closed_by_email)),
        ],
    )


def _mergeability(pr: PullRequestResponse) -> str:
    """Whether it can merge, and why not when it cannot.

    `can_merge` alone is the least useful true thing to print — the reason
    is what tells you what to do next, and the list endpoint does not
    compute either, which is why `show` exists.
    """
    if isinstance(pr.can_merge, Unset) or pr.can_merge is None:
        return "—"
    if pr.can_merge:
        return "yes"
    reason = _optional(pr.merge_reason)
    return f"no — {reason}" if reason != "—" else "no"


@app.command("create")
def create_pr(
    node_id: NodeIdArgument,
    title: Annotated[str, typer.Argument(help="PR title.")],
    org: SingleOrgOption = None,
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Branch to merge from."),
    ] = None,
    target: Annotated[
        str,
        typer.Option("--target", "-t", help="Branch to merge into."),
    ] = yertle.nodes.DEFAULT_BRANCH,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="What this changes and why."),
    ] = None,
    draft: Annotated[bool, typer.Option("--draft", help="Open it as a draft.")] = False,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Open a pull request from one branch into another."""
    org_id = resolve_one_org(org, command="prs create")
    if not source:
        die(
            "`prs create` needs a source branch.\n"
            "  Pass --source <branch>; see `yertle branches list <node-id>`.",
        )

    with api_errors():
        pr = yertle.prs.create(
            title,
            node_id=node_id,
            org_id=org_id,
            source_branch=source,
            target_branch=target,
            description=description,
            draft=draft,
        )

    if fmt is Format.JSON:
        dump_json(pr)
        return

    # The number leads: it is what `prs show`, `merge` and `close` all take.
    typer.echo(str(pr.number))
    console = Console()
    console.print(f"[green]✓[/green] Opened [bold]#{pr.number} {pr.title}[/bold]")
    console.print(f"[dim]  {pr.source_branch} → {pr.target_branch}[/dim]")


@app.command("merge")
def merge_pr(
    node_id: NodeIdArgument,
    number: NumberArgument,
    org: SingleOrgOption = None,
) -> None:
    """Merge a pull request into its target branch.

    Yertle merges fast-forward only: the target branch is advanced to the
    source branch's head, so history stays linear and no merge commit is
    created. If the target has diverged, the merge is refused and the
    source branch has to be rebased first.
    """
    org_id = resolve_one_org(org, command="prs merge")

    with api_errors():
        result = yertle.prs.merge(number, node_id=node_id, org_id=org_id)

    console = Console()
    # Defensive: every failure path on this endpoint is a 4xx, so a 200 always
    # carries merged=true and this cannot currently fire. Kept so a backend
    # that starts reporting soft failures is not read as success. yertle#389.
    if not result.merged:
        die(f"PR #{number} was not merged. Check `yertle prs show {node_id} {number}`.")
    console.print(f"[green]✓[/green] Merged [bold]#{number}[/bold]")
    # Not a merge commit, despite the field's name: Yertle fast-forwards, so
    # this is the source branch's head that the target was advanced to. Saying
    # "merge commit" would send someone looking for a two-parent commit that
    # does not exist. Filed as yertle#389.
    if result.merge_commit:
        console.print(f"[dim]  target fast-forwarded to {result.merge_commit}[/dim]")


@app.command("close")
def close_pr(
    node_id: NodeIdArgument,
    number: NumberArgument,
    org: SingleOrgOption = None,
) -> None:
    """Close a pull request without merging it."""
    org_id = resolve_one_org(org, command="prs close")

    with api_errors():
        pr = yertle.prs.close(number, node_id=node_id, org_id=org_id)

    Console().print(f"[green]✓[/green] Closed [bold]#{pr.number} {pr.title}[/bold]")
