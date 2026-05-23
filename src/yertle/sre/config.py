"""Runtime configuration loaded from environment + .env."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """User-tunable settings.

    Loaded from environment variables (prefix `YERTLE_SRE_`) and an optional
    `.env` file in the current working directory.

    The Anthropic API key is read directly from `ANTHROPIC_API_KEY` (no prefix)
    so it works with the existing convention used by every Anthropic SDK.
    """

    model_config = SettingsConfigDict(
        env_prefix="YERTLE_SRE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    """Anthropic API key. Required at agent-build time, not at import time."""

    model: str = "claude-sonnet-4-6"
    """Anthropic model name. Override per-invocation with `--model` on the CLI."""

    tool_timeout: int = 30
    """Per-tool subprocess timeout in seconds."""

    max_tool_output: int = 10_000
    """Maximum bytes of tool output (stdout or stderr) returned to the model."""

    max_iterations: int = 25
    """LangGraph recursion_limit — caps total agent steps. Cost guardrail."""

    allow_writes: bool = False
    """Enable mutating tools. v1 ships no mutating tools, but the flag is wired."""

    langchain_project: str = Field(
        default="yertle-sre",
        validation_alias="LANGCHAIN_PROJECT",
    )
    """LangSmith project name for traces. Only used when LANGCHAIN_TRACING_V2=true."""
