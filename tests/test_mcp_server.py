"""Unit tests for the FastMCP server tools — fake service, no network."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from idrd import mcp_server
from idrd.models import Schedule

# ── Fake service ──────────────────────────────────────────────────────────


class FakeService:
    """Minimal stand-in for IdrdService used by the MCP tools."""

    def __init__(self) -> None:
        self.schedules = {
            11409: Schedule(
                id=11409,
                program_name="BOGOTÁ FELIZ",
                activity_name="CAMINATAS RECREATIVAS",
                stage_name="PLAZA CULTURAL SANTA MARIA",
                park_name="INDEPENDENCIA-BICENTENARIO",
                quota=40,
                taken=32,
            ),
            11410: Schedule(
                id=11410,
                program_name="BOGOTÁ FELIZ",
                activity_name="AERÓBICOS",
                quota=20,
                taken=5,
            ),
        }

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        return self.schedules.get(schedule_id)

    async def search_schedules(self, **kwargs: Any) -> tuple[list[Schedule], dict, dict]:
        items = sorted(self.schedules.values(), key=lambda s: s.id)
        return items, {}, {"current_page": 1, "last_page": 1, "total": len(items)}


@pytest.fixture(autouse=True)
def _tmp_bookmarks_path(tmp_path, monkeypatch):
    """Point the bookmark store at a temp file for every test."""
    monkeypatch.setenv("IDRD_BOOKMARKS_PATH", str(tmp_path / "bookmarks.json"))
    yield


@pytest.fixture
def fake_service(monkeypatch) -> FakeService:
    service = FakeService()
    monkeypatch.setattr(mcp_server, "_get_service", lambda: service)
    monkeypatch.setattr(mcp_server, "_service", service)
    return service


# ── get_activity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_activity(fake_service) -> None:
    result = await mcp_server.get_activity(11409)
    assert result["id"] == 11409
    assert result["activity_name"] == "CAMINATAS RECREATIVAS"


@pytest.mark.asyncio
async def test_get_activity_not_found(fake_service) -> None:
    with pytest.raises(ValueError, match="not found"):
        await mcp_server.get_activity(99999)


# ── search_activities ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_activities(fake_service) -> None:
    result = await mcp_server.search_activities()
    assert result["meta"]["total"] == 2
    assert [r["id"] for r in result["results"]] == [11409, 11410]


@pytest.mark.asyncio
async def test_search_activities_passes_filters(fake_service) -> None:
    result = await mcp_server.search_activities(
        category="ATLETISMO",
        program_id=[12],
        locality=5,
        page=2,
    )
    assert result["meta"]["total"] == 2


# ── bookmark flow ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bookmark_activity(fake_service, tmp_path) -> None:
    result = await mcp_server.bookmark_activity(11409, note="quiero ir")

    assert result["bookmarked"] is True
    assert result["bookmark"]["schedule_id"] == 11409
    assert result["bookmark"]["note"] == "quiero ir"
    assert result["bookmark"]["schedule"]["activity_name"] == "CAMINATAS RECREATIVAS"

    listed = await mcp_server.list_bookmarks()
    assert listed["count"] == 1
    assert listed["bookmarks"][0]["schedule_id"] == 11409

    checked = await mcp_server.is_bookmarked(11409)
    assert checked["bookmarked"] is True


@pytest.mark.asyncio
async def test_bookmark_activity_not_found(fake_service) -> None:
    with pytest.raises(ValueError, match="not found"):
        await mcp_server.bookmark_activity(99999)


@pytest.mark.asyncio
async def test_remove_bookmark(fake_service) -> None:
    await mcp_server.bookmark_activity(11409)
    result = await mcp_server.remove_bookmark(11409)
    assert result == {"schedule_id": 11409, "removed": True}

    listed = await mcp_server.list_bookmarks()
    assert listed["count"] == 0
    assert (await mcp_server.is_bookmarked(11409))["bookmarked"] is False


@pytest.mark.asyncio
async def test_remove_bookmark_missing(fake_service) -> None:
    result = await mcp_server.remove_bookmark(555)
    assert result == {"schedule_id": 555, "removed": False}


# ── server surface ────────────────────────────────────────────────────────


def test_tool_names_registered() -> None:
    """Every expected tool name is registered on the FastMCP server."""
    import asyncio

    tool_names = {
        tool.name
        for tool in asyncio.run(mcp_server.mcp.list_tools())
    }
    expected = {
        "search_activities",
        "get_activity",
        "bookmark_activity",
        "list_bookmarks",
        "remove_bookmark",
        "is_bookmarked",
    }
    assert expected.issubset(tool_names)
