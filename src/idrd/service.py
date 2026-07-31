"""Service layer — business logic built on top of IdrdClientPort."""

from __future__ import annotations

from typing import Any, Optional

from idrd.models import AuthToken, Booking, Category, Program, Schedule, Stage, User
from idrd.ports import IdrdClientPort


class IdrdService:
    """Business-logic wrapper around the client port.

    Keeps CLI handlers thin — transform, decorate, or enrich data here.
    """

    def __init__(self, client: IdrdClientPort) -> None:
        self._client = client

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

    # ── Write / auth-gated ───────────────────────────────────────────────

    async def enroll(self, profile_id: int, schedule_id: int) -> dict:
        return await self._client.enroll(profile_id, schedule_id)

    async def my_bookings(self) -> list[Booking]:
        return await self._client.my_bookings()
