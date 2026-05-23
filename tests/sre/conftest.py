"""Shared test fixtures.

Tests never hit the network, never call Anthropic, and never run real CLIs.
We monkeypatch `subprocess.run` and `shutil.which` to simulate CLI behavior.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeCompleted:
    stdout: str
    stderr: str
    returncode: int


FakeFn = Callable[[list[str]], FakeCompleted]


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeFn], None]:
    """Install a fake `subprocess.run` keyed off argv.

    Usage:
        def test_x(fake_cli):
            def respond(argv):
                assert argv[0] == "yertle"
                return FakeCompleted(stdout='{"ok":true}', stderr="", returncode=0)
            fake_cli(respond)
            ...
    """

    def install(fn: FakeFn) -> None:
        def fake_run(argv: list[str], **_kwargs: Any) -> FakeCompleted:
            return fn(argv)

        # Treat every executable as installed.
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/fake")
        monkeypatch.setattr(subprocess, "run", fake_run)

    return install
