"""yertle-sre — natural-language SRE agent for Yertle-modeled systems."""

try:
    import langgraph  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as _e:
    import sys

    sys.exit(
        "yertle-sre requires the [sre] extra. "
        "Install with: pip install 'yertle[sre]'"
    )

from yertle.sre.agent import build_agent
from yertle.sre.config import Settings

__all__ = ["Settings", "ask", "build_agent"]
__version__ = "0.1.0"


def ask(question: str, *, settings: Settings | None = None) -> str:
    """Run a one-shot question through the agent and return the final answer.

    Convenience wrapper around `build_agent` for library users who don't need
    streaming or intermediate tool-call output.
    """
    settings = settings or Settings()
    agent = build_agent(settings)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": settings.max_iterations},
    )
    final = result["messages"][-1]
    content = final.content
    if isinstance(content, str):
        return content
    return str(content)
