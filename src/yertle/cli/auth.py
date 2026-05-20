"""Credentials I/O and authenticated client construction."""

import json
import os
from pathlib import Path

from yertle_client.auth import client_from_token
from yertle_client.client import AuthenticatedClient

CONFIG_PATH = Path.home() / ".yertle" / "config.json"


def save_credentials(api_url: str, token: str) -> None:
    """Persist `{api_url, token}` to ~/.yertle/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"api_url": api_url, "token": token}))


def get_client() -> AuthenticatedClient:
    """Build an AuthenticatedClient from `$YERTLE_TOKEN` env or the config file.

    Resolution order:
        1. `$YERTLE_TOKEN` + `$YERTLE_API_URL` env vars (CI / script use)
        2. `~/.yertle/config.json` (interactive `yertle login`)

    Raises:
        RuntimeError: if neither source is set.
    """
    if (token := os.environ.get("YERTLE_TOKEN")) and (url := os.environ.get("YERTLE_API_URL")):
        return client_from_token(token=token, base_url=url)

    if not CONFIG_PATH.exists():
        raise RuntimeError(
            "Not authenticated. Run `yertle login` or set $YERTLE_TOKEN and $YERTLE_API_URL.",
        )
    cfg = json.loads(CONFIG_PATH.read_text())
    return client_from_token(token=cfg["token"], base_url=cfg["api_url"])
