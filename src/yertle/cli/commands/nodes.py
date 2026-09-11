"""`yertle nodes` — work with nodes."""

import builtins
from collections import defaultdict
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.tree import Tree
from yertle_client.models import (
    HierarchyEntryResponse,
    NodeCompleteStateResponse,
    NodeResponse,
)
from yertle_client.types import Unset

import yertle
from yertle.cli._context import OrgOption, resolve_org
from yertle.cli._errors import api_errors, die
from yertle.cli._render import Column, Format, FormatOption, dump_json, render

app = typer.Typer(
    name="nodes",
    help="Work with nodes.",
    no_args_is_help=True,
)


def _count(value: Any) -> str:
    """Render an optional count.

    These arrive as `int | None | Unset`; anything that isn't a number means
    the backend didn't compute it for this row, which is different from zero
    and should not be displayed as one.
    """
    return str(value) if isinstance(value, int) else "—"


BASE_COLUMNS: list[Column[NodeResponse]] = [
    Column("ID", lambda node: node.id, style="cyan", no_wrap=True),
    Column("Title", lambda node: node.title),
    Column("Children", lambda node: _count(node.num_children)),
    Column("Parents", lambda node: _count(node.num_parents)),
]

# Only worth a column when the listing spans orgs; when scoped it is the same
# value on every row, and a second 36-character id squeezes the title off an
# 80-column terminal. Short ids will make this cheaper once the id cache lands
# for `nodes show` / `tree`.
ORG_COLUMN: Column[NodeResponse] = Column(
    "Org",
    lambda node: node.org_id,
    style="dim",
    no_wrap=True,
)


@app.command("list")
def list_nodes(org: OrgOption = None, fmt: FormatOption = Format.TABLE) -> None:
    """List nodes in an organization, or across every org you belong to."""
    org_id = resolve_org(org)

    with api_errors():
        nodes = yertle.nodes.list(org_id)

    across_orgs = org_id == yertle.nodes.ALL_ORGS
    scope = "all organizations" if across_orgs else f"org {org_id}"
    render(
        nodes,
        fmt=fmt,
        columns=[*BASE_COLUMNS, ORG_COLUMN] if across_orgs else BASE_COLUMNS,
        title=f"Nodes in {scope} ({len(nodes)})",
    )


_ROOT = "/"


def _full_path(entry: HierarchyEntryResponse) -> str:
    """The path of the entry itself, which is what its children are keyed by.

    Entries carry the path of their *parent*, absolute and slash-prefixed. As
    returned by `GET /orgs/{id}/hierarchy`, a root node has path "/" and its
    children have path "/Root"; a grandchild has "/Root/Yertle Webapp".

    So the leading slash is load-bearing. Building a root's own path as
    "Root" rather than "/Root" makes every child lookup miss, and the tree
    silently collapses to just its root nodes — which is exactly what shipped
    the first time.

    Titles are sanitised the same way the backend does when it builds these
    paths (`_sanitize_title` in `node_hierarchy_directories.py` replaces "/"
    with "-"), so a title containing a slash still matches its children.
    """
    parent = entry.path or _ROOT
    title = entry.title.replace("/", "-")
    return f"{_ROOT}{title}" if parent == _ROOT else f"{parent}/{title}"


def _add_branch(
    tree: Tree,
    entry: HierarchyEntryResponse,
    children_of: dict[str, list[HierarchyEntryResponse]],
    seen: set[str],
) -> None:
    """Attach `entry` to `tree`, recursing into directories.

    `seen` guards against a malformed hierarchy pointing back at itself; the
    backend should never produce one, but an infinite recursion in a read-only
    display command is a bad way to find out.
    """
    branch = tree.add(f"{entry.title}  [dim]{entry.node_id}[/dim]")
    path = _full_path(entry)
    if not entry.is_directory or path in seen:
        return
    seen.add(path)
    for child in sorted(children_of.get(path, []), key=lambda e: e.title):
        _add_branch(branch, child, children_of, seen)


