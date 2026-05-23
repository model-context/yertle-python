"""Safe subprocess helper used by every CLI-backed tool.

All shell-outs in yertle-sre go through `run_cli`. Centralizing here means:

- argv-only invocation (no `shell=True`, no string interpolation)
- consistent timeout enforcement
- consistent output truncation before content reaches the model
- a uniform `ShellResult` shape so tool wrappers handle success and failure
  the same way

Tool wrappers should translate non-zero exits into short, model-readable
messages — never dump raw stderr at the model.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_OUTPUT = 10_000
TRUNCATION_MARKER = "\n…[truncated]"


@dataclass(frozen=True, slots=True)
class ShellResult:
    """Result of a single CLI invocation."""

    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool

    def error_summary(self) -> str:
        """One-line, model-friendly description of why this failed.

        Only meaningful when `ok` is False.
        """
        first_stderr_line = self.stderr.strip().splitlines()[0] if self.stderr.strip() else ""
        if first_stderr_line:
            return f"exit {self.exit_code}: {first_stderr_line}"
        return f"exit {self.exit_code} (no stderr)"


def run_cli(
    argv: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> ShellResult:
    """Run a CLI command and return a structured result.

    Args:
        argv: Full argv list. argv[0] is the executable; never passed through a
            shell.
        timeout: Seconds before the process is killed.
        max_output: Maximum bytes of stdout (and separately stderr) returned.
            Larger output is truncated and `truncated=True` is set.

    The function never raises on non-zero exit codes — failure is encoded in
    the returned `ShellResult`. It does raise `FileNotFoundError` (wrapped in
    a clear ShellResult) only when the executable cannot be located, since
    that's a setup problem the model should report verbatim.
    """
    if not argv:
        raise ValueError("argv must not be empty")

    if shutil.which(argv[0]) is None:
        return ShellResult(
            ok=False,
            stdout="",
            stderr=f"executable not found: {argv[0]}",
            exit_code=127,
            truncated=False,
        )

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ShellResult(
            ok=False,
            stdout="",
            stderr=f"timeout after {timeout}s running {argv[0]}",
            exit_code=124,
            truncated=False,
        )

    stdout, stdout_truncated = _truncate(completed.stdout, max_output)
    stderr, stderr_truncated = _truncate(completed.stderr, max_output)

    return ShellResult(
        ok=completed.returncode == 0,
        stdout=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
        truncated=stdout_truncated or stderr_truncated,
    )


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + TRUNCATION_MARKER, True
