"""Library usage example for the SRE agent.

Prereqs:
- `pip install 'yertle[sre]'` (or `uv sync --extra sre`)
- `ANTHROPIC_API_KEY` set
- The yertle / aws / gh CLIs authenticated (yertle-sre uses your existing
  credentials — see `yertle-sre status` to verify before asking).
"""

from yertle.sre import ask

if __name__ == "__main__":
    answer = ask("what orgs do I have in yertle?")
    print(answer)
