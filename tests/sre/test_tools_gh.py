"""Tests for the gh CLI runner."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.sre.tools.gh import gh_run


def test_gh_run_allows_resource_list(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="[]", stderr="", returncode=0)

    fake_cli(respond)
    gh_run.invoke({"argv": ["pr", "list", "--repo", "model-context/yertle"]})
    assert captured[0] == ["gh", "pr", "list", "--repo", "model-context/yertle"]


def test_gh_run_allows_resource_view(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="{}", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["repo", "view", "x/y"]})
    assert not out.startswith("refused")


def test_gh_run_allows_resource_status(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="{}", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["pr", "status"]})
    assert not out.startswith("refused")


def test_gh_run_allows_search(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="[]", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["search", "issues", "is:open"]})
    assert not out.startswith("refused")


def test_gh_run_allows_api_get(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="{}", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["api", "/repos/x/y/commits"]})
    assert not out.startswith("refused")


def test_gh_run_refuses_api_post(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["api", "-X", "POST", "/repos/x/y/issues"]})
    assert out.startswith("refused")
    assert "leak" not in out


def test_gh_run_refuses_api_method_equals_post(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    out = gh_run.invoke({"argv": ["api", "--method=DELETE", "/repos/x/y"]})
    assert out.startswith("refused")
    assert "leak" not in out


def test_gh_run_refuses_mutating_subcommands(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    for argv in (
        ["pr", "create", "--repo", "x/y"],
        ["pr", "merge", "1", "--repo", "x/y"],
        ["issue", "close", "1"],
        ["repo", "delete", "x/y"],
        ["run", "rerun", "12345"],
    ):
        out = gh_run.invoke({"argv": argv})
        assert out.startswith("refused"), f"should refuse {argv}"
        assert "leak" not in out


def test_gh_run_refuses_empty(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="leak", stderr="", returncode=0))
    out = gh_run.invoke({"argv": []})
    assert out.startswith("refused")


def test_gh_run_translates_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout="",
            stderr="HTTP 401: Bad credentials",
            returncode=1,
        ),
    )
    out = gh_run.invoke({"argv": ["pr", "list", "--repo", "x/y"]})
    assert out.startswith("gh CLI failed:")
    assert "401" in out
