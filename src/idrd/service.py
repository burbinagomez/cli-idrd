"""Service layer — business logic built on top of IdrdClientPort."""

from __future__ import annotations

from typing import Any, Optional

from idrd.models import AuthToken, Booking, Category, Profile, Program, Schedule, Stage, User
from idrd.ports import IdrdClientPort


class IdrdService:
    """Business-logic wrapper around the client port.

    Keeps CLI handlers thin — transform, decorate, or enrich data here.
    """

    def __init__(self, client: IdrdClientPort) -> None:
        self._client = client

    @property
    def cache_stats(self) -> Optional[tuple[int, int]]:
        """(hits, misses) when the client has a caching layer, else None."""
        client = self._client
        if hasattr(client, "hits") and hasattr(client, "misses"):
            return client.hits, client.misses
        return None

    # ── Auth ──────────────────────────────────────────────────────────────

    async def login(self, email: str, password: str) -> AuthToken:
        return await self._client.login(email, password)

    async def whoami(self) -> Optional[User]:
        return await self._client.whoami()

    # ── Read (no auth) ───────────────────────────────────────────────────

    async def search_schedules(
        self,
        category: Optional[str] = None,
        program_id: Optional[list[int]] = None,
        locality: Optional[int] = None,
        page: int = 1,
    ) -> tuple[list[Schedule], dict, dict]:
        return await self._client.search_schedules(
            category=category,
            program_id=program_id,
            locality=locality,
            page=page,
        )

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        return await self._client.get_schedule(schedule_id)

    async def list_programs(self) -> list[Program]:
        return await self._client.list_programs()

    async def discover_hidden(
        self, max_probe: int = 800, delay: float = 0.05
    ) -> tuple[list[int], list[int]]:
        return await self._client.discover_hidden(max_probe=max_probe, delay=delay)

    async def list_categories(self) -> list[Category]:
        return await self._client.list_categories()

    async def list_stages(self) -> list[Stage]:
        return await self._client.list_stages()

    async def list_profiles(self) -> list[Profile]:
        return await self._client.list_profiles()

    # ── Write / auth-gated ───────────────────────────────────────────────

    async def enroll(
        self, profile_id: int, schedule_id: int
    ) -> dict:
        return await self._client.enroll(profile_id, schedule_id)

    async def enroll_for_user(
        self, schedule_id: int, profile_id: Optional[int] = None
    ) -> tuple[int, dict]:
        """Enroll a schedule, resolving the beneficiary profile when needed.

        When `profile_id` is omitted: uses the only profile if the user has
        exactly one, otherwise raises with the available profile ids so the
        caller can prompt for the right one.
        """
        pid = profile_id
        if pid is None:
            profiles = await self._client.list_profiles()
            if not profiles:
                raise RuntimeError(
                    "No beneficiary profiles found. Create one in the portal "
                    "(or pass --profile-id)."
                )
            if len(profiles) == 1:
                pid = profiles[0].id
            else:
                listing = ", ".join(
                    f"{p.id} ({p.full_name or '?'})" for p in profiles
                )
                raise RuntimeError(
                    f"Multiple profiles found — pass --profile-id. "
                    f"Available: {listing}"
                )
        result = await self._client.enroll(pid, schedule_id)
        return pid, result

    async def my_bookings(self) -> list[Booking]:
        return await self._client.my_bookings()

    async def close(self) -> None:
        """Release the underlying HTTP client resources."""
        await self._client.close()
