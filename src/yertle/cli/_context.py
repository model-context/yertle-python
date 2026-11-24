"""Working out which organization a command should act on.

Every org-scoped command asks the same question, from the same places, and
should fail the same way when it can't get an answer — so the chain lives here
rather than being re-derived per command.

There are two chains. A command that starts from an organization (`nodes
list`, `nodes create`) resolves flag → env → config → every org. A command
that takes a node id asks the backend which org the node is in, because the
node already knows; see `resolve_node()`.

The chain mirrors how `shared/auth.py` resolves the token and API URL, because
"which org" is the same kind of question as "which backend": per-key
precedence, with the winning source reported so `yertle auth status` can
explain itself.

File access stays in `shared/auth.py` — this module never touches
`config.json` directly (invariant 1). It only decides which rung wins.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, TypeVar
from uuid import UUID

import typer
from yertle_client.errors import UnexpectedStatus
from yertle_client.models import NodeLocationResponse

import yertle
from yertle._ids import MIN_SHORT_ID, is_short_id
from yertle.cli._errors import api_error_message, api_errors, die
from yertle.cli._render import short_id
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


def _is_id(value: str) -> bool:
    """True for a full UUID or a short id (`yertle._ids.is_short_id`)."""
    if is_short_id(value):
        return True
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def validate_node_id(value: str) -> str:
    """Return `value` if it is a usable node id, else exit with a hint.

    A node id is a full UUID or a short id, the first 8 or more characters of
    one, as git takes a short SHA (#60). Anything else is refused here, before
    a request: a node's `public_id` (`supabase`, `root-9e0aa98f`) is not an
    id, and a 7-character prefix is not one either, because the backend would
    pass it through unresolved and answer 404, which reads as "no such node"
    rather than "too short".

    This only checks the shape. Which node a short id means, and whether it
    means just one, is the backend's answer; see `resolve_node()`.
    """
    stripped = value.strip()
    if not _is_id(stripped):
        die(
            f"{value!r} is not a node id.\n"
            f"  Pass a UUID, or at least its first {MIN_SHORT_ID} characters. "
            f"Copy one from `yertle nodes list`.",
        )
    return stripped


NodeIdArgument = Annotated[
    str,
    typer.Argument(
        help=f"Node id from `yertle nodes list`, or its first {MIN_SHORT_ID}+ characters.",
        callback=validate_node_id,
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

    A full UUID or a short id, as for nodes. A short id is passed on as it
    is: every org id the CLI sends goes in a path, where the backend resolves
    it. Validating here means a typo fails with a sentence naming where to
    find a real id, rather than as a `ValueError` from deep inside the SDK.
    """
    if value == ALL_ORGS:
        return ALL_ORGS
    if not _is_id(value):
        die(
            f"{value!r} is not an organization id.\n"
            f"  Pass the id from `yertle orgs list` (its first {MIN_SHORT_ID} characters "
            f"will do), or '{ALL_ORGS}' for every org.",
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
    in one place. Commands that take a node id use `resolve_node()`.
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


@dataclass(frozen=True, slots=True)
class ResolvedNode:
    """The node a command acts on, by its full id, and its organization.

    `node_id` is always the full UUID, even when the caller typed a short id.
    Resolving once, here, means nothing downstream has to know short ids
    exist: not the output, which then names the node the way every response
    does, and not the request bodies, where the backend resolves nothing.
    """

    node_id: str
    org: ResolvedOrg
    #: The node's title, when the lookup returned one. For headings, so a
    #: table can say which node it is about without another request.
    title: str | None = None

    def label(self) -> str:
        """`Title abcd1234`, or the short id alone when there is no title."""
        short = short_id(self.node_id)
        return f"{self.title} {short}" if self.title else short


def _names(given: str, full: str) -> bool:
    """True if `given`, a full or short id, names the full id `full`."""
    if is_short_id(given):
        return full.lower().startswith(given.lower())
    return UUID(given) == UUID(full)


def resolve_node(node_id: str, override: str | None, *, public: bool = False) -> ResolvedNode:
    """Return the node a command acts on, with its full id and organization.

    Precedence for the organization:

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

    A short node id goes through the same lookup, which answers with the full
    id, except where the lookup will not match one: the anonymous lookup takes
    full ids only, and the signed-in one matches short ids only in the
    caller's own orgs, so that neither can be used to probe for nodes. In
    those two cases a named org stands in, and the id is resolved inside it,
    through the org's public routes (`_resolve_in_public_org`).
    """
    named = explicit_node_org(override)
    if named is not None:
        validate_org(named.value)
    location = _locate(node_id, named, public=public)
    if isinstance(location, ResolvedNode):
        return location
    if named is None:
        return ResolvedNode(
            location.node_id, ResolvedOrg(location.org_id, Source.LOOKUP), _title(location)
        )
    if not _names(named.value, location.org_id):
        option = "--org" if named.source is Source.FLAG else f"${ORG_ENV_VAR}"
        die(
            f"Node {location.node_id} is in organization {location.org_id} "
            f"({location.org_name}),\n"
            f"  not {named.value}, which came from {option}.\n"
            f"  Drop {option} and the node's own organization is used.",
        )
    return ResolvedNode(
        location.node_id, ResolvedOrg(location.org_id, named.source), _title(location)
    )


def _locate(
    node_id: str, named: ResolvedOrg | None, *, public: bool
) -> NodeLocationResponse | ResolvedNode:
    """Look the node up; for a short id the lookup cannot match, resolve it in `named`.

    Returns the lookup's answer, or, when it came from the named org, the
    node already resolved there, which needs no org check.
    """
    short = is_short_id(node_id)
    if public and short:
        if named is None:
            die(
                "Without a token, a short node id needs its organization.\n"
                "  Pass --org <id>, use the full node id, or run `yertle login`.",
            )
        with api_errors(public=True):
            return _resolve_in_public_org(node_id, named)

    with api_errors(public=public):
        try:
            return yertle.public.locate(node_id) if public else yertle.nodes.locate(node_id)
        except UnexpectedStatus as missing:
            if not short or missing.status_code != HTTPStatus.NOT_FOUND:
                raise
            if named is None:
                die(
                    f"{api_error_message(missing)}\n"
                    f"  A short id matches only nodes in organizations you belong to.\n"
                    f"  For a node in a public organization, pass --org <id> or the full id.",
                )
            # Signed in, but the node is not in one of your orgs: perhaps it
            # is in the public one you named. If not there either, the
            # original 404 is the answer.
            try:
                return _resolve_in_public_org(node_id, named)
            except UnexpectedStatus as public_failure:
                if public_failure.status_code == HTTPStatus.NOT_FOUND:
                    raise missing from None
                raise


def _resolve_in_public_org(node_id: str, named: ResolvedOrg) -> ResolvedNode:
    """Resolve a short node id inside a named public organization.

    The org-scoped public routes resolve a short node id within the org in
    the path, for anyone. The node's document is the read that echoes both
    full ids back; it costs a request a node lookup would have cost anyway.
    """
    doc = yertle.public.get_node(node_id, org_id=named.value)
    status = doc.status
    return ResolvedNode(
        status.node_id, ResolvedOrg(status.org_id, named.source), doc.state.node.title or None
    )


def _title(location: NodeLocationResponse) -> str | None:
    """The lookup's title, if it sent one. Untitled nodes have none."""
    return location.title if isinstance(location.title, str) and location.title else None


def anonymous() -> bool:
    """True when no token resolves, so a read goes to the public routes.

    Decided once per command, before any request. With a token the CLI keeps
    to the authenticated routes even for a public org, so a member always
    sees their own view of it (role, invite settings) rather than the public
    one. A signed-in caller who is not a member has no such view; for them,
    `member_or_public()` falls back to the public routes.
    """
    try:
        return auth.resolve().token is None
    except auth.AuthError as exc:
        die(str(exc))


T = TypeVar("T")

#: Shown when `member_or_public()` fell back, so a signed-in caller knows why
#: they got the public view (less than a member sees) and not their own.
PUBLIC_FALLBACK_HINT = (
    "Read through the public routes: you are signed in, but not a member of this organization."
)


def member_or_public(member: Callable[[], T], public: Callable[[], T]) -> tuple[T, bool]:
    """Run a member read; only if the token is refused, run the public one.

    Returns the result and whether it came from the public routes.

    A signed-in caller who isn't a member of an org gets a 403 from its member
    routes, even when the org is public and the same read works with no token
    (#70). So on a 403, and only then, the public read is tried:

    - it succeeds: the org is public, so return its public view;
    - it 404s: the org isn't public (or doesn't exist), so re-raise the
      original 403, and the caller sees exactly what they saw before.

    Members never get a 403, so they keep their own view and pay nothing
    extra. Call this inside `api_errors()`: any failure that escapes is a
    member-route failure, and is explained as one.
    """
    try:
        return member(), False
    except UnexpectedStatus as refused:
        if refused.status_code != HTTPStatus.FORBIDDEN:
            raise
        try:
            return public(), True
        except UnexpectedStatus as public_failure:
            if public_failure.status_code == HTTPStatus.NOT_FOUND:
                raise refused from None
            raise


def public_fallback_hint() -> None:
    """Say on stderr that a read fell back to the public routes.

    stderr, so `--format json` output stays exactly the JSON.
    """
    typer.secho(PUBLIC_FALLBACK_HINT, dim=True, err=True)


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
    "PUBLIC_FALLBACK_HINT",
    "NodeOrgOption",
    "OrgOption",
    "ResolvedNode",
    "ResolvedOrg",
    "SingleOrgOption",
    "anonymous",
    "explicit_node_org",
    "member_or_public",
    "public_fallback_hint",
    "resolve_node",
    "resolve_one_org",
    "resolve_org",
    "resolve_org_setting",
    "resolve_public_org",
    "validate_node_id",
    "validate_org",
]
