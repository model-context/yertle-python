"""Agent construction.

v1 uses LangGraph's prebuilt ReAct agent — a single-node loop with a tool list.
This is the simplest LangGraph pattern; we can graduate to a multi-node graph
without changing the public CLI or library surface.
"""

from __future__ import annotations

import os
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from pydantic import SecretStr

from yertle.sre.config import Settings
from yertle.sre.prompts import SYSTEM_PROMPT_V1
from yertle.sre.tools import ALL_TOOLS


def build_agent(
    settings: Settings | None = None,
    *,
    enable_memory: bool = False,
) -> Any:
    """Build a compiled LangGraph ReAct agent.

    Args:
        settings: Configuration. Defaults to environment-loaded `Settings()`.
        enable_memory: If True, attach an in-process `MemorySaver` checkpointer
            so the agent remembers the conversation across `.invoke` /
            `.stream` calls within the same session. Used by the REPL.

    Tool selection: v1 ships only read-only tools, so `settings.allow_writes`
    has no effect today. The flag is wired for future use.
    """
    settings = settings or Settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it or add it to a .env file.",
        )

    # If the user enabled LangSmith tracing but didn't pick a project, default
    # to ours so traces don't land in LangSmith's generic "default" bucket.
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)

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
