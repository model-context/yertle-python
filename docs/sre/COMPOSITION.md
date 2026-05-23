# Composing pipelines and agents — patterns, tradeoffs, and yertle-sre's plan

> **Status:** decision record / forward-looking design note. yertle-sre
> today is a single ReAct agent. Eventually we'll want to add structured
> workflows alongside it — auto-population from cloud accounts, drift
> detection, cost investigations. This document captures the industry
> patterns for composing those with the existing agent, why each one is
> useful, and which one yertle-sre should adopt when. Research-grounded
> with sources at the end. Intended to be readable cold — no prior
> context required.

## The composition question

`yertle-sre/src/yertle/sre/agent.py` is five lines that call
`langchain.agents.create_agent(...)`. It returns a compiled 2-node
LangGraph (agent ↔ tools) — Anthropic's standard ReAct pattern. That's
the entirety of the agent's structure today.

Now imagine we want a second capability. Concrete near-future example:
**yertle-auto-create**, a tool that bootstraps a Yertle org by scanning
AWS, proposing logical groupings, asking the user to approve, and then
creating yertle nodes. That's a four-step workflow with HITL — clearly
not a Q&A loop.

The question: **how does this second capability live alongside the
existing ReAct agent?** Three reflexes are wrong:

- *"Rebuild the agent as a multi-node graph."* Heavy, loses the simple
  shape, doesn't help most use cases.
- *"Make yertle-auto-create a separate tool the user runs explicitly."*
  Fine, but misses the chance to let users invoke it conversationally.
- *"Add a bunch of `aws_run` tools and let the agent figure it out."*
  Doesn't work — the workflow needs deterministic ordering and HITL.

The right answer is a named industry pattern with mature library
support. The rest of this document walks through it.

## What the industry calls this

In Anthropic's *Building Effective Agents* taxonomy, this is the
**orchestrator-workers** pattern:

