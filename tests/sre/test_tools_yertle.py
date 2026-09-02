"""Tests for the yertle CLI runner."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.sre.tools.yertle import yertle_run


def test_yertle_run_allows_listed_commands(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="{}", stderr="", returncode=0)

    fake_cli(respond)
    yertle_run.invoke({"argv": ["orgs", "list"]})
    assert captured[0] == ["yertle", "orgs", "list", "--format", "json"]


def test_yertle_run_appends_format_json_by_default(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="[]", stderr="", returncode=0)

    fake_cli(respond)
    yertle_run.invoke({"argv": ["orgs", "list"]})
    assert captured[0] == ["yertle", "orgs", "list", "--format", "json"]


def test_yertle_run_respects_existing_format_flag(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="title\n", stderr="", returncode=0)

    fake_cli(respond)
    yertle_run.invoke({"argv": ["orgs", "list", "--format", "table"]})
    assert captured[0].count("--format") == 1
    assert "json" not in captured[0]


def test_yertle_run_allows_the_nodes_group(fake_cli):
    """Landing a CLI command means widening the agent's allowlist too."""
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="[]", stderr="", returncode=0)

    fake_cli(respond)
    yertle_run.invoke({"argv": ["nodes", "list"]})
    assert captured[0] == ["yertle", "nodes", "list", "--format", "json"]


def test_yertle_run_refuses_unlisted(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    for cmd in ("login", "auth", "version", "tree", "canvas"):
        out = yertle_run.invoke({"argv": [cmd]})
        assert out.startswith("refused"), f"should refuse {cmd}"
        assert "leak" not in out


def test_yertle_run_refuses_empty(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    out = yertle_run.invoke({"argv": []})
    assert out.startswith("refused")


def test_yertle_run_translates_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout="",
            stderr="not found: node abc",
            returncode=1,
        ),
    )
    out = yertle_run.invoke({"argv": ["orgs", "list"]})
    assert out.startswith("yertle CLI failed:")
    assert "not found" in out
