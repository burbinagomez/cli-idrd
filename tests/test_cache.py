"""Unit tests for the search caching layer — no live network.

Covers the Cache backends (MemoryCache, FileCache) and the CachedClient
port decorator: hit/miss behavior, TTL expiry, key stability, pass-through
of auth/write calls, and error non-caching.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import pytest

from idrd.cache import CachedClient, FileCache, MemoryCache, cache_key
from idrd.client import IdrdClient
from idrd.models import AuthToken, Booking, Category, Program, Schedule, Stage, User
from idrd.ports import IdrdClientPort
from idrd.service import IdrdService


# ── Fake delegate ─────────────────────────────────────────────────────────

class FakeClient:
    """Minimal IdrdClientPort implementation with call counters."""

    def __init__(self) -> None:
        self.search_calls = 0
        self.schedule_calls = 0
        self.program_calls = 0
        self.login_calls = 0
        self.fail_search = False

    async def login(self, email: str, password: str) -> AuthToken:
        self.login_calls += 1
        return AuthToken(access_token="tok", token_type="Bearer")

    async def search_schedules(
        self,
        category: Optional[str] = None,
        program_id: Optional[list[int]] = None,
        locality: Optional[int] = None,
        page: int = 1,
    ) -> tuple[list[Schedule], dict, dict]:
        self.search_calls += 1
        if self.fail_search:
            raise RuntimeError("boom")
        return (
            [Schedule(id=1, activity_name="CAMINATAS", program_name="BOGOTÁ FELIZ")],
            {"next": None},
            {"current_page": page, "last_page": 1, "total": 1},
        )

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        self.schedule_calls += 1
        return Schedule(id=schedule_id, activity_name="CAMINATAS")

    async def list_programs(self) -> list[Program]:
        self.program_calls += 1
        return [Program(id=1, name="BOGOTÁ FELIZ")]

    async def list_categories(self) -> list[Category]:
        return [Category(name="Atletismo", value="ATLETISMO")]

    async def list_stages(self) -> list[Stage]:
        return [Stage(id=1, name="PLAZA CULTURAL")]

    async def enroll(self, profile_id: int, schedule_id: int) -> dict:
        return {"ok": True}

    async def my_bookings(self) -> list[Booking]:
        return []

    async def whoami(self) -> Optional[User]:
        return None

    async def discover_hidden(
        self, max_probe: int = 5, delay: float = 0.05
    ) -> tuple[list[int], list[int]]:
        return [], []


def make_cached(fake: FakeClient) -> CachedClient:
    return CachedClient(fake, cache=MemoryCache())


# ── cache_key ─────────────────────────────────────────────────────────────

def test_cache_key_deterministic_and_distinct() -> None:
    k1 = cache_key("v1", "search", {"category": "ATLETISMO", "page": 1})
    k2 = cache_key("v1", "search", {"page": 1, "category": "ATLETISMO"})
    assert k1 == k2  # dict order must not matter
    k3 = cache_key("v1", "search", {"category": "NATACION", "page": 1})
    assert k1 != k3
    k4 = cache_key("v1", "get_schedule", 11409)
    assert k4 != k1


# ── MemoryCache ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_cache_roundtrip() -> None:
    cache = MemoryCache()
    assert await cache.get("k") is None
    await cache.set("k", {"a": 1})
    assert await cache.get("k") == {"a": 1}
    assert await cache.clear() == 1
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_memory_cache_expiry() -> None:
    cache = MemoryCache()
    await cache.set("k", "v", ttl=0.05)
    assert await cache.get("k") == "v"
    await asyncio.sleep(0.1)
    assert await cache.get("k") is None


# ── FileCache ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_cache_roundtrip(tmp_path: Path) -> None:
    cache = FileCache(cache_dir=tmp_path)
    assert await cache.get("missing") is None
    await cache.set("k", {"name": "BOGOTÁ FELIZ", "ids": [1, 2]})
    assert await cache.get("k") == {"name": "BOGOTÁ FELIZ", "ids": [1, 2]}
    assert (tmp_path / "k.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_file_cache_ttl_expiry_removes_file(tmp_path: Path) -> None:
    cache = FileCache(cache_dir=tmp_path)
    await cache.set("k", "v", ttl=0.05)
    assert await cache.get("k") == "v"
    await asyncio.sleep(0.1)
    assert await cache.get("k") is None
    assert not (tmp_path / "k.json").exists()


@pytest.mark.asyncio
async def test_file_cache_corrupt_file_treated_as_miss(tmp_path: Path) -> None:
    cache = FileCache(cache_dir=tmp_path)
    (tmp_path / "bad.json").write_text("{not json!!", encoding="utf-8")
    assert await cache.get("bad") is None
    assert not (tmp_path / "bad.json").exists()  # cleaned up


@pytest.mark.asyncio
async def test_file_cache_clear(tmp_path: Path) -> None:
    cache = FileCache(cache_dir=tmp_path)
    await cache.set("a", 1)
    await cache.set("b", 2)
    (tmp_path / "leftover.json.tmp").write_text("x", encoding="utf-8")
    removed = await cache.clear()
    assert removed == 3
    assert not list(tmp_path.glob("*.json")) and not list(tmp_path.glob("*.json.tmp"))


def test_file_cache_stats(tmp_path: Path) -> None:
    cache = FileCache(cache_dir=tmp_path, ttl=42)
    (tmp_path / "a.json").write_text(
        json.dumps({"created_at": 1.0, "ttl": 42, "value": 1}), encoding="utf-8"
    )
    info = cache.stats()
    assert info["entries"] == 1
    assert info["oldest_seconds"] > 0
    assert info["ttl_default"] == 42


# ── CachedClient ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_cached_twice() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    r1 = await cached.search_schedules(category="ATLETISMO", page=1)
    r2 = await cached.search_schedules(category="ATLETISMO", page=1)
    assert fake.search_calls == 1  # second call served from cache
    assert [s.id for s in r1[0]] == [s.id for s in r2[0]]
    assert r1[2]["current_page"] == r2[2]["current_page"] == 1
    assert (cached.hits, cached.misses) == (1, 1)


@pytest.mark.asyncio
async def test_search_different_filters_are_distinct_keys() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    await cached.search_schedules(category="ATLETISMO")
    await cached.search_schedules(category="NATACION")
    await cached.search_schedules(locality=5)
    assert fake.search_calls == 3


@pytest.mark.asyncio
async def test_search_empty_program_list_same_key_as_none() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    await cached.search_schedules(program_id=[])
    await cached.search_schedules(program_id=None)
    assert fake.search_calls == 1


@pytest.mark.asyncio
async def test_get_schedule_cached() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    s1 = await cached.get_schedule(11409)
    s2 = await cached.get_schedule(11409)
    assert fake.schedule_calls == 1
    assert s1 is not None and s2 is not None and s1.id == s2.id == 11409
    await cached.get_schedule(99999)
    assert fake.schedule_calls == 2  # different id → miss


@pytest.mark.asyncio
async def test_reference_lists_cached() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    p1 = await cached.list_programs()
    p2 = await cached.list_programs()
    assert fake.program_calls == 1
    assert p1 == p2
    await cached.list_categories()
    await cached.list_categories()
    await cached.list_stages()
    await cached.list_stages()


@pytest.mark.asyncio
async def test_login_not_cached() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    await cached.login("a@b.c", "x")
    await cached.login("a@b.c", "x")
    assert fake.login_calls == 2  # auth never cached


@pytest.mark.asyncio
async def test_failed_call_not_cached() -> None:
    fake = FakeClient()
    cached = make_cached(fake)
    fake.fail_search = True
    with pytest.raises(RuntimeError):
        await cached.search_schedules()
    with pytest.raises(RuntimeError):
        await cached.search_schedules()
    assert fake.search_calls == 2  # error did not poison/prime the cache
    fake.fail_search = False
    await cached.search_schedules()
    assert fake.search_calls == 3  # first successful call is the only miss


@pytest.mark.asyncio
async def test_cached_client_satisfies_port() -> None:
    cached = make_cached(FakeClient())
    assert isinstance(cached, IdrdClientPort)


# ── Service integration ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_cache_stats_with_cached_client() -> None:
    fake = FakeClient()
    service = IdrdService(CachedClient(fake, cache=MemoryCache()))
    assert service.cache_stats == (0, 0)  # counters exist, nothing read yet
    await service.search_schedules(page=1)
    await service.search_schedules(page=1)
    assert service.cache_stats == (1, 1)


@pytest.mark.asyncio
async def test_service_cache_stats_none_for_plain_client() -> None:
    service = IdrdService(IdrdClient(token=None))
    assert service.cache_stats is None
