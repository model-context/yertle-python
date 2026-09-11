"""`yertle orgs` — work with organizations."""

from typing import Annotated

import typer
from yertle_client.models import OrganizationResponse

import yertle
from yertle.cli._context import ALL_ORGS, validate_org
from yertle.cli._errors import api_errors
from yertle.cli._render import Column, Format, FormatOption, display_path, render
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
    """Set the default organization for org-scoped commands.

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
