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

# Must stay a subset of the commands the CLI actually implements. The previous
# value was copied from the Go CLI and listed five commands the Python CLI has
# never had (`nodes`, `tree`, `canvas`, `about`, `config`), so the agent was
# being told to call things that could only fail. Grow this as Slice 3 lands
# commands — see yertle/docs/notes/features/yertle-python/IMPLEMENTATION_PLAN.md.
YERTLE_READ_COMMANDS: frozenset[str] = frozenset({"orgs"})


@tool
def yertle_run(argv: list[str]) -> str:
    """Run a read-only `yertle` command and return its JSON output.

    `argv` is the argument list after `yertle`. `--format json` is appended
    automatically if no `--format` flag is already present.

    Commands are noun-then-verb, like `gh` and the AWS CLI.

    Available shapes:

        yertle_run(["orgs", "list"])   # list organizations

    That is currently the whole read surface. Node, tree and search commands
    are being added; until they appear here, they are not callable.

    Anything outside the allowed set (login, auth, version) is refused.
    """
    if not argv:
        return "refused: yertle_run requires at least one argument."

    if argv[0] not in YERTLE_READ_COMMANDS:
        return (
            f"refused: 'yertle {argv[0]}' is not a read-only command. "
            f"Allowed: {sorted(YERTLE_READ_COMMANDS)}."
        )

    full_argv = ["yertle", *argv]
    if "--format" not in argv:
        full_argv += ["--format", "json"]

    result = run_cli(full_argv)
    if not result.ok:
        return f"yertle CLI failed: {result.error_summary()}"
    return result.stdout


YERTLE_TOOLS = [yertle_run]