> *"A central LLM dynamically breaks down tasks, delegates them to
> worker LLMs, and synthesizes their results … suits complex tasks
> where you can't predict the subtasks needed."*
> — [Anthropic, *Building Effective Agents*](https://www.anthropic.com/research/building-effective-agents)

For yertle-sre, the orchestrator is the existing ReAct agent. Each
*worker* is a focused capability — a pipeline, a sub-agent, a single
tool, whatever fits the problem. The orchestrator delegates via normal
tool calls. The workers do their thing and return summaries. The
orchestrator's context stays small.

LangGraph implements this natively. There are two technical surfaces:

- **`@tool`-wrapped compiled graph** — wrap the pipeline as a tool the
  ReAct agent can call. Lightweight. Same composition rules as any
  other tool.
- **`add_node(name, compiled_subgraph)`** — embed a compiled graph as a
  node in a parent graph. Heavier. Used when you need explicit state
  mapping at the boundary or when the parent itself is no longer a
  ReAct loop.

At scale there's a third, the **supervisor pattern** via the dedicated
`langgraph_supervisor` package — a tiny LLM whose only job is to route
each turn to one of N worker agents. Used in production at companies
including Uber, LinkedIn, and Klarna.

## The decision tree

Mapping our actual problem space onto these patterns:

| Shape of your problem | Pattern | Cost | Where yertle-sre is |
|---|---|---|---|
| One capability (Q&A only) | Vanilla ReAct via `langchain.agents.create_agent` | Lowest | **Today.** |
| One ReAct + one pipeline | Wrap pipeline as `@tool` (lightweight orchestrator-workers) | ~20 lines | **Near future.** When yertle-auto-create lands. |
| One ReAct + multi-step pipeline with HITL inside the parent graph | Subgraph-as-node, explicit state schema | ~50 lines + design | If the pipeline becomes structurally complex. |
| 3+ specialist capabilities | `langgraph_supervisor` (separate PyPI package) | +1 LLM call per turn for routing, but cleanest at scale | Later. When we have Q&A + auto-create + drift-check + cost-investigator. |

The right answer for **right now**: row 1 (we have nothing to compose
yet). The right answer for **yertle-sre v1.5 with yertle-auto-create
v1**: row 2. The right answer for the **yertle-* family at maturity**:
row 4.

## Worked sketch for yertle-auto-create

Once yertle-auto-create ships its pipeline, exposing it to yertle-sre
is a thin wrapper. The pipeline itself lives in its own repo / module;
the yertle-sre side is just a `@tool` registration:

```python
# src/yertle/sre/tools/auto_create.py — hypothetical
from langchain_core.tools import tool
from yertle_auto_create import build_auto_create_pipeline


@tool
def auto_create_aws_propose(region: str) -> str:
    """Scan an AWS region and propose Yertle nodes to create from it.
    Returns a human-readable summary of the proposed groupings. Does
    NOT create anything — the user must explicitly run
    `yertle-sre auto-create apply <plan-id>` to commit.

    Use this when the user asks to "populate Yertle from my AWS
    account" or "auto-detect what's in <region>".
    """
    pipeline = build_auto_create_pipeline()
    final_state = pipeline.invoke(
        {"region": region},
        config={"interrupt_before": ["apply"]},  # stop after propose
    )
    return format_proposal_summary(final_state["proposed_groups"])
```

Then add it to `ALL_TOOLS` in `tools/__init__.py`. That's the entire
integration. The orchestrator (ReAct agent) doesn't know or care that
the tool is implemented as a compiled subgraph — to it, it's just
another callable that returns a string.

User flow becomes:

```
> populate yertle from my AWS account in us-east-1
→ auto_create_aws_propose(region="us-east-1")

Found 47 resources. Proposed 12 groupings:
  - payments-api:   ALB + Lambda + RDS instance + …
  - checkout-api:   …
  - …
To apply, run: yertle-sre auto-create apply <plan-id>
```

Read-only. Safe. Aligns with yertle-sre's existing
"read-only-by-default" safety story. No `--allow-writes` flag needed
yet.

## HITL and write actions

The reflex when designing this is to push HITL *into* the tool —
"the tool should pause and ask the user mid-execution." That's the
wrong abstraction. Three reasons:

1. **Tools must return synchronously.** A `@tool` that pauses and
   waits for input violates the contract. The ReAct loop expects
   tool calls to produce results, not block on side channels.
2. **The agent's natural multi-turn shape is already HITL.** If the
   tool returns "here's a proposal, want me to apply it?", the
   user's next message is the human-in-the-loop confirmation. No
   special machinery needed.
3. **Writes need explicit consent, not implicit approval.** Even if
   an HITL prompt fires inside a tool, the user may not see it
   clearly amid the agent's other output. Better to make writes a
   *separate command* (or a separate tool gated behind
   `--allow-writes`) so the consent is unambiguous.

For yertle-sre specifically: the auto-create *propose* step is fine
as an agent tool. The auto-create *apply* step is **not** a tool —
it's a separate CLI command (`yertle-sre auto-create apply
<plan-id>`), or it's a second tool that only registers in
`ALL_TOOLS` when `--allow-writes` is on.

## Anti-patterns to avoid

The research surfaced a few patterns that *look* tempting but are
flagged across multiple sources:

- **Building custom orchestration on top of LangGraph.** Every
  agent-framework write-up since 2024 says the same thing: use the
  prebuilts (`create_agent`, `langgraph_supervisor`). They're
  battle-tested and benefit from continuous upstream improvements.
- **Going straight to swarm-style decentralized agents.** A swarm
  removes the supervisor and lets agents hand off control to each
  other directly. Faster, but harder to debug. The documented
  production default is supervisor; swarm earns its keep only with
  measurable evidence.
- **Skipping observability.** LangChain's 2025 *State of AI Agents*
  report puts production agent observability adoption at 89%. We
  already have LangSmith env vars wired up — just turn it on when
  running real traffic. See `CONTRIBUTING.md`.
- **Auto-executing writes from a tool call.** Already covered
  above. Writes need explicit user commands or `--allow-writes` +
  multi-turn confirmation, never silent.
- **Trying to make HITL work inside a tool.** Use a separate
  command or a follow-up tool call, not a blocking pause inside the
  current one.

## When to bump to `langgraph_supervisor`

Adopt the formal supervisor pattern when **any** of these is true:

- We have **3+ distinct specialist capabilities** (e.g. Q&A +
  auto-create + drift-check + cost-investigator) and the routing
  logic in the orchestrator's prompt is starting to look like a
  decision tree.
- We need **observability per specialist** — LangSmith traces grouped
  by which worker handled which turn.
- We're deploying as a **hosted/multi-tenant service** and need clean
  separation between user-specific specialist instances.
- The orchestrator's context regularly exceeds 30% of the window
  because of worker tool definitions or routing back-and-forth.

Until at least one of these is true, the tool-wrapper approach in row
2 is sufficient. Don't reach for supervisor before you need it.

## Relationship to other docs

- **[SUBAGENTS.md](./SUBAGENTS.md)** — when to graduate the ReAct agent
  itself into a multi-node graph. That's *scaling up* the agent's
  internal structure. This document is about *scaling out* — adding
  sibling capabilities without changing the existing agent. They pair
  naturally: if both motivations land, you'd build a supervisor whose
  workers are themselves multi-node sub-graphs.
- **[MEMORY.md](./MEMORY.md)** — checkpointer and state-schema
  primitives. Becomes relevant when a pipeline node needs structured
  state (per pattern row 3) or when the supervisor pattern needs
  per-thread routing memory.
- **[LANGGRAPH.md](./LANGGRAPH.md)** — explainer for the ReAct loop
  itself. The foundation everything else builds on.

## References

- [LangChain: Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) — official distinction between deterministic workflows and dynamic agents.
- [Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — the orchestrator-workers pattern and the "start simple" principle ("consider adding complexity only when it demonstrably improves outcomes").
- [LangGraph Multi-Agent Supervisor](https://reference.langchain.com/python/langgraph-supervisor) — the prebuilt package for row 4 of the decision tree.
- [LangGraph Multi-Agent Swarm](https://reference.langchain.com/python/langgraph-swarm) — the decentralized alternative we are explicitly *not* adopting.
- [Augment Code: Swarm vs. Supervisor](https://www.augmentcode.com/guides/swarm-vs-supervisor) — production tradeoffs between the two patterns.
- [LangGraph Agent Patterns 2026 (CallSphere)](https://callsphere.ai/blog/langgraph-agent-patterns-2026-stateful-multi-step-ai-workflows) — covers subgraph-as-tool examples in detail.
- [LangChain: `create_agent` reference](https://docs.langchain.com/oss/python/langchain/agents) — the prebuilt ReAct agent we use today.

## Action today

None. This is a forward-looking design record. `agent.py` stays
exactly as it is. When yertle-auto-create is built — likely in its
own repo per the architectural discussion notes — its first
integration with yertle-sre will follow row 2 of the decision tree:
a single `@tool`-wrapped read-only `auto_create_aws_propose` function
added to `ALL_TOOLS`.
