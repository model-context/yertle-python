"""Tests for the yertle CLI runner."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.cli.main import app as cli_app
from yertle.sre.tools.yertle import YERTLE_READ_COMMANDS, yertle_run


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


def test_allowlist_only_names_commands_the_cli_actually_has():
    """The allowlist is a hand-maintained mirror of the CLI, so it can rot.

    It already did once: it was copied from the Go CLI and listed `nodes`,
    `tree`, `canvas`, `about` and `config`, none of which the Python CLI had —
    so the agent was told to call five commands that could only fail. The
    subprocess mock in these tests hid it, because a fake `run_cli` happily
    "succeeds" for a command that does not exist.

    This asserts against the Typer app itself, which cannot drift.
    """
    registered = {command.name for command in cli_app.registered_commands}
    registered |= {
        group.name or (group.typer_instance.info.name if group.typer_instance else None)
        for group in cli_app.registered_groups
    }

    unknown = YERTLE_READ_COMMANDS - registered
    assert not unknown, (
        f"allowlisted commands the CLI does not have: {sorted(unknown)}. "
        f"Registered: {sorted(n for n in registered if n)}"
    )
