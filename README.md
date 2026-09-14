# yertle-python

Python ecosystem for [Yertle](https://yertle.com) — CLI, SDK, and tooling for
working with Yertle architecture graphs from Python.

## Install

The CLI and SRE agent are distributed on PyPI and installed with
[`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install "yertle[sre,mcp]"
```

That puts three commands on your PATH:

| Command | What it does |
|---|---|
| `yertle` | CLI — `about`, `version`, `login`, `orgs list`, `orgs show`, `orgs use`, `nodes list`, `nodes tree`, `nodes show`, `nodes search`, `auth status` |
| `yertle-sre` | Natural-language SRE agent |
| `yertle-mcp` | MCP server for AI agents |

All three commands land on your PATH regardless of which extras you pick —
Python entry points are not conditional on extras. Installing a subset, say
`uv tool install "yertle[cli]"`, still creates `yertle-sre` and `yertle-mcp`;
running one tells you which extra it needs rather than failing obscurely:

```
$ yertle-mcp
yertle-mcp requires the [mcp] extra. Install with: pip install 'yertle[mcp]'
```

So install the extras you want to *use*, not the ones you want to see.
`pipx install "yertle[sre,mcp]"` works too.

To upgrade later, `uv tool upgrade yertle`. That only works if you installed
without pinning a version — `uv tool install "yertle[sre,mcp]==0.3.0"` records
the pin as the requirement, and upgrades then have nothing to move to.
Reinstall with `uv tool install --force "yertle[sre,mcp]"` to unpin.

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
