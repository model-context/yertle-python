# CLI write commands — game plan

Status: plan, not yet built. Written 2026-09-22.

The CLI is read-only today. The goal is parity with the web app: anything you
can do there, you can do from the terminal. **The primary user is an agent**,
the way `gh` and the `aws` CLI are primarily driven by agents and scripts, so
the shape of every command is judged by "can a model use this correctly from
`--help` alone" before "is this pleasant to type".

Everything below marked *verified* was checked against the running backend or
the generated wire client on 2026-09-22, not inferred from docs.

## What the backend actually offers

*Verified against `yertle_client/api/` and `backend/src/api/routes/nodes.py`.*

Two kinds of write endpoint, and the difference drives the whole plan.

### Simple request/response

| Operation | Endpoint | Body |
|---|---|---|
| Create node | `POST /orgs/{org}/nodes` | `title` (required), `description`, `tags`, `directories`, `public_id`, `commit_message` |
| Delete node | `DELETE /orgs/{org}/nodes/{id}` | — |
| Create branch | `POST /orgs/{org}/nodes/{id}/branches` | `name` (required), `base_branch` (default `main`) |
| Delete branch | `DELETE /.../branches/{name}` | — |
| Create PR | `POST /.../pull_requests` | `source_branch`, `title` (required), `target_branch` (default `main`), `description`, `is_draft` |
| Merge / close PR | `POST /.../pull_requests/{n}/merge` `/close` | — |

Flat, few fields, no shared state. These map onto flags one-to-one.

Tags accept either form on input — `{"team": "backend"}` or
`{"team": {"value": "backend", "link": "..."}}`. `node_service.py` normalizes a
bare string into `{"value": ...}`. Output is always the nested form.

### Full-state push — everything else

    PUT /orgs/{org}/nodes/{parent}/tree/{branch}/push

Three properties make this a different kind of operation:

1. **`state` is the complete desired state, not a patch.** The route docstring
   says so: *"clients send the complete desired state, and the server handles
   diffing and object reuse automatically."* Omitted keys are **deleted**. The
   integration test carries the warning in its own payload comments —
   `# Keep same title`, `# Keep same tags`, `# Keep same directories`
   (`test_04_attach_child_node_branch.py`).
2. **`expected_head_commit` is required** (`requests.py`, Pydantic `...`) and
   enforced in `node_service.py` — a mismatch raises `ConflictError` (409).
   Every push must first read the branch head.
3. **Attachment is a canvas record, not an edge.** A child appears in the
   parent's `visual_properties` as
   `{child_node_id, position_x, position_y, z_index, width, height, rotation, transparency}`,
   with a large fixed-point coordinate space (the test uses `250000`).

So one push is: read head commit -> read complete state -> splice -> write the
whole thing back, with optimistic concurrency.

## The correction: "edit a node" is not an easy command

**There is no node update endpoint.** The full set of node operations is:

    create · delete · list · list-all · get-complete · get-canvas
    get-branch-head · push

*Verified* — that is every file in `yertle_client/api/nodes/`. No `PATCH`, no
`PUT /nodes/{id}`.

Changing a node's title, description, tags or directories therefore goes
through `push`, exactly like attaching a child. Edit and attach are not two
problems of different difficulty; they are **the same problem wearing two
hats**, along with connections and layout.

This matters for sequencing. The intuition "build the easy commands first and
the attach design will become obvious" only pays off if the easy commands
exercise the same machinery — and they do not. `nodes create`, `branches
create` and `prs create` touch none of the state, diffing, or concurrency
code. Building all of them teaches us nothing about `push`.

That is not an argument against building them. They are needed regardless, they
are genuinely low-risk, and they establish the conventions every later command
inherits. It is only an argument against expecting an answer to fall out of
them.

## We already know the shape of the answer

The ideal workflow, as stated: *create all the nodes, then in a single commit
attach all the children to the parent with the desired connections, properly
spaced.*

That is a description of one `push` call. The full-state replace that makes
attaching a single child awkward is exactly what makes attaching twenty
children natural — one request, one commit, children and connections and
layout together, no interleaving and no read-modify-write race.

