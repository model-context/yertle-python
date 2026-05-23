"""Tool that wraps the `aws` CLI.

Auth: handled by the user via `aws configure` / SSO / env vars. yertle-sre
does not manage credentials.

We expose a single read-only runner gated by AWS's verb naming convention.
This covers every current and future AWS service without us having to
enumerate subcommands.
"""

from __future__ import annotations

from langchain_core.tools import tool

from yertle.sre.tools._shell import run_cli

AWS_READ_VERBS: frozenset[str] = frozenset(
    {"describe", "list", "get", "show", "search", "head", "lookup"},
)


@tool
def aws_run(service: str, command: str, extra_args: list[str] | None = None) -> str:
    """Run a read-only `aws <service> <command>` and return its JSON output.

    `--output json` is appended automatically. Examples:

        aws_run("ec2", "describe-instances", ["--region", "us-east-1"])
        aws_run("cloudwatch", "describe-alarms", ["--region", "us-east-1"])
        aws_run("rds", "describe-db-instances", ["--region", "us-west-2"])
        aws_run("s3api", "list-buckets")
        aws_run("iam", "get-user")
        aws_run("cloudformation", "list-stacks", ["--region", "us-east-1"])

    Reading CloudWatch logs is a two-step pattern: first find the most
    recent log stream with `aws_run("logs", "describe-log-streams", […])`
    using `--order-by LastEventTime --descending --max-items 1`, then call
    `aws_run("logs", "get-log-events", […])` with that stream name.

    Only read-only verbs are allowed: describe-*, list-*, get-*, show-*,
    search-*, head-*, lookup-*. Any other verb is refused before the CLI
    runs. Always pass `--region` for regional services — the agent should
    not guess.
    """
    verb = command.split("-", 1)[0]
    if verb not in AWS_READ_VERBS:
        return (
            f"refused: '{command}' is not a read-only verb. "
            f"yertle-sre's aws_run only allows commands beginning with: "
            f"{sorted(AWS_READ_VERBS)}."
        )
    argv = ["aws", service, command, *(extra_args or []), "--output", "json"]
    result = run_cli(argv)
    if not result.ok:
        return f"aws CLI failed: {result.error_summary()}"
    return result.stdout


AWS_TOOLS = [aws_run]
