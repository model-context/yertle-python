"""Tool that wraps the `gh` CLI.

Auth: handled by the user via `gh auth login`. yertle-sre does not manage
credentials.

We expose a single read-only runner. Mutating commands (create, merge,
delete, edit, close, reopen, rerun, checkout, …) are refused before the
CLI is invoked.
"""

from __future__ import annotations

from langchain_core.tools import tool

from yertle.sre.tools._shell import run_cli

GH_READ_SUBCOMMANDS: frozenset[str] = frozenset({"list", "view", "status", "search"})
_RESOURCE_AND_VERB = 2  # `gh <resource> <verb> …`


@tool
def gh_run(argv: list[str]) -> str:
    """Run a read-only `gh` command and return its output.

    `argv` is the argument list after `gh`. Pass `--json <fields>` when you
    want structured output (recommended for `pr list`, `pr view`,
    `run list`, `issue list`, etc.). Examples:

        gh_run(["pr", "list", "--repo", "x/y", "--state", "open",
                "--json", "number,title,author,state,updatedAt,url"])
        gh_run(["pr", "view", "42", "--repo", "x/y",
                "--json", "number,title,body,state,statusCheckRollup,reviews"])
        gh_run(["run", "list", "--repo", "x/y", "--status", "failure",
                "--json", "databaseId,name,conclusion,headBranch,createdAt,url"])
        gh_run(["issue", "view", "1", "--repo", "x/y",
                "--json", "number,title,body,state,labels,comments,url"])
        gh_run(["release", "list", "--repo", "x/y"])
        gh_run(["repo", "view", "x/y", "--json", "name,description,url"])
        gh_run(["search", "issues", "is:open label:bug", "--repo", "x/y"])
        gh_run(["api", "/repos/x/y/commits"])

    Allowed shapes: `<resource> {list|view|status}`, `search …`, and
    `gh api …` with HTTP method GET. Mutating commands (create, merge,
    delete, edit, close, reopen, rerun, checkout) and any non-GET `gh api`
    are refused before the CLI runs.
    """
    if not argv:
        return "refused: gh_run requires at least one argument."

    head = argv[0]

    if head == "search":
        full_argv = ["gh", *argv]
    elif head == "api":
        if _gh_api_is_mutation(argv):
            return (
                "refused: gh api with non-GET method is not allowed. "
                "yertle-sre's gh_run only supports GET requests via `gh api`."
            )
        full_argv = ["gh", *argv]
    elif len(argv) >= _RESOURCE_AND_VERB and argv[1] in GH_READ_SUBCOMMANDS:
        full_argv = ["gh", *argv]
    else:
        return (
            f"refused: '{' '.join(argv[:2])}' is not a read-only gh invocation. "
            f"Allowed shapes: `<resource> {{list|view|status|search}} …`, "
            f"`search …`, or `api <GET endpoint>`."
        )

    result = run_cli(full_argv)
    if not result.ok:
        return f"gh CLI failed: {result.error_summary()}"
    return result.stdout


def _gh_api_is_mutation(argv: list[str]) -> bool:
    """True if a `gh api` invocation specifies a non-GET HTTP method."""
    for i, token in enumerate(argv):
        if token in {"-X", "--method"}:
            if i + 1 < len(argv) and argv[i + 1].upper() != "GET":
                return True
        elif token.startswith("--method="):
            value = token.split("=", 1)[1]
            if value.upper() != "GET":
                return True
    return False


GH_TOOLS = [gh_run]
