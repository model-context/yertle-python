"""Credential resolution and authenticated client construction.

Single source of truth for:

- The token + API URL precedence chain (`$YERTLE_TOKEN` env > `~/.yertle/config.json`
  > raise `AuthError`; URL falls back to `$YERTLE_API_URL` > config > prod default).
- Constructing a `yertle_client.AuthenticatedClient` configured the way the CLI,
  MCP server, and SDK all expect.

Consumers:
- `yertle.cli.main` — uses `get_client`, `save_credentials`, `AuthError`,
  `CONFIG_PATH` during `yertle login` and `yertle orgs`, and `resolve` for
  `yertle auth status`.
- `yertle.mcp.server` — uses `resolve_credentials` (pure tuple-of-strings, no
  `AuthenticatedClient` needed since FastMCP wires its own `httpx.AsyncClient`).
- `yertle._client` — uses `get_client` and `DEFAULT_API_URL` for the SDK's lazy
  default-client singleton and `configure()`.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from yertle_client.client import AuthenticatedClient

CONFIG_PATH = Path.home() / ".yertle" / "config.json"
DEFAULT_API_URL = "https://api.yertle.com"

TOKEN_ENV_VAR = "YERTLE_TOKEN"
API_URL_ENV_VAR = "YERTLE_API_URL"

# The config holds a bearer token, so it is owner-only — matching `gh`'s
# hosts.yml and `~/.aws/credentials`. Set explicitly rather than inherited
# from the caller's umask: under the common default of 022 the token would
# otherwise land world-readable.
_CONFIG_MODE = 0o600
_CONFIG_DIR_MODE = 0o700


class AuthError(Exception):
    """Raised when no credentials can be resolved.

    The CLI catches this in `cli/main.py` and the MCP server's `main()` catches
    it to render a clean message (not a traceback). The string `str(error)` IS
    the user-facing message.
    """


class Source(StrEnum):
    """Where a resolved credential value came from.

    Reported by `yertle auth status` so a user can see which of the two
    possible sources actually won for each key. Rendering (the `$YERTLE_TOKEN`
    / `~/.yertle/config.json` labels) belongs to the CLI, not here.
    """

    ENV = "env"
    CONFIG = "config"
    DEFAULT = "default"
    MISSING = "missing"


@dataclass(frozen=True)
class ResolvedCredentials:
    """Effective credentials plus the provenance of each key.

    `token` is `None` when no token could be resolved — `resolve()` reports
    that state rather than raising so `yertle auth status` can render it.
    Callers that need a usable token go through `resolve_credentials()`.
    """

    token: str | None
    api_url: str
    token_source: Source
    api_url_source: Source


def _read_config() -> dict[str, str]:
    """Return the parsed config file, or `{}` if it does not exist.

    A corrupt file raises `AuthError` rather than a bare `JSONDecodeError`, so
    every failure in this module reaches the user as a sentence instead of a
    traceback — and names the file they need to fix.
    """
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        raise AuthError(
            f"Config at {CONFIG_PATH} is not valid JSON ({e}). "
            f"Fix or delete it, then run `yertle login`.",
        ) from e


def save_credentials(api_url: str, token: str) -> None:
    """Persist `api_url` and `token` to ~/.yertle/config.json.

    Merges into any existing config rather than replacing it, so keys this
    version does not know about survive a re-login.

    Writes via a temp file in the same directory plus `os.replace`, which is
    atomic: an interrupted or failed write cannot truncate a working config,
    and the token is never briefly visible at a wider mode. `mkstemp` creates
    the file 0600 regardless of umask, and `os.replace` preserves that.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # `exist_ok=True` won't tighten a directory an earlier version created
    # under a loose umask, so set the mode unconditionally.
    CONFIG_PATH.parent.chmod(_CONFIG_DIR_MODE)

    config = _read_config()
    config.update({"api_url": api_url, "token": token})

    fd, tmp_name = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix=".config-", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, _CONFIG_MODE)  # explicit: mkstemp's 0600 is not contractual
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, CONFIG_PATH)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def resolve() -> ResolvedCredentials:
    """Resolve credentials with provenance, without raising on a missing token.

    Precedence is applied **per key**, matching `gh` / `aws-cli` — the two
    settings can come from different sources:

    - **Token**: `$YERTLE_TOKEN` env > config file > `None` (`Source.MISSING`)
    - **API URL**: `$YERTLE_API_URL` env > config file > `DEFAULT_API_URL`

    Because the keys resolve independently, a config-file token can pair with
    an env-var URL. That combination is legitimate (and the reason `yertle auth
    status` exists) but is also how a token issued by one backend ends up
    pointed at another, which surfaces as an opaque 401.
    """
    cfg = _read_config()

    if token := os.environ.get(TOKEN_ENV_VAR):
        token_source = Source.ENV
    elif token := cfg.get("token"):
        token_source = Source.CONFIG
    else:
        token, token_source = None, Source.MISSING

    if api_url := os.environ.get(API_URL_ENV_VAR):
        api_url_source = Source.ENV
    elif api_url := cfg.get("api_url"):
        api_url_source = Source.CONFIG
    else:
        api_url, api_url_source = DEFAULT_API_URL, Source.DEFAULT

    return ResolvedCredentials(
        token=token,
        api_url=api_url,
        token_source=token_source,
        api_url_source=api_url_source,
    )


def resolve_credentials() -> tuple[str, str]:
    """Return `(token, api_url)`, raising `AuthError` if no token is available.

    Thin wrapper over `resolve()` so the precedence logic lives in exactly one
    place. `YERTLE_TOKEN=yrt_...` alone is sufficient in production — the URL
    defaults to `https://api.yertle.com`. Local dev still needs to point at
    `localhost:8000` via env var or `yertle login --api-url`.
    """
    resolved = resolve()
    if resolved.token is None:
        raise AuthError(
            f"Not authenticated. Run `yertle login` or set ${TOKEN_ENV_VAR}.",
        )
    return resolved.token, resolved.api_url


def get_client() -> AuthenticatedClient:
    """Resolve credentials and return a configured `AuthenticatedClient`.

    `raise_on_unexpected_status=True` so non-documented statuses (e.g. 401)
    surface as exceptions to the caller — see the CLI's error handler in
    `cli/main.py` which catches `UnexpectedStatus` and renders a URL-aware
    message.
    """
    token, api_url = resolve_credentials()
    return AuthenticatedClient(
        base_url=api_url,
        token=token,
        raise_on_unexpected_status=True,
    )
