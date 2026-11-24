"""`yertle orgs` — work with organizations."""

from typing import Annotated

import typer
from rich.console import Console
from yertle_client.models import OrganizationResponse, PublicOrganizationResponse
from yertle_client.types import Unset

import yertle
from yertle._ids import is_short_id
from yertle.cli._context import (
    ALL_ORGS,
    anonymous,
    member_or_public,
    public_fallback_hint,
    validate_org,
)
from yertle.cli._errors import api_errors, die
from yertle.cli._render import (
    FORMAT_EPILOG,
    Column,
    Format,
    FormatOption,
    display_path,
    dump_json,
    fields,
    render,
    short_id,
)
from yertle.shared import auth

app = typer.Typer(
    name="orgs",
    help="Work with organizations.",
    no_args_is_help=True,
    epilog=FORMAT_EPILOG,
)


def _visibility(org: OrganizationResponse) -> str:
    """Render `is_public` the way the web app labels it.

    Shared by `list` and `show` so the two cannot disagree about what a
    boolean named `is_public` is called at a prompt.
    """
    return "public" if org.is_public else "private"


# Mirrors the columns the web app's organization list shows, in the same
# order. `/orgs` populates `member_count`, `node_count`, `is_public` and
# `role` already, so none of these costs an extra request — only
# `invite_mode` is null on this endpoint, which is why `show` still merges
# (see `_merged`).
COLUMNS: list[Column[OrganizationResponse]] = [
    Column("ID", lambda org: short_id(org.id), style="cyan", no_wrap=True),
    Column("Name", lambda org: org.name),
    Column("Members", lambda org: _optional(org.member_count), justify="right"),
    Column("Nodes", lambda org: _optional(org.node_count), justify="right"),
    Column("Visibility", _visibility),
    Column("Role", lambda org: _optional(org.role)),
]


@app.command("list")
def list_orgs(fmt: FormatOption = Format.TABLE) -> None:
    """List the organizations you belong to."""
    with api_errors():
        organizations = yertle.orgs.list()

    render(
        organizations,
        fmt=fmt,
        columns=COLUMNS,
        title=f"Organizations ({len(organizations)})",
    )


# The docstring's first line is what `yertle orgs` shows in its command list,
# and the only place most people look, so it names 'all': that is what makes
# the escape hatch discoverable rather than known only to readers of --help.
#
# A short id is resolved to the full one before it is saved. Stored as typed,
# it would be resolved afresh by every later command, and could start meaning
# a different org, or none, as orgs are created.
@app.command("use")
def use_org(
    org: Annotated[
        str,
        typer.Argument(
            help=f"Organization id from `yertle orgs list` (a short id will do), or '{ALL_ORGS}'."
        ),
    ],
) -> None:
    """Set the default organization, or 'all' to clear it.

    The default applies to commands that start from an organization: `nodes
    list`, `nodes tree`, `nodes search` and `nodes create`. Commands that take
    a node id (`nodes show`, `nodes delete`, `branches`, `prs`) look the
    organization up from the node instead, so they work for any node you can
    see, whatever the default.

    Persists to ~/.yertle/config.json, so it survives between shells, the
    same role `gcloud config set project` or `kubectl config use-context`
    plays. `--org` and $YERTLE_ORG still win over it for one-off overrides.

    Pass 'all' to go back to every organization, without hand-editing the
    config file.
    """
    value = validate_org(org.strip())
    name = None
    if is_short_id(value):
        value, name = _resolve_org(value)
    auth.save_org(value)

    where = display_path(auth.CONFIG_PATH)
    if value == ALL_ORGS:
        typer.echo(f"✓ Default organization cleared — commands will use every org ({where})")
        return
    named = f" ({name})" if name else ""
    typer.echo(f"✓ Default organization set to {value}{named} ({where})")


def _resolve_org(short: str) -> tuple[str, str]:
    """Return the full id and name of the org a short id names.

    The same read `orgs show` makes, so it works for exactly the orgs that
    command can show: your own, and a public one, signed in or not.
    """
    if anonymous():
        with api_errors(public=True):
            public_org = yertle.public.get_org(short)
        return public_org.id, public_org.name
    with api_errors():
        org, _ = member_or_public(
            lambda: yertle.orgs.get(short), lambda: yertle.public.get_org(short)
        )
    return org.id, org.name


def _optional(value: object) -> str:
    """Render a field the backend may not have populated.

    `—` is deliberately different from `0`: an absent member count means the
    endpoint did not compute one, which is not the same as an empty org.
    """
    if value is None or isinstance(value, Unset):
        return "—"
    return str(value)


