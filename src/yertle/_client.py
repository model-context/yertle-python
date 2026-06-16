"""Default-client plumbing for the SDK facade.

Module-private (leading underscore) because the public surface is just
`yertle.client()` and `yertle.configure(...)`, re-exported from
`yertle/__init__.py`. Same convention `stripe/_api_requestor.py` uses.
"""

from __future__ import annotations

from yertle_client.client import AuthenticatedClient

# TODO(consolidation): when shared/auth.py lands (CLI + MCP + SDK is now
# genuinely three consumers), have all three import resolve_credentials
# from there instead of cli.auth. Today this is the only thing tying
# the SDK to the CLI subpackage.
from yertle.cli.auth import DEFAULT_API_URL, get_client

__all__ = ["client", "configure", "get_client"]


_default_client: AuthenticatedClient | None = None


def client() -> AuthenticatedClient:
    """Return the cached default `AuthenticatedClient`, building it on first call.

    Resolution on first call: `$YERTLE_TOKEN` env > `~/.yertle/config.json` >
    raise `AuthError`. URL falls back to `$YERTLE_API_URL` > config > prod.
    Override either by calling `configure(...)` before the first SDK call.
    """
    global _default_client  # noqa: PLW0603 — module-level lazy singleton is intentional
    if _default_client is None:
        _default_client = get_client()
    return _default_client


def configure(*, token: str, api_url: str | None = None) -> None:
    """Set the default client explicitly, bypassing env/config resolution.

    Useful for scripts that don't want to depend on `yertle login` or the
    `$YERTLE_TOKEN` env var. Subsequent SDK calls (`yertle.orgs.list()` etc.)
    use the credentials passed here.

        >>> import yertle
        >>> yertle.configure(token="yrt_...", api_url="http://localhost:8000")
        >>> yertle.orgs.list()
    """
    global _default_client  # noqa: PLW0603
    _default_client = AuthenticatedClient(
        base_url=api_url or DEFAULT_API_URL,
        token=token,
        raise_on_unexpected_status=True,
    )
