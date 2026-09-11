"""Shared fixtures.

Both fixtures here exist to stop one test's ambient state leaking into the
next — or, worse, the developer's own machine leaking into the suite.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from yertle import _client as _client_module
from yertle.shared import auth


@pytest.fixture(autouse=True)
def reset_default_client() -> Iterator[None]:
    """Ensure each test starts and ends with a fresh lazy-init cache.

    The SDK caches its default client in a module-level singleton
    (`yertle._client._default_client`), so without a reset one test's client
    leaks into the next and a mocked-credentials test can silently pass on a
    client another test built.
    """
    _client_module._default_client = None  # pyright: ignore[reportPrivateUsage]
    yield
    _client_module._default_client = None  # pyright: ignore[reportPrivateUsage]


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point config and credential env vars somewhere the test owns.

    Without this the suite reads `~/.yertle/config.json`, so results depend on
    whether the developer happens to have run `yertle login` or `yertle orgs
    use`. That is not hypothetical: after `orgs use` landed, three tree tests
    began failing locally and passing in CI, purely because CI has no config
    file and a laptop does.

    Tests that need a specific value still set it — `monkeypatch` applies in
    order, so a later `setenv`/`setattr` in a test overrides this.
    """
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "isolated-config.json")
    for var in (auth.TOKEN_ENV_VAR, auth.API_URL_ENV_VAR, "YERTLE_ORG"):
        monkeypatch.delenv(var, raising=False)
    # Guard against a future env var being added to auth.py without being
    # cleared here — a leaked credential var is how this class of flake starts.
    assert not [k for k in os.environ if k.startswith("YERTLE_")], (
        "a YERTLE_* env var leaked into the test environment"
    )
