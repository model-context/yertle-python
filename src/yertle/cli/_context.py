"""Working out which organization a command should act on.

Every org-scoped command asks the same question, from the same places, and
should fail the same way when it can't get an answer — so the chain lives here
rather than being re-derived per command.

There are two chains. A command that starts from an organization (`nodes
list`, `nodes create`) resolves flag → env → config → every org. A command
that takes a node id asks the backend which org the node is in, because the
node already knows; see `resolve_node_org()`.

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

import yertle
from yertle.cli._errors import api_errors, die
from yertle.nodes import ALL_ORGS
from yertle.shared import auth
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

# Not every command can span organizations. `nodes search` and `nodes create`
# each act on exactly one, and offering them an option value they will refuse
# is worse than not offering it — the help page becomes a claim the command
# does not honour.
SingleOrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        "-o",
        help=f"Organization to act on. Defaults to ${ORG_ENV_VAR}, then "
        f"`yertle orgs use`. This command acts on one org, so 'all' is not valid.",
    ),
]


# A command that takes a node id learns the org from the node, so `--org` is
# optional there and only checked. The help says so, and says that `orgs use`
# does not reach these commands, because that is the surprising part.
NodeOrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        "-o",
        help=f"Organization the node is in. Looked up from the node when not given; "
        f"if given, or ${ORG_ENV_VAR} is set, it must match. `yertle orgs use` "
        f"does not apply.",
    ),
]


_UUID_LEN = 36


def validate_node_id(value: str) -> str:
    """Return `value` if it is a usable node id, else exit with a hint.

    Node ids are UUIDs and the backend accepts nothing else — a node's
    `public_id` (`supabase`, `root-9e0aa98f`) 400s, verified 2026-09-23. So a
    malformed id can be rejected here, before a request, with a message that
    names the offending value.

    Without this the backend answers `400 badly formed hexadecimal UUID
    string`, which does not say *which* of the ids in the request was wrong —
    a branch command sends two — and reads like a server fault rather than a
    typo. The length hint is there because the way this actually happens is a
    truncated copy-paste.
    """
    stripped = value.strip()
    try:
        UUID(stripped)
    except ValueError:
        hint = ""
        if len(stripped) != _UUID_LEN:
            hint = f" (got {len(stripped)} characters, expected {_UUID_LEN} — truncated?)"
        die(
            f"{value!r} is not a node id{hint}.\n"
            f"  Node ids are UUIDs. Copy one from `yertle nodes list`.",
        )
    return stripped


NodeIdArgument = Annotated[
    str,
    typer.Argument(help="Node id from `yertle nodes list`.", callback=validate_node_id),
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
    work for a command scoped to a single org. More than one command needs
    this; naming `command` keeps the error specific while the wording stays
    in one place. Commands that take a node id use `resolve_node_org()`.
    """
    org_id = resolve_org(override)
    if org_id == ALL_ORGS:
        die(
            f"`{command}` needs one organization.\n"
            f"  Pass --org <id>, or set a default with `yertle orgs use <id>`.",
        )
    return org_id


def explicit_node_org(override: str | None = None) -> ResolvedOrg | None:
    """The organization the caller named for a command on a node, if any, unvalidated.

    Only `--org` and `$YERTLE_ORG` count, decided before any request. The
    `yertle orgs use` default does not: it is a standing choice for commands
    that start from an org, and applying it here would turn every node
    outside that org into a mismatch error. 'all' names no organization, so
    it constrains nothing and the lookup decides.
    """
    # #61 puts an org written into the node argument itself first in line,
    # ahead of the flag.
    if value := (override or "").strip():
        source = Source.FLAG
    elif value := os.environ.get(ORG_ENV_VAR, "").strip():
        source = Source.ENV
    else:
        return None
    if value == ALL_ORGS:
        return None
    return ResolvedOrg(value, source)


def resolve_node_org(node_id: str, override: str | None, *, public: bool = False) -> ResolvedOrg:
    """Return the organization a command on `node_id` acts on, and where it came from.

    Precedence:

    1. An org the caller named: `--org`, then `$YERTLE_ORG`.
    2. The node's own org, from the backend (`Source.LOOKUP`).

    The node is looked up in both cases. A named org that is not the node's
    is a mistake worth stopping on, naming both, rather than following the
    node somewhere the caller did not ask to go. Checking it costs the same
    one request that finding the org would.

    Pass `public=True` when no token resolves, to look up through the
    anonymous route; only reads can use the result. Without it, the lookup
    needs a token, so a write with none fails as "Not authenticated" before
    any request. A node the caller cannot see is a 404 either way, explained
    as one by `api_errors`.
    """
    named = explicit_node_org(override)
    if named is not None:
        validate_org(named.value)
    with api_errors(public=public):
        location = yertle.public.locate(node_id) if public else yertle.nodes.locate(node_id)
    if named is None:
        return ResolvedOrg(location.org_id, Source.LOOKUP)
    if UUID(named.value) != UUID(location.org_id):
        option = "--org" if named.source is Source.FLAG else f"${ORG_ENV_VAR}"
        die(
            f"Node {node_id} is in organization {location.org_id} ({location.org_name}),\n"
            f"  not {named.value}, which came from {option}.\n"
            f"  Drop {option} and the node's own organization is used.",
        )
    return ResolvedOrg(location.org_id, named.source)


def anonymous() -> bool:
    """True when no token resolves, so a read goes to the public routes.

    Decided once per command, before any request. With a token the CLI keeps
    to the authenticated routes even for a public org, so a member always
    sees their own view of it (role, invite settings) rather than the public
    one.
    """
    try:
        return auth.resolve().token is None
    except auth.AuthError as exc:
        die(str(exc))


def resolve_public_org(override: str | None) -> str:
    """Resolve the one organization an anonymous read should target.

    The chain's default is every org the caller belongs to, which means
    nothing without a token — and nothing lists public orgs. So an anonymous
    command that lands on 'all' fails with the usual message, plus the one
    thing that would work instead.
    """
    org_id = resolve_org(override)
    if org_id == ALL_ORGS:
        die(
            f"{auth.NOT_AUTHENTICATED}\n"
            f"  Without a token you can still read a public organization: pass --org <id>.",
        )
    return org_id


__all__ = [
    "ALL_ORGS",
    "ORG_ENV_VAR",
    "NodeOrgOption",
    "OrgOption",
    "ResolvedOrg",
    "SingleOrgOption",
    "anonymous",
    "explicit_node_org",
    "resolve_node_org",
    "resolve_one_org",
    "resolve_org",
    "resolve_org_setting",
    "resolve_public_org",
    "validate_node_id",
    "validate_org",
]
