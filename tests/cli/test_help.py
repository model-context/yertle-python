"""Tests for what the help pages advertise.

Two ways help text has been wrong here, both caught after the code was
"done":

- `--format json` existed on every data command and was documented in `about`
  and on each leaf `--help`, but not on the group page (`yertle orgs`) — which
  is where you land *before* you know the verb. Options belong to verbs, so
  Typer has nowhere to show it there; the epilog is that somewhere.
- Three commands that refuse `--org all` advertised it as a valid value and
  as their default, because they shared the cross-org option.

Both are the same failure: help that describes a CLI other than this one.
"""

import click
import typer
from typer.testing import CliRunner

from tests._output import plain
from yertle.cli._render import FORMAT_EPILOG
from yertle.cli.main import app

runner = CliRunner()


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


def _help(*argv: str) -> str:
    return plain(runner.invoke(app, [*argv, "--help"]).output)


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
    assert "--format json" in plain(result.output)


def test_epilog_names_a_real_flag() -> None:
    """Cheap guard against the advertisement outliving the flag."""
    assert "--format json" in FORMAT_EPILOG
    assert "--format" in _help("orgs", "list")


def test_single_org_commands_do_not_offer_all() -> None:
    """A command that refuses 'all' must not advertise it.

    `nodes show`, `nodes search` and `nodes create` each act on exactly one
    organization and exit 1 when the chain resolves to 'all'. They shared the
    cross-org `--org` help, which told the reader 'all' was both valid and the
    default — a claim none of them honours.
    """
    for verb in ("show", "search", "create"):
        text = _help("nodes", verb)
        assert "'all' is not valid" in text, f"nodes {verb} still offers 'all'"
        assert "then 'all'" not in text, f"nodes {verb} still defaults to 'all'"


def test_cross_org_commands_still_offer_all() -> None:
    """The inverse: `list` and `tree` genuinely do span organizations."""
    for verb in ("list", "tree"):
        assert "or 'all'" in _help("nodes", verb), f"nodes {verb} lost 'all'"
