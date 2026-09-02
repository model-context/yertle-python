"""`yertle login`."""

from urllib.parse import urlparse

import typer

from yertle.shared import auth


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
