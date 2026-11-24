"""Captured responses for short ids (#60), and the ids they use.

Every body under `tests/fixtures/short_ids/` was captured from a running
backend (yertle `origin/main`, with the `IdPrefixMiddleware` from yertle#588)
by requesting each route with a short id, then scrubbed of real ids and
names. They are not written from memory.

- `org_member.json`, `org_public.json`: `GET /orgs/{short}` with the owner's
  token, and `GET /public/orgs/{short}` with none.
- `node_location.json`: `GET /nodes/{short}` with the owner's token. The
  signed-in lookup resolves a short id within the caller's own orgs.
- `tree_document.json`, `branches.json`: the node's document and its
  branches, read through `/orgs/{short}/nodes/{short}/...`. The public tree
  route returned the identical document.
- `ambiguous_org.json`, `ambiguous_node.json`, `ambiguous_public_node.json`:
  the 409 the path middleware returns for a prefix shared by two orgs, or by
  two nodes in an org: from `/orgs/...`, and the node one again from
  `/public/orgs/...` without a token. No candidates are listed, because the
  middleware runs before authentication.
- `ambiguous_node_location.json`: the 409 from the signed-in lookup, which
  does list the candidates (auth has run, and every match is in one of the
  caller's own orgs).
- `nonmember_locate_short.json`: a signed-in non-member's lookup of a short
  id for a node in a public org: 404, since short ids match only in the
  caller's own orgs.
- `unmatched_org.json`, `unmatched_node_location.json`,
  `unmatched_public_tree.json`: a prefix that matches nothing. The backend
  zero-pads it to a UUID that cannot exist, so these are exactly the 404s a
  nonexistent full id gets.
- `nodes.json`: `GET /orgs/{short}/nodes`.
- `search.json`: `POST /orgs/{short}/search/retrieve`, unscoped.
- `search_scoped.json`: `POST /orgs/{short}/search/retrieve` with a full
  `scope.root_node_id`. A short one there is a 400 ("must be a valid UUID"):
  the backend resolves ids in paths only.

No two real ids shared 8 characters in the database used, so two bare rows
were inserted with crafted ids to produce the 409s: an org sharing the demo
org's first 8 characters, and a node sharing the demo node's. They were
deleted afterwards. That made the 8-character prefixes ambiguous, so the
successful reads were captured with a longer prefix (`ab7bd00e-05`); the body
does not depend on the prefix, and tests serve it at the 8-character path.
"""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "short_ids"

#: The org and node as the fixtures name them, full and short.
FULL_ORG = "dc047318-0000-4000-8000-000000000001"
SHORT_ORG = "dc047318"
FULL_NODE = "ab7bd00e-0000-4000-8000-000000000002"
SHORT_NODE = "ab7bd00e"
#: The second node with the same first 8 characters, from the ambiguous lookup.
TWIN_NODE = "ab7bd00e-0000-4000-8000-000000000003"
ROOT_NODE = "0f1e2d3c-0000-4000-8000-000000000004"
#: Prefixes that matched nothing.
UNMATCHED_ORG = "dc047319"
UNMATCHED_NODE = "ab7bd00f"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())
