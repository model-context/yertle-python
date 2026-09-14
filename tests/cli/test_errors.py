"""Tests for the CLI's error translation.

These assert the contract in `CLAUDE.md` — "errors reaching a user are
sentences, not tracebacks" — at the layer that owns it, rather than only
incidentally through whichever command happens to fail.
"""

import pytest
import typer
from yertle_client.errors import UnexpectedStatus

from yertle.cli._errors import api_error_message, api_errors, die
from yertle.shared import auth


@pytest.fixture(autouse=True)
def _pinned_api_url(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Messages name the resolved backend, so pin it rather than read the host's."""
    monkeypatch.setenv("YERTLE_API_URL", "https://api.example.test")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "401 Unauthorized"),
        (403, "403 Forbidden"),
        (404, "404 from the API"),
        (500, "500 from the API"),
        (503, "503 from the API"),
    ],
)
def test_api_error_message_explains_each_status(status: int, expected: str) -> None:
    message = api_error_message(UnexpectedStatus(status, b""))
    assert expected in message


def test_api_error_message_names_the_backend() -> None:
    """A misconfigured $YERTLE_API_URL is otherwise invisible in a 401."""
    message = api_error_message(UnexpectedStatus(401, b""))
    assert "https://api.example.test" in message


def test_api_error_message_does_not_mention_the_removed_edge_authorizer() -> None:
    """The API Gateway JWT authorizer was removed 2026-08-31.

    Its advice — that PATs only work against a local backend — is now the
    opposite of true, so it must not come back.
    """
    message = api_error_message(UnexpectedStatus(401, b'{"message":"Unauthorized"}'))
    assert "locally-run" not in message
    assert "JWT authorizer" not in message


def test_api_errors_translates_auth_failures() -> None:
    with pytest.raises(typer.Exit) as excinfo, api_errors():
        raise auth.AuthError("Not authenticated. Run `yertle login`.")
    assert excinfo.value.exit_code == 1


def test_api_errors_translates_unexpected_status() -> None:
    with pytest.raises(typer.Exit) as excinfo, api_errors():
        raise UnexpectedStatus(500, b"")
    assert excinfo.value.exit_code == 1


def test_api_errors_translates_an_unexpected_response_shape() -> None:
    """The SDK raises RuntimeError when a documented non-200 arrives."""
    with pytest.raises(typer.Exit) as excinfo, api_errors():
        raise RuntimeError("Unexpected response from orgs.list(): None")
    assert excinfo.value.exit_code == 1


def test_api_errors_lets_real_bugs_through() -> None:
    """Deliberately narrow: a genuine bug stays a traceback, not a tidy message."""
    with pytest.raises(ZeroDivisionError), api_errors():
        _ = 1 / 0


def test_api_error_message_surfaces_the_backend_detail() -> None:
    """The cause of a 500 is in the body; showing it is the whole point."""
    body = b'{"detail":"Failed to get hierarchy: column x does not exist"}'
    message = api_error_message(UnexpectedStatus(500, body))
    assert "column x does not exist" in message


def test_api_error_message_says_so_when_a_500_carries_no_detail() -> None:
    message = api_error_message(UnexpectedStatus(500, b""))
    assert "No detail in the response body" in message


@pytest.mark.parametrize(
    "body",
    [
        b"<html>502 Bad Gateway</html>",  # not JSON
        b'["detail"]',  # JSON, but not an object
        b'{"detail":[{"loc":["body"],"msg":"field required"}]}',  # 422 shape
        b'{"detail":"   "}',  # blank
    ],
)
def test_api_error_message_ignores_bodies_with_no_usable_detail(body: bytes) -> None:
    """A malformed body must not crash the error path — it is the error path."""
    message = api_error_message(UnexpectedStatus(500, body))
    assert "500 from the API" in message


def test_api_error_message_truncates_a_huge_detail() -> None:
    """A stack trace in the body should not flood the terminal."""
    body = b'{"detail":"' + b"x" * 5000 + b'"}'
    message = api_error_message(UnexpectedStatus(500, body))
    assert len(message) < 700
    assert message.endswith("…")


def test_api_errors_lets_a_clean_exit_through() -> None:
    """`typer.Exit` subclasses RuntimeError, so it must be re-raised first.

    A command that validates its own arguments inside an `api_errors()` block
    calls `die()`, which raises `typer.Exit`. Before this was handled, the
    RuntimeError branch caught it and printed a second, wrong error after the
    real one.
    """
    with pytest.raises(typer.Exit) as excinfo, api_errors():
        die("bad --tag")
    assert excinfo.value.exit_code == 1