def _attach(parent: Tree, entries: list[HierarchyEntryResponse]) -> None:
    """Build one org's hierarchy under `parent`."""
    children_of: dict[str, list[HierarchyEntryResponse]] = defaultdict(list)
    for entry in entries:
        children_of[entry.path or _ROOT].append(entry)

    seen: set[str] = set()
    for entry in sorted(children_of.get(_ROOT, []), key=lambda e: e.title):
        _add_branch(parent, entry, children_of, seen)


def _group_by_org(
    entries: list[HierarchyEntryResponse],
) -> dict[tuple[str, str], list[HierarchyEntryResponse]]:
    """Split entries by organization, preserving first-seen order.

    Paths are only unique *within* an org — two orgs that each have a node
    called "Root" both produce children at "/Root". Grouping before building
    is what stops one org's children being attached to another's tree, and is
    why the Go implementation grouped first too.
    """
    groups: dict[tuple[str, str], list[HierarchyEntryResponse]] = defaultdict(list)
    for entry in entries:
        org_id = entry.org_id if isinstance(entry.org_id, str) else ""
        org_name = entry.org_name if isinstance(entry.org_name, str) else org_id
        groups[(org_id, org_name)].append(entry)
    return groups


def _build_tree(entries: list[HierarchyEntryResponse], label: str) -> Tree:
    """Assemble a Rich tree from the flat, parent-path-keyed entry list."""
    tree = Tree(label)
    groups = _group_by_org(entries)
    if len(groups) == 1:
        _attach(tree, next(iter(groups.values())))
        return tree

    # More than one org in play: give each its own branch, so identical paths
    # in different orgs cannot collide and the reader can tell them apart.
    for (org_id, org_name), org_entries in groups.items():
        _attach(tree.add(f"[bold]{org_name}[/bold]  [dim]{org_id}[/dim]"), org_entries)
    return tree


@app.command("tree")
def tree_nodes(org: OrgOption = None, fmt: FormatOption = Format.TABLE) -> None:
    """Show the containment hierarchy — what contains what."""
    org_id = resolve_org(org)

    with api_errors():
        entries = yertle.nodes.tree(org_id)

    if fmt is Format.JSON:
        dump_json(entries)
        return

    if not entries:
        typer.echo("No nodes found.")
        return

    across_orgs = org_id == yertle.nodes.ALL_ORGS
    scope = "all organizations" if across_orgs else f"org {org_id}"
    Console().print(_build_tree(entries, f"Hierarchy in {scope} ({len(entries)})"))


def _tag_value(raw: object) -> str:
    """Render one tag value.

    The wire shape is `{"Team": {"value": "Backend"}}` — a nested object, not
    a flat string map, which the architecture doc's example does not show.
    Unwrap it, but fall back to the raw value so an unexpected shape prints
    something rather than raising inside a display command.
    """
    if isinstance(raw, dict):
        inner = raw.get("value")
        return str(inner) if inner is not None else ""
    return str(raw)


def _items(value: object) -> builtins.list[Any]:
    """Coerce an optional wire list into a list. `Unset` and `None` mean empty."""
    return value if isinstance(value, builtins.list) else []


def _section(console: Console, title: str, count: int | None = None) -> None:
    console.print(f"\n[bold]{title if count is None else f'{title} ({count})'}[/bold]")


def _labelled(label: object) -> str:
    """Trailing dim label for a connection, or nothing. Labels are often null."""
    return f"  [dim]{label}[/dim]" if label else ""


def _titles_by_id(state: NodeCompleteStateResponse) -> dict[str, str]:
    """Map child id → title, for resolving the ids inside `connections`.

    Internal connections reference `from_child_id` / `to_child_id`, so without
    this the section renders as a wall of uuids.
    """
    titles: dict[str, str] = {}
    for child in _items(state.child_nodes):
        entry = child.to_dict()
        node_id, title = entry.get("id"), entry.get("title")
        if isinstance(node_id, str) and isinstance(title, str):
            titles[node_id] = title
    return titles


