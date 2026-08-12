"""Cross-cutting helpers used by `yertle.cli`, `yertle.mcp`, and the SDK facade.

Currently houses credential resolution (`yertle.shared.auth`). Additional
shared modules (e.g. `shared.api` for the SDK proto-facade, `shared.id_cache`
for the CLI's short-ID resolver) land here once they hit the same
"second real consumer" trigger.
"""
