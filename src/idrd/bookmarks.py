"""Local bookmark store — ~/.idrd/bookmarks.json.

The IDRD API has no bookmark endpoint, so bookmarks live on disk next to the
session token. Each bookmark is a snapshot of a schedule plus an optional note.

Path resolution: IDRD_BOOKMARKS_PATH env var wins (used by tests and power
users); otherwise ~/.idrd/bookmarks.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from idrd.models import Schedule

_BOOKMARK_FIELDS = (
    "id",
    "icon",
    "program_name",
    "activity_name",
    "stage_name",
    "park_code",
    "park_name",
    "park_address",
    "weekday_name",
    "daily_name",
    "min_age",
    "max_age",
    "quota",
    "taken",
    "is_paid",
    "is_initiate",
    "start_date",
    "final_date",
    "is_activated",
    "disability",
)


def bookmarks_path() -> Path:
    """Resolve the bookmarks file path (env override first)."""
    override = os.environ.get("IDRD_BOOKMARKS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".idrd" / "bookmarks.json"


def load_bookmarks() -> list[dict[str, Any]]:
    """Load bookmarks from disk (empty list when missing/corrupt)."""
    path = bookmarks_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save(items: list[dict[str, Any]]) -> None:
    path = bookmarks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _snapshot(schedule: Schedule) -> dict[str, Any]:
    """Extract a stable, compact snapshot from a Schedule."""
    data = schedule.model_dump(mode="json")
    return {field: data.get(field) for field in _BOOKMARK_FIELDS}


def add_bookmark(
    schedule: Schedule,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Add (or refresh) a bookmark for a schedule. Returns the stored record."""
    items = load_bookmarks()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    record: dict[str, Any] = {
        "schedule_id": schedule.id,
        "schedule": _snapshot(schedule),
        "note": note or "",
        "bookmarked_at": now,
    }
    # Replace existing bookmark for the same schedule (refresh + keep position).
    items = [item for item in items if item.get("schedule_id") != schedule.id]
    items.append(record)
    _save(items)
    return record


def remove_bookmark(schedule_id: int) -> bool:
    """Remove a bookmark by schedule id. Returns True if one was removed."""
    items = load_bookmarks()
    remaining = [item for item in items if item.get("schedule_id") != schedule_id]
    if len(remaining) == len(items):
        return False
    _save(remaining)
    return True


def list_bookmarks() -> list[dict[str, Any]]:
    """Return all bookmarks, most recently bookmarked last (append order)."""
    return load_bookmarks()


def is_bookmarked(schedule_id: int) -> bool:
    """Return True when a bookmark exists for the schedule id."""
    return any(item.get("schedule_id") == schedule_id for item in load_bookmarks())
