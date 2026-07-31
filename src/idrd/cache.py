"""Response caching layer for the IDRD client.

The CLI is one-shot (a fresh process per invocation), so an in-memory
cache alone would never serve a second command. The default backend is a
TTL-bounded JSON cache on disk under ``~/.idrd/cache`` (override with the
``IDRD_CACHE_DIR`` env var; TTL with ``IDRD_CACHE_TTL`` seconds). A
``MemoryCache`` exists for tests and in-process reuse.

Only read/search endpoints are cached (the API is rate-limited,
``X-Ratelimit-Limit: 300``). Auth/write calls (login, enroll, my-bookings,
whoami) and hidden-id probing always pass straight through to the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Type, runtime_checkable

from idrd.models import (
    AuthToken,
    Booking,
    Category,
    Program,
    Schedule,
    Stage,
    User,
)
from idrd.ports import IdrdClientPort

DEFAULT_TTL = 300.0  # seconds

_CACHE_KEY_VERSION = "v1"


def cache_key(*parts: Any) -> str:
    """Deterministic sha256 key from JSON-safe parts.

    ``sort_keys=True`` + explicit separators keep the key stable across
    processes, so the same query always maps to the same file.
    """
    payload = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_cache_dir() -> Path:
    override = os.environ.get("IDRD_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".idrd" / "cache"


def _env_ttl() -> Optional[float]:
    raw = os.environ.get("IDRD_CACHE_TTL")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@runtime_checkable
class Cache(Protocol):
    """Generic TTL cache backend (async interface to match the client)."""

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value or None."""
        ...

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds (default: instance TTL)."""
        ...

    async def delete(self, key: str) -> None:
        """Remove one entry."""
        ...

    async def clear(self) -> int:
        """Remove all entries; return how many were removed."""
        ...


class MemoryCache:
    """In-process TTL cache (tests / long-running processes)."""

    def __init__(self, ttl: Optional[float] = None) -> None:
        # None ttl = never expires
        self._ttl = ttl
        self._entries: dict[str, tuple[Optional[float], Any]] = {}

    async def get(self, key: str) -> Optional[Any]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and time.monotonic() > expires_at:
            self._entries.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        effective = ttl if ttl is not None else self._ttl
        expires_at = time.monotonic() + effective if effective is not None else None
        self._entries[key] = (expires_at, value)

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def clear(self) -> int:
        removed = len(self._entries)
        self._entries.clear()
        return removed


class FileCache:
    """JSON-file-backed TTL cache. One file per key, atomic writes.

    Uses wall-clock time (not monotonic) so TTLs stay comparable across
    separate CLI processes. Corrupt or expired files are treated as misses
    and removed.
    """

    def __init__(
        self,
        cache_dir: Optional[Path | str] = None,
        ttl: Optional[float] = None,
    ) -> None:
        self._dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl if ttl is not None else (_env_ttl() or DEFAULT_TTL)

    def _path(self, key: str) -> Path:
        # keys are sha256 hexdigests → safe as filenames
        return self._dir / f"{key}.json"

    async def get(self, key: str) -> Optional[Any]:
        path = self._path(key)
        try:
            raw = path.read_text(encoding="utf-8")
            entry = json.loads(raw)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            self._discard(path)
            return None
        created = entry.get("created_at", 0.0)
        entry_ttl = entry.get("ttl")
        if entry_ttl is not None and time.time() - created >= entry_ttl:
            self._discard(path)
            return None
        return entry.get("value")

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        effective = ttl if ttl is not None else self._ttl
        entry = {"created_at": time.time(), "ttl": effective, "value": value}
        # atomic write: temp file + os.replace so concurrent CLI runs never
        # observe a half-written entry
        tmp = self._dir / f"{key}.json.tmp"
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path(key))

    async def delete(self, key: str) -> None:
        self._discard(self._path(key))

    async def clear(self) -> int:
        removed = 0
        for path in list(self._dir.glob("*.json")) + list(self._dir.glob("*.json.tmp")):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def stats(self) -> dict[str, Any]:
        """Sync introspection for the `idrd cache stats` command."""
        now = time.time()
        ages: list[float] = []
        entries = 0
        for path in self._dir.glob("*.json"):
            entries += 1
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                ages.append(now - entry.get("created_at", now))
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return {
            "dir": str(self._dir),
            "entries": entries,
            "oldest_seconds": max(ages) if ages else 0.0,
            "ttl_default": self._ttl,
        }

    def _discard(self, path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass


class CachedClient:
    """IdrdClientPort decorator that caches read/search calls.

    Wraps a delegate client and stores successful responses of the
    read-only endpoints (search_schedules, get_schedule, list_programs,
    list_categories, list_stages) in a ``Cache`` backend. Failed calls are
    never cached. Auth/write methods and ``discover_hidden`` pass through
    untouched.

    Exposes ``hits`` / ``misses`` counters (per process) so callers can
    report whether output came from the cache.
    """

    _CACHEABLE = frozenset(
        {
            "search_schedules",
            "get_schedule",
            "list_programs",
            "list_categories",
            "list_stages",
        }
    )

    def __init__(
        self,
        delegate: IdrdClientPort,
        cache: Optional[Cache] = None,
        ttl: Optional[float] = None,
    ) -> None:
        self._delegate = delegate
        self._cache: Cache = cache if cache is not None else FileCache(ttl=ttl)
        self._ttl = ttl
        self.hits = 0
        self.misses = 0

    async def _cached_call(
        self,
        key: str,
        serialize: Callable[[Any], Any],
        deserialize: Callable[[Any], Any],
        loader: Callable[[], Any],
    ) -> Any:
        cached = await self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return deserialize(cached)
        self.misses += 1
        result = await loader()
        await self._cache.set(key, serialize(result), ttl=self._ttl)
        return result

    async def _cached_model_list(
        self,
        key: str,
        model_type: Type,
        loader: Callable[[], Any],
    ) -> Any:
        return await self._cached_call(
            key,
            serialize=lambda items: [m.model_dump(mode="json") for m in items],
            deserialize=lambda data: [model_type.model_validate(item) for item in data],
            loader=loader,
        )

    # ── cached reads ─────────────────────────────────────────────────────

    async def search_schedules(
        self,
        category: Optional[str] = None,
        program_id: Optional[list[int]] = None,
        locality: Optional[int] = None,
        page: int = 1,
    ) -> tuple[list[Schedule], dict, dict]:
        key = cache_key(
            _CACHE_KEY_VERSION,
            "search_schedules",
            {
                "category": category,
                "program_id": sorted(program_id) if program_id else None,
                "locality": locality,
                "page": page,
            },
        )
        return await self._cached_call(
            key,
            serialize=lambda res: {
                "schedules": [s.model_dump(mode="json") for s in res[0]],
                "links": res[1],
                "meta": res[2],
            },
            deserialize=lambda data: (
                [Schedule.model_validate(item) for item in data["schedules"]],
                data["links"],
                data["meta"],
            ),
            loader=lambda: self._delegate.search_schedules(
                category=category,
                program_id=program_id,
                locality=locality,
                page=page,
            ),
        )

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        key = cache_key(_CACHE_KEY_VERSION, "get_schedule", schedule_id)
        return await self._cached_call(
            key,
            serialize=lambda s: {
                "schedule": s.model_dump(mode="json") if s is not None else None
            },
            deserialize=lambda data: (
                Schedule.model_validate(data["schedule"]) if data["schedule"] else None
            ),
            loader=lambda: self._delegate.get_schedule(schedule_id),
        )

    async def list_programs(self) -> list[Program]:
        return await self._cached_model_list(
            cache_key(_CACHE_KEY_VERSION, "list_programs"),
            Program,
            self._delegate.list_programs,
        )

    async def list_categories(self) -> list[Category]:
        return await self._cached_model_list(
            cache_key(_CACHE_KEY_VERSION, "list_categories"),
            Category,
            self._delegate.list_categories,
        )

    async def list_stages(self) -> list[Stage]:
        return await self._cached_model_list(
            cache_key(_CACHE_KEY_VERSION, "list_stages"),
            Stage,
            self._delegate.list_stages,
        )

    # ── pass-through (auth / write / probing) ────────────────────────────

    async def login(self, email: str, password: str) -> AuthToken:
        return await self._delegate.login(email, password)

    async def enroll(self, profile_id: int, schedule_id: int) -> dict:
        return await self._delegate.enroll(profile_id, schedule_id)

    async def my_bookings(self) -> list[Booking]:
        return await self._delegate.my_bookings()

    async def whoami(self) -> Optional[User]:
        return await self._delegate.whoami()

    async def discover_hidden(
        self, max_probe: int = 5, delay: float = 0.05
    ) -> tuple[list[int], list[int]]:
        return await self._delegate.discover_hidden(max_probe=max_probe, delay=delay)
