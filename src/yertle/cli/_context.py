"""Working out which organization a command should act on.

Every org-scoped command asks the same question, from the same places, and
should fail the same way when it can't get an answer — so the chain lives here
rather than being re-derived per command.

Deliberately *not* in `shared/auth.py`: this reads a flag and an env var, never
`~/.yertle/config.json`. If a persisted default org is ever added, it has to be
read there instead, so config access stays in one module (invariant 1).
"""

import os
from typing import Annotated
from uuid import UUID

import typer

from yertle.cli._errors import die
from yertle.nodes import ALL_ORGS

ORG_ENV_VAR = "YERTLE_ORG"

OrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        "-o",
        help=f"Organization to act on, or 'all'. Defaults to ${ORG_ENV_VAR}, then 'all'.",
    ),
]


def resolve_org(org: str | None) -> str:
    """Return the organization id a command should use.

    Precedence: `--org` flag, then `$YERTLE_ORG`, then every org the caller
    belongs to. Defaulting to "all" rather than erroring matches what the Go
    CLI did and suits the orienting commands — `yertle nodes list` with no
    arguments should show you your world, not a usage error.

    Validates the shape here so a typo'd id fails with a sentence naming where
    to find a real one, rather than as a `ValueError` from deep in the SDK.
    """
    # Strip before falling through: a flag or env var set to whitespace means
    # "unset", not "malformed".
    value = (org or "").strip() or os.environ.get(ORG_ENV_VAR, "").strip() or ALL_ORGS
    if value == ALL_ORGS:
        return ALL_ORGS
    try:
        UUID(value)
    except ValueError:
        die(
            f"{value!r} is not an organization id.\n"
            "  Pass the full id from `yertle orgs list`, or --org all for every org.",
        )
    return value


__all__ = ["ORG_ENV_VAR", "OrgOption", "resolve_org"]
