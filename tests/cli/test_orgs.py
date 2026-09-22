"""Tests for the `yertle orgs` command group.

Mocks the *wire* layer rather than the SDK, so these exercise the real
CLI → `yertle.orgs` → `yertle_client` path. Patching `yertle.orgs.list`
itself would pass even if the CLI stopped calling the SDK at all.
"""

import datetime
import json
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.errors import UnexpectedStatus
from yertle_client.models import (
    OrganizationListResponse,
    OrganizationResponse,
    OrganizationResponseRoleType0,
)

from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app
from yertle.shared import auth as auth_mod

runner = CliRunner()

# Rich highlights option-shaped text and wraps to width; see tests/cli/test_help.py.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX = re.compile(r"[\u2500-\u257f]")


def _cells(output: str) -> str:
    """Table output as flat text, so a row can be matched as its cell values.

    Strips the colour codes and the box-drawing borders, then collapses
    whitespace — leaving `"Beta Corp 3 12 public owner"` for a row, which is
    readable in the assertion and independent of column widths.
    """
    return " ".join(_BOX.sub(" ", _ANSI.sub("", output)).split())


def _fake_response() -> OrganizationListResponse:
    now = datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC)
    return OrganizationListResponse(
        organizations=[
            OrganizationResponse(
                id="org-1",
                name="Acme",
                public_id="acme",
                created_at=now,
                updated_at=now,
            ),
            # Populated the way `/orgs` really answers — captured from a live
            # response, not written from memory. The endpoint fills
            # member_count, node_count, is_public and role; only invite_mode
            # comes back null, which is what `_merged` exists to patch up for
            # `show`. `org-1` above leaves them unset on purpose, so both the
            # populated and the absent (`—`) paths are covered.
            OrganizationResponse(
                id="org-2",
                name="Beta Corp",
                public_id="beta",
                created_at=now,
                updated_at=now,
                is_public=True,
                role=OrganizationResponseRoleType0.OWNER,
                member_count=3,
                node_count=12,
            ),
        ],
        total=2,
    )


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_table_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs", "list"])
    assert result.exit_code == 0, result.output
    assert "Acme" in result.output
    assert "Beta Corp" in result.output
    assert "Organizations (2)" in result.output


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_shows_counts_visibility_and_role(_get_client, _sync) -> None:
    """The columns the web app shows, from the same single request."""
    result = runner.invoke(app, ["orgs", "list"], terminal_width=200)
    assert result.exit_code == 0, result.output
    plain = _cells(result.output)
    for header in ("Members", "Nodes", "Visibility", "Role"):
        assert header in plain, f"missing {header} column"
    # org-2 is fully populated; org-1 is not.
    assert "Beta Corp 3 12 public owner" in plain
    assert "Acme — — private —" in plain


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_json_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Acme"


def test_orgs_is_a_group_not_a_command() -> None:
    """A bare noun prints help, the way `gh repo` does — it never lists."""
    result = runner.invoke(app, ["orgs"])
    assert "list" in result.output
    assert "Acme" not in result.output


@pytest.mark.parametrize("bad", ["xml", "yaml", ""])
def test_orgs_list_rejects_an_unknown_format(bad: str) -> None:
    """`--format` is an enum, so a typo errors instead of silently tabling."""
    result = runner.invoke(app, ["orgs", "list", "--format", bad])
    assert result.exit_code != 0


@patch(
    "yertle.orgs.list_organizations_orgs_get.sync",
    side_effect=UnexpectedStatus(401, b'{"detail":"Invalid or expired token"}'),
)
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_renders_an_api_error_as_a_sentence(_get_client, _sync) -> None:
    """A wire failure exits 1 with prose naming the backend, not a traceback."""
    result = runner.invoke(app, ["orgs", "list"])
    assert result.exit_code == 1
    assert "401 Unauthorized" in result.output
    assert "Traceback" not in result.output


# --- `yertle orgs use` -------------------------------------------------------


@pytest.fixture
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A config file the test owns, and no ambient $YERTLE_ORG."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", path)
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)
    return path


ORG_ID = "8f14e45f-ceea-467a-9575-28db8d0dc4db"


def test_orgs_use_persists_the_org(isolated_config) -> None:
    result = runner.invoke(app, ["orgs", "use", ORG_ID])
    assert result.exit_code == 0, result.output
    assert ORG_ID in result.output
    assert json.loads(isolated_config.read_text())["org"] == ORG_ID


def test_orgs_use_all_resets(isolated_config) -> None:
    runner.invoke(app, ["orgs", "use", ORG_ID])
    result = runner.invoke(app, ["orgs", "use", "all"])
    assert result.exit_code == 0, result.output
    assert "every org" in result.output
    assert json.loads(isolated_config.read_text())["org"] == "all"


def test_orgs_use_rejects_a_malformed_id(isolated_config) -> None:
    result = runner.invoke(app, ["orgs", "use", "acme-corp"])
    assert result.exit_code == 1
    assert "not an organization id" in result.output
    assert not isolated_config.exists(), "a rejected id must not be written"


