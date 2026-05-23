# How yertle-sre's agent works — LangGraph and ReAct, walked through

> **Status:** explainer / onboarding doc. If you want to know what
> happens between `yertle-sre ask "…"` and the printed answer, read
> this. It's intended to be readable cold — no prior LangGraph or ReAct
> background required.

## What this document covers

1. The problem an agent has to solve, and why we use a loop.
2. What ReAct actually is (and isn't).
3. How LangGraph implements that loop as a 2-node graph.
4. How our code wires it up — concrete file/line references.
5. Two worked examples, traced step by step.
6. Where in the code each piece lives.

If you've already read [README.md → How it works](../README.md#how-it-works),
this document is the deeper version with the actual file references and
example traces.

## The problem

The user asks plain English: *"Are any CloudWatch alarms firing in
us-east-1?"* The agent has to:

1. Decide *which* of its tools to call (and with what arguments).
2. Run the tool and read the result.
3. Decide whether the result is enough to answer — or whether it needs
   another tool call.
4. Repeat (3) until satisfied, then write the answer.

The number of round-trips isn't fixed. A simple question might need one
tool call. A cross-source question ("which AWS resources back this
Yertle node, and are any alarming?") might need three or four. So the
control flow has to be a *loop*, with the LLM itself making the
"continue or stop?" decision each iteration.

## What ReAct is

ReAct (Yao et al., 2022) is the pattern that interleaves **Reasoning**
and **Acting** in that loop. The original paper had the model produce
explicit text like:

```
Thought: I need to find which alarms are in ALARM state.
Action: aws cloudwatch describe-alarms --state-value ALARM
Observation: { "MetricAlarms": [...] }
Thought: Two alarms are firing. I have enough to answer.
```

Modern frameworks — including LangGraph — use a **function-calling**
variant of ReAct. The model doesn't write `Thought:` / `Action:` text;
it natively emits a structured `tool_calls` block when it wants to act,
and plain text when it wants to answer. The "reasoning" is implicit in
the choice between those two responses.

The shape, in pseudocode:

```python
loop:
    response = llm(messages)               # reason
    if response.tool_calls:
        results = run_tools(response.tool_calls)   # act + observe
        messages.append(response, results)
        continue
    else:
        return response.text               # done
```

So your one-line summary of "the LLM reasons then uses tools before
responding" is *partially* right — but ReAct is specifically a **loop**
of reason → act → observe → reason → act → … with the LLM choosing each
iteration whether to act again or to respond.

## How LangGraph implements the loop

A LangGraph agent is a **state graph**: a set of nodes connected by
edges, with a typed state object that flows between them. We don't
build the graph ourselves — `langchain.agents.create_agent` (formerly
`langgraph.prebuilt.create_react_agent` before LangChain 1.0) ships a
prebuilt graph that *is* the ReAct loop:

```
        ┌────────┐
        │ START  │
        └───┬────┘
            ▼
        ┌────────┐
   ┌───▶│ agent  │  ← calls the LLM with messages + tool defs
   │    └───┬────┘
   │        │
   │   does the response include tool_calls?
   │        │
   │   ┌────┴─────┐
   │   │          │
   │  yes        no
   │   │          │
   │   ▼          ▼
   │ ┌──────┐  ┌─────┐
   └─┤tools │  │ END │
     └──────┘  └─────┘
        │
        └─── (tool results appended, loop back)
```

Two real nodes:

- **`agent`** — sends the current `messages` list to Claude. Claude
  returns either text (an answer) or `tool_calls` (a request to act).
- **`tools`** — a `ToolNode` that runs whatever Claude asked for and
  appends the results to `messages` as `ToolMessage` entries.

One conditional edge — the *only* "decision" written in code, not
made by the LLM:

```
agent → END    if response has no tool_calls
agent → tools  if response has tool_calls
```

Plus an unconditional edge `tools → agent` that closes the loop.

Verify the shape against your installed code:

```bash
ANTHROPIC_API_KEY=fake uv run python -c "
from yertle.sre.agent import build_agent
from yertle.sre.config import Settings
g = build_agent(Settings(anthropic_api_key='fake')).get_graph()
for n in g.nodes.values(): print('node:', n.id)
for e in g.edges: print('edge:', e.source, '→', e.target)
"
```

You should see:

```
node: __start__
node: agent
node: tools
node: __end__
edge: __start__ → agent
edge: agent → __end__ (conditional)
edge: agent → tools (conditional)
edge: tools → agent
```

## How our code wires it up

`src/yertle/sre/agent.py:24-60` — the entire agent setup:

```python
def build_agent(settings, *, enable_memory=False):
    settings = settings or Settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. …")

    model = ChatAnthropic(
        model_name=settings.model,
        api_key=SecretStr(settings.anthropic_api_key),
        timeout=60,
        stop=None,
    )

    checkpointer = MemorySaver() if enable_memory else None

    return create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT_V1,
        checkpointer=checkpointer,
    )
```

That's the whole graph. The four moving parts:

| Part | What it is | Where it lives |
|---|---|---|
| `model` | A `ChatAnthropic` chat model (Claude). | `agent.py` |
| `tools` | List of `@tool`-decorated functions Claude can call. | `tools/__init__.py` re-exports `[*YERTLE_TOOLS, *AWS_TOOLS, *GH_TOOLS]` from the per-CLI runners. |
| `prompt` | The system prompt teaching Claude what each tool is for and how to plan. | `prompts.py` |
| `checkpointer` | Saves graph state between user turns. Only used by the REPL. | `agent.py` |

## How Claude sees the tools

This is the bit most people don't realize: **the docstrings on our
`@tool` functions are the spec Claude reads.** LangGraph introspects
each tool's signature and docstring and converts them into the JSON
schema Anthropic's API expects.

Look at `src/yertle/sre/tools/aws.py:25-46`:

```python
@tool
def aws_run(service: str, command: str, extra_args: list[str] | None = None) -> str:
    """Run a read-only `aws <service> <command>` and return its JSON output.

    `--output json` is appended automatically. Examples:

        aws_run("ec2", "describe-instances", ["--region", "us-east-1"])
        aws_run("cloudwatch", "describe-alarms", ["--region", "us-east-1"])
        …

    Only read-only verbs are allowed: describe-*, list-*, get-*, …
    """
    …
```

Claude sees a tool named `aws_run` whose schema is "service: string,
command: string, extra_args: list of strings, optional" with that
docstring as the description. When it decides to act, it constructs an
argument dict matching that schema. That's why our tool docstrings are
written for the model first and humans second — they're effectively
prompt engineering disguised as documentation.

## Worked example 1 — single tool call

Question: *"Are any CloudWatch alarms firing in us-east-1?"*

### Iteration 1 — `agent` node

Inputs (the `messages` list):

```
SystemMessage(content=SYSTEM_PROMPT_V1)          # teaches Claude about the 3 runners
HumanMessage(content="Are any CloudWatch alarms firing in us-east-1?")
```

Claude sees both, plus the tool schemas auto-generated from the
runners' docstrings. It produces:

```python
AIMessage(
    content="",
    tool_calls=[ToolCall(
        name="aws_run",
        args={
            "service": "cloudwatch",
            "command": "describe-alarms",
            "extra_args": ["--region", "us-east-1", "--state-value", "ALARM"],
        },
    )],
)
```

Conditional edge: `tool_calls` is non-empty → route to **tools**.

### Iteration 1 — `tools` node

`ToolNode` looks up `aws_run` in `ALL_TOOLS`, invokes it with the args.
Our runner (`tools/aws.py`) checks `describe` against `AWS_READ_VERBS`,
sees it's allowed, calls `_shell.run_cli(["aws", "cloudwatch",
"describe-alarms", "--region", "us-east-1", "--state-value", "ALARM",
"--output", "json"])`, and returns the JSON. `ToolNode` appends:

```python
ToolMessage(
    content='{"MetricAlarms":[{"AlarmName":"payments-api-5xx",…}]}',
    tool_call_id="...",
)
```

Edge `tools → agent` is unconditional. Loop back.

### Iteration 2 — `agent` node

Claude now sees:

```
SystemMessage(...)
HumanMessage(...)
AIMessage(tool_calls=[aws_run(...)])
ToolMessage(content='{"MetricAlarms":[…]}')
```

It "reasons" again. This time it has enough info to answer:

```python
AIMessage(content=
    "Yes — 1 alarm is firing in us-east-1: `payments-api-5xx`, "
    "in ALARM state since 14:32 UTC. Watches the 5xx-error count "
    "metric on the payments-api ALB target group."
)
```

No `tool_calls` → conditional edge routes to **END**. The final message
is what `cli.py:_print_final` prints.

Total: 2 iterations, 1 tool call, 1 final answer.

## Worked example 2 — cross-source

Question: *"Given my Yertle architecture, which AWS resources back the
`api` node, and are any of them alarming?"*

| Iter | `agent` emits | `tools` runs |
|------|-------------|--------------|
| 1 | tool_call: `yertle_run(["nodes", "api"])` | returns `{"id":"...","tags":{"aws_alb_arn":"arn:aws:elbv2:..."}}` |
| 2 | tool_call: `aws_run("cloudwatch", "describe-alarms", […alb-arn-filter…])` | returns `{"MetricAlarms":[{"AlarmName":"api-5xx","StateValue":"ALARM"}]}` |
| 3 | text answer: "The `api` node maps to ALB `arn:aws:elbv2:…` and one alarm (`api-5xx`) is firing." | — |

What's interesting is iteration 2: Claude **read the ARN out of the
prior `ToolMessage`** to construct the next call. That's reasoning +
acting + observing doing real work — and it only works because the
unified message history carries Yertle's response into the AWS step.
(See [SUBAGENTS.md](./SUBAGENTS.md) for why splitting this loop into
provider specialists would *regress* on these questions.)

## What the LLM sees on every call

A common misunderstanding: that the LLM somehow "only acts on the last
message" each iteration. It doesn't. The `agent` node sends the **full**
`messages` list to Claude every time — no filtering, no truncation, no
"just the latest." Claude reads:

- The system prompt
- The original user question
- Every prior `AIMessage` (including its `tool_calls`)
- Every prior `ToolMessage` (the tool results)

…and the response Claude returns is computed from all of it. The
"action" Claude takes is informed by the whole conversation, not just
the last message.

| Common framing | More precise |
|---|---|
| "the LLM reads the full block of messages" | ✅ correct — every call |
| "the LLM only takes action on the last message" | ❌ the action is informed by the whole history; "the last message" isn't a special slot |

You can see this in Worked Example 2 above: in iteration 2, Claude's
new tool call uses an ARN that came from the iteration-1
`ToolMessage`. That only works because the iter-1 tool result is still
in the messages list when iter-2's LLM call happens.

### Three practical consequences

**1. Token cost compounds.** Every iteration sends the full history. A
5-iteration question sends the system prompt 5 times, the original
question 5 times, the iter-1 tool result 4 times, and so on. This is
why we cap loops with `--max-iterations` and why `_shell.run_cli`
truncates large tool outputs before they reach the model — every byte
we add to a tool result is paid for in every subsequent iteration.

**2. Long histories degrade quality.** Past a certain length, models
start losing focus and missing earlier context. This is one of the
motivations behind subagents (see [SUBAGENTS.md](./SUBAGENTS.md)) —
they isolate provider-specific reasoning into focused histories that
don't pollute the parent's.

**3. Prompt caching makes the loop viable.** Anthropic's API supports
caching repeated message-prefix tokens at ~90% discount. Since the
system prompt and early-iteration messages don't change between calls,
they get cached and reused. Without this, ReAct loops would be
significantly more expensive than they are in practice.
`langchain-anthropic` enables ephemeral caching by default for
sufficiently large prompts; we benefit from it automatically without
setting `cache_control` headers ourselves.

### The mental model

Each call to the `agent` node is a **stateless function**:
`llm(messages) → response`. The LLM doesn't "remember" anything —
memory of prior iterations lives in the `messages` list the graph
carries between nodes. The LLM just reads, decides, and emits one new
message. The graph appends it (and any tool results from the `tools`
node) to the list, then calls the LLM again with the larger list.

So:

- The **LLM** is stateless.
- The **graph** carries state (the growing `messages` list).
- **Reasoning** happens inside one LLM call, given the full history.
- **Acting** = the LLM emitting a tool_call in its response.
- **Observing** = the graph appending the tool result to the history
  before the next call.

That separation — stateless LLM, stateful graph — is the foundation
everything else builds on. Checkpointers persist the graph's state;
subagents wrap an entire stateful sub-graph as a tool; custom state
schemas extend what the graph carries. See
[MEMORY.md](./MEMORY.md).

## What `--verbose` actually shows

`src/yertle/sre/cli.py:_stream` loops over `agent.stream(...,
stream_mode="values")` and prints each tool call as it's emitted:

```bash
$ yertle-sre ask -v "are any alarms firing in us-east-1?"
→ aws_run({'service': 'cloudwatch', 'command': 'describe-alarms', 'extra_args': ['--region', 'us-east-1', '--state-value', 'ALARM']})
Yes — 1 alarm is firing: payments-api-5xx (ALARM since 14:32 UTC)…
```

That's literally the `agent → tools` transition surfaced to your
terminal. Without `-v`, the same loop runs but only the final message
prints.

## How `repl` extends the loop across user turns

One-shot `ask` discards the `messages` list when the process exits.
`repl` doesn't — it attaches a `MemorySaver` checkpointer
(`agent.py:43`) so the graph snapshots state after every node. When
you ask a follow-up question, LangGraph re-loads the prior `messages`
list (system prompt + question 1 + tool calls + answer 1 + …),
appends your new question, and the loop continues from there. That's
why "now show me only the failures" works — Claude is reading the
full history of *both* turns. See [MEMORY.md](./MEMORY.md) for the
three flavors of memory and which one this is.

## Where to look in code

| Concept | File | Function |
|---|---|---|
| Build the graph | `src/yertle/sre/agent.py` | `build_agent` |
| Run it (one-shot) | `src/yertle/sre/cli.py` | `ask` (line 27) |
| Run it (interactive, with checkpointer) | `src/yertle/sre/cli.py` | `repl` (line 61) |
| Stream tool calls (`-v`) | `src/yertle/sre/cli.py` | `_stream` (line 147) |
| System prompt — the "operating manual" Claude reads | `src/yertle/sre/prompts.py` | `SYSTEM_PROMPT_V1` |
| Tool registry | `src/yertle/sre/tools/__init__.py` | `ALL_TOOLS` |
| Per-CLI runners | `src/yertle/sre/tools/{yertle,aws,gh}.py` | `*_run` |
| Subprocess chokepoint | `src/yertle/sre/tools/_shell.py` | `run_cli` |

## TL;DR

- LangGraph turns the ReAct pattern into a 2-node graph: `agent` (LLM)
  and `tools` (executes calls), with one conditional edge that decides
  "loop or stop."
- We don't build the graph by hand — `langchain.agents.create_agent`
  does it. We supply (a) the model, (b) the tool list, (c) the system
  prompt, (d) optionally a checkpointer.
- The "decision" of *what* tool to call and *with what arguments* is
  Claude's, made implicitly by what it emits each iteration. The only
  decision *we* code is "if there are tool_calls, route to tools;
  otherwise end."
- Tool docstrings are the spec Claude reads — they're prompt
  engineering, not just documentation.
- **The LLM is stateless; the graph carries state.** Every `agent` call
  sends the full `messages` history. There's no "act on last message
  only" — Claude reads everything every time, and that's what makes
  cross-iteration reasoning (using an ARN from iter-1 in iter-2's tool
  call) possible.
- That same fact is why long histories cost more, why prompt caching
  is load-bearing, and why subagents (via context isolation) are the
  natural next step once histories get heavy.

## References

- [LangGraph: prebuilt agents](https://langchain-ai.github.io/langgraph/how-tos/create-react-agent/)
- [LangGraph: low-level concepts (nodes, edges, state)](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [Yao et al., 2022 — *ReAct: Synergizing Reasoning and Acting in
  Language Models*](https://arxiv.org/abs/2210.03629) — the original
  paper.
- [Anthropic: tool use overview](https://docs.anthropic.com/claude/docs/tool-use) — how function-calling works at the API level.
- [docs/SUBAGENTS.md](./SUBAGENTS.md) — when this single-loop shape
  graduates to a subagent architecture.
- [docs/MEMORY.md](./MEMORY.md) — the three flavors of LangGraph memory
  and which we use.
