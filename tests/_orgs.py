"""Captured organization payloads, and org listings built from them.

Both payloads are captured from live responses. The asymmetry between them is
the point of `orgs show`'s backfill: `/orgs/{id}` returns `invite_mode` but
leaves `role` and `member_count` null, while `/orgs` returns the opposite.
"""

from yertle_client.models import OrganizationListResponse, OrganizationResponse

ORG_ID = "8f14e45f-ceea-467a-9575-28db8d0dc4db"

CAPTURED_DETAIL: dict[str, object] = {
    "id": ORG_ID,
    "name": "Yertle",
    "public_id": "yertle-befed489",
    "created_at": "2026-04-15T00:52:23.240961+00:00",
    "updated_at": "2026-05-02T18:46:09.342788+00:00",
    "description": "The platform org.",
    "invite_mode": "open",
    "is_public": True,
    "role": None,
    "member_count": None,
    "node_count": 13,
    "root_node_id": "bbbff903-64a8-448e-a6c6-d3dfcfe4641f",
}

CAPTURED_SUMMARY: dict[str, object] = {
    **CAPTURED_DETAIL,
    "role": "owner",
    "member_count": 4,
    "invite_mode": None,
}

#: A second org, for "you belong to several".
OTHER_ORG = "1c383cd3-0b3f-4e1f-8e2a-9a1f0a0d1c2b"


def org_list(*ids: str) -> OrganizationListResponse:
    """`GET /orgs` as the caller who belongs to exactly these orgs."""
    return OrganizationListResponse(
        organizations=[
            OrganizationResponse.from_dict({**CAPTURED_SUMMARY, "id": org_id}) for org_id in ids
        ],
        total=len(ids),
    )


LIST_ORGS = "yertle.orgs.list_organizations_orgs_get.sync"