def test_orgs_use_keeps_credentials(isolated_config) -> None:
    """The whole risk of writing to this file is clobbering the token."""
    auth_mod.save_credentials(api_url="https://api.example.test", token="yrt_secret")
    runner.invoke(app, ["orgs", "use", ORG_ID])
    stored = json.loads(isolated_config.read_text())
    assert stored["token"] == "yrt_secret"
    assert stored["api_url"] == "https://api.example.test"
    assert stored["org"] == ORG_ID


# --- `yertle orgs show` ------------------------------------------------------
#
# Both payloads are captured from live responses. The asymmetry between them is
# the point of the backfill: `/orgs/{id}` returns `invite_mode` but leaves
# `role` and `member_count` null, while `/orgs` returns the opposite.

_DETAIL = {
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

_SUMMARY = {**_DETAIL, "role": "owner", "member_count": 4, "invite_mode": None}

_GET_ORG = "yertle.orgs.get_organization_orgs_org_id_get.sync"
_LIST_ORGS = "yertle.orgs.list_organizations_orgs_get.sync"


def _detail(**overrides: object) -> OrganizationResponse:
    return OrganizationResponse.from_dict({**_DETAIL, **overrides})


def _summary_list() -> OrganizationListResponse:
    return OrganizationListResponse(
        organizations=[OrganizationResponse.from_dict(_SUMMARY)],
        total=1,
    )


@patch(_LIST_ORGS, return_value=_summary_list())
@patch(_GET_ORG, return_value=_detail())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_renders_the_detail_view(_get_client, _get, _list) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG_ID])
    assert result.exit_code == 0, result.output
    assert "Yertle" in result.output
    assert "The platform org." in result.output
    assert "yertle-befed489" in result.output
    assert "open" in result.output
    assert "public" in result.output
    assert "13" in result.output


@patch(_LIST_ORGS, return_value=_summary_list())
@patch(_GET_ORG, return_value=_detail())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_backfills_role_and_members(_get_client, _get, list_orgs) -> None:
    """A detail view must never show less than the list view for the same org."""
    result = runner.invoke(app, ["orgs", "show", ORG_ID])
    assert result.exit_code == 0, result.output
    assert "owner" in result.output
    assert "4" in result.output
    assert list_orgs.called, "should have consulted /orgs to fill the gaps"


@patch(_LIST_ORGS)
@patch(_GET_ORG, return_value=_detail(role="editor", member_count=9))
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_skips_the_backfill_when_unnecessary(_get_client, _get, list_orgs) -> None:
    """If the detail endpoint ever populates role, stop paying for a second call."""
    result = runner.invoke(app, ["orgs", "show", ORG_ID])
    assert result.exit_code == 0, result.output
    assert "editor" in result.output
    assert not list_orgs.called


@patch(_LIST_ORGS, return_value=OrganizationListResponse(organizations=[], total=0))
@patch(_GET_ORG, return_value=_detail())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_renders_unknown_fields_as_a_dash(_get_client, _get, _list) -> None:
    """An absent member count is not zero, and must not look like one."""
    result = runner.invoke(app, ["orgs", "show", ORG_ID])
    assert result.exit_code == 0, result.output
    assert "—" in result.output


@patch(_LIST_ORGS, return_value=_summary_list())
@patch(_GET_ORG, return_value=_detail(description=""))
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_omits_an_empty_description(_get_client, _get, _list) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG_ID])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].strip() == "Yertle"
    assert lines[1].strip() == ORG_ID


@patch(_LIST_ORGS, return_value=_summary_list())
@patch(_GET_ORG, return_value=_detail())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_json_dumps_an_object(_get_client, _get, _list) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG_ID, "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    assert parsed["name"] == "Yertle"


def test_orgs_show_rejects_all() -> None:
    result = runner.invoke(app, ["orgs", "show", "all"])
    assert result.exit_code == 1
    assert "needs one organization id" in result.output


def test_orgs_show_rejects_a_malformed_id() -> None:
    result = runner.invoke(app, ["orgs", "show", "acme-corp"])
    assert result.exit_code == 1
    assert "not an organization id" in result.output


@patch(_LIST_ORGS, return_value=_summary_list())
@patch(_GET_ORG, return_value=_detail(id="9f14e45f-ceea-467a-9575-28db8d0dc4db"))
@patch("yertle._client.get_client", return_value=object())
def test_orgs_show_survives_a_backfill_miss(_get_client, _get, _list) -> None:
    """If the list response does not contain the org, show what we have."""
    result = runner.invoke(app, ["orgs", "show", "9f14e45f-ceea-467a-9575-28db8d0dc4db"])
    assert result.exit_code == 0, result.output
    assert "—" in result.output


def test_orgs_group_listing_mentions_how_to_clear() -> None:
    """`yertle orgs` must name 'all' as the way out of a scoped default.

    The group's command list is where someone scoped to one org actually looks
    when they want every org back, and Typer builds it from the first line of
    each docstring — so a well-meaning rewrite of that line silently removes
    the only signpost. `--help` and `about` both document it, but neither is
    on the path of a user who does not yet know the option exists.
    """
    result = runner.invoke(app, ["orgs"])
    assert "all" in result.output, (
        "`yertle orgs` no longer mentions 'all'; check the first line of "
        "use_org's docstring, which Typer renders as the short help."
    )
