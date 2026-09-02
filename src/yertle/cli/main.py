"""Entry point for the `yertle` command."""

import json as _json
from http import HTTPStatus
from importlib.metadata import Distribution, PackageNotFoundError
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer
from rich.console import Console
from rich.table import Table
from yertle_client.api.organizations import list_organizations_orgs_get
from yertle_client.client import AuthenticatedClient
from yertle_client.errors import UnexpectedStatus
from yertle_client.models import OrganizationListResponse

from yertle import __version__
from yertle.shared import auth


def _format_api_error(client: AuthenticatedClient, exc: UnexpectedStatus) -> str:
    """Build a user-facing message for an unexpected API response.

    Critically, the message includes the effective base URL so a misconfigured
    `$YERTLE_API_URL` (or stale config) becomes obvious instead of silently
    hitting the wrong backend.
    """
    base_url = getattr(client, "_base_url", "<unknown>")
    status = exc.status_code
    if status == HTTPStatus.UNAUTHORIZED and _is_edge_rejection(exc.content):
        hint = (
            "401 Unauthorized — rejected before reaching the Yertle backend.\n"
            "  This host sits behind a JWT authorizer that does not accept "
            "personal access tokens:\n"
            "  a `yrt_` token isn't a JWT, so it's refused on sight and never "
            "looked up.\n"
            "  Your token is almost certainly fine — PATs currently work only "
            "against a locally-run backend."
        )
    elif status == HTTPStatus.UNAUTHORIZED:
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


# Below this length a prefix+suffix reveal would expose most of the secret,
# so short values are masked entirely.
_MIN_MASKABLE_TOKEN_LEN = 16


def _web_url_for(api_url: str) -> str | None:
    """Best-effort web-app URL for an API base URL, or `None` if unsure.

    Personal access tokens are minted in the web app, not by the API, so the
    two hosts differ. Deriving the wrong one sends a first-time user to a 401
    page during their very first interaction with the tool — which is what
    this command did until now, by appending `/settings` to the API URL.

    Returns `None` rather than guessing when the mapping isn't obvious, so the
    prompt can stay vague instead of confidently wrong.
    """
    parsed = urlparse(api_url)
    host, scheme = parsed.hostname, parsed.scheme or "https"
    if not host:
        return None
    if host in {"localhost", "127.0.0.1"}:
        # Local convention: backend on :8000, web app on :3000.
        return f"{scheme}://{host}:3000"
    if host.startswith("api."):
        return f"{scheme}://{host.removeprefix('api.')}"
    return None


def _is_edge_rejection(content: bytes) -> bool:
    """True if a 401 body came from the API Gateway authorizer, not the app.

    API Gateway's JWT authorizer rejects a request before Lambda runs and
    returns `{"message": "Unauthorized"}`. The Yertle backend, reached
    directly, returns FastAPI's `{"detail": "..."}`. The difference matters:
    an edge rejection means the token was never looked up at all, so
    "revoked or expired" is the wrong thing to tell the user.
    """
    try:
        body = _json.loads(content)
    except (ValueError, TypeError):
        return False
    return isinstance(body, dict) and "message" in body and "detail" not in body


def _mask_token(token: str) -> str:
    """Redact a token for display, keeping enough to identify which one it is.

    `yertle auth status` output is the kind of thing users paste into bug
    reports, so the full secret must never appear. Short/unexpected values are
    masked entirely rather than leaking a meaningful fraction of themselves.
    """
    if len(token) <= _MIN_MASKABLE_TOKEN_LEN:
        return "*" * len(token)
    return f"{token[:8]}…{token[-4:]}"


def _source_checkout() -> Path | None:
    """Return the working-tree path if this is an editable install, else `None`.

    Homebrew ships the *same* CLI in its own venv, so a bare `yertle` can be
    the last published release while `uv run yertle` is your working tree —
    identical commands, different code, no visible difference. PEP 610 records
    how a distribution was installed in `direct_url.json`; an editable install
    carries `dir_info.editable`, a wheel from PyPI carries no such file.
    """
    try:
        raw = Distribution.from_name("yertle").read_text("direct_url.json")
    except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
        return None
    if not raw:
        return None
    direct_url = _json.loads(raw)
    if not direct_url.get("dir_info", {}).get("editable"):
        return None
    url = direct_url.get("url", "")
    if not url.startswith("file://"):  # pragma: no cover — non-local editable
        return None
    return Path(unquote(urlparse(url).path))


