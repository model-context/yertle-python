"""Command modules for the `yertle` CLI — one per noun group.

Adding a command: create a module here, then wire it up in `cli/main.py`.
That's the entire extension surface — there is no registry to update and no
base class to subclass.

Shape of a module:

- A noun with several verbs (`orgs list`, `orgs show`) exposes a
  `typer.Typer` named `app`, and `main.py` mounts it with `add_typer`.
- A bare command (`version`, `login`) exposes a plain function, and `main.py`
  registers it with `app.command()`.

Commands call the SDK (`yertle.orgs`, `yertle.nodes`, …), never
`yertle_client` directly — one implementation per endpoint, shared with
library users. `tests/test_invariants.py` enforces this.
"""
