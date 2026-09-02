"""Shared fixtures.

The SDK caches its default client in a module-level singleton
(`yertle._client._default_client`), so without a reset one test's client
leaks into the next and a mocked-credentials test can silently pass on a
client another test built. Resetting for every test is cheap and removes a
class of order-dependent flake.
"""

from collections.abc import Iterator

import pytest

from yertle import _client as _client_module


@pytest.fixture(autouse=True)
def reset_default_client() -> Iterator[None]:
    """Ensure each test starts and ends with a fresh lazy-init cache."""
    _client_module._default_client = None  # pyright: ignore[reportPrivateUsage]
    yield
    _client_module._default_client = None  # pyright: ignore[reportPrivateUsage]
