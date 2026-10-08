"""Comparing two node states, so `apply` can say what it is about to do.

Push is a **full replace**: an omitted section is stored as empty. That makes
the difference between "I edited one tag" and "I deleted everything else"
invisible in the document itself — both are just a document. The diff is what
makes it visible, which is why `apply` always shows one.

Deletions are tracked separately from the rest because they are the only
irreversible half. Additions and modifications land as a commit you can
revert; a deletion of something the document simply forgot is the failure
this whole design exists to prevent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rich.console import Console
from yertle_client.models import Connection, NodeState, VisualProperty
from yertle_client.types import Unset

__all__ = ["Change", "Kind", "StateDiff", "diff_states", "render_diff"]


class Kind(StrEnum):
    """What is happening to one entry."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


_MARK = {Kind.ADDED: ("+", "green"), Kind.REMOVED: ("-", "red"), Kind.CHANGED: ("~", "yellow")}


@dataclass(frozen=True, slots=True)
class Change:
    """One difference, already rendered to a human-readable line."""

    section: str
    kind: Kind
    detail: str


@dataclass(slots=True)
class StateDiff:
    changes: list[Change] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.changes

    @property
    def removals(self) -> list[Change]:
        """The irreversible half, which `apply` gates behind a flag."""
        return [c for c in self.changes if c.kind is Kind.REMOVED]

    def counts(self) -> dict[Kind, int]:
        return {k: sum(1 for c in self.changes if c.kind is k) for k in Kind}


def _listed(value: object) -> list[Any]:
    """`Unset` and `None` mean empty — and for push they mean *deleted*."""
    return value if isinstance(value, list) else []


def _tags(state: NodeState) -> dict[str, Any]:
    return state.tags.to_dict() if not isinstance(state.tags, Unset) else {}


def _tag_text(raw: Any) -> str:
    """A tag is `{"value": ..., "link": ...}`; a bare string is shorthand.

    Also what the diff compares on. Comparing raw dicts instead reports a
    change whenever any key differs — including one push will ignore — and
    then renders it as `keep: yes → yes`, which reads as a bug in the tool.
    """
    if not isinstance(raw, dict):
        return str(raw)
    value = str(raw.get("value", ""))
    link = raw.get("link")
    return f"{value} ({link})" if link else value


def _child_label(vp: VisualProperty) -> str:
    """Prefer the `_title` annotation; an id alone tells the reader nothing."""
    title = vp.field_title if not isinstance(vp.field_title, Unset) else None
    return str(title or vp.child_node_id)


def _edge_label(c: Connection) -> str:
    source = c.field_from_title if not isinstance(c.field_from_title, Unset) else None
    target = c.field_to_title if not isinstance(c.field_to_title, Unset) else None
    line = f"{source or c.from_child_id} → {target or c.to_child_id}"
    label = c.label if not isinstance(c.label, Unset) else None
    return f"{line}  ({label})" if label else line


def _position(vp: VisualProperty) -> tuple[Any, ...]:
    """The fields a reader would call "where and how big"."""
    return (vp.position_x, vp.position_y, vp.z_index, vp.width, vp.height)


def _diff_node(current: NodeState, desired: NodeState) -> list[Change]:
    changes = []
    if current.node.title != desired.node.title:
        changes.append(
            Change("Node", Kind.CHANGED, f"title: {current.node.title} → {desired.node.title}")
        )
    if current.node.description != desired.node.description:
        changes.append(Change("Node", Kind.CHANGED, "description"))
    return changes


def _diff_tags(current: NodeState, desired: NodeState) -> list[Change]:
    before, after = _tags(current), _tags(desired)
    changes = []
    for key in sorted(set(before) | set(after)):
        if key not in after:
            changes.append(Change("Tags", Kind.REMOVED, f"{key}: {_tag_text(before[key])}"))
        elif key not in before:
            changes.append(Change("Tags", Kind.ADDED, f"{key}: {_tag_text(after[key])}"))
        elif _tag_text(before[key]) != _tag_text(after[key]):
            changes.append(
                Change(
                    "Tags",
                    Kind.CHANGED,
                    f"{key}: {_tag_text(before[key])} → {_tag_text(after[key])}",
                )
            )
    return changes


def _diff_directories(current: NodeState, desired: NodeState) -> list[Change]:
    before = set(_listed(current.directories))
    after = set(_listed(desired.directories))
    return [
        *(Change("Directories", Kind.REMOVED, str(p)) for p in sorted(before - after)),
        *(Change("Directories", Kind.ADDED, str(p)) for p in sorted(after - before)),
    ]


def _diff_keyed(
    section: str,
    before: dict[Any, Any],
    after: dict[Any, Any],
    *,
    label: Callable[[Any], str],
    compare: Callable[[Any], Any],
    changed_suffix: str = "",
) -> list[Change]:
    """Diff two collections keyed by identity — children, connections.

    `compare` picks the fields that count as a change, so annotations and
    server-owned fields can be left out of the comparison without being
    stripped from the document.
    """
    changes = [
        *(
            Change(section, Kind.REMOVED, label(before[k]))
            for k in sorted(set(before) - set(after))
        ),
        *(Change(section, Kind.ADDED, label(after[k])) for k in sorted(set(after) - set(before))),
    ]
    changes.extend(
        Change(section, Kind.CHANGED, f"{label(after[k])}{changed_suffix}")
        for k in sorted(set(before) & set(after))
        if compare(before[k]) != compare(after[k])
    )
    return changes


def diff_states(current: NodeState, desired: NodeState) -> StateDiff:
    """What applying `desired` over `current` would change.

    Annotations (`_title`, `_snapshot_commit_id`, …) are deliberately not
    compared. Push drops them, so a difference in one is not a change to
    anything stored, and reporting it would make every diff noisy with
    nothing the user can act on.
    """
    return StateDiff(
        [
            *_diff_node(current, desired),
            *_diff_tags(current, desired),
            *_diff_directories(current, desired),
            *_diff_keyed(
                "Children",
                {vp.child_node_id: vp for vp in _listed(current.visual_properties)},
                {vp.child_node_id: vp for vp in _listed(desired.visual_properties)},
                label=_child_label,
                compare=_position,
                changed_suffix=" moved/resized",
            ),
            *_diff_keyed(
                "Connections",
                {c.id: c for c in _listed(current.connections)},
                {c.id: c for c in _listed(desired.connections)},
                label=_edge_label,
                compare=lambda c: (c.label, c.from_child_id, c.to_child_id),
            ),
        ]
    )


def render_diff(console: Console, diff: StateDiff) -> None:
    """Print the diff grouped by section, in the document's own order."""
    if diff.is_empty:
        console.print("  [dim]No changes.[/dim]")
        return

    order = ["Node", "Tags", "Directories", "Children", "Connections"]
    width = max(len(section) for section in order)
    for section in order:
        entries = [c for c in diff.changes if c.section == section]
        for index, change in enumerate(entries):
            mark, colour = _MARK[change.kind]
            label = section if index == 0 else ""
            console.print(
                f"  [bold]{label:<{width}}[/bold]  [{colour}]{mark}[/{colour}] {change.detail}",
                soft_wrap=True,
            )

    counts = diff.counts()
    console.print(
        f"\n  [dim]{counts[Kind.ADDED]} added, "
        f"{counts[Kind.CHANGED]} changed, {counts[Kind.REMOVED]} removed[/dim]"
    )
