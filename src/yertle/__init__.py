"""yertle — Python SDK for the Yertle architecture-graph platform.

    >>> import yertle
    >>> for org in yertle.orgs.list():
    ...     print(org.name)

Resources live in per-feature modules (`yertle.orgs`, `yertle.nodes`, future
`yertle.branches`, …) and are re-exported here. Default-client plumbing
lives in `yertle._client`; users interact with it via the top-level
`yertle.client()` and `yertle.configure(...)` re-exports.

The wire layer (`yertle_client`) remains available as the escape hatch
for callers who want an explicit client, async variants, or untyped raw
responses.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from yertle_client.client import AuthenticatedClient

from yertle import nodes, orgs
from yertle._client import client, configure, get_client

try:
    # Read the version back from installed distribution metadata rather than
    # hardcoding it. `pyproject.toml` stays the single place the number is
    # written; previously this constant was a second copy and drifted — the
    # published 0.1.0 wheel reported 0.0.1 from `yertle version`.
    __version__ = _dist_version("yertle")
except PackageNotFoundError:  # pragma: no cover — running from an uninstalled tree
    __version__ = "0.0.0+unknown"
__all__ = [
    "AuthenticatedClient",
    "client",
    "configure",
    "get_client",
    "nodes",
    "orgs",
]
