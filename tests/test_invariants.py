"""Architectural invariants, enforced as tests.

These assert properties of the *source tree* rather than of any single
function: that credential handling stays in one module, that subprocess
execution stays behind one helper, and that the MCP surface stays read-only.

Each invariant is one an ordinary code review would have to catch by eye, and
so is exactly the kind that erodes one reasonable-looking change at a time.
Encoding them here makes the erosion a failing test instead of a discovery
six months later.

If an invariant genuinely needs to change, change it here deliberately — the
docstring on each test says what the rule protects.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "yertle"

AUTH_MODULE = SRC / "shared" / "auth.py"
SHELL_MODULE = SRC / "sre" / "tools" / "_shell.py"

CREDENTIAL_ENV_VARS = ("YERTLE_TOKEN", "YERTLE_API_URL")


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


@pytest.fixture(scope="module")
def source_files() -> list[Path]:
    files = _python_files()
    # Guard against the walk silently matching nothing (a moved package root
    # would otherwise make every test below vacuously pass).
    assert len(files) > 5, f"expected to find the package source under {SRC}"
    return files


def _rel(path: Path) -> str:
    return str(path.relative_to(SRC.parent.parent))


def test_credentials_are_resolved_only_in_shared_auth(source_files: list[Path]) -> None:
    """`shared/auth.py` is the single source of truth for credential resolution.

    The SDK, CLI, and MCP server each need a token and an API URL, and each is
    a plausible place to "just read the env var". Doing so forks the precedence
    chain documented in `auth.resolve()` — the failure mode is a surface that
    honors `$YERTLE_TOKEN` but silently ignores `~/.yertle/config.json`.
    """
    offenders: list[str] = []
    for path in source_files:
        if path == AUTH_MODULE:
            continue
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Constant) and node.value in CREDENTIAL_ENV_VARS:
                offenders.append(f"{_rel(path)}:{node.lineno} references {node.value!r}")

    assert not offenders, (
        "Credential environment variables must only be read in shared/auth.py. "
        "Use `auth.resolve()` / `auth.resolve_credentials()` instead:\n  " + "\n  ".join(offenders)
    )


def test_config_path_is_not_reconstructed(source_files: list[Path]) -> None:
    """Only `shared/auth.py` knows where the config file lives.

    Same reasoning as the env vars: a second module joining `.yertle` and
    `config.json` itself is a second definition of the config location that
    will not move when the first one does.
    """
    offenders = [
        f"{_rel(path)}:{node.lineno}"
        for path in source_files
        if path != AUTH_MODULE
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Constant) and node.value in (".yertle", "config.json")
    ]
    assert not offenders, (
        "Import `auth.CONFIG_PATH` rather than rebuilding the config path:\n  "
        + "\n  ".join(offenders)
    )


def test_subprocess_is_only_used_by_the_shell_helper(source_files: list[Path]) -> None:
    """Every shell-out goes through `sre/tools/_shell.py::run_cli`.

    `run_cli` is where argv-only invocation, the timeout, and output truncation
    live. A tool that calls `subprocess` directly silently opts out of all
    three — the model can then be handed unbounded output, or the agent can
    hang on a command that never returns.
    """
    offenders: list[str] = []
    for path in source_files:
        if path == SHELL_MODULE:
            continue
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{_rel(path)}:{node.lineno} imports {alias.name}"
                    for alias in node.names
                    if alias.name == "subprocess"
                ]
            elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                offenders.append(f"{_rel(path)}:{node.lineno} imports from subprocess")

    assert not offenders, (
        "Use `yertle.sre.tools._shell.run_cli` instead of calling subprocess "
        "directly:\n  " + "\n  ".join(offenders)
    )


def test_no_shell_true_anywhere(source_files: list[Path]) -> None:
    """`shell=True` is never acceptable in this package.

    Every command this package runs is assembled from model-supplied or
    user-supplied fragments. `shell=True` turns any of them into an injection
    point, which is why `run_cli` takes an argv list and documents that argv[0]
    is never passed through a shell.
    """
    offenders = [
        f"{_rel(path)}:{node.lineno}"
        for path in source_files
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.keyword)
        and node.arg == "shell"
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
    ]
    assert not offenders, "`shell=True` is banned:\n  " + "\n  ".join(offenders)


def test_mcp_route_maps_stay_read_only() -> None:
    """The MCP server mounts GET operations and excludes everything else.

    `mcp/server.py` builds its tool surface from the backend's live OpenAPI
    spec, so the set of mounted operations changes whenever the backend does.
    Read-only-ness is therefore a property of the RouteMap filter, not of any
    reviewed list of tools: the trailing catch-all EXCLUDE is the only thing
    standing between a newly added mutating endpoint and an agent calling it.
    """
    source = (SRC / "mcp" / "server.py").read_text()

    assert 'RouteMap(methods=["GET"], mcp_type=MCPType.TOOL)' in source, (
        "The GET-only RouteMap in mcp/server.py has changed shape. If the MCP "
        "surface is meant to expose non-GET operations, that is a product "
        "decision — make it explicitly."
    )
    assert 'RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE)' in source, (
        "The catch-all EXCLUDE RouteMap is missing from mcp/server.py. Without "
        "it, endpoints the backend adds later are mounted by default."
    )
    assert source.index('methods=["GET"]') < source.index("MCPType.EXCLUDE"), (
        "The catch-all EXCLUDE must come last — route maps are matched in "
        "order, so an EXCLUDE placed first swallows the GET mount."
    )
