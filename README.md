# yertle-python

Python ecosystem for [Yertle](https://yertle.com) — CLI, SDK, and tooling for
working with Yertle architecture graphs from Python.

## Install

The CLI is distributed on PyPI and installed with
[`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install yertle
```

That puts `yertle` on your PATH:

| | |
|---|---|
| Find your way around | `orgs list`, `orgs show`, `orgs use`, `nodes list`, `nodes tree` |
| Inspect | `nodes show`, `nodes search`, `branches list`, `prs list`, `prs show` |
| Change things | `orgs create`, `orgs update`, `nodes create`, `nodes apply`, `nodes delete`, `branches create`, `branches delete` |
| Review | `prs create`, `prs merge`, `prs close` |
| Everything else | `about`, `version`, `login`, `auth status` |

Editing a node is a read-edit-write round trip, like `git`:

```bash
yertle nodes show <id> --format json > node.json
# ...edit node.json...
yertle nodes apply -f node.json -m "what changed"
```

A push replaces the node's whole state, so `apply` prints a diff every time,
refuses a change that removes anything unless you pass `--allow-deletes`, and
will not accept a document that was not produced by a read.

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

`uv tool install` gives you the **command**, not the library. It puts the
package in an isolated environment and links only the entry points onto your
PATH, so `import yertle` in a script will not find it:

```console
$ uv tool install yertle && yertle version
0.3.0
$ python -c "import yertle"
ModuleNotFoundError: No module named 'yertle'
```

That is how `uv tool` is meant to work, not a packaging mistake. To use the
SDK, install into the project that imports it:

```bash
uv add yertle               # or: pip install yertle
```

That direction gives you both — `import yertle` in your code, and the CLI via
`uv run yertle`. Installing as a tool as well is only worth it if you want
`yertle` available outside the project.

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
make install        # uv sync --extra sre --extra mcp --extra dev
make check          # lint + format-check + typecheck + test
```

See `make help` for the full target list.

## License

MIT. See [LICENSE](./LICENSE).
