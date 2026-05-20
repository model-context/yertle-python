"""Entry point for the `yertle` command."""

import json as _json

import typer
from rich.console import Console
from rich.table import Table
from yertle_client.api.organizations import list_organizations_orgs_get
from yertle_client.models import OrganizationListResponse

from yertle import __version__
from yertle.cli.auth import CONFIG_PATH, get_client, save_credentials

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


@app.command()
def login(
    api_url: str = typer.Option(
        ...,
        "--api-url",
        help="Yertle API base URL (e.g. https://api.yertle.com).",
    ),
) -> None:
    """Save API credentials to ~/.yertle/config.json."""
    typer.echo(
        f"Generate a token at {api_url.rstrip('/')}/settings/tokens "
        "(PAT support coming soon — a JWT works today).",
    )
    token = typer.prompt("Token", hide_input=True)
    save_credentials(api_url=api_url, token=token)
    typer.echo(f"✓ Saved credentials to {CONFIG_PATH}")


@app.command()
def orgs(
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table | json",
    ),
) -> None:
    """List the organizations you belong to."""
    response = list_organizations_orgs_get.sync(client=get_client())
    if not isinstance(response, OrganizationListResponse):
        typer.secho(f"Unexpected response: {response!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if format == "json":
        payload = [o.to_dict() for o in response.organizations]
        typer.echo(_json.dumps(payload, indent=2, default=str))
        return

    table = Table(title=f"Organizations ({response.total})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    for org in response.organizations:
        table.add_row(str(org.id), org.name)
    Console().print(table)


if __name__ == "__main__":
    app()
