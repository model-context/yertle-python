"""Tests for the aws CLI runner."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.sre.tools.aws import aws_run


def test_aws_run_allows_describe(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout='{"DBInstances":[]}', stderr="", returncode=0)

    fake_cli(respond)
    out = aws_run.invoke(
        {
            "service": "rds",
            "command": "describe-db-instances",
            "extra_args": ["--region", "us-east-1"],
        },
    )
    assert out == '{"DBInstances":[]}'
    assert captured[0][:3] == ["aws", "rds", "describe-db-instances"]
    assert "--region" in captured[0]
    assert "us-east-1" in captured[0]
    # Always appends JSON output flag.
    assert captured[0][-2:] == ["--output", "json"]


def test_aws_run_allows_all_read_verbs(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="{}", stderr="", returncode=0))
    for command in (
        "describe-instances",
        "list-buckets",
        "get-user",
        "show-policies",
        "search-products",
        "head-object",
        "lookup-events",
    ):
        out = aws_run.invoke({"service": "x", "command": command, "extra_args": []})
        assert not out.startswith("refused"), f"should allow {command}"


def test_aws_run_refuses_destructive_verbs(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="should-not-run", stderr="", returncode=0))
    for command in (
        "terminate-instances",
        "delete-bucket",
        "create-stack",
        "put-object",
        "update-function-code",
        "modify-db-instance",
        "attach-volume",
        "stop-instances",
    ):
        out = aws_run.invoke({"service": "x", "command": command, "extra_args": []})
        assert out.startswith("refused"), f"should refuse {command}"
        assert "should-not-run" not in out


def test_aws_run_handles_missing_extra_args(fake_cli):
    captured: list[list[str]] = []

    def respond(argv):
        captured.append(argv)
        return FakeCompleted(stdout="{}", stderr="", returncode=0)

    fake_cli(respond)
    aws_run.invoke({"service": "ec2", "command": "describe-regions"})
    assert captured[0] == ["aws", "ec2", "describe-regions", "--output", "json"]


def test_aws_run_translates_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout="",
            stderr="An error occurred (UnauthorizedOperation)",
            returncode=255,
        ),
    )
    out = aws_run.invoke(
        {
            "service": "ec2",
            "command": "describe-instances",
            "extra_args": ["--region", "us-east-1"],
        },
    )
    assert out.startswith("aws CLI failed:")
    assert "Unauthorized" in out
