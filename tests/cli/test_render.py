"""Tests for the shared rendering helpers."""

from yertle.cli._render import fields


def test_fields_prints_nothing_for_no_rows(capsys) -> None:
    """An empty section must not emit a stray blank line."""
    fields([])
    assert capsys.readouterr().out == ""


def test_fields_aligns_values_to_the_widest_label(capsys) -> None:
    fields([("Role", "owner"), ("Invite mode", "open")])
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0].index("owner") == lines[1].index("open")
