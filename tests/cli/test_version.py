"""Tests for `yertle version` and source-checkout detection."""

import json
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

import yertle
from yertle.cli.commands.version import _source_checkout
from yertle.cli.main import app

_DISTRIBUTION = "yertle.cli.commands.version.Distribution.from_name"
_SOURCE_CHECKOUT = "yertle.cli.commands.version._source_checkout"

runner = CliRunner()


def _fake_distribution(direct_url: object | None) -> Mock:
    """A `Distribution` whose `direct_url.json` holds `direct_url` (None = absent)."""
    dist = Mock()
    dist.read_text.return_value = None if direct_url is None else json.dumps(direct_url)
    return dist


def test_version_matches_distribution_metadata() -> None:
    """Guards the drift that shipped 0.1.0 wheels reporting 0.0.1."""
    assert yertle.__version__ == dist_version("yertle")


def test_source_checkout_detects_editable_install() -> None:
    payload = {"url": "file:///home/dev/yertle-python", "dir_info": {"editable": True}}
    with patch(_DISTRIBUTION, return_value=_fake_distribution(payload)):
        assert _source_checkout() == Path("/home/dev/yertle-python")


def test_source_checkout_returns_none_for_a_wheel() -> None:
    """A PyPI wheel has no direct_url.json at all."""
    with patch(_DISTRIBUTION, return_value=_fake_distribution(None)):
        assert _source_checkout() is None


def test_source_checkout_returns_none_for_non_editable_local_install() -> None:
    """`pip install .` records direct_url.json but without `dir_info.editable`."""
    payload = {"url": "file:///home/dev/yertle-python", "dir_info": {}}
    with patch(_DISTRIBUTION, return_value=_fake_distribution(payload)):
        assert _source_checkout() is None


def test_source_checkout_decodes_percent_escapes_in_path() -> None:
    """Editable installs from paths with spaces arrive percent-encoded."""
    payload = {"url": "file:///home/dev/my%20projects/yertle", "dir_info": {"editable": True}}
    with patch(_DISTRIBUTION, return_value=_fake_distribution(payload)):
        assert _source_checkout() == Path("/home/dev/my projects/yertle")


def test_source_checkout_survives_missing_distribution() -> None:
    with patch(_DISTRIBUTION, side_effect=PackageNotFoundError):
        assert _source_checkout() is None


def test_version_flags_a_source_checkout() -> None:
    with patch(_SOURCE_CHECKOUT, return_value=Path("/home/dev/yertle-python")):
        result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "editable" in result.output
    assert "/home/dev/yertle-python" in result.output


def test_version_is_bare_when_installed_normally() -> None:
    with patch(_SOURCE_CHECKOUT, return_value=None):
        result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == yertle.__version__


def test_version_collapses_home_to_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = Path.home() / "src" / "yertle-python"
    with patch(_SOURCE_CHECKOUT, return_value=checkout):
        result = runner.invoke(app, ["version"])

    assert "~/src/yertle-python" in result.output
    assert str(Path.home()) not in result.output
