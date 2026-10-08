"""`yertle nodes` — work with nodes."""

import builtins
import json
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.tree import Tree
from yertle_client.models import (
    HierarchyEntryResponse,
    NodeResponse,
    NodeTreeDocument,
    PushStateResponse,
)
from yertle_client.types import Unset

import yertle
from yertle.cli._context import (
    NodeIdArgument,
    OrgOption,
    SingleOrgOption,
    resolve_one_org,
    resolve_org,
)
from yertle.cli._diff import diff_states, render_diff
from yertle.cli._errors import api_errors, die
from yertle.cli._render import FORMAT_EPILOG, Column, Format, FormatOption, dump_json, render

app = typer.Typer(
    name="nodes",
    help="Work with nodes.",
    no_args_is_help=True,
    epilog=FORMAT_EPILOG,
)


def _count(value: Any) -> str:
    """Render an optional count.

    These arrive as `int | None | Unset`; anything that isn't a number means
    the backend didn't compute it for this row, which is different from zero
    and should not be displayed as one.
    """
    return str(value) if isinstance(value, int) else "—"


# Ordered to pair each direct count with its transitive total, the way the
# web app's node list does: Children/Descendants walk down, Parents/Ancestors
# walk up. All four come from the response this command already makes.
#
# Caveat on the two totals: the generated model defaults them to 0 rather
# than UNSET, so a backend that omits them renders as "0 descendants" instead
# of "—". The direct counts default to UNSET and so degrade honestly. Nothing
# to do here — it is the OpenAPI schema's default — but it means a 0 in these
# two columns is slightly weaker evidence than a 0 in the other two.
BASE_COLUMNS: list[Column[NodeResponse]] = [
    Column("ID", lambda node: node.id, style="cyan", no_wrap=True),
    Column("Title", lambda node: node.title),
    Column("Children", lambda node: _count(node.num_children), justify="right"),
    Column("Descendants", lambda node: _count(node.num_descendants), justify="right"),
    Column("Parents", lambda node: _count(node.num_parents), justify="right"),
    Column("Ancestors", lambda node: _count(node.num_ancestors), justify="right"),
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


def _section(console: Console, title: str, count: int | None = None) -> None:
    console.print(f"\n[bold]{title if count is None else f'{title} ({count})'}[/bold]")


def _labelled(label: object) -> str:
    """Trailing dim label for a connection, or nothing. Labels are often null."""
    return f"  [dim]{label}[/dim]" if label else ""


def _listed(value: object) -> builtins.list[Any]:
    """Coerce an optional wire list into a list. `Unset` and `None` mean empty."""
    return value if isinstance(value, builtins.list) else []


def _render_header(console: Console, doc: NodeTreeDocument) -> None:
    node = doc.state.node
    console.print(f"[bold]{node.title or '(untitled)'}[/bold]")
    console.print(f"[dim]{doc.status.node_id} · branch {doc.status.branch}[/dim]")
    if description := (node.description or "").strip():
        console.print(f"\n{description}")


def _render_tags(console: Console, doc: NodeTreeDocument) -> None:
    tags = doc.state.tags
    entries = tags.to_dict() if not isinstance(tags, Unset) else {}
    if not entries:
        return
    _section(console, "Tags")
    for key in sorted(entries):
        entry = entries[key]
        # A tag is {"value": ..., "link": ...}; `link` is usually absent.
        value = entry.get("value", "") if isinstance(entry, dict) else entry
        link = entry.get("link") if isinstance(entry, dict) else None
        console.print(f"  {key}  [cyan]{value}[/cyan]{_labelled(link)}")


def _render_directories(console: Console, doc: NodeTreeDocument) -> None:
    directories = _listed(doc.state.directories)
    if not directories:
        return
    _section(console, "Directories")
    for path in directories:
        console.print(f"  {path}")


def _render_related(console: Console, doc: NodeTreeDocument) -> None:
    """Parents, then children.

    The two come from different halves of the document. Parents are
    read-only context in `status` — the containment edge lives in the
    *parent's* canvas, not here. Children are `state.visual_properties`,
    because containing a node is a thing this node stores and can change.

    Parents are always read from main, whatever branch was asked for, since
    that is where other nodes' canvases live.
    """
    parents = _listed(doc.status.parents)
    if parents:
        _section(console, "Parents", len(parents))
        for parent in parents:
            entry = parent.to_dict()
            console.print(f"  {entry.get('title', '')}  [dim]{entry.get('id', '')}[/dim]")

    children = _listed(doc.state.visual_properties)
    if children:
        _section(console, "Children", len(children))
        for child in children:
            title = child.field_title if not isinstance(child.field_title, Unset) else None
            console.print(f"  {title or ''}  [dim]{child.child_node_id}[/dim]")


def _render_connections(console: Console, doc: NodeTreeDocument) -> None:
    """Connections between this node's children.

    The document carries `_from_title` / `_to_title` annotations, so unlike
    the `/complete` version this needs no id-to-title lookup of its own.
    """
    connections = _listed(doc.state.connections)
    if not connections:
        return
    _section(console, "Connections between children", len(connections))
    for connection in connections:
        source = connection.field_from_title or connection.from_child_id
        target = connection.field_to_title or connection.to_child_id
        console.print(f"  {source} → {target}{_labelled(connection.label)}")


def _render_boundary(console: Console, doc: NodeTreeDocument) -> None:
    """Connections crossing this node's own boundary, from `status`."""
    for heading, related in (("Ingress", doc.status.ingress), ("Egress", doc.status.egress)):
        items = _listed(related)
        if not items:
            continue
        _section(console, heading, len(items))
        for item in items:
            edge = item.to_dict()
            # Denormalised with the far end attached, so no lookup is needed.
            other = (edge.get("connected_node") or {}).get("title", "?")
            line = f"{other} → this" if heading == "Ingress" else f"this → {other}"
            console.print(f"  {line}{_labelled(edge.get('label'))}")


def _render_show(doc: NodeTreeDocument) -> None:
    """Print a node's detail view.

    Empty sections are omitted rather than printed as headings with nothing
    under them — a node with no connections should read as a short page, not
    a form full of blanks.
    """
    console = Console()
    _render_header(console, doc)
    _render_tags(console, doc)
    _render_directories(console, doc)
    _render_related(console, doc)
    _render_connections(console, doc)
    _render_boundary(console, doc)


@app.command("show")
def show_node(
    node_id: NodeIdArgument,
    org: SingleOrgOption = None,
    branch: Annotated[str, typer.Option("--branch", "-b", help="Branch to read.")] = (
        yertle.nodes.DEFAULT_BRANCH
    ),
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Show a node's details — tags, parents, children and connections."""
    org_id = resolve_one_org(org, command="nodes show")

    with api_errors():
        doc = yertle.nodes.get(node_id, org_id=org_id, branch=branch)

    if fmt is Format.JSON:
        dump_json(doc)
        return
    _render_show(doc)


def _tag_filters(pairs: builtins.list[str]) -> dict[str, str]:
    """Parse repeated `--tag key=value` options.

    Shared by `search` (which filters on them) and `create` (which sets them),
    so the two cannot drift on what `--tag` accepts.
    """
    filters: dict[str, str] = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key.strip():
            die(f"--tag must be key=value, got {pair!r}.")
        filters[key.strip()] = value.strip()
    return filters


# A one-segment path is the node itself, so there is no parent to show.
_PATH_WITH_PARENT = 2


def _path_of(node: Any) -> str:
    """Ancestor breadcrumb, excluding the node itself.

    The API returns the full chain ending in the node's own title, which the
    Title column already shows. Dropping that last segment removes the
    duplication and buys back the width it was costing — the path was wrapping
    over four lines on an 80-column terminal.
    """
    path = node.get("path")
    if not isinstance(path, builtins.list) or len(path) < _PATH_WITH_PARENT:
        return ""
    return " / ".join(path[:-1])


MATCH_COLUMNS: builtins.list[Column[Any]] = [
    Column("Score", lambda m: f"{m['score']:.3f}"),
    Column("Title", lambda m: m["title"]),
    Column("Why", lambda m: m.get("match_reason") or "", style="dim"),
    Column("ID", lambda m: m["node_id"], style="cyan", no_wrap=True),
]

# The API only populates `path` on expanded results, so without --expand this
# column is blank on every row. Shown only when some row can fill it.
PATH_COLUMN: Column[Any] = Column("Path", lambda m: m["_path"], style="dim")

CONNECTION_COLUMNS: builtins.list[Column[Any]] = [
    Column("From", lambda c: c.get("from_title") or "?"),
    # A null label is common; the type is the useful fallback.
    Column("Edge", lambda c: c.get("label") or c.get("connection_type") or "", style="dim"),
    Column("To", lambda c: c.get("to_title") or "?"),
]


@app.command("search")
def search_nodes(
    query: Annotated[str, typer.Argument(help="Natural-language query.")],
    org: SingleOrgOption = None,
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="Max matches to return.")] = 5,
    expand: Annotated[
        yertle.search.Expansion | None,
        typer.Option("--expand", help="Also return surrounding nodes and connections."),
    ] = None,
    tag: Annotated[
        builtins.list[str] | None,
        typer.Option("--tag", help="Pre-filter by tag (key=value, repeatable)."),
    ] = None,
    scope_root: Annotated[
        str | None,
        typer.Option("--scope-root", help="Restrict to this node's subtree."),
    ] = None,
    dir_prefix: Annotated[
        str | None,
        typer.Option("--dir-prefix", help="Restrict to nodes under this directory."),
    ] = None,
    include_text: Annotated[
        bool,
        typer.Option("--include-text", help="Also print each match's prose content."),
    ] = False,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Find the nodes most likely to match a natural-language query."""
    org_id = resolve_one_org(org, command="nodes search")

    with api_errors():
        result = yertle.search.retrieve(
            query,
            org_id=org_id,
            top_k=top_k,
            expansion=expand,
            root_node_id=scope_root,
            tag_filters=_tag_filters(tag or []) or None,
            directory_prefix=dir_prefix,
            include_text=include_text,
        )

    if fmt is Format.JSON:
        dump_json(result)
        return

    matches = [m.to_dict() for m in result.matches]
    if not matches:
        typer.echo(f"No matches for {query!r}.")
        return

    # Path lives on the node, not the match, so fold it in before rendering
    # rather than making every column accessor do the lookup.
    nodes_by_id = {n.to_dict()["node_id"]: n.to_dict() for n in result.nodes}
    for match in matches:
        match["_path"] = _path_of(nodes_by_id.get(match["node_id"], {}))

    columns = builtins.list(MATCH_COLUMNS)
    if any(match["_path"] for match in matches):
        columns.insert(-1, PATH_COLUMN)

    console = Console()
    render(matches, fmt=fmt, columns=columns, title=f"Matches for {query!r}")

    connections = [c.to_dict() for c in result.connections]
    if connections:
        console.print()
        render(connections, fmt=fmt, columns=CONNECTION_COLUMNS, title="Connections")

    if include_text:
        for match in matches:
            node = nodes_by_id.get(match["node_id"], {})
            if text := (node.get("text_content") or "").strip():
                console.print(
                    f"\n[bold]{node.get('title', '')}[/bold]  [dim]{match['node_id']}[/dim]"
                )
                console.print(text)


@app.command("create")
def create_node(
    title: Annotated[str, typer.Argument(help="Node title.")],
    org: SingleOrgOption = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Node description."),
    ] = None,
    tag: Annotated[
        builtins.list[str] | None,
        typer.Option("--tag", help="Tag to set (key=value, repeatable)."),
    ] = None,
    directory: Annotated[
        builtins.list[str] | None,
        typer.Option("--dir", help="Directory path to file it under (repeatable)."),
    ] = None,
    public_id: Annotated[
        str | None,
        typer.Option("--public-id", help="Custom public identifier. Generated if omitted."),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Commit message. Defaults to 'Initial commit'."),
    ] = None,
    fmt: FormatOption = Format.TABLE,
) -> None:
    """Create a node.

    The node is created unattached — it belongs to the organization but sits
    under no parent, so `nodes tree` shows it at the top level beside the
    org's root rather than inside the hierarchy. Attaching it to a parent is
    a separate operation against that parent's branch, which the CLI cannot
    do yet (see docs/cli/ROADMAP.md).

    Repeat --tag and --dir to set more than one:

        yertle nodes create "Checkout API" \\
            --tag team=backend --tag tier=1 --dir /services --dir /apis
    """
    org_id = resolve_one_org(org, command="nodes create")

    with api_errors():
        node = yertle.nodes.create(
            title,
            org_id=org_id,
            description=description,
            tags=_tag_filters(tag or []) or None,
            directories=directory or None,
            public_id=public_id,
            commit_message=message,
        )

    if fmt is Format.JSON:
        dump_json(node)
        return

    # Print the id on its own line before anything else: it is the one piece
    # a caller needs for the next command, and this keeps `... | head -1`
    # working as a way to capture it.
    typer.echo(node.id)
    console = Console()
    console.print(f"[green]✓[/green] Created [bold]{node.title}[/bold]")
    # Say it outright rather than leaving it to be discovered. A node sitting
    # at the top of `nodes tree` beside the org's root looks like a mistake
    # until you know that creating and attaching are separate operations.
    #
    # An earlier version of this line claimed the node would not appear in
    # `nodes tree` at all. It does: the hierarchy endpoint treats a parentless
    # node as a root. The claim survived its unit tests, which asserted only
    # that the word "Unattached" was printed, and was caught by running the
    # command against a real backend.
    console.print(
        "[dim]  Unattached — `yertle nodes tree` lists it as a root, not under a parent.[/dim]"
    )


def _load_document(path: Path) -> NodeTreeDocument:
    """Parse a document file, refusing anything that is not one.

    The base-commit check is the load-bearing one. `expected_head_commit` is
    only obtainable by reading, so a document without it was assembled by
    hand — and since push replaces the whole state, a hand-written partial
    document deletes everything it forgot to mention. Refusing here is what
    makes read-before-write a precondition rather than advice.
    """
    try:
        raw = json.loads(path.read_text())
    except OSError as exc:
        die(f"Cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON ({exc}).")

    if not isinstance(raw, dict) or "state" not in raw:
        die(
            f"{path} does not look like a node document.\n"
            f"  Produce one with `yertle nodes show <id> --format json > {path}`.",
        )
    if not raw.get("expected_head_commit"):
        die(
            f"{path} has no `expected_head_commit`, so it was not produced by a read.\n"
            f"  Pushing it would replace the node's whole state with just this file.\n"
            f"  Start from `yertle nodes show <id> --format json > {path}` and edit that.",
        )
    try:
        return NodeTreeDocument.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        die(f"{path} is not a valid node document: {exc}")


@app.command("apply")
def apply_node(
    file: Annotated[
        Path,
        typer.Option("--file", "-f", help="Document from `nodes show --format json`."),
    ],
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Commit message. Falls back to the document's."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the diff and exit without writing."),
    ] = False,
    allow_deletes: Annotated[
        bool,
        typer.Option("--allow-deletes", help="Permit changes that remove something."),
    ] = False,
) -> None:
    """Write an edited node document back.

    The round trip:

        yertle nodes show <id> --format json > node.json
        # ...edit node.json...
        yertle nodes apply -f node.json -m "what changed"

    Push replaces the node's entire state, so anything missing from the file
    is deleted. The diff is printed every time, and a change that removes
    anything needs --allow-deletes. The organization, node and branch come
    from the document, so there is no --org here: a document knows where it
    belongs.
    """
    document = _load_document(file)
    org_id, node_id = document.status.org_id, document.status.node_id
    branch = document.status.branch

    with api_errors():
        current = yertle.nodes.get(node_id, org_id=org_id, branch=branch)

    console = Console()
    console.print(
        f"Applying to [bold]{current.state.node.title}[/bold] "
        f"[dim]{node_id} · branch {branch}[/dim]"
    )

    # Drift is worth naming before the diff, because it changes what the
    # diff means: it is then against a state nobody edited.
    if current.expected_head_commit != document.expected_head_commit:
        die(
            f"The branch moved since this document was read.\n"
            f"  document: {document.expected_head_commit}\n"
            f"  current:  {current.expected_head_commit}\n"
            f"  Re-read it with `yertle nodes show {node_id} --format json`, "
            f"reapply the edit, and try again.",
        )

    diff = diff_states(current.state, document.state)
    console.print()
    render_diff(console, diff)
    console.print()

    if diff.is_empty and not dry_run:
        console.print("[dim]Nothing to apply.[/dim]")
        return
    if dry_run:
        console.print("[dim]Dry run — nothing written.[/dim]")
        return
    if diff.removals and not allow_deletes:
        die(
            f"This would remove {len(diff.removals)} thing(s), listed above.\n"
            f"  Re-run with --allow-deletes if that is intended.",
        )

    commit_message = message or (
        document.message if isinstance(document.message, str) and document.message.strip() else None
    )
    if not commit_message:
        die("A commit message is required. Pass -m, or set `message` in the document.")

    with api_errors():
        result = yertle.nodes.push(document, message=commit_message)

    _render_push_result(console, result)


def _render_push_result(console: Console, result: PushStateResponse) -> None:
    """Report what the push did, including the parts that are easy to miss."""
    if result.unchanged:
        console.print("[green]✓[/green] Already up to date — no commit created.")
        return

    console.print(f"[green]✓[/green] Committed [bold]{result.commit_id}[/bold]")
    console.print(
        f"[dim]  {result.objects_created} object(s) created, {result.objects_reused} reused[/dim]"
    )

    mappings = result.connection_id_mappings
    if mappings is not None and not isinstance(mappings, Unset):
        for temporary, real in (mappings.to_dict() or {}).items():
            console.print(f"[dim]  connection {temporary} → {real}[/dim]")

    # The only signal that a typo was dropped: push stores what it knows and
    # ignores the rest, so a misspelled field fails silently without this.
    ignored = result.ignored_keys
    if ignored and not isinstance(ignored, Unset):
        console.print(f"\n[yellow]![/yellow] Ignored {len(ignored)} unknown key(s):")
        for key in ignored:
            console.print(f"    {key}")
        console.print(
            "[dim]  These were not stored. A misspelled field looks exactly like this.[/dim]"
        )
