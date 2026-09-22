"""Tests for what the help pages advertise.

`--format json` existed on every data command from the start, and was
documented in `about` and on each leaf `--help` — but not on the group page
(`yertle orgs`), which is where you land *before* you know the verb. Options
belong to verbs, so Typer has nowhere to show it there; the epilog is that
somewhere. This guards the wiring, since a new noun group would otherwise
reintroduce the gap silently.
"""

import re

import click
import typer
from typer.testing import CliRunner

from yertle.cli._render import FORMAT_EPILOG
from yertle.cli.main import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """Rendered help as flat text, safe to substring-match against.

    Two things make a raw `in result.output` check unreliable here, and CI
    caught both after it passed locally:

    - Rich highlights anything option-shaped, so with colour enabled
      `--format` renders as `ESC[1;36m-ESC[0mESC[1;36m-formatESC[0m` — the
      escape codes land *between the two dashes*. Colour is on in CI and off
      on a piped local terminal, so the substring exists locally and does not
      in CI.
    - Help text is wrapped to the terminal width, which can split the phrase
      across a newline at a width nobody tested at.

    Stripping the codes and collapsing whitespace removes both.
    """
    return " ".join(_ANSI.sub("", output).split())


def _groups() -> list[click.Group]:
    root = typer.main.get_command(app)
    assert isinstance(root, click.Group)
    ctx = click.Context(root)
    return [
        command
        for name in root.list_commands(ctx)
        if isinstance(command := root.get_command(ctx, name), click.Group)
    ]


def _takes_format(group: click.Group) -> bool:
    ctx = click.Context(group)
    return any(
        any(param.name == "fmt" for param in command.params)
        for name in group.list_commands(ctx)
        if (command := group.get_command(ctx, name)) is not None
    )


def test_groups_with_data_commands_advertise_json() -> None:
    """A noun whose verbs take `--format` must say so on its own help page."""
    silent = [group.name for group in _groups() if _takes_format(group) and not group.epilog]
    assert not silent, (
        f"These groups have --format commands but no epilog: {silent}. "
        f"Pass `epilog=FORMAT_EPILOG` to their `typer.Typer(...)`."
    )


def test_group_help_renders_the_epilog() -> None:
    """The end-to-end check: the text actually reaches the terminal."""
    result = runner.invoke(app, ["orgs"])
    assert "--format json" in _plain(result.output)


def test_epilog_names_a_real_flag() -> None:
    """Cheap guard against the advertisement outliving the flag."""
    assert "--format json" in FORMAT_EPILOG
    result = runner.invoke(app, ["orgs", "list", "--help"])
    assert "--format" in _plain(result.output)
