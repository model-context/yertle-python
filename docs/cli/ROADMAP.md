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

Fix it in `create`'s **output**, not its signature: print the new id and the
exact next command to attach it. That costs nothing and distorts nothing.

### Rejected: a `--parent` flag on `create`

An earlier draft proposed `nodes create <title> --parent <id>`, doing
create-then-attach in one command. **Rejected**, because it is wrong for the
workflow we actually care about — an agent creating several children and
attaching them together.

Creating five children with `--parent P` produces:

- **Five commits on P's branch** instead of one, for what is conceptually a
  single change.
- **Five full read-modify-write cycles** over P's entire state, rather than
  one.
- **A 409 storm if the agent parallelizes.** Each push carries
  `expected_head_commit`, and each successful push invalidates the value the
  others are holding. Four of five fail. Agents parallelize independent-looking
  work by default, and five `create` calls look independent.
- **A layout that cannot be good.** Spacing children sensibly requires knowing
  how many there are. Placed one at a time, each call can only guess, and
  "properly spaced" is unreachable by construction.

The flag optimizes the single-node case at the cost of the batch case, and the
batch case is the normal one. Two commands (`create`, then `attach`) is one
mental model for both, instead of a shortcut whose failure mode is a
conflict storm.

### Phase 2 — one honest push layer

One SDK primitive, in `yertle.nodes`, that owns the whole sequence: read head,
read complete state, apply a caller-supplied change, push, retry once on 409.
Everything state-shaped is built on it — edit, attach, connect, lay out.

**Attach is variadic from day one.** Not a single-child verb that callers loop
over:

    yertle nodes attach <child> [<child>...] --to <parent>

One push, one commit, every child and its placement decided together. This is
the direct expression of the workflow — create the nodes, then attach them all
at once — and it is the reason the `--parent` flag above was rejected rather
than deferred. The single-child case is just the batch case with one argument,
so there is no second code path and no incremental-layout heuristic to invent.

Connections belong in the same call once they exist, for the same reason: they
are part of the one change being described, and splitting them out means a
second commit and a second chance to conflict.

The failure mode to design against is specific and severe: **a push that sends
only the fields it means to change silently deletes the parent's tags and
directories.** It returns 200 and a commit id while doing it. That is the
failure shape `CLAUDE.md` names — something standing in for the real thing and
reporting success — and it would ship green. Whatever the implementation, a
test that asserts tags and directories survive an unrelated change is
mandatory, and should be written before the feature.

### Phase 3 — declarative subtree authoring

    yertle nodes get <id> > diagram.json     # state, and its own base commit
    # ...edit...
    yertle apply -f diagram.json

The whole desired state of a subtree in one document: nodes, containment,
connections, positions. Maps 1:1 onto `push` with no translation layer, and is
the shape a model is best at — emit one document rather than orchestrate
twenty calls that can each fail halfway.

#### Why this is the target, and not just ergonomics