def _merged(org_id: str) -> OrganizationResponse:
    """Fetch one org, filling the gaps the detail endpoint leaves.

    The two endpoints disagree about what they populate: `/orgs` returns
    `role` and `member_count` but not `invite_mode`; `/orgs/{id}` returns
    `invite_mode` but leaves the other two null. Showing only the detail
    endpoint would make `orgs show` display *less* than `orgs list` for the
    same org, which reads as a bug rather than as a backend quirk.

    So the list response backfills. It is one extra request on an interactive
    command, and `/orgs` returns every org the caller belongs to in a single
    response. The real fix is for `/orgs/{id}` to populate all three; until
    then this keeps the detail view a superset of the list view.
    """
    org = yertle.orgs.get(org_id)
    if org.role is not None and not isinstance(org.role, Unset):
        return org
    # Compare with the id the backend returned, not the one typed: that may
    # be a short id, and would then match nothing.
    for candidate in yertle.orgs.list():
        if str(candidate.id) == str(org.id):
            org.role = candidate.role
            org.member_count = candidate.member_count
            break
    return org


@app.command("show")
def show_org(
    org_id: Annotated[str, typer.Argument(help="Organization id from `yertle orgs list`.")],
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Show an organization's details. Works without a token for a public org."""
    if validate_org(org_id.strip()) == ALL_ORGS:
        die(f"`orgs show` needs one organization id, not '{ALL_ORGS}'.")

    org_id = org_id.strip()
    if anonymous():
        with api_errors(public=True):
            public_org = yertle.public.get_org(org_id)
        _show_public_org(
            public_org, fmt, note="Read without a token. Run `yertle login` to see your own orgs."
        )
        return

    with api_errors():
        org, _ = member_or_public(lambda: _merged(org_id), lambda: yertle.public.get_org(org_id))
    if isinstance(org, PublicOrganizationResponse):
        _show_public_org(org, fmt)
        public_fallback_hint()
        return

    if fmt is Format.JSON:
        dump_json(org)
        return

    typer.echo(f"{org.name}")
    typer.secho(str(org.id), dim=True)
    if description := (org.description or "").strip():
        typer.echo(f"\n{description}")

    typer.echo()
    fields(
        [
            ("Public ID", _optional(org.public_id)),
            ("Role", _optional(org.role)),
            ("Members", _optional(org.member_count)),
            ("Nodes", _optional(org.node_count)),
            ("Invite mode", _optional(org.invite_mode)),
            ("Visibility", _visibility(org)),
            ("Root node", _optional(org.root_node_id)),
        ],
    )


def _show_public_org(
    org: PublicOrganizationResponse, fmt: Format, *, note: str | None = None
) -> None:
    """Show what the public route returns about an org: less than a member sees.

    `note` closes the table view only, so `--format json` stays exactly the
    backend's response.
    """
    if fmt is Format.JSON:
        dump_json(org)
        return

    typer.echo(org.name)
    typer.secho(org.id, dim=True)
    if description := (org.description or "").strip():
        typer.echo(f"\n{description}")
    typer.echo()
    fields(
        [
            ("Members", str(org.member_count)),
            ("Nodes", str(org.node_count)),
            ("Visibility", "public"),
        ],
    )
    if note:
        typer.secho(f"\n{note}", dim=True)


@app.command("create")
def create_org(
    name: Annotated[str, typer.Argument(help="Name for the new organization.")],
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="What this organization is for."),
    ] = None,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Create an organization.

    You become its owner. The backend also creates a [bold]Root[/bold] node for it —
    that is the node everything else hangs off, so its id is printed too.
    """
    with api_errors():
        org = yertle.orgs.create(name, description=description)

    if fmt is Format.JSON:
        dump_json(org)
        return

    # The id leads, matching `nodes create`, so `$(... | head -1)` captures it.
    typer.echo(str(org.id))
    console = Console()
    console.print(f"[green]✓[/green] Created [bold]{org.name}[/bold]")
    root = org.root_node_id
    if root and not isinstance(root, Unset):
        console.print(f"[dim]  Root node {root} — attach nodes to this one.[/dim]")
    console.print(f"[dim]  Use it by default: yertle orgs use {org.id}[/dim]")


@app.command("update")
def update_org(
    org_id: Annotated[str, typer.Argument(help="Organization id from `yertle orgs list`.")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="New name.")] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="New description. Pass '' to clear it."),
    ] = None,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Rename an organization, or change its description.

    Only what you pass is changed; anything you leave out is untouched. An
    empty --description clears the description, which is different from
    omitting the option.
    """
    if validate_org(org_id.strip()) == ALL_ORGS:
        die(f"`orgs update` needs one organization id, not '{ALL_ORGS}'.")
    if name is None and description is None:
        die("Nothing to change. Pass --name, --description, or both.")

    with api_errors():
        org = yertle.orgs.update(org_id.strip(), name=name, description=description)

    if fmt is Format.JSON:
        dump_json(org)
        return

    console = Console()
    console.print(f"[green]✓[/green] Updated [bold]{org.name}[/bold]")
    changed = [
        label
        for label, value in (("name", name), ("description", description))
        if value is not None
    ]
    console.print(f"[dim]  {' and '.join(changed)} changed · {org.id}[/dim]")
