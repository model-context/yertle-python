"""Tool registry.

Adding a new tool: implement it in a sibling module (or a new one) using the
`@tool` decorator from `langchain_core.tools`, then add it to `ALL_TOOLS`
below. That's the entire extension surface.
"""

from langchain_core.tools import BaseTool

from yertle.sre.tools.aws import AWS_TOOLS
from yertle.sre.tools.gh import GH_TOOLS
from yertle.sre.tools.yertle import YERTLE_TOOLS

ALL_TOOLS: list[BaseTool] = [*YERTLE_TOOLS, *AWS_TOOLS, *GH_TOOLS]

__all__ = ["ALL_TOOLS"]
