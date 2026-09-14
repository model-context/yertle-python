"""Failure paths for CLI commands.

`CLAUDE.md`: "Errors reaching a user are sentences, not tracebacks." Commands
wrap their API calls in `api_errors()` so that promise is kept in one place
rather than in a near-identical try/except in every command — the duplication
this package is most likely to grow as commands are added.
"""

import json
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


def die(message: str) -> NoReturn:
    """Print a message to stderr and exit non-zero.

    `from None` keeps the traceback out of the user's terminal; the message is
    the whole error report.
    """
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from None


@contextmanager
def api_errors() -> Iterator[None]:
    """Translate credential and wire failures into a sentence plus exit 1.

        with api_errors():
            organizations = yertle.orgs.list()

    Deliberately narrow: it catches the three ways an SDK call is expected to
    fail and nothing else, so a genuine bug still surfaces as a traceback
    rather than being flattened into a friendly message.
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
        die(api_error_message(exc))
    except RuntimeError as exc:
        # The SDK raises RuntimeError when a documented non-200 (a 422
        # validation body, say) arrives where a model was expected.
        die(f"Unexpected response from the API: {exc}")


__all__ = ["api_error_message", "api_errors", "die"]
