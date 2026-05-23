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

YERTLE_READ_COMMANDS: frozenset[str] = frozenset(
    {"orgs", "nodes", "tree", "canvas", "about", "config"},
)


@tool
def yertle_run(argv: list[str]) -> str:
    """Run a read-only `yertle` command and return its JSON output.

    `argv` is the argument list after `yertle`. `--format json` is appended
    automatically if no `--format` flag is already present.

    Common shapes:

        yertle_run(["orgs"])                     # list organizations
        yertle_run(["orgs", "<org-id>"])         # one org's details
        yertle_run(["nodes"])                    # list nodes in default org
        yertle_run(["nodes", "--org", "<id>"])   # list nodes in a given org
        yertle_run(["nodes", "<node-id>"])       # one node's full details
                                                  # (tags, connections, attrs)
        yertle_run(["tree"])                     # containment hierarchy
        yertle_run(["canvas", "<node-id>"])      # child layout for a node

    Use `nodes <node-id>` as your primary way to resolve a component name
    into its underlying AWS / GitHub identifiers — node attributes typically
    include AWS resource IDs, GitHub repo URLs, owners, etc.

    Allowed top-level commands: orgs, nodes, tree, canvas, about, config.
    Anything else (login, auth, monitor, debug) is refused.
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
