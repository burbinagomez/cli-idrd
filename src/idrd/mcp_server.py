"""FastMCP server exposing IDRD Portal Ciudadano activities + local bookmarks.

Run with:  uv run idrd-mcp        (stdio, for MCP clients)
       or:  fastmcp run src/idrd/mcp_server.py:mcp --transport http

Bookmarks are stored locally in ~/.idrd/bookmarks.json (the IDRD API has no
bookmark endpoint). Override the location with IDRD_BOOKMARKS_PATH.
"""

from __future__ import annotations

from typing import Any, Optional

from fastmcp import FastMCP

from idrd.bookmarks import (
    add_bookmark as store_add_bookmark,
    is_bookmarked as store_is_bookmarked,
    list_bookmarks as store_list_bookmarks,
    remove_bookmark as store_remove_bookmark,
)
from idrd.client import IdrdClient
from idrd.models import Schedule
from idrd.service import IdrdService

mcp = FastMCP(
    "idrd",
    instructions=(
        "IDRD Portal Ciudadano — Bogotá recreation institute. Search public "
        "activity schedules, view details, and keep a local bookmark list of "
        "activities you care about. Bookmarks are stored on this machine, not "
        "on the IDRD servers."
    ),
)

_service: Optional[IdrdService] = None


def _get_service() -> IdrdService:
    """Lazily build the service (auto-loads session token from disk)."""
    global _service
    if _service is None:
        _service = IdrdService(IdrdClient())
    return _service


def _schedule_dict(schedule: Schedule) -> dict[str, Any]:
    return schedule.model_dump(mode="json")


async def _fetch_schedule(schedule_id: int) -> Schedule:
    """Fetch a schedule by id, raising ValueError with a clean message."""
    try:
        schedule = await _get_service().get_schedule(schedule_id)
    except Exception as e:  # httpx errors, timeouts, upstream 5xx
        raise ValueError(f"IDRD get_activity failed: {e}") from e
    if schedule is None:
        raise ValueError(f"Activity {schedule_id} not found.")
    return schedule


@mcp.tool
async def search_activities(
    category: Optional[str] = None,
    program_id: Optional[list[int]] = None,
    locality: Optional[int] = None,
    page: int = 1,
) -> dict[str, Any]:
    """Search public activity schedules.

    Args:
        category: Category filter value (e.g. "ATLETISMO"); omit for all.
        program_id: One or more program IDs to filter by (e.g. [12, 27]).
        locality: Locality ID to filter by (integer).
        page: Page number (10 items per page).

    Returns the matching schedules plus pagination meta.
    """
    try:
        schedules, _, meta = await _get_service().search_schedules(
            category=category,
            program_id=program_id,
            locality=locality,
            page=page,
        )
    except Exception as e:  # httpx errors, timeouts, upstream 5xx
        raise ValueError(f"IDRD search failed: {e}") from e
    return {
        "results": [_schedule_dict(s) for s in schedules],
        "meta": meta,
    }


@mcp.tool
async def get_activity(schedule_id: int) -> dict[str, Any]:
    """Fetch full details for one activity schedule by ID.

    Args:
        schedule_id: The activity/schedule ID (from search_activities).

    Raises ValueError when the activity does not exist or the API errors.
    """
    return _schedule_dict(await _fetch_schedule(schedule_id))


@mcp.tool
async def bookmark_activity(
    schedule_id: int,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Bookmark an activity schedule for later (stored locally).

    Fetches the current schedule details and saves a snapshot plus an
    optional note to the local bookmark store. Bookmarking the same activity
    again refreshes its snapshot and note.

    Args:
        schedule_id: The activity/schedule ID to bookmark.
        note: Optional free-text note to attach to the bookmark.

    Raises ValueError when the activity does not exist.
    """
    schedule = await _fetch_schedule(schedule_id)
    record = store_add_bookmark(schedule, note=note)
    return {
        "bookmarked": True,
        "bookmark": record,
    }


@mcp.tool
async def list_bookmarks() -> dict[str, Any]:
    """List all locally bookmarked activities, newest last."""
    items = store_list_bookmarks()
    return {
        "count": len(items),
        "bookmarks": items,
    }


@mcp.tool
async def remove_bookmark(schedule_id: int) -> dict[str, Any]:
    """Remove a locally bookmarked activity by schedule ID.

    Returns removed=False when no bookmark existed for that ID.
    """
    removed = store_remove_bookmark(schedule_id)
    return {
        "schedule_id": schedule_id,
        "removed": removed,
    }


@mcp.tool
async def is_bookmarked(schedule_id: int) -> dict[str, Any]:
    """Check whether an activity is already bookmarked locally."""
    return {
        "schedule_id": schedule_id,
        "bookmarked": store_is_bookmarked(schedule_id),
    }


def main() -> None:
    """Entry point for `uv run idrd-mcp` (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
