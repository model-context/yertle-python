"""Default-client plumbing for the SDK facade.

Module-private (leading underscore) because the public surface is just
`yertle.client()` and `yertle.configure(...)`, re-exported from
`yertle/__init__.py`. Same convention `stripe/_api_requestor.py` uses.
"""

from __future__ import annotations

from yertle_client.client import AuthenticatedClient, Client

from yertle.shared.auth import DEFAULT_API_URL, get_anonymous_client, get_client

__all__ = ["anonymous_client", "client", "configure", "get_client"]


_default_client: AuthenticatedClient | None = None
_anonymous_client: Client | None = None


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


def anonymous_client() -> Client:
    """Return the cached token-less `Client` that `yertle.public` reads through.

    Kept separate from `client()` rather than being a mode of it: building the
    authenticated client raises when no token resolves, and reading a public
    org must work in exactly that case.
    """
    global _anonymous_client  # noqa: PLW0603
    if _anonymous_client is None:
        _anonymous_client = get_anonymous_client()
    return _anonymous_client


def configure(*, token: str, api_url: str | None = None) -> None:
    """Set the default client explicitly, bypassing env/config resolution.

    Useful for scripts that don't want to depend on `yertle login` or the
    `$YERTLE_TOKEN` env var. Subsequent SDK calls (`yertle.orgs.list()` etc.)
    use the credentials passed here, and `yertle.public` reads go to the same
    `api_url`.

        >>> import yertle
        >>> yertle.configure(token="yrt_...", api_url="http://localhost:8000")
        >>> yertle.orgs.list()
    """
    global _default_client, _anonymous_client  # noqa: PLW0603
    base_url = api_url or DEFAULT_API_URL
    _default_client = AuthenticatedClient(
        base_url=base_url,
        token=token,
        raise_on_unexpected_status=True,
    )
    _anonymous_client = Client(base_url=base_url, raise_on_unexpected_status=True)