def _display_path(path: Path) -> str:
    """Render a path with `$HOME` collapsed to `~` for compact output."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _source_label(source: auth.Source, env_var: str) -> str:
    """Human-readable provenance for one resolved key.

    Lives in the CLI rather than `shared.auth` because it is presentation:
    the resolver reports *which* source won, this decides how to name it.
    """
    if source is auth.Source.ENV:
        return f"from ${env_var}"
    if source is auth.Source.CONFIG:
        return f"from {_display_path(auth.CONFIG_PATH)}"
    if source is auth.Source.DEFAULT:
        return "default"
    return "not set"


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
    """Print the yertle version, and flag when running from a source checkout.

    The suffix is the difference between "I'm testing my changes" and "I'm
    running the release I installed months ago" — worth stating outright,
    since the two are otherwise indistinguishable at the prompt.
    """
    checkout = _source_checkout()
    if checkout is None:
        typer.echo(__version__)
    else:
        typer.echo(f"{__version__} (editable: {_display_path(checkout)})")


@app.command()
def login(
    api_url: str = typer.Option(
        ...,
        "--api-url",
        help="Yertle API base URL (e.g. https://api.yertle.com).",
    ),
    web_url: str | None = typer.Option(
        None,
        "--web-url",
        help="Web app base URL, if it can't be derived from --api-url.",
    ),
) -> None:
    """Save API credentials to ~/.yertle/config.json."""
    settings_url = web_url or _web_url_for(api_url)
    if settings_url:
        typer.echo(
            f"Generate a personal access token at {settings_url.rstrip('/')}/settings, "
            "then paste it below.",
        )
    else:
        typer.echo(
            "Generate a personal access token from the Settings page of your "
            "Yertle web app, then paste it below.",
        )
    token = typer.prompt("Token", hide_input=True).strip()
    if not token:
        # An empty token would persist a config that looks populated but
        # resolves as unauthenticated, since `resolve()` treats "" as absent.
        typer.secho("No token entered — nothing saved.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    auth.save_credentials(api_url=api_url, token=token)
    typer.echo(f"✓ Saved credentials to {auth.CONFIG_PATH}")


orgs_app = typer.Typer(
    name="orgs",
    help="Work with organizations.",
    no_args_is_help=True,
)
app.add_typer(orgs_app)


@orgs_app.command("list")
def orgs_list(
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table | json",
    ),
) -> None:
    """List the organizations you belong to."""
    try:
        client = auth.get_client()
    except auth.AuthError as e:
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


auth_app = typer.Typer(
    name="auth",
    help="Inspect authentication state.",
    no_args_is_help=True,
)
app.add_typer(auth_app)


@auth_app.command("status")
def auth_status() -> None:
    """Show which credentials the CLI would use, and where they came from.

    Answers "which backend am I actually pointed at right now?" without making
    a request. Because token and API URL resolve independently, they can come
    from different sources — a config-file token paired with an env-var URL is
    exactly how a token issued by one backend ends up aimed at another, which
    otherwise only surfaces as an opaque 401.

    Exits non-zero when no token resolves, so it is usable as a scripted
    precondition check.
    """
    resolved = auth.resolve()
    console = Console()

    # Plain (unmarked) placeholder: Rich markup counts toward the f-string
    # padding width below but not the rendered width, which would misalign
    # the column.
    token_display = _mask_token(resolved.token) if resolved.token is not None else "—"
    rows = [
        ("API URL", resolved.api_url, _source_label(resolved.api_url_source, auth.API_URL_ENV_VAR)),
        ("Token", token_display, _source_label(resolved.token_source, auth.TOKEN_ENV_VAR)),
    ]
    # Size the value column to its contents rather than a fixed width: a long
    # API URL would otherwise shove the source column out of alignment.
    value_width = max(len(value) for _, value, _ in rows)
    for label, value, source in rows:
        # soft_wrap: values are URLs and filesystem paths, which Rich would
        # otherwise hard-break mid-token to fit the console (splitting
        # `config.json` across lines on a narrow terminal). Let the terminal
        # wrap instead, so the value stays greppable and copy-pasteable.
        console.print(
            f"  [bold]{label:<8}[/bold] {value:<{value_width}}  [dim]({source})[/dim]",
            soft_wrap=True,
        )

    if resolved.token is None:
        console.print(
            f"\n[red]Not authenticated.[/red] Run `yertle login` or set ${auth.TOKEN_ENV_VAR}.",
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
