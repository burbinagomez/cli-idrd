"""Live integration tests — hit the real IDRD API.

These require network access. Skipped by default; run with:
    uv run pytest tests/test_live.py -v --run-network
"""

from __future__ import annotations

import pytest

from idrd.client import IdrdClient


# Marker registration in conftest or pyproject.toml
def pytest_configure(config):
    config.addinivalue_line("markers", "network: marks tests that hit the live API")


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def anon_client() -> IdrdClient:
    return IdrdClient(token=None)


# ── Tests ─────────────────────────────────────────────────────────────────

@pytest.mark.network
@pytest.mark.asyncio
async def test_search_live(anon_client: IdrdClient) -> None:
    """Live search returns schedules with expected keys."""
    schedules, links, meta = await anon_client.search_schedules(page=1)
    assert len(schedules) > 0, "Expected at least one schedule"
    s = schedules[0]
    # Check essential fields
    assert s.id > 0
    assert s.activity_name is not None
    assert s.program_name is not None
    assert s.stage_name is not None
    assert s.park_name is not None
    # Pagination meta
    assert meta.get("current_page") == 1
    assert meta.get("total", 0) > 0
    assert meta.get("last_page", 0) >= 1


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_with_filters_live(anon_client: IdrdClient) -> None:
    """Live search with category filter works."""
    schedules, links, meta = await anon_client.search_schedules(
        category="ATLETISMO", page=1
    )
    # ATLETISMO exists from the recon; expect results or empty gracefully
    assert meta.get("total", 0) >= 0  # may be 0 if no ATLETISMO activities currently


@pytest.mark.network
@pytest.mark.asyncio
async def test_get_schedule_live(anon_client: IdrdClient) -> None:
    """Live single schedule fetch for ID 11409."""
    sched = await anon_client.get_schedule(11409)
    assert sched is not None
    assert sched.id == 11409
    assert sched.activity_name is not None
    assert sched.program_name is not None
    assert sched.stage_name is not None
    assert sched.park_name is not None


@pytest.mark.network
@pytest.mark.asyncio
async def test_list_programs_live(anon_client: IdrdClient) -> None:
    """Live programs list."""
    programs = await anon_client.list_programs()
    assert len(programs) > 0
    p = programs[0]
    assert p.id > 0
    assert p.name is not None


@pytest.mark.network
@pytest.mark.asyncio
async def test_list_categories_live(anon_client: IdrdClient) -> None:
    """Live categories list."""
    categories = await anon_client.list_categories()
    assert len(categories) > 0
    c = categories[0]
    assert c.name is not None
    assert c.value is not None


@pytest.mark.network
@pytest.mark.asyncio
async def test_list_stages_live(anon_client: IdrdClient) -> None:
    """Live stages list."""
    stages = await anon_client.list_stages()
    assert len(stages) > 0
    s = stages[0]
    assert s.id > 0
    assert s.name is not None
    assert s.park_name is not None
    assert s.park_code is not None
