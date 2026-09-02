"""Failure paths for CLI commands.

`CLAUDE.md`: "Errors reaching a user are sentences, not tracebacks." Commands
wrap their API calls in `api_errors()` so that promise is kept in one place
rather than in a near-identical try/except in every command — the duplication
this package is most likely to grow as commands are added.
"""

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
        hint = f"{status} from the API. Try again, or check backend logs."
    else:
        hint = f"{status} from the API."
    return f"API error from {auth.resolve().api_url}\n  {hint}"


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
    except auth.AuthError as exc:
        die(str(exc))
    except UnexpectedStatus as exc:
        die(api_error_message(exc))
    except RuntimeError as exc:
        # The SDK raises RuntimeError when a documented non-200 (a 422
        # validation body, say) arrives where a model was expected.
        die(f"Unexpected response from the API: {exc}")


__all__ = ["api_error_message", "api_errors", "die"]
