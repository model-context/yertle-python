"""`yertle auth` — inspect authentication state."""

import typer
from rich.console import Console

from yertle.cli._render import display_path
from yertle.shared import auth

app = typer.Typer(
    name="auth",
    help="Inspect authentication state.",
    no_args_is_help=True,
)

# Below this length a prefix+suffix reveal would expose most of the secret,
# so short values are masked entirely.
_MIN_MASKABLE_TOKEN_LEN = 16


def _mask_token(token: str) -> str:
    """Redact a token for display, keeping enough to identify which one it is.

    `yertle auth status` output is the kind of thing users paste into bug
    reports, so the full secret must never appear. Short/unexpected values are
    masked entirely rather than leaking a meaningful fraction of themselves.
    """
    if len(token) <= _MIN_MASKABLE_TOKEN_LEN:
        return "*" * len(token)
    return f"{token[:8]}…{token[-4:]}"


def _source_label(source: auth.Source, env_var: str) -> str:
    """Human-readable provenance for one resolved key.

    Lives in the CLI rather than `shared.auth` because it is presentation:
    the resolver reports *which* source won, this decides how to name it.
    """
    if source is auth.Source.ENV:
        return f"from ${env_var}"
    if source is auth.Source.CONFIG:
        return f"from {display_path(auth.CONFIG_PATH)}"
    if source is auth.Source.DEFAULT:
        return "default"
    return "not set"


@app.command("status")
def status() -> None:
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
