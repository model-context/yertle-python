# yertle-python — working notes for agents

The published `yertle` PyPI package: SDK facade, `yertle` CLI, `yertle-sre`
agent, and `yertle-mcp` server, all in one distribution with optional extras.

This file records the conventions and invariants that the code cannot tell you
on its own. Read it before making changes; the rest you can learn from the
source, which is small (~1,200 lines) and heavily commented on purpose.

## The one command that matters

```bash
make check     # lint + format-check + typecheck + test — exactly what CI runs
```

If `make check` passes locally, CI passes. Run it before you claim a change is
done. `make install` first if the venv is cold.

## Architectural invariants

These are enforced by `tests/test_invariants.py`. Don't work around the test —
if an invariant genuinely needs to change, change it deliberately and say why.

1. **`shared/auth.py` is the only place credentials are resolved.** Nothing else
   reads `$YERTLE_TOKEN`, `$YERTLE_API_URL`, or `~/.yertle/config.json`. The SDK,
   CLI, and MCP server all go through it. The precedence chain is per-key and is
   documented in `resolve()` — that docstring is the spec.
2. **All subprocess execution goes through `sre/tools/_shell.py::run_cli`.** No
   direct `subprocess` calls elsewhere, never `shell=True`, no string
   interpolation into a command. `run_cli` is where the timeout, output
   truncation, and uniform `ShellResult` shape live.
3. **The SRE agent's tools are read-only.** `settings.allow_writes` exists but no
   mutating tool ships. Adding one is a product decision, not a refactor.
4. **CLI commands call the SDK, not the generated wire layer.** Nothing under
   `cli/` imports `yertle_client.api.*`; it goes through `yertle.orgs`,
   `yertle.nodes`, and so on. One implementation per endpoint, shared with
   library users.
5. **The MCP server is read-only by construction** — the `RouteMap` filter in
   `mcp/server.py` mounts GET operations and excludes everything else. Keep the
   catch-all `EXCLUDE` route last.

## Conventions

- **Comments explain *why*, not *what*.** The existing comments record decisions
  and the bugs that motivated them (see `__init__.py` on reading the version from
  distribution metadata, or `shared/auth.py` on the 0600 file mode). Match that
  register. Don't add comments that restate the line below them.
- **Public API is deliberate.** `__all__` is maintained in every module that has
  a public surface. Adding a name to the package's public API means someone
  outside this repo can depend on it — do it on purpose, not incidentally.
- **New SDK resources are modules, not classes.** `orgs.py` is the template: a
  module of plain functions, imported as `yertle.orgs`, unwrapping the generated
  `yertle_client` wire types into something ergonomic. `nodes`, `branches`, etc.
  follow the same shape.
- **New SRE tools are one function + a registry entry.** Implement with `@tool`
  in `sre/tools/`, add it to `ALL_TOOLS` in `sre/tools/__init__.py`. That is the
  whole extension surface. Translate non-zero exits into short model-readable
  messages; never dump raw stderr at the model.
- **New CLI commands are a module per noun group.** One file in
  `cli/commands/`, wired up in `cli/main.py` — a `typer.Typer` named `app` for
  a noun with verbs (`orgs list`, `orgs show`), a plain function for a bare
  command (`version`). Commands are noun-then-verb like `gh` and the AWS CLI; a
  bare noun prints help, never a default action. Declare columns and call
  `_render.render()` rather than building tables inline, and wrap API calls in
  `_errors.api_errors()` rather than writing your own try/except. `main.py` is
  a composition root — no command logic belongs in it.
- **The CLI calls the SDK, never `yertle_client` directly.** Both can reach the
  same endpoint; using the wire layer gives that endpoint two implementations
  that drift in error handling and unwrapping. Routing through `yertle.orgs`,
  `yertle.nodes`, … also means each new command ships the SDK function it
  needs, instead of the two surfaces being built twice. Enforced by
  `test_cli_calls_the_sdk_not_the_wire_layer`. Wire *types*
  (`yertle_client.models`, `.errors`) stay fine to import.
- **Errors reaching a user are sentences, not tracebacks.** `AuthError`'s message
  *is* the user-facing text. The CLI catches `UnexpectedStatus` and renders a
  URL-aware explanation. Preserve that when touching error paths.
- **`yertle_client` is the generated wire layer** and lives in the backend repo.
  It is never hand-edited here; if an endpoint is missing, it is regenerated
  upstream.

## Dependencies

Do not add a runtime dependency without asking. The base install is deliberately
thin — `yertle` alone pulls in only `yertle-client`, and everything heavier
(typer, rich, langchain, fastmcp) sits behind an extra. A new import in
`src/yertle/` that isn't in the base dependency list breaks the plain
`pip install yertle` case.

`pyproject.toml` and `.github/workflows/` are review-gated. Propose changes;
don't land them as a side effect of another task.

## Testing

- Every new module gets tests. Coverage on changed lines is gated in CI at 80%
  (`make coverage` locally to see where you stand).
- Tests may reach into module-private helpers — that loosening is configured
  per-directory in the pyright block and is intentional.
- Prefer testing observable behavior through the public surface; drop to private
  helpers only for edge cases the surface can't reach.

## Quality gates beyond `make check`

CI also runs an advisory hygiene job (`make hygiene`) that reports code
duplication and dead code. It does not block merges today, but a PR that moves
either number in the wrong direction should explain why. Duplication is the
failure mode to watch: the temptation is to add a near-copy of an existing
helper rather than extend it.
