"""A stand-in for the backend's `/public` routes, serving captured responses.

The fixtures under `tests/fixtures/public/` were captured from a running
backend — an org created for the purpose, marked public, and read with no
token — then scrubbed of real ids and names. They are not written from memory.

Serving them through an `httpx.MockTransport`, rather than patching the
generated `.sync` functions, keeps the real bindings in the loop: the URL each
one builds and the parsing of each body are exercised, not assumed. And every
request is recorded, so a test can check that no token was sent.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from yertle_client.client import Client

from yertle import _client as _client_module

FIXTURES = Path(__file__).parent / "fixtures" / "public"

#: Ids as they appear in the scrubbed fixtures.
ORG = "00000000-0000-4000-8000-000000000002"
ROOT = "00000000-0000-4000-8000-000000000001"
PAYMENTS = "00000000-0000-4000-8000-000000000003"
LEDGER = "00000000-0000-4000-8000-000000000004"
CHECKOUT = "00000000-0000-4000-8000-000000000005"
BASE_URL = "https://api.test"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@dataclass
class PublicAPI:
    """Routes from path to `(status, body)`, plus every request received."""

    routes: dict[str, tuple[int, object]] = field(default_factory=dict[str, tuple[int, object]])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def serve(self, path: str, body: object, status: int = 200) -> None:
        self.routes[path] = (status, body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        # A page of a listing can be served on its own, keyed by its offset.
        paged = f"{path}?offset={request.url.params.get('offset')}"
        if paged in self.routes:
            path = paged
        # Unrouted paths 404 exactly as the backend does for an unknown org.
        status, body = self.routes.get(path, (404, fixture("not_found_org.json")))
        return httpx.Response(status, json=body)


def install() -> PublicAPI:
    """Point `yertle.public` at a fresh `PublicAPI` and return it."""
    api = PublicAPI()
    _client_module._anonymous_client = Client(  # pyright: ignore[reportPrivateUsage]
        base_url=BASE_URL,
        raise_on_unexpected_status=True,
        httpx_args={"transport": httpx.MockTransport(api.handle)},
    )
    return api
