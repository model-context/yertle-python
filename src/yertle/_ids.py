"""Checking an organization id before it goes on the wire."""

from __future__ import annotations

from uuid import UUID

__all__ = ["wire_org_id"]


def wire_org_id(org_id: str) -> str:
    """Return `org_id` in canonical form, raising `ValueError` if it is not a UUID.

    `yertle-client` 0.5 types every `org_id` path parameter as `str`, because
    the backend also accepts a unique prefix of at least 8 hex characters.
    Until 0.5 they were typed `UUID`, and the SDK converted with `UUID(org_id)`
    — which is also what made a malformed id fail here, with a `ValueError`,
    rather than as a 400 from the backend. That check is kept on purpose:
    accepting prefixes is a separate decision for the CLI and SDK, not a side
    effect of a client bump.
    """
    return str(UUID(org_id))
