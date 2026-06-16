"""yertle — Python SDK for the Yertle architecture-graph platform.

    >>> import yertle
    >>> for org in yertle.orgs.list():
    ...     print(org.name)

Resources live in per-feature modules (`yertle.orgs`, future `yertle.nodes`,
`yertle.branches`, …) and are re-exported here. Default-client plumbing
lives in `yertle._client`; users interact with it via the top-level
`yertle.client()` and `yertle.configure(...)` re-exports.

The wire layer (`yertle_client`) remains available as the escape hatch
for callers who want an explicit client, async variants, or untyped raw
responses.
"""

from yertle_client.client import AuthenticatedClient

from yertle import orgs
from yertle._client import client, configure, get_client

__version__ = "0.0.1"
__all__ = [
    "AuthenticatedClient",
    "client",
    "configure",
    "get_client",
    "orgs",
]
