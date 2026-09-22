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
from typing import Annotated, Any, Generic, Literal, Protocol, TypeVar, runtime_checkable

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

# Group help pages list verbs but not their options, so `yertle orgs` — the
# page you land on before you know the verb — showed no sign that JSON
# output existed. Lives beside `FormatOption` so the advertisement and the
# flag cannot drift apart.
FORMAT_EPILOG = "Every data command takes --format json. Run `yertle about` for an overview."


@runtime_checkable
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
    # Counts read better right-aligned; Rich defaults every column to left.
    justify: Literal["left", "right", "center"] = "left"


def dump_json(data: WireModel | Sequence[WireModel]) -> None:
    """Print one model, or a sequence of them, as JSON.

    Split out from `render` because not every command's display half is a
    table — `nodes tree` draws a tree, `nodes show` draws sections — but every
    command's machine-readable half is the same. Shared here so `--format
    json` cannot drift between commands.

    A single model dumps as an object rather than a one-element array, so
    `yertle nodes show <id> --format json | jq .node.title` reads the way a
    caller expects.
    """
    payload = data.to_dict() if isinstance(data, WireModel) else [row.to_dict() for row in data]
    typer.echo(json.dumps(payload, indent=2, default=str))


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
        dump_json(rows)
        return

    table = Table(title=title)
    for column in columns:
        table.add_column(
            column.header,
            style=column.style,
            no_wrap=column.no_wrap,
            justify=column.justify,
        )
    for row in rows:
        table.add_row(*(column.value(row) for column in columns))
    Console().print(table)


def fields(rows: Sequence[tuple[str, str]], *, indent: str = "  ") -> None:
    """Print aligned label/value pairs.

    The shape every detail view needs — `nodes show`'s tag block and `orgs
    show`'s whole body are both this. Width is measured from the labels rather
    than fixed, so a long one cannot push its value out of the column.
    """
    if not rows:
        return
    width = max(len(label) for label, _ in rows)
    console = Console()
    for label, value in rows:
        # soft_wrap: values are ids, URLs and ARNs, which Rich would otherwise
        # hard-break mid-token to fit the console.
        console.print(f"{indent}[bold]{label:<{width}}[/bold]  {value}", soft_wrap=True)


def display_path(path: Path) -> str:
    """Render a path with `$HOME` collapsed to `~` for compact output."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


__all__ = [
    "FORMAT_EPILOG",
    "Column",
    "Format",
    "FormatOption",
    "WireModel",
    "display_path",
    "dump_json",
    "fields",
    "render",
]
