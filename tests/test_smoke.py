"""Smoke test: the package imports cleanly and exposes a version."""

import yertle


def test_version_is_set() -> None:
    assert yertle.__version__
