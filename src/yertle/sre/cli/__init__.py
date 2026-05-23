"""CLI subpackage. Re-exports the Typer app so the entry point and
`python -m yertle.sre` keep resolving to `yertle.sre.cli:app`.

The [sre] extras-guard lives in `yertle/sre/__init__.py` (the package root)
so that any import path — console script, `python -m yertle.sre`, or
`from yertle import sre` — hits it before Python tries to import langchain.
"""

from yertle.sre.cli.app import app

__all__ = ["app"]
