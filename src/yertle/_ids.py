"""Checking an organization or node id before it goes on the wire.

An id is a full UUID or a **short id**: a unique prefix of one, as git takes a
short SHA (#60). The backend resolves a short id where it appears in a path,
after `/orgs/` and after `/orgs/{org}/nodes/` (both also under `/public`), and
in the signed-in node lookup `GET /nodes/{id}`. It does not resolve one in a
query string or a request body, so anything bound there has to be resolved to
the full UUID first. See `api/id_prefix.py` in the backend repo.
"""

from __future__ import annotations

import re
from uuid import UUID

__all__ = ["MIN_SHORT_ID", "full_id", "is_short_id", "wire_node_id", "wire_org_id"]

#: The fewest hex digits a short id may have. This is the backend's
#: `MIN_PREFIX_HEX` and must stay equal to it: shorter, and the backend passes
#: the segment through unresolved, so an id that looks valid here 404s there;
#: longer, and the CLI refuses ids the backend would take. Eight is also the
#: first group of a UUID, so the usual short id has no hyphen.
MIN_SHORT_ID = 8
_UUID_HEX = 32
_HEXISH = re.compile(r"^[0-9a-fA-F-]+$")


def is_short_id(value: str) -> bool:
    """True if `value` is a strict prefix of a UUID's canonical form, of 8+ hex digits.

    Mirrors the backend's `parse_prefix`, including that hyphens count only
    where the canonical form has them: `ab7bd00e-eb4f` is a short id and
    `ab-7bd00e` is not. A full UUID is not a short id.
    """
    if not _HEXISH.match(value):
        return False
    digits = value.replace("-", "")
    if not MIN_SHORT_ID <= len(digits) < _UUID_HEX:
        return False
    return str(UUID(digits.ljust(_UUID_HEX, "0"))).startswith(value.lower())


def full_id(value: str) -> str:
    """Return `value` in canonical form, raising `ValueError` if it is not a full UUID."""
    return str(UUID(value))


def wire_org_id(org_id: str) -> str:
    """Return `org_id` ready for a path, raising `ValueError` if it is not an id.

    A full UUID is canonicalised; a short id is sent lowercased. Anything else
    fails here, as a `ValueError`, rather than as a backend 400 or as a 404
    that reads like "no such org". `yertle-client` types these parameters as
    `str` precisely so that a short id can be sent at all.
    """
    return org_id.lower() if is_short_id(org_id) else full_id(org_id)


def wire_node_id(node_id: str) -> str:
    """Return `node_id` ready for a path, raising `ValueError` if it is not an id.

    The same rule as `wire_org_id`. Where the backend takes only a full id,
    as the anonymous node lookup does, use `full_id` instead.
    """
    return wire_org_id(node_id)
