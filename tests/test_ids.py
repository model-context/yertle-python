"""What the SDK accepts as an org or node id: a full UUID or a short id (#60).

The rule mirrors the backend's `parse_prefix` in yertle's `api/id_prefix.py`,
so an id this accepts is one the backend will try to resolve, and an id it
refuses would have been passed through unresolved and answered with a 404.
"""

import pytest

from yertle._ids import MIN_SHORT_ID, full_id, is_short_id, wire_node_id, wire_org_id

FULL = "ab7bd00e-eb4f-4c2a-9d1e-0123456789ab"


def test_the_minimum_is_the_backends() -> None:
    """`MIN_PREFIX_HEX` in yertle's `api/id_prefix.py`. Change both or neither."""
    assert MIN_SHORT_ID == 8


@pytest.mark.parametrize(
    "value",
    [
        FULL[:8],
        FULL[:8].upper(),
        FULL[:9],  # "ab7bd00e-": the hyphen is where the canonical form has one
        FULL[:13],
        FULL[:-1],  # 31 hex digits: still a prefix, not a full id
    ],
)
def test_short_ids(value: str) -> None:
    assert is_short_id(value)
    assert wire_org_id(value) == value.lower()
    assert wire_node_id(value) == value.lower()


@pytest.mark.parametrize(
    "value",
    [
        FULL,  # a full id is not a short one
        FULL[:7],  # one short of the minimum
        "ab-7bd00e",  # a hyphen where the canonical form has none
        "ab7bd00eeb4f",  # hyphens left out
        "ab7bd00g",  # not hex
        "",
    ],
)
def test_not_short_ids(value: str) -> None:
    assert not is_short_id(value)


def test_a_full_id_is_canonicalised() -> None:
    assert wire_org_id(FULL.upper()) == FULL
    assert full_id(FULL.upper()) == FULL


@pytest.mark.parametrize("value", [FULL[:7], "ab-7bd00e", "payments", "all"])
def test_anything_else_is_a_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        wire_org_id(value)


def test_full_id_refuses_a_short_one() -> None:
    with pytest.raises(ValueError):
        full_id(FULL[:8])