def _render_header(console: Console, state: NodeCompleteStateResponse, branch: str) -> None:
    node = state.node.to_dict()
    console.print(f"[bold]{node.get('title', '(untitled)')}[/bold]")
    console.print(f"[dim]{node.get('id', '')} · branch {branch}[/dim]")
    if description := (node.get("description") or "").strip():
        console.print(f"\n{description}")


def _render_tags(console: Console, state: NodeCompleteStateResponse) -> None:
    tags = state.tags.to_dict() if not isinstance(state.tags, Unset) else {}
    if not tags:
        return
    _section(console, "Tags")
    for key in sorted(tags):
        console.print(f"  {key}  [cyan]{_tag_value(tags[key])}[/cyan]")


def _render_directories(console: Console, state: NodeCompleteStateResponse) -> None:
    directories = _items(state.directories)
    if not directories:
        return
    _section(console, "Directories")
    for path in directories:
        console.print(f"  {path}")


def _render_related(console: Console, state: NodeCompleteStateResponse) -> None:
    for label, related in (("Parents", state.parent_nodes), ("Children", state.child_nodes)):
        items = _items(related)
        if not items:
            continue
        _section(console, label, len(items))
        for item in items:
            entry = item.to_dict()
            console.print(f"  {entry.get('title', '')}  [dim]{entry.get('id', '')}[/dim]")


def _render_connections(console: Console, state: NodeCompleteStateResponse) -> None:
    connections = _items(state.connections)
    if not connections:
        return
    titles = _titles_by_id(state)
    _section(console, "Connections between children", len(connections))
    for connection in connections:
        edge = connection.to_dict()
        source = titles.get(str(edge.get("from_child_id")), "?")
        target = titles.get(str(edge.get("to_child_id")), "?")
        console.print(f"  {source} → {target}{_labelled(edge.get('label'))}")


def _render_boundary(console: Console, state: NodeCompleteStateResponse) -> None:
    """Connections crossing this node's own boundary."""
    for heading, related in (
        ("Ingress", state.ingress_connections),
        ("Egress", state.egress_connections),
    ):
        items = _items(related)
        if not items:
            continue
        _section(console, heading, len(items))
        for item in items:
            edge = item.to_dict()
            # These arrive denormalised with the far end's title attached, so
            # unlike internal connections they need no id lookup.
            other = (edge.get("connected_node") or {}).get("title", "?")
            line = f"{other} → this" if heading == "Ingress" else f"this → {other}"
            console.print(f"  {line}{_labelled(edge.get('label'))}")


def _render_show(state: NodeCompleteStateResponse, branch: str) -> None:
    """Print a node's detail view.

    Empty sections are omitted rather than printed as headings with nothing
    under them — a node with no connections should read as a short page, not a
    form full of blanks.
    """
    console = Console()
    _render_header(console, state, branch)
    _render_tags(console, state)
    _render_directories(console, state)
    _render_related(console, state)
    _render_connections(console, state)
    _render_boundary(console, state)


@app.command("show")
def show_node(
    node_id: Annotated[str, typer.Argument(help="Node id from `yertle nodes list`.")],
    org: OrgOption = None,
    branch: Annotated[str, typer.Option("--branch", "-b", help="Branch to read.")] = (
        yertle.nodes.DEFAULT_BRANCH
    ),
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Show a node's details — tags, parents, children and connections."""
    org_id = resolve_org(org)
    if org_id == yertle.nodes.ALL_ORGS:
        die(
            "`nodes show` needs one organization.\n"
            "  Pass --org <id>, or set a default with `yertle orgs use <id>`.",
        )

    with api_errors():
        state = yertle.nodes.get(node_id, org_id=org_id, branch=branch)

    if fmt is Format.JSON:
        dump_json(state)
        return
    _render_show(state, branch)
