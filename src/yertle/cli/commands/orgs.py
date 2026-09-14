"""`yertle orgs` — work with organizations."""

from typing import Annotated

import typer
from yertle_client.models import OrganizationResponse
from yertle_client.types import Unset

import yertle
from yertle.cli._context import ALL_ORGS, validate_org
from yertle.cli._errors import api_errors, die
from yertle.cli._render import (
    Column,
    Format,
    FormatOption,
    display_path,
    dump_json,
    fields,
    render,
)
from yertle.shared import auth

app = typer.Typer(
    name="orgs",
    help="Work with organizations.",
    no_args_is_help=True,
)

COLUMNS: list[Column[OrganizationResponse]] = [
    Column("ID", lambda org: str(org.id), style="cyan", no_wrap=True),
    Column("Name", lambda org: org.name),
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


@app.command("use")
def use_org(
    org: Annotated[
        str,
        typer.Argument(help=f"Organization id from `yertle orgs list`, or '{ALL_ORGS}'."),
    ],
) -> None:
    """Set the default organization, or 'all' to clear it.

    The first line is what `yertle orgs` shows in its command list, and it is
    the only place most people will look. Naming 'all' there is the difference
    between the escape hatch being discoverable and it existing only for
    readers of `--help`.

    Persists to ~/.yertle/config.json, so it survives between shells — the
    same role `gcloud config set project` or `kubectl config use-context`
    plays. `--org` and $YERTLE_ORG still win over it for one-off overrides.

    Pass 'all' to go back to every organization; that is the way to undo a
    previous choice without hand-editing the config file.
    """
    value = validate_org(org.strip())
    auth.save_org(value)

    where = display_path(auth.CONFIG_PATH)
    if value == ALL_ORGS:
        typer.echo(f"✓ Default organization cleared — commands will use every org ({where})")
        return
    typer.echo(f"✓ Default organization set to {value} ({where})")


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
    for candidate in yertle.orgs.list():
        if str(candidate.id) == org_id:
            org.role = candidate.role
            org.member_count = candidate.member_count
            break
    return org


@app.command("show")
def show_org(
    org_id: Annotated[str, typer.Argument(help="Organization id from `yertle orgs list`.")],
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Show an organization's details."""
    if validate_org(org_id.strip()) == ALL_ORGS:
        die(f"`orgs show` needs one organization id, not '{ALL_ORGS}'.")

    with api_errors():
        org = _merged(org_id.strip())

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
            ("Visibility", "public" if org.is_public else "private"),
            ("Root node", _optional(org.root_node_id)),
        ],
    )
