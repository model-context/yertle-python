# yertle-python

Python ecosystem for [Yertle](https://yertle.com) — CLI, SDK, and tooling for
working with Yertle architecture graphs from Python.

## Install

The CLI is distributed on PyPI and installed with
[`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install yertle
```

That puts `yertle` on your PATH: `about`, `version`, `login`, `orgs list`,
`orgs show`, `orgs use`, `nodes list`, `nodes tree`, `nodes show`,
`nodes search`, `auth status`.

Two optional extras ship alongside it, neither needed for the CLI:

| Extra | What it adds |
|---|---|
| `yertle[sre]` | `yertle-sre`, a natural-language SRE agent (~37MB more) |
| `yertle[mcp]` | the MCP server — launched by MCP hosts, not installed by you |

The MCP server is deliberately **not** part of a tool install. MCP hosts launch
it themselves, so it never needs to sit on your PATH — point your host at
`uvx`, which resolves and runs it on demand:

```json
{
  "mcpServers": {
    "yertle": {
      "command": "uvx",
      "args": ["--from", "yertle[mcp]", "yertle-mcp"],
      "env": { "YERTLE_TOKEN": "yrt_..." }
    }
  }
}
```

Every command lands on your PATH regardless of which extras you pick — Python
entry points are not conditional on extras. So a plain `uv tool install yertle`
still creates `yertle-sre` and `yertle-mcp`. Running one tells you which extra
it needs rather than failing obscurely:

```
$ yertle-sre
yertle-sre requires the [sre] extra. Install with: pip install 'yertle[sre]'
```

So install the extras you want to *use*, not the ones you want to see.
`pipx install yertle` works too.

To upgrade later, `uv tool upgrade yertle`. That only works if you installed
without pinning a version — `uv tool install "yertle==0.3.0"` records
the pin as the requirement, and upgrades then have nothing to move to.
Reinstall with `uv tool install --force yertle` to unpin.

Verify:

```bash
yertle version
yertle auth status     # shows which API URL and token are in effect
```

### Using it as a library

For the SDK alone, install into your project rather than as a tool:

```bash
pip install yertle          # or: uv add yertle
```

```python
import yertle

yertle.configure(token="yrt_...")
for org in yertle.orgs.list():
    print(org.name)
```

Credentials resolve from `$YERTLE_TOKEN` then `~/.yertle/config.json`; the API
URL from `$YERTLE_API_URL`, then the config file, then `https://api.yertle.com`.
`yertle auth status` reports which source won for each.

## Development

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
make install        # uv sync --extra cli --extra dev
make check          # lint + format-check + typecheck + test
```

See `make help` for the full target list.

## License

MIT. See [LICENSE](./LICENSE).
