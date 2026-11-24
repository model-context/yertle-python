"""Failure paths for CLI commands.

`CLAUDE.md`: "Errors reaching a user are sentences, not tracebacks." Commands
wrap their API calls in `api_errors()` so that promise is kept in one place
rather than in a near-identical try/except in every command — the duplication
this package is most likely to grow as commands are added.
"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
from typing import NoReturn

import typer
from yertle_client.errors import UnexpectedStatus

from yertle.shared import auth


def api_error_message(exc: UnexpectedStatus) -> str:
    """Explain an unexpected API response, naming the backend it came from.

    The effective base URL leads the message because a misconfigured
    `$YERTLE_API_URL` (or stale config) is otherwise invisible: the request
    does reach *something*, which then rejects it, and the resulting 401 looks
    identical to a genuinely bad token.

    Until 2026-08-31 this also special-cased `{"message": "Unauthorized"}` as
    an API Gateway JWT-authorizer rejection and told the user PATs only worked
    against a local backend. The authorizer was removed in the in-app auth
    migration — every route is `AuthorizationType: NONE` and FastAPI is the
    sole gate — so that branch detected a mechanism that no longer exists and
    its advice had become actively wrong.
    """
    status = exc.status_code
    if status == HTTPStatus.UNAUTHORIZED:
        hint = (
            "401 Unauthorized — the backend rejected this token. Likely causes: "
            "it was issued by a different backend than the one you're hitting, "
            "it was revoked, or it has expired."
        )
    elif status == HTTPStatus.FORBIDDEN:
        hint = "403 Forbidden — token is valid but lacks permission for this resource."
    elif status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        hint = f"{status} from the API."
    else:
        hint = f"{status} from the API."

    lines = [f"API error from {auth.resolve().api_url}", f"  {hint}"]
    if detail := _detail_of(exc.content):
        lines.append(f"  {detail}")
    elif status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        lines.append("  No detail in the response body — check the backend logs.")
    return "\n".join(lines)


# Long bodies are an HTML error page or a stack trace, not a message meant for
# a terminal. Show a prefix and let the logs carry the rest.
_MAX_DETAIL_LEN = 400


def _detail_of(content: bytes) -> str | None:
    """Pull FastAPI's `detail` string out of an error body, if there is one.

    The backend puts the actual cause here — a hierarchy 500 arrives as
    `{"detail": "Failed to get hierarchy: column ... does not exist"}`. Dropping
    it left every server error reading "500 from the API, check backend logs",
    which is the least useful true thing the CLI could say, and turned an
    answerable question into a guess.

    Returns `None` for a body that is not JSON, not an object, or whose detail
    is not a plain string (FastAPI uses a list of objects for 422 validation
    errors, which is noise at a prompt).
    """
    try:
        body = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail") or body.get("message")
    if not isinstance(detail, str) or not detail.strip():
        return None
    detail = " ".join(detail.split())
    if len(detail) > _MAX_DETAIL_LEN:
        detail = f"{detail[:_MAX_DETAIL_LEN]}…"
    return detail


# The backend's wording for a short id that matches more than one org or node
# (`api/id_prefix.py`, and `GET /nodes/{id}`). Only the signed-in node lookup
# lists the matches: everywhere else the prefix is resolved before
# authentication, so listing them would show ids to anyone.
_AMBIGUOUS = re.compile(
    r"^(?P<kind>Organization|Node) ID prefix '(?P<prefix>[^']*)' matches more than one "
    r"\w+(?:: (?P<candidates>.*))?\. Use more characters, or the full ID\.$",
    re.DOTALL,
)
# Splits the candidate list between entries: "<uuid> (<title>, in <org>)".
_NEXT_CANDIDATE = re.compile(r"(?<=\)), (?=[0-9a-f]{8}-)")


def ambiguous_id_message(exc: UnexpectedStatus) -> str | None:
    """Explain a 409 for an ambiguous short id the way git does, or return None.

    `git show ab7b` answers "short object ID ab7b is ambiguous". The 409 is
    the same situation, and the fix is the same, so the message is too. It
    names no backend URL: unlike a 401 or a 403, the cause here is never the
    configuration, always the id.

    Returns None for any other 409 (a branch that already exists, say), which
    then gets the generic message.
    """
    if exc.status_code != HTTPStatus.CONFLICT:
        return None
    try:
        detail = json.loads(exc.content).get("detail")
    except (ValueError, TypeError, AttributeError):
        return None
    match = _AMBIGUOUS.match(detail) if isinstance(detail, str) else None
    if match is None:
        return None
    lines = [
        f"Short ID '{match['prefix']}' is ambiguous: it matches more than one "
        f"{match['kind'].lower()}.",
        "  Use more characters, or the full ID.",
    ]
    if candidates := match["candidates"]:
        lines.append("  It matches:")
        lines.extend(f"    {entry}" for entry in _NEXT_CANDIDATE.split(candidates))
    return "\n".join(lines)


def die(message: str) -> NoReturn:
    """Print a message to stderr and exit non-zero.

    `from None` keeps the traceback out of the user's terminal; the message is
    the whole error report.
    """
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from None


def public_not_found_message() -> str:
    """Explain a 404 from a `/public` route, which has two possible causes.

    The backend answers 404 both for an id that does not exist and for an org
    that exists but is private, on purpose, so the two cannot be told apart
    from outside. The message therefore names both, and the way out of the
    second: an org you are a member of is readable once you log in.
    """
    return (
        f"Not found at {auth.resolve().api_url}, or not a public organization.\n"
        f"  Without a token, only public organizations can be read. If this one "
        f"is yours, run `yertle login` or set ${auth.TOKEN_ENV_VAR}."
    )


@contextmanager
def api_errors(*, public: bool = False) -> Iterator[None]:
    """Translate credential and wire failures into a sentence plus exit 1.

        with api_errors():
            organizations = yertle.orgs.list()

    Deliberately narrow: it catches the three ways an SDK call is expected to
    fail and nothing else, so a genuine bug still surfaces as a traceback
    rather than being flattened into a friendly message.

    Pass `public=True` around a `yertle.public` call, so that a 404 is
    explained as "not found, or not public" rather than as a bare status.
    """
    try:
        yield
    except typer.Exit:
        # `typer.Exit` subclasses RuntimeError, so without this it is caught by
        # the handler below and re-reported as "Unexpected response from the
        # API" — turning a command's own clean exit into a confusing second
        # error. Any `die()` inside an `api_errors()` block hits this.
        raise
    except auth.AuthError as exc:
        die(str(exc))
    except UnexpectedStatus as exc:
        if ambiguous := ambiguous_id_message(exc):
            die(ambiguous)
        if public and exc.status_code == HTTPStatus.NOT_FOUND:
            die(public_not_found_message())
        die(api_error_message(exc))
    except RuntimeError as exc:
        # The SDK raises RuntimeError when a documented non-200 (a 422
        # validation body, say) arrives where a model was expected.
        die(f"Unexpected response from the API: {exc}")


__all__ = [
    "ambiguous_id_message",
    "api_error_message",
    "api_errors",
    "die",
    "public_not_found_message",
]
