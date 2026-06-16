"""Credential resolution and authenticated client construction.

Single source of truth for:

- The token + API URL precedence chain (`$YERTLE_TOKEN` env > `~/.yertle/config.json`
  > raise `AuthError`; URL falls back to `$YERTLE_API_URL` > config > prod default).
- Constructing a `yertle_client.AuthenticatedClient` configured the way the CLI,
  MCP server, and SDK all expect.

Consumers:
- `yertle.cli.main` — uses `get_client`, `save_credentials`, `AuthError`,
  `CONFIG_PATH` during `yertle login` and `yertle orgs`.
- `yertle.mcp.server` — uses `resolve_credentials` (pure tuple-of-strings, no
  `AuthenticatedClient` needed since FastMCP wires its own `httpx.AsyncClient`).
- `yertle._client` — uses `get_client` and `DEFAULT_API_URL` for the SDK's lazy
  default-client singleton and `configure()`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from yertle_client.client import AuthenticatedClient

CONFIG_PATH = Path.home() / ".yertle" / "config.json"
DEFAULT_API_URL = "https://api.yertle.com"


class AuthError(Exception):
    """Raised when no credentials can be resolved.

    The CLI catches this in `cli/main.py` and the MCP server's `main()` catches
    it to render a clean message (not a traceback). The string `str(error)` IS
    the user-facing message.
    """


def save_credentials(api_url: str, token: str) -> None:
    """Persist `{api_url, token}` to ~/.yertle/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"api_url": api_url, "token": token}))


def resolve_credentials() -> tuple[str, str]:
    """Return `(token, api_url)` using per-key precedence.

    Resolution matches `gh` / `aws-cli` — the two settings can come from
    different sources:

    - **Token**: `$YERTLE_TOKEN` env > config file > raise `AuthError`
    - **API URL**: `$YERTLE_API_URL` env > config file > `DEFAULT_API_URL`

    So `YERTLE_TOKEN=yrt_...` alone is sufficient in production — the URL
    defaults to `https://api.yertle.com`. Local dev still needs to point at
    `localhost:8000` via env var or `yertle login --api-url`.
    """
    cfg: dict[str, str] = {}
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())

    token = os.environ.get("YERTLE_TOKEN") or cfg.get("token")
    if not token:
        raise AuthError(
            "Not authenticated. Run `yertle login` or set $YERTLE_TOKEN.",
        )

    api_url = os.environ.get("YERTLE_API_URL") or cfg.get("api_url") or DEFAULT_API_URL
    return token, api_url


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
