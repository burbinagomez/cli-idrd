"""Protocol (port) for the IDRD client — enables DI and unit testing."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from idrd.models import (
    AuthToken,
    Booking,
    Category,
    Profile,
    Program,
    Schedule,
    Stage,
    User,
)


@runtime_checkable
class IdrdClientPort(Protocol):
    """Port interface for the IDRD API client."""

    async def login(self, email: str, password: str) -> AuthToken:
        """Authenticate and return an access token."""
        ...

    async def search_schedules(
        self,
        category: Optional[str] = None,
        program_id: Optional[List[int]] = None,
        locality: Optional[int] = None,
        page: int = 1,
    ) -> tuple[list[Schedule], dict, dict]:
        """Search public schedules. Returns (items, links, meta)."""
        ...

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        """Get a single schedule by id."""
        ...

    async def discover_hidden(
        self, max_probe: int = 5, delay: float = 0.05
    ) -> tuple[list[int], list[int]]:
        """Probe singular schedule ids past the public list.

        Returns (found_ids, probed_ids).
        """
        ...

    async def list_programs(self) -> list[Program]:
        """List all programs."""
        ...

    async def list_categories(self) -> list[Category]:
        """List all activity categories."""
        ...

    async def list_stages(self) -> list[Stage]:
        """List all stages/scenarios."""
        ...

    async def list_profiles(self) -> list[Profile]:
        """List beneficiary profiles for the current user (auth)."""
        ...

    async def enroll(self, profile_id: int, schedule_id: int) -> dict:
        """Enroll a profile in a schedule."""
        ...

    async def my_bookings(self) -> list[Booking]:
        """List current user's bookings."""
        ...

    async def whoami(self) -> Optional[User]:
        """Get current user info."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        ...
