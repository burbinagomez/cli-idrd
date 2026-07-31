"""Unit tests for the local bookmark store — no network, uses tmp paths."""

from __future__ import annotations

import json

import pytest

from idrd import bookmarks
from idrd.models import Schedule
from pathlib import Path


@pytest.fixture(autouse=True)
def _tmp_bookmarks_path(tmp_path, monkeypatch):
    """Point the bookmark store at a temp file for every test."""
    monkeypatch.setenv("IDRD_BOOKMARKS_PATH", str(tmp_path / "bookmarks.json"))
    yield


def _schedule(schedule_id: int = 11409, activity_name: str = "CAMINATAS RECREATIVAS") -> Schedule:
    return Schedule(
        id=schedule_id,
        program_name="BOGOTÁ FELIZ",
        activity_name=activity_name,
        stage_name="PLAZA CULTURAL SANTA MARIA",
        park_name="INDEPENDENCIA-BICENTENARIO",
        park_address="CALLE 24 N 6A 01",
        weekday_name="VIERNES 31 DE JULIO DE 2026",
        daily_name="06:00 P.M. A 08:00 P.M.",
        quota=40,
        taken=32,
        is_paid=False,
    )


def test_bookmarks_path_uses_env_override(monkeypatch):
    monkeypatch.setenv("IDRD_BOOKMARKS_PATH", "C:/tmp/custom.json")
    assert str(bookmarks.bookmarks_path()) == str(Path("C:/tmp/custom.json"))


def test_empty_store(tmp_path):
    assert bookmarks.list_bookmarks() == []
    assert bookmarks.is_bookmarked(11409) is False
    assert bookmarks.remove_bookmark(11409) is False


def test_add_bookmark_persists(tmp_path):
    record = bookmarks.add_bookmark(_schedule(), note="check this one")

    assert record["schedule_id"] == 11409
    assert record["note"] == "check this one"
    assert record["bookmarked_at"]
    assert record["schedule"]["activity_name"] == "CAMINATAS RECREATIVAS"
    assert record["schedule"]["quota"] == 40

    # File exists on disk and is loadable JSON
    path = tmp_path / "bookmarks.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["schedule_id"] == 11409


def test_add_bookmark_dedupes_and_refreshes(tmp_path):
    first = bookmarks.add_bookmark(_schedule(), note="old note")
    updated = bookmarks.add_bookmark(
        _schedule(activity_name="NUEVO NOMBRE"),
        note="new note",
    )

    items = bookmarks.list_bookmarks()
    assert len(items) == 1  # same schedule_id replaced, not duplicated
    assert items[0]["note"] == "new note"
    assert items[0]["schedule"]["activity_name"] == "NUEVO NOMBRE"
    assert items[0]["bookmarked_at"] != first["bookmarked_at"]


def test_add_bookmark_multiple_schedules(tmp_path):
    bookmarks.add_bookmark(_schedule(11409))
    bookmarks.add_bookmark(_schedule(11410, activity_name="AERÓBICOS"))

    items = bookmarks.list_bookmarks()
    assert len(items) == 2
    assert bookmarks.is_bookmarked(11409) is True
    assert bookmarks.is_bookmarked(11410) is True
    assert bookmarks.is_bookmarked(99999) is False


def test_remove_bookmark(tmp_path):
    bookmarks.add_bookmark(_schedule(11409))
    assert bookmarks.remove_bookmark(11409) is True
    assert bookmarks.list_bookmarks() == []
    # Removing again is a no-op
    assert bookmarks.remove_bookmark(11409) is False


def test_load_bookmarks_handles_corrupt_file(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert bookmarks.load_bookmarks() == []
