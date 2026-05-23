"""Credentials I/O and authenticated client construction."""

import json
import os
from pathlib import Path

from yertle_client.client import AuthenticatedClient

CONFIG_PATH = Path.home() / ".yertle" / "config.json"
DEFAULT_API_URL = "https://api.yertle.com"


class AuthError(Exception):
    """Raised when no credentials can be resolved.

    The CLI catches this in `cli/main.py` and renders a clean message
    (not a traceback). The string `str(error)` IS the user-facing message.
    """


def save_credentials(api_url: str, token: str) -> None:
    """Persist `{api_url, token}` to ~/.yertle/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"api_url": api_url, "token": token}))


def get_client() -> AuthenticatedClient:
    """Build an AuthenticatedClient from env vars and/or the config file.

    Resolution is **per-key** so the two settings can come from different
    sources (matches `gh`, `aws-cli`, etc.):

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

    # `raise_on_unexpected_status=True`: the generated client returns `None`
    # on any non-documented status (e.g. 401). We'd rather surface the real
    # status to the user than silently get `None` back — see the CLI's error
    # handler which includes the base_url in its message.
    return AuthenticatedClient(
        base_url=api_url,
        token=token,
        raise_on_unexpected_status=True,
    )
