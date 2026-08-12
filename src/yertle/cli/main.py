"""Entry point for the `yertle` command."""

import json as _json
from http import HTTPStatus

import typer
from rich.console import Console
from rich.table import Table
from yertle_client.api.organizations import list_organizations_orgs_get
from yertle_client.client import AuthenticatedClient
from yertle_client.errors import UnexpectedStatus
from yertle_client.models import OrganizationListResponse

from yertle import __version__
from yertle.shared.auth import CONFIG_PATH, AuthError, get_client, save_credentials


def _format_api_error(client: AuthenticatedClient, exc: UnexpectedStatus) -> str:
    """Build a user-facing message for an unexpected API response.

    Critically, the message includes the effective base URL so a misconfigured
    `$YERTLE_API_URL` (or stale config) becomes obvious instead of silently
    hitting the wrong backend.
    """
    base_url = getattr(client, "_base_url", "<unknown>")
    status = exc.status_code
    if status == HTTPStatus.UNAUTHORIZED:
        hint = (
            "401 Unauthorized — token rejected by the backend. "
            "Likely causes: the token was issued by a different backend than "
            "the one you're hitting, the token was revoked, or it has expired."
        )
    elif status == HTTPStatus.FORBIDDEN:
        hint = "403 Forbidden — token is valid but lacks permission for this resource."
    elif status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        hint = f"{status} from the API. Try again, or check backend logs."
    else:
        hint = f"{status} from the API."
    return f"API error from {base_url}\n  {hint}"


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
        f"Generate a personal access token at {api_url.rstrip('/')}/settings, then paste it below.",
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
    try:
        client = get_client()
    except AuthError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    try:
        response = list_organizations_orgs_get.sync(client=client)
    except UnexpectedStatus as e:
        typer.secho(_format_api_error(client, e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if not isinstance(response, OrganizationListResponse):
        # Documented non-200 responses (e.g. 422 validation errors) land here.
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
