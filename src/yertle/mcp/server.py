"""Read-only MCP server for the Yertle API.

Spike: mounts every GET endpoint from the backend's live OpenAPI spec as
an MCP tool via `FastMCP.from_openapi(...)`. Authenticates by forwarding
the user's Personal Access Token (`YERTLE_TOKEN`) as a Bearer header.

No hand-written tools, no response transforms, no push wrapper — those
are the next layer once this spike validates the auto-mount path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

# TODO(consolidation): when the SDK MVP lands, move this resolution into
# `yertle.shared.auth` and have both `yertle.cli.auth.get_client()` and
# this module import from there. Inlined here to keep the spike tiny.
_CONFIG_PATH = Path.home() / ".yertle" / "config.json"
_DEFAULT_API_URL = "https://api.yertle.com"


def _resolve_credentials() -> tuple[str, str]:
    """Return (token, api_url) using the same precedence as `yertle.cli.auth`.

    Token: $YERTLE_TOKEN > config file > exit 1.
    URL:   $YERTLE_API_URL > config file > default prod URL.
    """
    cfg: dict[str, str] = {}
    if _CONFIG_PATH.exists():
        cfg = json.loads(_CONFIG_PATH.read_text())

    token = os.environ.get("YERTLE_TOKEN") or cfg.get("token")
    if not token:
        sys.exit("yertle-mcp: no credentials found. Run `yertle login` or set $YERTLE_TOKEN.")

    api_url = os.environ.get("YERTLE_API_URL") or cfg.get("api_url") or _DEFAULT_API_URL
    return token, api_url


def build_server() -> FastMCP:
    """Construct the FastMCP server from the live backend OpenAPI spec.

    Filters to GET-only operations so the mounted surface is read-only by
    construction — any mutating endpoint is excluded before it can be
    called. The hand-written `push_node_state` merge wrapper from the
    old yertle-mcp will return as an explicit tool in a follow-up.
    """
    token, api_url = _resolve_credentials()

    spec = httpx.get(f"{api_url}/openapi.json", timeout=10).json()

    client = httpx.AsyncClient(
        base_url=api_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    return FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="yertle",
        route_maps=[
            RouteMap(methods=["GET"], mcp_type=MCPType.TOOL),
            RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
        ],
    )


def main() -> None:
    """Console-script entry point. Runs the server on stdio."""
    server = build_server()
    server.run()  # transport="stdio" by default


if __name__ == "__main__":
    main()
