"""`yertle about` — what Yertle is, and how this CLI fits together.

Prose, not generated. But `tests/cli/test_about.py` asserts that every command
the app registers appears somewhere in this text, so a new command cannot ship
undocumented. That check is the reason this command was written last: it
describes a surface that was still moving, and the guard is what stops it
quietly going stale afterwards.
"""

from rich.console import Console

ABOUT = """\
[bold]Yertle[/bold] — a hierarchical context layer for software systems

Yertle gives engineers and AI agents a structured, navigable view of their
software systems. Think of it like a filesystem for your infrastructure:
organizations contain nodes, nodes contain child nodes, and connections
describe how they interact — forming a living map of your architecture.

The point is context. When you are debugging an incident or trying to
understand an unfamiliar system, Yertle answers what depends on what, how
services connect, and where things live.

[bold]Data model[/bold]

  Organizations   Top-level containers — a workspace or team
  Nodes           Any component: a service, database, queue, deployment
  Containment     Nodes contain child nodes (parent/child ownership)
  Connections     Labeled edges between nodes ("calls", "reads from")
  Tags            Key-value metadata (ARN, GitHub repo, owner, tier)
  Directories     Organizational paths for browsing (/infra, /services)
  Branches        Git-like versioning — every change is a commit

[bold]Getting started[/bold]

  yertle login
      Paste a personal access token, minted in the web app under Settings.
      Defaults to production; pass --api-url for another backend, or set
      $YERTLE_TOKEN and $YERTLE_API_URL instead and skip login entirely.

  yertle auth status
      Which backend and token are in effect, and where each came from.
      Exits non-zero when unauthenticated, so it works as a script check.

[bold]Choosing an organization[/bold]

  Most commands act on one organization. They resolve it in this order:

      --org <id>  >  $YERTLE_ORG  >  yertle orgs use  >  every org

  yertle orgs use <id>       Set a default, so you stop typing --org
  yertle orgs use all        Undo it

  Commands that can span organizations (nodes list, nodes tree) will do so
  by default. Commands that cannot (nodes show, nodes search) ask you to
  pick one.

[bold]Finding your way around[/bold]

  yertle orgs list                    Organizations you belong to
  yertle orgs show <id>               One organization in detail
  yertle nodes tree                   The containment hierarchy
  yertle nodes list                   Every node, with relationship counts

[bold]Answering a question[/bold]

  yertle nodes search "<query>"       Rank nodes by meaning, not by name
  yertle nodes search "<query>" --expand standard
                                      ...and pull in their neighbours
  yertle nodes show <id>              One node: tags, parents, children,
                                      connections in and out

  Start with [bold]nodes search[/bold] when you know what a thing does but not
  what it is called. Tags on the result usually carry the ARN, repo or owner
  you actually needed.

[bold]Making changes[/bold]

  yertle nodes create "<title>"       Create a node
  yertle nodes create "<title>" --tag team=backend --dir /services

  A new node is created [bold]unattached[/bold]: it belongs to the organization but
  sits under no parent, so nodes tree lists it at the top level beside the
  org's root rather than inside the hierarchy. Attaching it to a parent is a
  separate operation that the CLI cannot do yet.

[bold]Scripting[/bold]

  Every data command takes --format json. Errors go to stderr and exit 1, so
  piping is safe:

      yertle nodes search "payment path" --format json | jq '.matches[].title'

  Commands that create something print the new id on the first line, so it
  can be captured directly:

      NODE=$(yertle nodes create "Checkout API" | head -1)

[bold]More[/bold]

  yertle about               This overview
  yertle <command> --help    Options for any command
  yertle version             Version, and whether you are on a source checkout
  https://docs.yertle.com    Full documentation
"""


def about() -> None:
    """Learn what Yertle is and how to use this CLI."""
    # soft_wrap: the text is hand-wrapped to a readable width already, and
    # letting Rich re-wrap it would break the aligned data-model block.
    Console().print(ABOUT, soft_wrap=True)


__all__ = ["ABOUT", "about"]