The API is built for the batch case. It is the one-at-a-time verb that fights
it. So the design question is not "how do we attach one child safely" but
"what is the smallest declarative surface that covers a whole subtree" — with
single-child attach as a convenience on top, not the primitive underneath.

## Phases

### Phase 1 — the simple writes

- `yertle nodes create <title>` with `--description`, `--tag key=value`
  (repeatable, matching `nodes search`), `--dir`, `--public-id`, `--message`
- `yertle nodes delete <id>` with a confirmation prompt and `--yes` to skip it
- `yertle branches create <name>` / `list` / `delete`, node-scoped
- `yertle prs create` / `list` / `show` / `merge` / `close`

No state machinery, no concurrency. Establishes the conventions in
*Principles* below and gets the CLI writing at all.

**Known wart to design around:** a created node is an orphan. After two
creates, `test_04` asserts `visual_properties_main: 0` — nothing is attached to
anything. The node shows up in `nodes list` but hangs off nothing in `nodes
tree`. An agent's first attempt will produce an invisible node, and the fix
requires understanding branches, head commits and full-state pushes.

A `--parent <id>` flag on `create` that does create-then-attach is the single
highest-value ergonomic decision available, but it needs Phase 2's machinery.
It is listed here so Phase 1's `create` is designed to grow the flag rather
than be rewritten for it.

### Phase 2 — one honest push layer

One SDK primitive, in `yertle.nodes`, that owns the whole sequence: read head,
read complete state, apply a caller-supplied change, push, retry once on 409.
Everything state-shaped is built on it — edit, attach, connect, lay out.

The failure mode to design against is specific and severe: **a push that sends
only the fields it means to change silently deletes the parent's tags and
directories.** It returns 200 and a commit id while doing it. That is the
failure shape `CLAUDE.md` names — something standing in for the real thing and
reporting success — and it would ship green. Whatever the implementation, a
test that asserts tags and directories survive an unrelated change is
mandatory, and should be written before the feature.

### Phase 3 — declarative subtree authoring

    yertle apply -f diagram.json

The whole desired state of a subtree in one document: nodes, containment,
connections, positions. Maps 1:1 onto `push` with no translation layer, and is
the shape a model is best at — emit one document rather than orchestrate
twenty calls that can each fail halfway.

Open: whether `apply` creates missing nodes or requires them to exist first.
Creating them makes the document self-contained (the stated ideal workflow in
one command) but means `apply` spans both endpoint families and has to reason
about partial failure.

## Principles for agent-facing commands

- **Flags, not a wizard.** An interactive prompt is unusable by the primary
  user and makes the command unscriptable. `--help` is the tool schema.
- **Flags, not a JSON blob**, for the simple writes. A blob yields a Pydantic
  validation dump instead of "missing `--title`", and puts the schema where
  the CLI cannot check it. Phase 3's `apply` is the deliberate exception: a
  whole subtree is genuinely a document.
- **Every mutating command prints the resulting id and supports
  `--format json`**, so one command's output feeds the next.
- **`--dry-run` shows the diff before pushing.** This matters far more than
  usual when the API's native mode is full-state replace.
- **Idempotence where it is cheap.** Attaching an already-attached child is a
  no-op success, not a duplicate.
- **Conflicts are a distinct, explainable failure.** A 409 means the branch
  moved; say that, and say to retry.

## Guardrails

- `YERTLE_READ_COMMANDS` in the SRE agent allowlists **(noun, verb) pairs**
  precisely so a write verb cannot enter under a read noun. No command from
  this roadmap goes in it. Enforced by
  `test_allowlist_admits_no_write_commands`.
- The MCP server is read-only by construction — the `RouteMap` filter mounts
  GET operations only — so these commands cannot leak into it. Keep it that
  way.

## Related

- `docs/todo/todo.txt` item 1 — `--format json` is not 1:1 with the backend
  response. Worth settling before write commands make round-tripping
  (read a state, edit it, push it back) a normal thing to do.
- `docs/todo/todo.txt` item 2 — identifiers are raw UUIDs. Every command here
  takes at least one id, and most take two.
