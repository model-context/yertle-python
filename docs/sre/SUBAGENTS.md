# Subagents in LangGraph — patterns, tradeoffs, and yertle-sre's plan

> **Status:** decision record. We discussed adopting a subagent layer for
> yertle-sre and deferred it. This document captures the three patterns
> we considered, why each one is useful, why we deferred for v1, and the
> trigger conditions that should make us revisit. It's intended to be
> readable cold — no prior context required.

## The problem subagents solve

Today, yertle-sre is one LangGraph ReAct loop with three tools
(`yertle_run`, `aws_run`, `gh_run`) sharing a single context window. As
agents grow, that single-loop shape hits three walls:

1. **Context bloat.** Every CLI JSON blob the agent reads stays in the
   message history for the rest of the session. A few `aws describe-*`
   calls against busy services can fill tens of thousands of tokens of
   context the agent never needs to look at again.
2. **Tool-choice confusion.** With ~3 tools the LLM picks correctly
   almost every time. With 20+ tools across multiple providers, choices
   get noisy — the LLM occasionally reaches for the wrong provider, or
   forgets a critical flag because the unified system prompt has too much
   to teach.
3. **No natural parallelism.** Cross-provider questions ("are any AWS
   alarms firing AND any GitHub workflows failing?") run sequentially in
   a single loop, even when they're independent.

Subagents are the standard answer. The orchestrator delegates focused
sub-questions to focused specialist agents whose internal reasoning
(tool calls, raw JSON, scratch thinking) **never reaches the
orchestrator's context**. The orchestrator sees one delegation call and
one synthesized answer.

LangGraph supports three flavors of subagent. They differ in how much
structure you impose on the delegation.

---

## Pattern 1 — Subagent-as-tool

The most common pattern, and the one most likely to fit yertle-sre.

You build a fully compiled agent for a focused domain, then wrap it as a
LangChain `@tool` on the orchestrator. The orchestrator sees a tool with
a name, a docstring, and a string-in / string-out signature. Internally,
that tool runs an entire ReAct loop with its own tools and its own
context.

### Sketch

```python
from langchain.agents import create_agent
from langchain_core.tools import tool

# Focused subagent: only AWS, only the AWS-specialist prompt
aws_subagent = create_agent(
    model,
    tools=[aws_run],
    system_prompt=AWS_SPECIALIST_PROMPT,
)

@tool
def aws_specialist(question: str) -> str:
    """Investigate an AWS-specific question. Has its own context window
    and iteration budget. Returns a synthesized prose answer, not raw
    CLI output. Use this for any question about live AWS state."""
    result = aws_subagent.invoke(
        {"messages": [{"role": "user", "content": question}]},
    )
    return result["messages"][-1].content

# Orchestrator only sees the three specialists, never the runners
orchestrator = create_agent(
    model,
    tools=[yertle_specialist, aws_specialist, gh_specialist],
    system_prompt=ORCHESTRATOR_PROMPT,
)
```

### What the orchestrator's context looks like

```
[tool_call] aws_specialist(question="Are any alarms firing in us-east-1
                                     for the payments-api service?")
[tool_result] "2 alarms firing: payments-api-5xx (ALARM since 14:32 UTC),
               payments-api-latency-p99 (ALARM since 14:18 UTC). Both
               watch metrics from the payments-api ALB target group."
```

…not the 8 underlying `aws_run` calls and 200 KB of CloudWatch JSON the
subagent waded through to produce that paragraph.

### When it's useful

- Each provider has enough tools (5+) that a specialist prompt + focused
  tool list demonstrably steers the LLM better than the unified prompt.
- Investigations routinely fill a meaningful chunk of the context window.
- You want providers to be independently extensible (e.g. a contributed
  `kubectl_specialist` plugin shouldn't conflict with `aws_specialist`).

### Tradeoffs

- **2-3× total token cost.** Every specialist has its own system prompt
  and reasoning trace.
- **More LLM round-trips → slower.**
- **Cross-source synthesis is harder.** "Which AWS resources back the
  Yertle node `api`, and are any alarming?" *was* trivial in the unified
  loop because the agent saw both Yertle's response and the AWS check in
  one context. With strict subagents the orchestrator must extract IDs
  from one specialist's *prose* and pass them to another. Possible,
  brittle, more LLM calls.

---

## Pattern 2 — Subgraphs as nodes

More structure, more control. Instead of wrapping a subagent as a tool,
you embed an entire compiled `StateGraph` as a node inside a larger
graph.

```python
from langgraph.graph import StateGraph

main = StateGraph(MyState)
main.add_node("plan", planner_subgraph)        # compiled subgraph
main.add_node("investigate", investigator_subgraph)
main.add_node("summarize", summarizer_subgraph)
main.add_edge("plan", "investigate")
main.add_edge("investigate", "summarize")
```

State is mapped explicitly at the node boundaries — the parent graph and
each subgraph can have different state schemas, and you control which
fields flow in and out.

### When it's useful

- The investigation has a **fixed pipeline**: planner → fan-out across
  investigators → summarizer. You don't want the LLM deciding the shape
  of the workflow on every question.
- You need **parallelism via `Send`**. `Send(node_name, state)` from a
  parent node fans out to N concurrent subagents, each working on its
  own slice of state. LangGraph collects results and routes them to the
  next node.
- Each subgraph is itself complex (multi-node), not just a single ReAct
  loop you'd wrap as a tool.

### Tradeoffs

- More machinery (state schemas, edge wiring, mapping).
- Harder to evolve — adding a new step means changing the graph topology,
  not just adding a tool.
- Overkill when the orchestrator's job is simple "pick the right
  specialist and ask it" — Pattern 1 is lighter for that.

---

## Pattern 3 — The supervisor pattern

A supervisor LLM whose only job is to **route**. It looks at the current
conversation, picks one of N worker subagents, hands off, gets a result
back, and decides whether to route again or finish.

LangGraph ships a prebuilt for this:

```python
from langgraph_supervisor import create_supervisor

app = create_supervisor(
    [yertle_subagent, aws_subagent, gh_subagent],
    model=model,
    prompt="You route questions to the right specialist…",
).compile()
```

This is the architecture popularized by frameworks like CrewAI and
AutoGen. It generalizes Pattern 1 — the supervisor is essentially an
orchestrator whose tools are *only* the specialists, and whose decisions
are pure routing.

### When it's useful

- You have **many workers** (5+) and the routing logic is non-trivial.
- You want a clear separation between "plan/route" and "execute" — the
  supervisor reads only summaries, never raw tool output.
- You want to swap supervisors easily (e.g. a deterministic router for
  cheap questions, an LLM router for hard ones).

### Tradeoffs

- One more layer of indirection.
- The supervisor itself is an LLM call per turn — adds latency.
- Pattern 1 already does most of what a supervisor does for small N
  (≤ 5 workers). The supervisor pattern earns its keep at scale.

---

## Why yertle-sre is deferring (today)

We considered Pattern 1 specifically — `yertle_specialist`,
`aws_specialist`, `gh_specialist` wrapping the existing runners — and
chose not to adopt it for v1. Four reasons:

1. **yertle-sre's flagship questions are cross-source.** *"Given my
   Yertle architecture, which AWS resources back the `api` node, and are
   any of them alarming?"* In the current unified loop, the agent reads
   Yertle's response, sees the ARN sitting in the node attributes, and
   uses it directly in the next `aws_run` call. With strict subagents,
   the orchestrator has to extract that ARN from the yertle specialist's
   prose and pass it to the aws specialist. That's a structural
   regression on exactly the kind of question that makes this tool
   interesting.
2. **With 3 runners, there's nothing to specialize.** Each "specialist"
   would have exactly one tool. That's not a subagent earning its keep;
   it's just an extra LLM hop wrapping a single function call.
3. **Zero real-world evidence of the pain subagents solve.** We've never
   run yertle-sre on real questions in real environments. Refactoring to
   solve imagined context bloat before measuring real bloat is the kind
   of premature architecture that ages worst.
4. **2-3× token cost is a real regression for v1 users.** This is a
   public CLI; users pay per token. Asking them to swallow that for
   no observed benefit is hard to justify.

## When to revisit

Adopt Pattern 1 when **any one** of these becomes true:

- A 4th provider lands (k8s, datadog, sentry, …). The unified prompt
  starts groaning, and per-provider specialists carve cleanly.
- Curated tools come back per-provider on real evidence (the runner
  consistently fails the model on a class of questions), and any one
  provider ends up with 5+ tools.
- A typical investigation regularly fills **30%+ of the context window**.
  This is measurable — set up logging on tool-result token counts and
  watch.
- Users report the agent picking the wrong tool because the unified tool
  list has grown unwieldy.

If none of these are true, the unified loop remains the right shape.

## What the implementation will look like (when the time comes)

Pattern 1, one specialist per provider. Files to change:

- **`src/yertle/sre/agent.py`** — instead of one `create_agent`
  with `ALL_TOOLS`, build three subagents (one per runner), wrap each as
  a `@tool` named `yertle_specialist` / `aws_specialist` /
  `gh_specialist`, and build the orchestrator with those three wrappers
  as its tool list. `build_agent`'s public signature stays unchanged —
  CLI and library callers see no difference.
- **`src/yertle/sre/prompts.py`** — split the current `SYSTEM_PROMPT_V1`
  into a shorter `ORCHESTRATOR_PROMPT` (teaches "you have three
  specialists; pick one and ask a focused question") plus three
  specialist prompts that own the per-CLI worked-example sections
  currently in the unified prompt.
- **`src/yertle/sre/tools/__init__.py`** — `ALL_TOOLS` becomes the three
  specialist wrappers. The runners are still importable but no longer
  wired to the orchestrator directly.
- **`tests/test_subagents.py`** (new) — smoke test that each specialist
  builds and exposes exactly one runner. Don't run the live LLM; just
  introspect the compiled graphs.
- **README.md / PLAN.md / CONTRIBUTING.md** — graph diagram updated;
  "Adding a new provider" walkthrough adds a specialist prompt + wrapper
  alongside the runner.

What stays exactly the same: `tools/_shell.py`, the runners themselves,
`cli.py`, `config.py`, every existing runner test.

## References

- [LangChain: `create_agent`](https://docs.langchain.com/oss/python/langchain/agents) — the prebuilt ReAct agent. (Was `langgraph.prebuilt.create_react_agent` before LangChain 1.0.)
- [LangGraph: subgraphs](https://langchain-ai.github.io/langgraph/concepts/subgraphs/)
- [LangGraph: `Send` for parallel fan-out](https://langchain-ai.github.io/langgraph/concepts/low_level/#send)
- [`langgraph_supervisor` prebuilt](https://github.com/langchain-ai/langgraph/tree/main/libs/langgraph-supervisor)
- [Anthropic: building effective agents](https://www.anthropic.com/research/building-effective-agents) — useful general guidance on when delegation pays off vs. when a single loop is enough.
