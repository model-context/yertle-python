"""Tests for `cli/_diff.py`.

The diff is the only thing standing between an edited document and a silent
deletion, so what it must not do matters as much as what it reports:

- it must not miss a removal, because that is the gate `--allow-deletes`
  hangs off;
- it must not invent one, because a diff that cries wolf stops being read.
"""

from yertle_client.models import Connection, NodeFields, NodeState, NodeStateTags, VisualProperty

from yertle.cli._diff import Kind, diff_states


def _state(
    *,
    node: NodeFields | None = None,
    tags: NodeStateTags | None = None,
    directories: list[str] | None = None,
    visual_properties: list[VisualProperty] | None = None,
    connections: list[Connection] | None = None,
) -> NodeState:
    """A small state, with each section overridable.

    Written out rather than splatted from a dict so the type-checker still
    sees the real parameter types — a `**overrides` helper silently accepts
    a tag list where a tag map belongs.
    """
    return NodeState(
        node=node if node is not None else NodeFields(title="Parent", description="desc"),
        tags=tags if tags is not None else NodeStateTags.from_dict({"team": {"value": "core"}}),
        directories=directories if directories is not None else ["/services"],
        visual_properties=(
            visual_properties
            if visual_properties is not None
            else [VisualProperty(child_node_id="c1", position_x=0.0, position_y=0.0)]
        ),
        connections=connections if connections is not None else [],
    )


def _kinds(diff) -> list[tuple[str, Kind]]:
    return [(c.section, c.kind) for c in diff.changes]


def test_identical_states_produce_nothing() -> None:
    assert diff_states(_state(), _state()).is_empty


def test_an_unknown_key_inside_a_tag_is_not_a_change() -> None:
    """Push ignores it, so reporting it renders as `team: core → core`.

    A diff line whose two sides are identical reads as a bug in the tool,
    and this is how it happens: comparing raw dicts rather than the fields
    that are actually stored.
    """
    typo = NodeStateTags.from_dict({"team": {"value": "core", "lable": "oops"}})
    assert diff_states(_state(), _state(tags=typo)).is_empty


def test_a_dropped_section_reads_as_removal_not_absence() -> None:
    """An omitted section is stored as empty, so it is a deletion."""
    diff = diff_states(_state(), _state(tags=NodeStateTags.from_dict({}), directories=[]))
    assert ("Tags", Kind.REMOVED) in _kinds(diff)
    assert ("Directories", Kind.REMOVED) in _kinds(diff)
    assert len(diff.removals) == 2


def test_removing_a_child_is_a_removal() -> None:
    diff = diff_states(_state(), _state(visual_properties=[]))
    assert [c.kind for c in diff.changes] == [Kind.REMOVED]
    assert diff.removals


def test_moving_a_child_is_a_change_not_a_removal() -> None:
    moved = [VisualProperty(child_node_id="c1", position_x=99.0, position_y=0.0)]
    diff = diff_states(_state(), _state(visual_properties=moved))
    assert [c.kind for c in diff.changes] == [Kind.CHANGED]
    assert not diff.removals


def test_children_are_named_by_their_annotation() -> None:
    """A bare uuid tells the reader nothing about what they are deleting."""
    named = [VisualProperty(child_node_id="c1", position_x=0.0, position_y=0.0)]
    named[0].field_title = "Payments API"
    diff = diff_states(_state(visual_properties=named), _state(visual_properties=[]))
    assert diff.changes[0].detail == "Payments API"


def test_connections_are_named_by_both_ends() -> None:
    edge = Connection(id="e1", from_child_id="c1", to_child_id="c2")
    edge.field_from_title, edge.field_to_title = "User", "API"
    diff = diff_states(_state(), _state(connections=[edge]))
    assert diff.changes[0].detail.startswith("User → API")
    assert diff.changes[0].kind is Kind.ADDED


def test_counts_cover_every_kind() -> None:
    diff = diff_states(
        _state(),
        _state(
            node=NodeFields(title="Renamed", description="desc"),
            tags=NodeStateTags.from_dict({}),
            connections=[Connection(id="e1", from_child_id="c1", to_child_id="c2")],
        ),
    )
    counts = diff.counts()
    assert counts[Kind.CHANGED] == 1
    assert counts[Kind.REMOVED] == 1
    assert counts[Kind.ADDED] == 1
