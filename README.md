# yertle-python

Python ecosystem for [Yertle](https://yertle.com) — CLI, SDK, and tooling for
working with Yertle architecture graphs from Python.

> **Status:** under construction. Initial scaffolding only.

## Planned shape

A single PyPI package `yertle` with extras for different consumers:

```bash
pip install yertle              # SDK only (planned)
pip install yertle[cli]         # + `yertle` command
pip install yertle[sre]         # + `yertle-sre` agent (planned)
pip install yertle[mcp]         # + `yertle-mcp` MCP server (planned)
```

## Development

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
make install        # uv sync --extra cli --extra dev
make check          # lint + format-check + typecheck + test
```

See `make help` for the full target list.

## License

MIT. See [LICENSE](./LICENSE).
