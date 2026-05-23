"""yertle-mcp — MCP server exposing the Yertle API to LLM hosts.

Extras-guard at the package root so any import path — console script,
`python -m yertle.mcp`, or `from yertle import mcp` — hits it before
Python tries to import fastmcp.
"""

try:
    import fastmcp  # noqa: F401  # pyright: ignore[reportUnusedImport, reportMissingImports]
except ImportError:
    import sys

    sys.exit("yertle-mcp requires the [mcp] extra. Install with: pip install 'yertle[mcp]'")
