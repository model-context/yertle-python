"""Auth / connection probes for the prerequisites yertle-sre depends on.

These are pure functions — no console output, no formatting. They run
short-timeout CLI checks and return a `ProbeResult` per prerequisite.
The CLI's `status` command turns the results into terminal output.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

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
    """Check the yertle CLI by listing orgs."""
    result = run_cli(["yertle", "orgs", "--format", "json"], timeout=PROBE_TIMEOUT)
    if not result.ok:
        return ProbeResult("yertle", False, "not authenticated — run `yertle login`")
    return ProbeResult("yertle", True, "authenticated")


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
