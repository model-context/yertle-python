# yertle.mcp — the MCP server

> **Status:** spike landed 2026-05-23 in [PR #7](https://github.com/model-context/yertle-python/pull/7). Read-only auto-mount of the backend OpenAPI spec is proven; this doc captures how it works and what's next.

## What this is

A Model Context Protocol server that exposes the Yertle API to MCP-compatible LLM hosts (Claude Desktop, Cursor, Continue, mcp-cli, etc.). When a user adds `yertle-mcp` to their host's config, the LLM can call Yertle endpoints as tools and the host streams the responses back into the conversation.

The new server is **one file, ~50 lines of real code**. It does that by leaning on `FastMCP.from_openapi(...)` instead of hand-writing one tool per endpoint.

## How the new approach works

```
┌────────────────┐    stdio     ┌────────────────────┐    https     ┌────────────┐
│  Claude / IDE  │ ◀──────────▶ │  yertle-mcp        │ ◀──────────▶ │  yertle    │
│  (MCP host)    │              │  (FastMCP server)  │              │  backend   │
└────────────────┘              └────────────────────┘              └────────────┘
                                          ▲
                                          │  fetches /openapi.json
                                          │  at startup
                                          ▼
                                ┌────────────────────┐
                                │ FastAPI OpenAPI    │
                                │ spec (88 routes)   │
                                └────────────────────┘
```

At startup, `yertle.mcp.server:build_server()`:

1. Resolves a PAT and API URL the same way the CLI does (`$YERTLE_TOKEN` env > `~/.yertle/config.json` > error).
2. `GET`s `/openapi.json` from the resolved API URL.
3. Constructs an `httpx.AsyncClient` with `Authorization: Bearer {token}` baked in.
4. Calls `FastMCP.from_openapi(spec, client=..., route_maps=[GETs→TOOL, ".*"→EXCLUDE])`.
5. `server.run()` over stdio.

**Read-only by construction.** The `route_maps` filter excludes every non-GET operation before it ever becomes an MCP tool. Mutating endpoints aren't dropped at call time — they don't exist on the server. When we want to expose mutating operations, we'll do it with explicit hand-written tools that wrap the underlying API call with our own validation (see ["Hand-written mutating tools"](#hand-written-mutating-tools-future) below).

**No code per endpoint.** The old `yertle-mcp` repo had one hand-written httpx wrapper per endpoint in `client/api.py` (plus a custom `FlowClient` with auth/retry logic). All of that goes away — the spec is the source of truth, and FastMCP generates the tool surface from it.

**Auth simplifies dramatically.** The old MCP server validated Cognito JWTs in the Lambda before forwarding to the backend (extra IAM, extra config, extra failure modes). The new server is dumb middleware — it forwards whatever Bearer token the user configured straight to the backend, which has a single validator that accepts both PATs (`yrt_*`) and JWTs as of Slice 2.

### Why FastMCP over alternatives

We considered four shapes:

| Approach | Verdict |
|---|---|
| Official `mcp` SDK with `@mcp.tool` decorators | Maximum control, maximum hand-written code. What the old `yertle-mcp` does indirectly. Wrong shape when the spec already describes everything. |
| **FastMCP + `from_openapi()`** | Auto-mounts the spec, lets us add hand-written tools alongside for the cases that need validation. **Chosen.** |
| Generic `mcp-server-openapi` / `mcp-openapi-proxy` | Zero code, but no escape hatch for hand-written tools. Wrong shape long-term because we need the push wrapper. |
| Hand-rolled stdio JSON-RPC | Educational only. Nobody ships this in 2026. |

The industry has converged on the FastMCP shape. The Anthropic-published `mcp.server.fastmcp` is the same library; `fastmcp` standalone tracks slightly ahead.

## Sanity check: why hybrid, not port-as-is

A reasonable instinct when looking at the spike is: "if we're going to hand-write some tools anyway, why not just lift `yertle-mcp` over wholesale and skip the FastMCP layer?" The answer is that the two approaches are solving different problems on different halves of the surface, and the hybrid wins both halves. Capturing the math here so we don't second-guess the call later.

### What the old `yertle-mcp` actually exposes

Counting today's surface in `model-context/yertle-mcp`:

- **4 read resources**: `flow://orgs`, `flow://orgs/{org_id}/nodes`, `…/complete`, `…/canvas`
- **2 read tools**: `search_nodes`, `list_branches`
- **5 mutating tools**: `create_organization`, `create_node`, `push_node_state`, `delete_node`, `create_branch`

That's **6 read endpoints** total — a tiny fraction of the 50 GETs the backend actually serves. Every one is a hand-written httpx wrapper in `client/api.py`, plus a hand-maintained registration in `tools/` or `resources/`. New endpoints don't appear unless someone writes the wrapper.

### What the spike replaces, and what it doesn't

The hybrid splits the surface cleanly:

| Surface | Old `yertle-mcp` | Spike + planned follow-ups |
|---|---|---|
| **50 read GET endpoints** | 6 hand-written | All 50 auto-mounted from spec; new ones appear automatically on next backend deploy |
| **~5 mutating ops where validation matters** | 5 hand-written (incl. `push.py` merge wrapper) | 5 hand-written, ported verbatim from `push.py` and `transform.py` |
| **Wire-layer HTTP boilerplate** | ~200 LOC in `client/api.py` + `flow_client.py` (auth, retry, JWT refresh, one fn per endpoint) | 0 LOC — `yertle-client` + FastMCP cover it |
| **Auth** | Hand-coded JWT validation in the Lambda + email/password sign-in in MCP itself | Forward the user's PAT as a Bearer header; let the backend validate |

### What to delete from old `yertle-mcp`

Confirmed deletions when the new MCP takes over:

- **`client/api.py`** (~one function per endpoint, all httpx wrappers) — replaced by FastMCP's auto-mount over `yertle-client`.
- **`flow_client.py`** (auth, retry, `_with_retry`, `_handle_response`, JWT refresh) — replaced by PAT auth forwarded through a bare `httpx.AsyncClient` plus the backend's existing middleware.
- **The email/password sign-in flow** (`FLOW_USER_EMAIL` / `FLOW_USER_PASSWORD` env vars) — replaced by `YERTLE_TOKEN` (PAT). No more password-in-env smell.
- **The Cognito JWT validation** in the deployed Lambda (`COGNITO_USER_POOL_ID` / `COGNITO_APP_CLIENT_ID` / `COGNITO_DOMAIN`) — same reason; auth is now PAT-uniform across all clients.

Estimate: 60–70% LOC reduction vs the old repo, concentrated in the wire layer.

### What to keep and port

Lifted verbatim from `model-context/yertle-mcp/client/` into `src/yertle/mcp/`:

- **`client/push.py`** — fetch current snapshot, merge partial update by `child_node_id` / connection `id`, validate required fields (visual properties must include `child_node_id`; connections must include `id`, `from_child_id`, `to_child_id`), apply defaults, push full snapshot. **This is the actual value-add of the old repo.** Cannot be autogenerated; the merge step is what stops an LLM from wiping a node's state with a partial update.
- **`client/transform.py`** — reshapes backend responses into LLM-friendly output where the raw OpenAPI shape is awkward. Apply selectively per endpoint via FastMCP's `mcp_component_fn`.
- **The layout-policy instruction block** from `app.py` — "diagrams flow left-to-right, `position_x` increases right, `position_y` increases down, default node size 200×100, horizontal spacing 250, vertical 130, stay compact, don't resend visual properties for existing nodes unless the user wants a rearrangement." Pure prompt engineering that already works. Wire into FastMCP's server-level instructions.

### Goalposts: when do we know the hybrid was the right call?

Decision-quality checks for after the rewrite lands and runs in real use for a few weeks:

1. **Auto-mounted read coverage is being used.** If logs show the LLM only ever calls 3–5 of the 50 mounted tools, the surface-reduction work paid off and the auto-mount didn't earn its keep on coverage. If 15+ get called, the auto-mount is paying for itself.
2. **No safety incidents on mutating ops.** Zero cases of "the LLM called `push_node_state` and lost data" — the merge wrapper is doing its job.
3. **Description-override volume stays bounded.** If we end up overriding descriptions for 40+ of 50 tools, we've effectively migrated the source-of-truth out of the OpenAPI spec and into MCP-layer code; reconsider whether keeping FastAPI docstrings as the canonical source is still right.
4. **New backend endpoints show up "for free"** in MCP without a yertle-python release. That's the auto-mount's marquee feature; if we end up adding hand-written wrappers for every new endpoint anyway (because LLM descriptions or filtering need work), we've lost the main benefit.

If two or more of these fail in real use, revisit. Until then, the hybrid is the chosen shape.

### What we'd give up by porting yertle-mcp as-is

For symmetry:

- **Regression in read coverage** from 50 → 6 tools. The LLM loses access to commits, history, diffs, pull requests, hierarchy traversal, etc.
- **All future backend endpoint additions become hand-write work** in MCP. Spec drift returns immediately.
- **The password-in-env auth smell stays** unless we separately rip it out.
- **No PAT alignment with the rest of the platform** — the MCP keeps its own bespoke auth shape forever.

The savings would be: ~50 lines less of `server.py` (no FastMCP integration). Not worth the trade.

## Next steps

These are the three immediate follow-ups in priority order:

### 1. End-to-end smoke against Claude Desktop with a real PAT

Issue a token in the web UI, then add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yertle": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/model-context/yertle-python.git@mcp-spike", "yertle-mcp"],
      "env": {
        "YERTLE_TOKEN": "yrt_...",
        "YERTLE_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

Restart Claude Desktop. Ask "what orgs do I have in yertle?" Confirm a tool call fires and the answer is grounded in real data. This is the actual proof the loop works end-to-end — the spike's in-process `call_tool` tests proved auth + routing but not the host-side discovery and invocation path.

### 2. File the backend bug surfaced during the spike

The 401 path runs JWT validation **before** PAT validation, and the JWT validator crashes on non-JWT input. Pass `Authorization: Bearer not-a-real-token` to any authenticated endpoint and the 401 body leaks `"module 'jose.jwt' has no attribute 'InvalidTokenError'"`. The PAT validator never gets a chance to reject cleanly.

Fix: check the `yrt_` prefix and route to the PAT validator first. Add as a new entry in `yertle/docs/notes/features/yertle-python/BACKEND_FOLLOWUPS.md`.

### 3. Pick the next slice for `yertle-python`

After the MCP spike, three things are queued. In rough priority order:

- **SDK MVP.** ~15 lines: re-export `list_orgs` (and a couple others) from `yertle/__init__.py` with a lazy default-client singleton, so `import yertle; yertle.list_orgs()` works. Completes the four-skeleton goal (CLI / SRE / MCP / SDK) the original consolidation plan called for.
- **Port the push wrapper.** Lift `yertle-mcp/client/push.py`'s merge-on-push safety logic onto the spike. Required before the new MCP is feature-equivalent with the old one. See ["Hand-written mutating tools"](#hand-written-mutating-tools-future).
- **Tool-name cleanup.** 8/50 tool names have noise like `_orgs_get` appended by FastMCP's default naming. One `mcp_component_fn` callback fixes all of them. Cosmetic but visible.

## Improving the server: better context, fewer APIs exposed

The spike mounts every GET endpoint indiscriminately — 50 tools out of the box, many of which an LLM probably shouldn't see or doesn't have enough context to use well. Two complementary directions for improvement:

### Reduce the surface

50 tools is more than the LLM should be considering for most questions. Three filters worth exploring:

- **Tag-based filtering.** FastAPI lets you tag routes (`@router.get("...", tags=["public"])`). We could add an `[mcp]` tag to the routes worth exposing and have the route_map include only those. The backend opts routes *in* rather than the MCP server opting routes *out*, which keeps the policy in the same place as the API definition.
- **Drop the trivially-redundant.** `liveness_check_health_live_get`, `readiness_check_health_ready_get`, `root` — useful for monitoring, useless to an LLM. Allowlist or denylist.
- **Drop the dangerous-without-context.** Endpoints like `get_install_state_github_install_state_get` generate signed tokens for OAuth flows; an LLM should never call them. These are GET-by-shape but mutating-by-effect (issue a token, change app state).

Target: cut from ~50 to ~15–20 tools that meaningfully help an LLM answer "what's in my Yertle?"

### Improve the descriptions

FastAPI route docstrings come through to the LLM as tool descriptions. Right now they're written for human API consumers ("Get the containment hierarchy for an organization"). For an LLM agent, what helps is:

- **What the tool answers.** "Use when the user asks about parent/child relationships, what's inside an org, or the org's structure."
- **Which other tool to call instead.** "For all orgs at once, prefer `get_all_orgs_hierarchy`. For a single specific org, use this one."
- **Realistic input shape.** "`org_id` is a UUID — get it from `list_organizations` first."
- **What the response looks like.** Even one-line shape hints save the LLM round-trips.

Two options for getting better descriptions:

1. **Edit the backend FastAPI docstrings** so they double as LLM context. Best long-term; the spec stays canonical. Cost: every route's docstring needs a rewrite.
2. **Override descriptions in the MCP layer** via FastMCP's `mcp_component_fn` callback. Quick to iterate without backend deploys. Cost: the descriptions live in two places and can drift.

Recommend option 2 for the first pass (fast feedback while learning what works), then option 1 for the keepers once descriptions stabilize.

### Add hand-written mutating tools (future)

The old `yertle-mcp` repo's main value-add is `client/push.py` — fetch current snapshot → merge partial update by `child_node_id` / connection `id` → validate required fields → apply defaults → push full snapshot. That logic stops an LLM from accidentally wiping a node's state by sending an incomplete update. It cannot be autogenerated; the merge step is the safety feature.

Plan: alongside the FastMCP auto-mount, register a small set (~3–5) of hand-written `@mcp.tool` functions for mutating operations where validation matters. `push_node_state`, `create_node`, `create_branch`. Each one wraps the underlying `yertle-client` call with the merge/validate/default logic. The auto-mount filter still excludes the raw API equivalents, so the LLM only sees the safe wrapper, not both.

### Layout-policy prompt instructions

The old `yertle-mcp` includes a block of "how to lay out diagrams" guidance in its server instructions (left-to-right flow, 200×100 default node size, 250/130 spacing, "don't re-send visual properties for existing nodes unless the user wants a rearrangement"). FastMCP supports server-level instructions; port this verbatim alongside the push wrapper. It's prompt engineering that already works — no reason to redesign it.

## Sunset and deployment changes

Three things need to change downstream as the new MCP matures. None block the spike merging.

### Deployment pipeline: cut over the Lambda

Today, `yertle/deployment/dev.yaml` and `yertle/deployment/infrastructure/backend/mcp-lambda.yml` build a zip from `../yertle-mcp/` and deploy it as a Cognito-authed Lambda behind API Gateway. To cut over:

- **Source location.** `source_dir: ../yertle-mcp` → `source_dir: ../yertle-python`. The build script's existing `*/src` branch in `build-versioned-package.sh` already handles the `src/yertle/mcp/` layout, so the change is small.
- **Lambda handler.** Add `src/yertle/mcp/lambda_handler.py` that wraps FastMCP's ASGI/HTTP app for Lambda's event shape — Mangum or AWS Lambda Web Adapter is the standard one-liner.
- **CloudFormation env vars.** Drop the Cognito-specific parameters (`CognitoUserPoolId`, `OAuthClientId`, `CognitoDomain`). The new server doesn't validate JWTs locally — it forwards whatever Bearer token arrives to the backend and lets the backend's middleware decide. The CFN template gets shorter, not longer.
- **Transport.** Today's Lambda likely serves HTTP+SSE. Stdio (what the spike runs) is for local subprocess hosts; the Lambda needs `streamable-http` transport — same FastMCP server, different `mcp.run()` arg.

**The bigger strategic question:** do we still want a remote-Lambda MCP at all? The MCP ecosystem in 2026 increasingly distributes servers as `uvx`/`pipx`-installable packages that the user's host launches as a local subprocess (the pattern the spike demonstrates). The Lambda made sense pre-PAT when centralized Cognito validation was the only auth story. Now that PATs work everywhere, the case for keeping the Lambda is multi-tenant or no-install hosted use ("point Claude at `https://mcp.yertle.com` without installing anything"). The case for dropping it is operational simplicity — nobody is using it that way yet. Worth deciding before we invest in the cutover.

### Sunset the standalone `yertle-mcp` repo

Once the new MCP is feature-equivalent (push wrapper + transforms ported, tool descriptions cleaned up):

1. Tag the final `model-context/yertle-mcp` commit so the historical version is permanently fetchable.
2. Update `model-context/yertle-mcp`'s README to point at `yertle-python`'s `yertle.mcp` subpackage and `pip install yertle[mcp]`.
3. Archive the repo (read-only mode).
4. Remove the `build_mcp_package` hook + `mcp-lambda.yml` from the backend repo if we also retire the Lambda; otherwise update them to source from `yertle-python`.

### Sunset the legacy Go `yertle-cli`

Tangential to MCP but worth mentioning since it's the parallel sunset on the consolidation roadmap. The Python `yertle-cli` rewrite lives in this repo (`yertle-python`); the original Go implementation is at `model-context/yertle-cli`. Slice 7 of the consolidation plan covers the cutover:

1. Tag the Go repo's final commit as `v0.x.x-go`.
2. Rename `model-context/yertle-cli` → `model-context/yertle-cli-old`.
3. The Python repo (currently `model-context/yertle-python`) takes over the `yertle-cli` name.
4. Update Homebrew tap to wrap the PyPI package instead of fetching GoReleaser binaries — `brew install yertle` keeps working with no user-facing change.
5. Archive `model-context/yertle-cli-old`.

That's blocked on finishing Slice 3 (full CLI command surface in Python) so the rename doesn't strand any commands users depend on. Independent of the MCP work.

## Reference

- Spike PR: [#7](https://github.com/model-context/yertle-python/pull/7)
- Source: `src/yertle/mcp/server.py`, `src/yertle/mcp/__init__.py`
- FastMCP docs: <https://gofastmcp.com>
- MCP spec: <https://modelcontextprotocol.io>
- Consolidation plan (the *why* of yertle-python): `yertle/docs/notes/features/yertle-python/CONSOLIDATE_CLIENTS_TO_PYTHON.md`
