"""Output rendering shared by every command.

One `--format` implementation and one table style. Each command branching on
the format string itself is exactly the near-copy duplication `make hygiene`
watches for, so the branch lives here and commands only describe their columns.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Generic, Protocol, TypeVar

import typer
from rich.console import Console
from rich.table import Table


class Format(StrEnum):
    """Output formats every data command supports."""

    TABLE = "table"
    JSON = "json"


# Shared so `--format`/`-f` reads and validates identically everywhere. As an
# enum rather than a bare string, Typer rejects an unknown value instead of
# silently falling through to the table branch.
FormatOption = Annotated[Format, typer.Option("--format", "-f", help="Output format.")]


class WireModel(Protocol):
    """The only shape `render` needs; every generated model satisfies it."""

    def to_dict(self) -> dict[str, Any]: ...


T = TypeVar("T", bound=WireModel)


@dataclass(frozen=True, slots=True)
class Column(Generic[T]):
    """One table column: a header, and how to get its cell out of a row.

    Generic in the row type so a command declaring
    `list[Column[OrganizationResponse]]` gets its accessors type-checked
    against the model — a renamed field fails `make check` rather than at the
    user's terminal.
    """

    header: str
    value: Callable[[T], str]
    style: str | None = None
    no_wrap: bool = False


def render(
    rows: Sequence[T],
    *,
    fmt: Format,
    columns: Sequence[Column[T]],
    title: str | None = None,
) -> None:
    """Print `rows` as a Rich table or as JSON.

    JSON output calls `.to_dict()` on each row — every `yertle_client` model
    provides it — so the machine-readable shape tracks the wire format rather
    than whichever subset of fields the table happens to show.
    """
    if fmt is Format.JSON:
        typer.echo(json.dumps([row.to_dict() for row in rows], indent=2, default=str))
        return

    table = Table(title=title)
    for column in columns:
        table.add_column(column.header, style=column.style, no_wrap=column.no_wrap)
    for row in rows:
        table.add_row(*(column.value(row) for column in columns))
    Console().print(table)


def display_path(path: Path) -> str:
    """Render a path with `$HOME` collapsed to `~` for compact output."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


__all__ = ["Column", "Format", "FormatOption", "WireModel", "display_path", "render"]
