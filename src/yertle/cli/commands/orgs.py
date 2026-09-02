"""`yertle orgs` — work with organizations."""

import typer
from yertle_client.models import OrganizationResponse

import yertle
from yertle.cli._errors import api_errors
from yertle.cli._render import Column, Format, FormatOption, render

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