An MCP server can tell an agent "read the diagram before writing to it,"
because the instruction sits inches from the call. A CLI cannot match that.
`--help` is a real channel — it is how an agent learns any CLI, and why `gh`
and `aws` work well for them — and error messages are a better one still
(`git`'s `hint:` lines teach more than its documentation does). But all of it
is **advice an agent can skip**.

So do not rely on it. Make the unsafe thing impossible instead.

*Verified 2026-09-22:* `GET /complete` returns an undocumented top-level key,
present only in `additional_properties` and absent from the typed model:

    "_branch_context": {
      "branch": "main",
      "commit": "a64edca5-a874-4255-a22b-4066712d89ee",
      "loaded_from_branch": true
    }

**The same read that returns the state returns its base commit** — exactly
what `push` requires as `expected_head_commit`. That collapses the problem:

- `nodes get` emits a document that is precisely `apply`'s input format,
  carrying its own base commit.
- **`apply` refuses a document with no base commit**, with a message naming
  the read that produces one.

An agent cannot skip the read, because the read is the only way to obtain a
valid input. An instruction has been replaced with a precondition. Concurrency
falls out for free: a stale embedded commit is a specific, explainable 409
rather than a silent clobber.

This is `kubectl get -o yaml` -> edit -> `kubectl apply -f`, and it is why
that workflow is safe for agents with no tool description attached.

A verb-per-mutation surface cannot get here. `nodes attach --to P` must do a
hidden read, and a hidden read is a hidden merge policy the caller can neither
see nor reason about.

#### Hazards to settle before building

1. **The read is a superset of the write.** `push`'s `state` takes
   `node` / `tags` / `directories` / `visual_properties`. The read also returns
   `child_nodes`, `parent_nodes`, `ingress_connections`, `egress_connections`
   and `metadata` — all derived views. A round-trip must project down. What
   `push` does with the extra keys is **unknown**: `state_diff_service.
   compare_states` may create spurious objects. Test this against a scratch
   org before building on it. Assuming it is fine is exactly the
   fixture-written-from-memory trap.

2. **Every push re-pins every child.** `node_service.py`:

       if "ref" not in vp:
           vp["ref"] = {}
       vp["ref"]["snapshot_commit_id"] = str(child_branch.head_commit)

   Unconditional, from the child's *current* head. So a push that changes only
   the parent's title silently advances every child's pin, and the
   `?resolve_children=snapshot` view changes without anyone asking. **An apply
   that looks like a no-op is not semantically a no-op.** A dry run has to
   surface it, and the backend arguably should stop overwriting a `ref` the
   client supplied.

3. **Coordinates are unbounded floats.** Real data has
   `position_x: -129.664158033288`. The `250000` integers in
   `test_04_attach_child_node_branch.py` are that test's choice, not a fixed
   point scheme. Layout code should assume a free float plane.

#### Safety rails on `apply`

Four small mechanisms, each refusing for one specific reason, rather than one
blanket `--force`. A single catch-all flag ends up in an agent's template line
and then gates nothing.

| Mechanism | Guards against | On failure |
|---|---|---|
| Base commit in the document (`--expected-commit` overrides) | Concurrent modification | 409 — "branch moved, re-read" |
| Missing base commit | A fabricated document | Refuse, naming the read that produces one |
| Three-way diff | — | Always shown; `--dry-run` prints and exits 0 |
| `--allow-deletes` | Clobbering | Refuse, listing exactly what would be deleted |

**Concurrency and completeness are different problems.** `expected_head_commit`
only solves the first. An agent can fetch the head cheaply from
`/tree/{branch}/head` without ever reading the state, hand-write a document
containing only the children it cares about, and push it with a perfectly
valid commit id — deleting the parent's tags and directories on the way
through. The commit was current; the state was incomplete. So the commit check
cannot be the deletion gate, and the deletion gate cannot be the commit check.

**Derive intent, do not require proof of it.** Because the document carries a
base commit, `apply` can re-read the state at that commit and classify every
difference:

    in document, not in base  ->  addition
    in both, different        ->  modification
    in base, not in document  ->  deletion

That turns "did they read first?" from a matter of trust into arithmetic, and
the gate then goes on what the change *does* rather than on whether a ritual
was followed. It also makes for an honest error: "this would delete 3 tags and
1 child; pass --allow-deletes if you meant it" names a consequence, where "you
did not read first" only describes process.

If the current head differs from the document's base commit, that is drift,
not merely a conflict — say so, rather than failing with a bare 409.

**What the diff must show**, beyond additions and deletions:

    Applying to "Root" (a64edca5) on branch main

      Children       + Payments API, + Ledger DB
                     - Legacy Queue
      Tags           ~ team: backend -> platform
      Directories    (unchanged)
      Child pins     ! 4 children will be re-pinned to their current head

The last line is hazard 2 above. Nobody would think to ask for it, and the
diff is the only place it becomes visible — a push that changes one title
silently advances every child's snapshot pin.

**Validate locally before sending.** A FastAPI 422 is a nested blob;
`diagram.json: visual_properties[2] missing child_node_id` is actionable.
Worth checking further that every `child_node_id` exists and belongs to this
org — a typo'd UUID otherwise pushes successfully and leaves a visual property
pointing at nothing.

**Do not validate layout.** Uniform spacing is not correct-by-definition: real
diagrams have clusters, deliberate gaps, and nodes of different sizes.
Rejecting a valid layout for failing a house style is how a tool gets routed
around. The useful version is generation — `--auto-layout` places nodes that
have no position and leaves explicit ones alone, which solves the actual
problem (an agent emitting nodes without coordinates) without asserting taste.
Any spacing check should be a warning naming what looks off, never an error.

**Confirm on a TTY, require the flag otherwise** — the `gh` convention. Never
block on a prompt when stdin is not a terminal; that is the one failure mode
that hangs an agent indefinitely rather than failing it.

**Sequencing:** none of this can be built before hazard 1 is settled. A
trustworthy diff requires knowing which keys `push` actually consumes.

#### Open

Whether `apply` creates missing nodes or requires them to exist first.
Creating them makes the document self-contained — the whole ideal workflow in
one command — but means `apply` spans both endpoint families and has to reason
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
  usual when the API's native mode is full-state replace. Gate the destructive
  half specifically (`--allow-deletes`), never behind a blanket `--force` —
  see *Safety rails on `apply`*.
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
