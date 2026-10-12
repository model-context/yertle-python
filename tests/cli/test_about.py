"""Tests for `yertle about`, and for the README's command list.

Both are hand-written prose describing a surface that keeps moving, which is
exactly the shape of thing that goes quietly stale. The Go CLI's own `about`
text still advertised `yertle canvas`, a command that never existed; the
README went a full release cycle without `nodes create`, `nodes apply` or any
of `branches`, which is what prompted the second guard here.

Deriving either from the app would lose the prose. Asserting the prose covers
the app keeps both.
"""

import re
from pathlib import Path

from typer.testing import CliRunner

from yertle.cli.commands.about import ABOUT
from yertle.cli.main import app

runner = CliRunner()


def _registered_commands() -> set[str]:
    """Every invocable command, as the string a user would type after `yertle`."""
    names = {command.name for command in app.registered_commands if command.name}
    for group in app.registered_groups:
        sub = group.typer_instance
        if sub is None:
            continue
        noun = group.name or sub.info.name
        if noun is None:
            continue
        names |= {f"{noun} {c.name}" for c in sub.registered_commands if c.name}
    return names


def test_about_documents_every_command() -> None:
    """Adding a command without documenting it should fail here, not in the wild."""
    undocumented = {name for name in _registered_commands() if f"yertle {name}" not in ABOUT}
    assert not undocumented, (
        f"`yertle about` does not mention: {sorted(undocumented)}. "
        f"Add them to ABOUT in cli/commands/about.py."
    )


def test_about_promises_nothing_the_cli_lacks() -> None:
    """The inverse: no `yertle <noun> <verb>` in the prose that does not exist.

    The Go CLI's about text advertised `yertle canvas`, which was never a
    command. Claiming a command is worse than omitting one.

    Only lowercase word pairs are checked, so `yertle login --api-url ...` and
    `yertle <command> --help` are skipped — neither names a noun-verb pair.
    """
    claimed = set(re.findall(r"yertle ([a-z]+ [a-z]+)", ABOUT))
    phantom = claimed - _registered_commands()
    assert not phantom, f"`about` claims commands that do not exist: {sorted(phantom)}"


def test_about_runs_and_exits_zero() -> None:
    result = runner.invoke(app, ["about"])
    assert result.exit_code == 0, result.output
    assert "hierarchical context layer" in result.output


def test_about_does_not_leak_rich_markup() -> None:
    """Markup tags must render, not print literally."""
    result = runner.invoke(app, ["about"])
    assert "[bold]" not in result.output
    assert "[/bold]" not in result.output


README = Path(__file__).parent.parent.parent / "README.md"


def test_readme_lists_every_command() -> None:
    """The README enumerates the commands, so the list has to be complete.

    It went stale silently between 0.3.1 and 0.4.0 — three new commands and a
    whole noun group missing — because nothing checked. A reader installing
    from PyPI sees this list before anything else.
    """
    text = README.read_text()
    undocumented = sorted(name for name in _registered_commands() if f"`{name}`" not in text)
    assert not undocumented, (
        f"README.md does not mention: {undocumented}. "
        f"Add them to the command table under the install instructions."
    )
