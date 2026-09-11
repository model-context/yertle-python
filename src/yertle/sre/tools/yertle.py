"""Tool that wraps the `yertle` CLI.

Auth: handled by the user via `yertle login`. yertle-sre does not manage
credentials.

We expose a single read-only runner. The yertle CLI's surface is small and
its commands all return JSON via `--format json`, so a generic gated runner
covers every useful question without needing per-command wrappers.
"""

from __future__ import annotations

from langchain_core.tools import tool

from yertle.sre.tools._shell import run_cli

# Allowlisted (noun, verb) pairs — NOT bare nouns.
#
# Gating on the noun alone was safe only while every verb under it read. It
# stopped being safe the moment `orgs use` landed: that writes the user's
# config file, and an argv[0] check would have waved it straight through,
# quietly breaking the read-only invariant in CLAUDE.md.
#
# Must stay a subset of what the CLI actually implements — an earlier version
# was copied from the Go CLI and advertised five commands this CLI never had,
# so the agent was told to call things that could only fail. Both properties
# are enforced by tests/sre/test_tools_yertle.py.
YERTLE_READ_COMMANDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("orgs", "list"),
        ("nodes", "list"),
        ("nodes", "tree"),
    },
)

# Every allowlisted command is a (noun, verb) pair, so an argv shorter than
# this cannot name one.
_NOUN_VERB = 2


@tool
def yertle_run(argv: list[str]) -> str:
    """Run a read-only `yertle` command and return its JSON output.

    `argv` is the argument list after `yertle`. `--format json` is appended
    automatically if no `--format` flag is already present.

    Commands are noun-then-verb, like `gh` and the AWS CLI.

    Available shapes:

        yertle_run(["orgs", "list"])                    # list organizations
        yertle_run(["nodes", "list"])                   # nodes across every org
        yertle_run(["nodes", "list", "--org", "<id>"])  # nodes in one org
        yertle_run(["nodes", "tree"])                   # containment hierarchy

    `nodes tree` is the fastest way to see what contains what; `nodes list`
    gives counts per node. That is currently the whole read surface. Search and
    per-node detail commands are being added; until they appear here, they are
    not callable.

    Every call needs a noun AND a verb. Anything outside the allowed set is
    refused — including write commands such as `orgs use`, which changes the
    user's saved configuration.
    """
    allowed = sorted(" ".join(pair) for pair in YERTLE_READ_COMMANDS)
    if len(argv) < _NOUN_VERB:
        return f"refused: yertle_run needs a noun and a verb. Allowed: {allowed}."

    if (argv[0], argv[1]) not in YERTLE_READ_COMMANDS:
        return (
            f"refused: 'yertle {argv[0]} {argv[1]}' is not a read-only command. Allowed: {allowed}."
        )

    full_argv = ["yertle", *argv]
    if "--format" not in argv:
        full_argv += ["--format", "json"]

    result = run_cli(full_argv)
    if not result.ok:
        return f"yertle CLI failed: {result.error_summary()}"
    return result.stdout


YERTLE_TOOLS = [yertle_run]
