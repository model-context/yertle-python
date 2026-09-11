"""Auth / connection probes for the prerequisites yertle-sre depends on.

These are pure functions — no console output, no formatting. They run
short-timeout CLI checks and return a `ProbeResult` per prerequisite.
The CLI's `status` command turns the results into terminal output.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import yertle
from yertle.shared import auth
from yertle.sre.tools._shell import run_cli

PROBE_TIMEOUT = 5


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one prerequisite check."""

    name: str
    ok: bool
    detail: str  # principal/identity on success, fix instruction on failure


def probe_anthropic() -> ProbeResult:
    """Check that ANTHROPIC_API_KEY is set. We don't validate it against the API."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ProbeResult("ANTHROPIC_API_KEY", True, "set")
    return ProbeResult(
        "ANTHROPIC_API_KEY",
        False,
        "not set — export ANTHROPIC_API_KEY=sk-ant-…",
    )


def probe_yertle() -> ProbeResult:
    """Check Yertle credentials by listing organizations.

    Calls the SDK in-process rather than shelling out to the `yertle` CLI.
    The CLI form was `yertle orgs --format json`, which silently became a
    usage error the moment `orgs` grew subcommands — and because the test
    mocked the subprocess, nothing caught it; the probe just started telling
    authenticated users to log in.

    Going through the SDK deletes the string that can drift and answers the
    question the probe actually asks — are these credentials good — without a
    process spawn. `aws` and `gh` still shell out because they genuinely are
    external CLIs.
    """
    try:
        api_url = auth.resolve().api_url
        yertle.orgs.list()
    except auth.AuthError as e:
        # AuthError's message is written to be shown to a user as-is.
        return ProbeResult("yertle", False, str(e))
    except Exception as e:  # noqa: BLE001 — probes never raise; they report.
        return ProbeResult("yertle", False, f"could not reach the API ({type(e).__name__})")
    return ProbeResult("yertle", True, f"authenticated to {api_url}")


def probe_aws() -> ProbeResult:
    """Check the aws CLI via STS get-caller-identity. Returns the ARN on success."""
    result = run_cli(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        timeout=PROBE_TIMEOUT,
    )
    if not result.ok:
        return ProbeResult("aws", False, "not authenticated — run `aws configure`")
    arn = "(unknown principal)"
    try:
        parsed = json.loads(result.stdout)
        if isinstance(parsed, dict):
            arn = parsed.get("Arn", arn)
    except (ValueError, TypeError):
        pass
    profile = os.environ.get("AWS_PROFILE", "default")
    return ProbeResult("aws", True, f"{arn} (profile: {profile})")


def probe_gh() -> ProbeResult:
    """Check the gh CLI's auth state."""
    result = run_cli(["gh", "auth", "status"], timeout=PROBE_TIMEOUT)
    if not result.ok:
        return ProbeResult("gh", False, "not authenticated — run `gh auth login`")
    return ProbeResult("gh", True, "authenticated")


def probe_all() -> list[ProbeResult]:
    """Run every probe in order. Probes never raise; they return a ProbeResult."""
    return [probe_anthropic(), probe_yertle(), probe_aws(), probe_gh()]
