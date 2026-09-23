"""Working out which organization a command should act on.

Every org-scoped command asks the same question, from the same places, and
should fail the same way when it can't get an answer — so the chain lives here
rather than being re-derived per command.

The chain mirrors how `shared/auth.py` resolves the token and API URL, because
"which org" is the same kind of question as "which backend": per-key
precedence, with the winning source reported so `yertle auth status` can
explain itself.

File access stays in `shared/auth.py` — this module never touches
`config.json` directly (invariant 1). It only decides which rung wins.
"""

import os
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import typer

from yertle.cli._errors import die
from yertle.nodes import ALL_ORGS
from yertle.shared.auth import Source, configured_org

ORG_ENV_VAR = "YERTLE_ORG"

OrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        "-o",
        help=f"Organization to act on, or 'all'. Defaults to ${ORG_ENV_VAR}, "
        f"then `yertle orgs use`, then 'all'.",
    ),
]

# Not every command can span organizations. `nodes show`, `nodes search` and
# `nodes create` each act on exactly one, and offering them an option value
# they will refuse is worse than not offering it — the help page becomes a
# claim the command does not honour.
SingleOrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        "-o",
        help=f"Organization to act on. Defaults to ${ORG_ENV_VAR}, then "
        f"`yertle orgs use`. This command acts on one org, so 'all' is not valid.",
    ),
]


@dataclass(frozen=True, slots=True)
class ResolvedOrg:
    """The effective organization, and which rung of the chain supplied it."""

    value: str
    source: Source


def resolve_org_setting(override: str | None = None) -> ResolvedOrg:
    """Resolve the organization with provenance, without validating its shape.

    Precedence: `--org` flag > `$YERTLE_ORG` > config file > every org.

    Blank values at any rung are treated as *unset* rather than as a malformed
    id, so `YERTLE_ORG=` in a sourced env file falls through instead of
    erroring.

    Defaulting to "all" rather than demanding a choice suits the orienting
    commands: `yertle nodes list` with no arguments should show you your world,
    not a usage error.
    """
    if value := (override or "").strip():
        return ResolvedOrg(value, Source.FLAG)
    if value := os.environ.get(ORG_ENV_VAR, "").strip():
        return ResolvedOrg(value, Source.ENV)
    if value := (configured_org() or "").strip():
        return ResolvedOrg(value, Source.CONFIG)
    return ResolvedOrg(ALL_ORGS, Source.DEFAULT)


def validate_org(value: str) -> str:
    """Return `value` if it is a usable organization id, else exit with a hint.

    Validating here means a typo fails with a sentence naming where to find a
    real id, rather than as a `ValueError` from deep inside the SDK.
    """
    if value == ALL_ORGS:
        return ALL_ORGS
    try:
        UUID(value)
    except ValueError:
        die(
            f"{value!r} is not an organization id.\n"
            f"  Pass the id from `yertle orgs list`, or '{ALL_ORGS}' for every org.",
        )
    return value


def resolve_org(override: str | None = None) -> str:
    """Return the organization id a command should use, validated."""
    return validate_org(resolve_org_setting(override).value)


def resolve_one_org(override: str | None, *, command: str) -> str:
    """Resolve to exactly one organization, exiting if the answer is 'all'.

    The default chain ends at `ALL_ORGS`, which suits a listing and cannot
    work for a command scoped to a single org. Three commands need this and
    each had its own copy of the check and the message; naming `command` keeps
    the error specific while the wording stays in one place.
    """
    org_id = resolve_org(override)
    if org_id == ALL_ORGS:
        die(
            f"`{command}` needs one organization.\n"
            f"  Pass --org <id>, or set a default with `yertle orgs use <id>`.",
        )
    return org_id


__all__ = [
    "ALL_ORGS",
    "ORG_ENV_VAR",
    "OrgOption",
    "ResolvedOrg",
    "SingleOrgOption",
    "resolve_one_org",
    "resolve_org",
    "resolve_org_setting",
    "validate_org",
]
