"""Tests for the yertle CLI runner."""

from __future__ import annotations

import pytest

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
    """Full noun-verb pairs, so this exercises the allowlist and not the arity check."""
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    unlisted = [
        ["orgs", "use", "abc"],  # a real command, but it writes
        ["auth", "status"],  # real and harmless, simply not granted
        ["nodes", "delete", "abc"],  # would mutate, and does not exist
        ["canvas", "render"],  # never existed
    ]
    for argv in unlisted:
        out = yertle_run.invoke({"argv": argv})
        assert out.startswith("refused"), f"should refuse {argv}"
        assert "leak" not in out


@pytest.mark.parametrize("argv", [[], ["orgs"], ["nodes"]])
def test_yertle_run_refuses_an_incomplete_command(fake_cli, argv):
    """A bare noun names no command — and must not fall through to the CLI."""
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    out = yertle_run.invoke({"argv": argv})
    assert out.startswith("refused")
    assert "leak" not in out


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


def _cli_noun_verbs() -> set[tuple[str, str]]:
    """Every (noun, verb) pair the CLI actually registers."""
    pairs: set[tuple[str, str]] = set()
    for group in cli_app.registered_groups:
        sub = group.typer_instance
        if sub is None:
            continue
        noun = group.name or sub.info.name
        if noun is None:
            continue
        for command in sub.registered_commands:
            if command.name:
                pairs.add((noun, command.name))
    return pairs


def test_allowlist_only_names_commands_the_cli_actually_has():
    """The allowlist is a hand-maintained mirror of the CLI, so it can rot.

    It already did once: copied from the Go CLI, it listed `nodes`, `tree`,
    `canvas`, `about` and `config`, none of which this CLI had — so the agent
    was told to call five commands that could only fail. The subprocess mock in
    these tests hid it, because a fake `run_cli` happily "succeeds" for a
    command that does not exist.

    Asserting against the Typer app itself cannot drift.
    """
    unknown = YERTLE_READ_COMMANDS - _cli_noun_verbs()
    assert not unknown, (
        f"allowlisted commands the CLI does not have: {sorted(unknown)}. "
        f"Registered: {sorted(_cli_noun_verbs())}"
    )


def test_allowlist_admits_no_write_commands():
    """CLAUDE.md invariant 3: the agent's tools are read-only.

    `orgs use` writes ~/.yertle/config.json. While the gate keyed on the noun
    alone, allowlisting `orgs` admitted every verb under it — including that
    one. This pins the noun-verb gate so a future write verb cannot ride in on
    an already-trusted noun.
    """
    writes = {("orgs", "use")}
    assert not (YERTLE_READ_COMMANDS & writes), (
        f"write commands in the read-only allowlist: {sorted(YERTLE_READ_COMMANDS & writes)}"
    )
    assert writes <= _cli_noun_verbs(), "test is stale — `orgs use` no longer exists"
