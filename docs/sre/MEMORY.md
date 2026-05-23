# Memory in LangGraph — patterns, tradeoffs, and yertle-sre's plan

> **Status:** decision record. We discussed adopting LangGraph's memory
> primitives and chose to defer most of them for v1. This document
> captures what "memory" means in LangGraph (three distinct things),
> which ones we already use, why we're deferring the rest, and the
> triggers that should make us revisit. It's intended to be readable
> cold — no prior context required.

## The problem memory solves

A single-shot ReAct loop is *stateless* across invocations. Every time
the user runs `yertle-sre ask "…"`, the agent starts fresh — no recall of
prior questions, no learned facts about the user's environment, no
defaults. For a tool engineers will use repeatedly against the same
infrastructure, that's a real source of friction:

- The user has to specify the same `--org` or `--region` every time.
- The agent re-resolves "the `api` node" to its underlying ARN on every
  question, costing one extra `yertle_run` call per session.
- Long investigations can't pause and resume — quitting and re-launching
  loses everything.
- Cross-session learnings ("this org has 3 prod environments at these
  account IDs") aren't accumulated.

LangGraph offers three distinct primitives for solving this. They look
like one feature ("memory") but they answer different questions and have
different costs.

---

## Pattern 1 — Checkpointer (short-term, intra-session memory)

**What it is:** A snapshotting layer that persists graph *state* after
every node execution. The default state is the message history, so a
checkpointer effectively remembers the conversation.

**What we ship today:** `MemorySaver` (in-memory, per-process) attached
to the agent when `enable_memory=True`. This is what `yertle-sre repl`
uses to keep context across user turns within one session.

```python
# src/yertle/sre/agent.py — already shipping
checkpointer = MemorySaver() if enable_memory else None
return create_agent(model=..., tools=..., checkpointer=checkpointer)
```

### Persistent variants we don't use

`MemorySaver` is volatile — quit the process, lose the state. LangGraph
ships durable backends:

- `langgraph.checkpoint.sqlite.SqliteSaver` — single-file, no server.
- `langgraph.checkpoint.postgres.PostgresSaver` — for shared / multi-host
  setups.
- Third-party backends for Redis, MySQL, Mongo, etc.

Swapping `MemorySaver` for a durable backend is one line; the rest of
the code is unchanged.

### When the upgrade is useful

- The REPL session is long-lived and you want it to survive a `Ctrl-C`
  / restart.
- You want time-travel debugging: rewind state to a prior step, fork off
  a different choice.
- You want **HITL resumption** — an interrupted run can be resumed by a
  later process (a different terminal, a CI bot, a cron job).

### Tradeoffs

- **Deployment surface.** Persistent checkpointers mean a file, a
  database, or a server to manage.
- **Privacy.** Checkpoints contain the full message history, including
  any secrets the agent saw. Disk-resident state needs a clear story for
  who can read it.
- **Schema migrations.** If state shape changes, prior snapshots may
  need to be discarded or migrated.

---

## Pattern 2 — Long-term store (`BaseStore`)

**What it is:** A separate key-value layer for **cross-session,
cross-thread** memory. The checkpointer remembers *one* conversation;
the store remembers things *between* conversations and even between
users. The agent reads/writes through tool nodes or graph nodes.

```python
# Sketch — not currently shipping
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()
store.put(("user:123", "preferences"), key="default_org",
          value={"org_id": "acme"})

# Inside a tool or node:
existing = store.get(("user:123", "preferences"), key="default_org")
```

Backends parallel the checkpointer's: in-memory for dev, Postgres /
SQLite / Redis / etc. for production.

### When it's useful

- **Persistent user defaults.** "Use my default org if I don't say one."
  "I prefer `us-east-1`."
- **Learned facts.** "The `payments-api` node maps to ARN
  `arn:aws:elbv2:…`. (Cached for 1 hour.)" Skip the resolution lookup on
  repeat questions.
- **Cross-session context accumulation.** Things the agent figures out
  in one investigation that another investigation could reuse.
- **Multi-user / multi-tenant deployments.** If yertle-sre is ever
  hosted as a service, the store namespaces per user.

### Tradeoffs

- **Privacy is a real question.** Caching infra topology to disk is fine
  for personal use, riskier in shared/CI contexts. Needs an explicit
  opt-in and a clear "where is this data stored, who can read it" story.
- **Cache invalidation.** ARNs change. Nodes get renamed. Stale facts
  cached as if they were ground truth produce confidently-wrong answers.
  Every cached fact needs a TTL or invalidation strategy.
- **Scope boundaries.** Personal defaults (region, org) belong in a
  different namespace than learned facts (which are infrastructure
  metadata). Mixing them in one store invites bugs.
- **80% of the practical value can be had without LangGraph.** A simple
  `~/.yertle-sre/config.json` plus `--org` / `--region` CLI flags
  handles the most common pain point ("remember my defaults") with zero
  agent-framework involvement.

---

## Pattern 3 — Custom state schema (TypedDict)

**What it is:** The graph's state is a `TypedDict`. By default it's
`MessagesState`, which only has `messages`. You can extend it with
arbitrary fields the agent and graph treat as first-class.

```python
# Sketch — not currently shipping
from operator import add
from typing import Annotated

from langgraph.graph import MessagesState


class YertleState(MessagesState):
    org_id: str | None
    region: str | None
    facts: dict[str, str]
    iteration_count: Annotated[int, add]   # reducer: sum across nodes
```

Tools and nodes can read/write structured fields directly, instead of
stuffing everything into the message history.

### When it's useful

- **Structured data deserves structure.** A "things I've checked"
  checklist, a running cost counter, or a plan-of-record reads more
  reliably as a typed field than as prose buried in a message.
- **Subagents need explicit state passing.** When subagents land
  (see [SUBAGENTS.md](./SUBAGENTS.md)), parent and child graphs map
  state in/out at the boundary — that mapping needs a state schema.
- **HITL benefits from inspectable state.** A human-in-the-loop pause
  point is much more useful when the human can read structured fields
  ("about to call `aws_run` with these args; budget remaining: 12
  iterations") rather than scrolling a message history.
- **Reducers compose cleanly.** `Annotated[list, add]` lets parallel
  branches contribute to the same field without race conditions.

### Tradeoffs

- **Premature in a single-loop ReAct.** If there are no subagents and no
  HITL, the message history *is* the working memory — the agent reads
  prior tool results from messages just fine. Adding a TypedDict before
  there's machinery that benefits from it is overhead with no payoff.
- **Schema migrations.** Same problem as checkpointers — changing the
  shape of `YertleState` invalidates checkpoints unless you write
  migration logic.
- **Discoverability.** Tools that read/write state aren't visible in the
  same way as tools that just take parameters — contributors have to
  know to look for it.

---

## Why yertle-sre is deferring (today)

We considered all three patterns and chose to keep v1 as it is. Four
reasons:

1. **No measured pain.** We've never run yertle-sre on real questions in
   real environments. We don't know which kinds of memory users would
   actually want. Adding it speculatively risks building the wrong
   abstraction.
2. **Single-loop ReAct already has working memory.** The message history
   is the agent's scratch space — anything it learned in this session is
   in messages it can read. Pattern 3 (custom state) earns its keep when
   subagents or HITL land; both are deferred.
3. **Privacy needs a real story.** Pattern 2 (persistent store) means
   writing infra topology to disk. Personal-use is fine; shared/CI use
   needs an explicit opt-in design and probably a redaction layer. That
   design is premature without users telling us what they're worried
   about.
4. **80% of the obvious pain is solvable without LangGraph.** The
   single biggest UX improvement — "remember my default org and
   region" — needs nothing more than a `~/.yertle-sre/config.json` and
   two CLI flags. We can ship that as a normal feature, not a memory
   architecture.

## When to revisit

Adopt these in roughly this order, when the corresponding trigger fires:

| Pattern | Trigger to adopt |
|---|---|
| **Persistent checkpointer** (SQLite/Postgres) | REPL becomes long-lived enough that users want survivability across restarts. Or HITL lands and we need resumable interrupted runs. |
| **Long-term store** (BaseStore) | Real users tell us they want recall ("stop asking me which org") and we have a privacy opt-in story written. Or yertle-sre gets deployed as a hosted service where multi-user namespacing matters. |
| **Custom state schema** (TypedDict) | Subagents land (state-passing requirement) or HITL lands (state-inspection requirement) — see [SUBAGENTS.md](./SUBAGENTS.md). Don't add this in isolation. |

A reasonable v1.5 sequence: (a) ship a `~/.yertle-sre/config.json` for
defaults; (b) when subagents or HITL land, add a custom state schema as
part of that work; (c) add a `BaseStore`-backed long-term layer only
once we have real signal that users want it and the privacy design is
nailed down.

## What the implementation will look like (when the time comes)

### For persistent session memory

One-line swap in `src/yertle/sre/agent.py`:

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string(
    str(Path.home() / ".yertle-sre" / "checkpoints.sqlite"),
)
```

Plus a config knob (`YERTLE_SRE_CHECKPOINT_PATH`), plus a doc note about
where state lives.

### For long-term store

New module — `src/yertle/sre/memory.py`:

- A thin wrapper over `BaseStore` with namespaces: `("user", user_id)`
  for personal preferences, `("org", org_id, "facts")` for learned
  identifiers.
- One or two store-aware tools (e.g. `remember_default(key, value)`,
  `recall(key)`) that the agent can call.
- Cache-invalidation policy: TTLs on facts, no TTL on preferences.
- Opt-in via `YERTLE_SRE_MEMORY_PATH` (unset = no persistence) so users
  who don't want disk-resident topology can skip it entirely.

### For custom state schema

Extend `MessagesState` in a new module `src/yertle/sre/state.py`:

```python
from operator import add
from typing import Annotated

from langgraph.graph import MessagesState


class YertleState(MessagesState):
    org_id: str | None
    region: str | None
    iteration_count: Annotated[int, add]
    facts_used: Annotated[list[str], add]
```

Pass `state_schema=YertleState` to `create_agent`. Tools that read
state need to be node functions, not plain `@tool` functions, so they
can take the state argument — that's the shape we'd switch to once
subagents or HITL motivate it.

## References

- [LangGraph: persistence overview](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph: checkpointer reference](https://langchain-ai.github.io/langgraph/reference/checkpoints/)
- [LangGraph: `BaseStore` reference](https://langchain-ai.github.io/langgraph/reference/store/)
- [LangGraph: state schemas and reducers](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [yertle-sre/docs/SUBAGENTS.md](./SUBAGENTS.md) — the related deferred
  decision; subagents and custom state schemas are best adopted
  together.
