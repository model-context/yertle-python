"""Flattening Rich-rendered CLI output so it can be substring-matched.

Three things make a raw `in result.output` check unreliable, and CI has caught
two of them after they passed locally:

- **Colour codes land inside words.** Rich highlights anything option-shaped,
  so `--format` renders as `ESC[1;36m-ESC[0mESC[1;36m-formatESC[0m` — the
  escapes sit between the two dashes. Colour is on in CI and off on a piped
  local terminal, so the substring exists in one and not the other.
- **Output is wrapped to the terminal width**, which can split a phrase across
  a newline at a width nobody tested at.
- **Borders interleave with text.** Wrapped help inside a panel, and every
  table row, carries box-drawing characters between the cells.

Shared rather than copied per test module: this normalization was written
twice before it was extracted, which is the near-duplication `make hygiene`
watches for.
"""

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX = re.compile(r"[─-╿]")


def plain(output: str) -> str:
    """Rendered output as flat text: no colour, no borders, single spaces.

    A table row flattens to its cell values in order — `"Beta Corp 3 12 public
    owner"` — which is readable in an assertion and independent of column
    widths.
    """
    return " ".join(_BOX.sub(" ", _ANSI.sub("", output)).split())
