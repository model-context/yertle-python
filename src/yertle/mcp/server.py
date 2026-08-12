"""Read-only MCP server for the Yertle API.

Spike: mounts every GET endpoint from the backend's live OpenAPI spec as
an MCP tool via `FastMCP.from_openapi(...)`. Authenticates by forwarding
the user's Personal Access Token (`YERTLE_TOKEN`) as a Bearer header.

No hand-written tools, no response transforms, no push wrapper — those
are the next layer once this spike validates the auto-mount path.
"""

from __future__ import annotations

import sys

import httpx
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

from yertle.shared.auth import AuthError, resolve_credentials


def build_server() -> FastMCP:
    """Construct the FastMCP server from the live backend OpenAPI spec.

    Filters to GET-only operations so the mounted surface is read-only by
    construction — any mutating endpoint is excluded before it can be
    called. The hand-written `push_node_state` merge wrapper from the
    old yertle-mcp will return as an explicit tool in a follow-up.
    """
    token, api_url = resolve_credentials()

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
    """Console-script entry point. Runs the server on stdio.

    Catches `AuthError` so the console-script case still exits with a clean
    user-facing message (matching the previous `sys.exit(...)` behavior),
    not a stack trace.
    """
    try:
        server = build_server()
    except AuthError as e:
        sys.exit(f"yertle-mcp: {e}")
    server.run()  # transport="stdio" by default


if __name__ == "__main__":
    main()
