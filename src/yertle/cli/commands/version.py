"""`yertle version`."""

import json
from importlib.metadata import Distribution, PackageNotFoundError
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer

from yertle import __version__
from yertle.cli._render import display_path


def _source_checkout() -> Path | None:
    """Return the working-tree path if this is an editable install, else `None`.

    Homebrew ships the *same* CLI in its own venv, so a bare `yertle` can be
    the last published release while `uv run yertle` is your working tree —
    identical commands, different code, no visible difference. PEP 610 records
    how a distribution was installed in `direct_url.json`; an editable install
    carries `dir_info.editable`, a wheel from PyPI carries no such file.
    """
    try:
        raw = Distribution.from_name("yertle").read_text("direct_url.json")
    except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
        return None
    if not raw:
        return None
    direct_url = json.loads(raw)
    if not direct_url.get("dir_info", {}).get("editable"):
        return None
    url = direct_url.get("url", "")
    if not url.startswith("file://"):  # pragma: no cover — non-local editable
        return None
    return Path(unquote(urlparse(url).path))


def version() -> None:
    """Print the yertle version, and flag when running from a source checkout.

    The suffix is the difference between "I'm testing my changes" and "I'm
    running the release I installed months ago" — worth stating outright,
    since the two are otherwise indistinguishable at the prompt.
    """
    checkout = _source_checkout()
    if checkout is None:
        typer.echo(__version__)
    else:
        typer.echo(f"{__version__} (editable: {display_path(checkout)})")
