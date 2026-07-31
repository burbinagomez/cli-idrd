"""IdrdClient — async HTTP client for the IDRD Portal Ciudadano API."""

from __future__ import annotations

from typing import Any, Optional, Union

import httpx
from pydantic import TypeAdapter

from idrd.models import (
    AuthToken,
    Booking,
    Category,
    LoginError,
    Program,
    Schedule,
    SingleResponse,
    Stage,
    User,
)
from idrd.ports import IdrdClientPort
from idrd.session import load_token, save_token

_UNSET = object()

#: Headers every request sends; shared by all httpx clients the class owns.
_DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "idrd-cli/0.1",
}


class IdrdClient(IdrdClientPort):
    """Concrete async client backed by httpx.AsyncClient.

    An instance is bound to the event loop in which it first performs
    requests — do not reuse one across ``asyncio.run()`` boundaries.
    The CLI creates a fresh instance per command and runs each command's
    awaits in a single loop.
    """

    BASE_URL = "https://portalciudadano-back.idrd.gov.co"

    def __init__(
        self,
        token: Union[AuthToken, None, object] = _UNSET,
        token_prefix: str = "Bearer",
    ) -> None:
        # _UNSET means "not provided" → auto-load from disk
        # None means "explicitly no token" → skip disk load
        if token is _UNSET:
            self._token = load_token()
        else:
            self._token = token
        self._token_prefix = token_prefix
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=dict(_DEFAULT_HEADERS),
            timeout=30.0,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _auth_header(self) -> dict[str, str]:
        """Return Authorization header if token is set."""
        if self._token:
            return {"Authorization": f"{self._token_prefix} {self._token.access_token}"}
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        **kwargs,
    ) -> httpx.Response:
        """Send a request, merging the auth header into any caller headers."""
        headers = dict(kwargs.pop("headers", {}))
        if auth:
            headers.update(self._auth_header())
        return await self._client.request(method, path, headers=headers, **kwargs)

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("POST", path, **kwargs)

    async def _put(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("PUT", path, **kwargs)

    async def _delete(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("DELETE", path, **kwargs)

    async def _check_auth(self) -> None:
        """Raise if no token is loaded."""
        if not self._token:
            raise RuntimeError(
                "Not authenticated. Run 'idrd login' first or provide a token."
            )

    # ── public API ────────────────────────────────────────────────────────

    async def login(self, email: str, password: str) -> AuthToken:
        """Authenticate, store the token, return it."""
        resp = await self._post(
            "/api/login",
            json={"email": email, "password": password},
            auth=False,
        )
        if resp.status_code == 401:
            err = LoginError.model_validate(resp.json())
            raise RuntimeError(err.message)
        if resp.status_code == 422:
            msg = resp.json().get("message", "Validation failed")
            raise RuntimeError(msg)
        resp.raise_for_status()
        token = AuthToken.model_validate(resp.json())
        self._token = token
        save_token(token)
        return token

    async def search_schedules(
        self,
        category: Optional[str] = None,
        program_id: Optional[list[int]] = None,
        locality: Optional[int] = None,
        page: int = 1,
    ) -> tuple[list[Schedule], dict, dict]:
        params: dict[str, Any] = {"page": page}
        if category:
            params["category"] = category
        if program_id:
            # API requires program_id[]=...
            params["program_id[]"] = [str(pid) for pid in program_id]
        if locality is not None:
            params["locality"] = str(locality)

        resp = await self._get("/api/citizen-portal/public-schedules", params=params)
        resp.raise_for_status()
        body = resp.json()

        data_list = body.get("data", [])
        schedules = [Schedule.model_validate(item) for item in data_list]
        links = body.get("links", {})
        meta = body.get("meta", {})
        return schedules, links, meta

    async def discover_hidden(
        self, max_probe: int = 5, delay: float = 0.05
    ) -> tuple[list[int], list[int]]:
        """Probe singular schedule ids past the public list to find hidden ones.

        `GET /api/citizen-portal/public-schedules/{id}` returns 200 for real
        activities and 404 past the last one, so we probe forward from the
        last known real id (11410) and stop at the first 404.
        Returns (found_ids, probed_ids).
        """
        import asyncio

        found: list[int] = []
        probed: list[int] = []
        start = 11410  # last known real activity id
        for pid in range(start, start + max_probe):
            url = f"/api/citizen-portal/public-schedules/{pid}"
            try:
                resp = await self._get(url)
            except httpx.HTTPError:
                # Transport error — boundary unknown past here, stop probing.
                probed.append(pid)
                break
            probed.append(pid)
            if resp.status_code == 404:
                # Boundary of real ids — stop probing.
                break
            if resp.status_code == 200:
                found.append(pid)
            await asyncio.sleep(delay)
        return found, probed

    async def get_schedule(self, schedule_id: int) -> Optional[Schedule]:
        """Get a single schedule by id (uses the shared client)."""
        resp = await self._get(f"/api/citizen-portal/public-schedules/{schedule_id}")
        resp.raise_for_status()
        body = resp.json()
        sr = SingleResponse.model_validate(body)
        if sr.data:
            return Schedule.model_validate(sr.data)
        return None

    async def list_programs(self) -> list[Program]:
        resp = await self._get("/api/citizen-portal/programs")
        resp.raise_for_status()
        body = resp.json()
        data_list = body if isinstance(body, list) else body.get("data", [])
        ta = TypeAdapter(list[Program])
        return ta.validate_python(data_list)

    async def list_categories(self) -> list[Category]:
        resp = await self._get("/api/citizen-portal/schedules/categories")
        resp.raise_for_status()
        body = resp.json()
        data_list = body if isinstance(body, list) else body.get("data", [])
        ta = TypeAdapter(list[Category])
        return ta.validate_python(data_list)

    async def list_stages(self) -> list[Stage]:
        resp = await self._get("/api/citizen-portal/stages")
        resp.raise_for_status()
        body = resp.json()
        data_list = body if isinstance(body, list) else body.get("data", [])
        ta = TypeAdapter(list[Stage])
        return ta.validate_python(data_list)

    async def enroll(self, profile_id: int, schedule_id: int) -> dict:
        await self._check_auth()
        resp = await self._put(
            f"/api/profiles/{profile_id}/schedules/{schedule_id}",
            json={},
        )
        # If 401, bubble the error clearly
        if resp.status_code == 401:
            raise RuntimeError(
                f"Unauthorized (401) — PUT /api/profiles/{profile_id}/schedules/{schedule_id}. "
                "Your token may be invalid or expired. Re-run 'idrd login'."
            )
        resp.raise_for_status()
        return resp.json()

    async def my_bookings(self) -> list[Booking]:
        await self._check_auth()
        resp = await self._get("/api/citizen-portal/bookings")
        if resp.status_code == 401:
            raise RuntimeError(
                "Unauthorized (401) — GET /api/citizen-portal/bookings. "
                "Your token may be invalid or expired."
            )
        resp.raise_for_status()
        body = resp.json()
        data_list = body if isinstance(body, list) else body.get("data", [])
        ta = TypeAdapter(list[Booking])
        return ta.validate_python(data_list)

    async def whoami(self) -> Optional[User]:
        await self._check_auth()
        resp = await self._get("/api/user")
        if resp.status_code == 401:
            raise RuntimeError(
                "Unauthorized (401) — GET /api/user. "
                "Your token may be invalid or expired."
            )
        resp.raise_for_status()
        body = resp.json()
        # The live /api/user response wraps the user object in a "data" key.
        # Unwrap it (fall back to the bare body if not wrapped) before validating.
        data = body.get("data", body) if isinstance(body, dict) else body
        if isinstance(data, dict):
            return User.model_validate(data)
        raise RuntimeError("Unexpected /api/user response shape.")

    async def close(self) -> None:
        await self._client.aclose()
