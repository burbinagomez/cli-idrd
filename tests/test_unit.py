"""Unit tests for IdrdClient request building — no live network.

Uses httpx.MockTransport to verify exact URLs, methods, headers, and query params.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import patch

import httpx
import pytest
from pydantic import TypeAdapter

from idrd.client import IdrdClient
from idrd.models import AuthToken, Booking, Category, Program, Schedule, Stage, User
from idrd.ports import IdrdClientPort
from idrd.session import load_token, save_token


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def token() -> AuthToken:
    return AuthToken(access_token="test-token-abc", token_type="Bearer")


@pytest.fixture
def client(token: AuthToken) -> IdrdClient:
    return IdrdClient(token=token)


@pytest.fixture
def anon_client() -> IdrdClient:
    return IdrdClient(token=None)


# ── Helpers ───────────────────────────────────────────────────────────────

def _mock_transport(handler):
    """Build an AsyncClient with a mock transport."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://portalciudadano-back.idrd.gov.co")


# ── Test: login request shape ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_request_shape() -> None:
    """Verify login sends POST /api/login with correct JSON body."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://portalciudadano-back.idrd.gov.co/api/login"
        import json
        body = json.loads(request.content)
        assert body["email"] == "test@test.com"
        assert body["password"] == "secret123"
        return httpx.Response(200, json={"access_token": "abc123", "token_type": "Bearer"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    token = await client.login("test@test.com", "secret123")
    assert token.access_token == "abc123"
    assert token.token_type == "Bearer"


@pytest.mark.asyncio
async def test_login_401() -> None:
    """Verify login raises RuntimeError on bad credentials."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Usuario o contraseña incorrectos", "code": 401})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="Usuario o contraseña incorrectos"):
        await client.login("wrong@test.com", "wrong")


@pytest.mark.asyncio
async def test_login_422() -> None:
    """Verify login raises RuntimeError on missing fields."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Por favor completa todos los datos del formulario.", "errors": {}})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="Por favor completa"):
        await client.login("", "")


# ── Test: search_schedules request shape ──────────────────────────────────

@pytest.mark.asyncio
async def test_search_default() -> None:
    """Search with no filters sends ?page=1."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "public-schedules" in str(request.url)
        assert "page=1" in str(request.url)
        # No auth header for anon
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [], "links": {}, "meta": {"current_page": 1, "last_page": 1, "total": 0}})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    await client.search_schedules()


@pytest.mark.asyncio
async def test_search_program_id_array() -> None:
    """CRITICAL: program_id MUST be sent as array param program_id[]."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        url = str(request.url)
        # program_id[]=12&program_id[]=34
        assert "program_id%5B%5D=12" in url or "program_id[]=12" in url, f"Missing program_id[] array param in {url}"
        assert "program_id%5B%5D=34" in url or "program_id[]=34" in url
        return httpx.Response(200, json={"data": [], "links": {}, "meta": {"current_page": 1, "last_page": 1, "total": 0}})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    await client.search_schedules(program_id=[12, 34])


@pytest.mark.asyncio
async def test_search_category_and_locality() -> None:
    """Verify category and locality params are sent."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        url = str(request.url)
        assert "category=ATLETISMO" in url
        assert "locality=5" in url
        assert "page=2" in url
        return httpx.Response(200, json={"data": [], "links": {}, "meta": {"current_page": 2, "last_page": 1, "total": 0}})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    await client.search_schedules(category="ATLETISMO", locality=5, page=2)


# ── Test: get_schedule ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_schedule() -> None:
    """Verify GET /api/citizen-portal/public-schedules/{id}."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "public-schedules/11409" in str(request.url)
        return httpx.Response(200, json={
            "data": {"id": 11409, "activity_name": "CAMINATAS RECREATIVAS", "program_name": "BOGOTÁ FELIZ"},
            "code": 200,
        })

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    sched = await client.get_schedule(11409)
    assert sched is not None
    assert sched.id == 11409
    assert sched.activity_name == "CAMINATAS RECREATIVAS"


# ── Test: list_programs ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_programs() -> None:
    """Verify GET /api/citizen-portal/programs."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/programs" in str(request.url)
        return httpx.Response(200, json=[
            {"id": 1, "name": "BOGOTÁ FELIZ", "composed_name": "BOGOTÁ FELIZ - RECREACIÓN", "schedules_count": 10},
        ])

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    programs = await client.list_programs()
    assert len(programs) == 1
    assert programs[0].name == "BOGOTÁ FELIZ"


# ── Test: list_categories ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_categories() -> None:
    """Verify GET /api/citizen-portal/schedules/categories."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/schedules/categories" in str(request.url)
        return httpx.Response(200, json=[
            {"name": "Atletismo", "value": "ATLETISMO", "icon": "mdi-run"},
        ])

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    cats = await client.list_categories()
    assert cats[0].value == "ATLETISMO"


# ── Test: list_stages ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_stages() -> None:
    """Verify GET /api/citizen-portal/stages."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/stages" in str(request.url)
        return httpx.Response(200, json=[
            {"id": 1, "name": "PLAZA CULTURAL", "park_name": "INDEPENDENCIA"},
        ])

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    stages = await client.list_stages()
    assert stages[0].name == "PLAZA CULTURAL"


# ── Test: enroll request shape (auth required) ────────────────────────────

@pytest.mark.asyncio
async def test_enroll_request_shape(client: IdrdClient) -> None:
    """Verify enroll sends PUT /api/profiles/{pid}/schedules/{sid} with empty body."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert "/api/profiles/42/schedules/11409" in str(request.url)
        # Should have auth header
        assert "Authorization" in request.headers
        assert "Bearer test-token-abc" in request.headers["Authorization"]
        # Body should be empty JSON
        import json
        assert json.loads(request.content) == {}
        return httpx.Response(200, json={"success": True})

    client._client = _mock_transport(handler)
    result = await client.enroll(profile_id=42, schedule_id=11409)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_enroll_no_auth(anon_client: IdrdClient) -> None:
    """Verify enroll raises RuntimeError when not authenticated."""
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await anon_client.enroll(profile_id=42, schedule_id=11409)


# ── Test: my_bookings request shape (auth required) ───────────────────────

@pytest.mark.asyncio
async def test_my_bookings_request(client: IdrdClient) -> None:
    """Verify my_bookings sends GET /api/citizen-portal/bookings with auth."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/bookings" in str(request.url)
        assert "Authorization" in request.headers
        return httpx.Response(200, json={"data": []})

    client._client = _mock_transport(handler)
    bookings = await client.my_bookings()
    assert bookings == []


@pytest.mark.asyncio
async def test_my_bookings_no_auth(anon_client: IdrdClient) -> None:
    """Verify my_bookings raises RuntimeError when not authenticated."""
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await anon_client.my_bookings()


# ── Test: whoami request shape ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_whoami_request(client: IdrdClient) -> None:
    """Verify whoami sends GET /api/user with auth."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/api/user" in str(request.url)
        assert "Authorization" in request.headers
        return httpx.Response(200, json={
            "id": 1, "name": "Test User", "email": "test@test.com",
        })

    client._client = _mock_transport(handler)
    user = await client.whoami()
    assert user is not None
    assert user.email == "test@test.com"


@pytest.mark.asyncio
async def test_whoami_no_auth(anon_client: IdrdClient) -> None:
    """Verify whoami raises RuntimeError when not authenticated."""
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await anon_client.whoami()


# ── Test: discover_hidden ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_hidden_probes_and_stops_at_404() -> None:
    """Verify discover_hidden probes singular ids from 11410 and stops at 404."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Request must hit the singular endpoint on the shared base URL.
        assert request.method == "GET"
        assert "public-schedules/" in str(request.url)
        pid = int(str(request.url).rsplit("/", 1)[1])
        seen.append(pid)
        if pid >= 11412:
            return httpx.Response(404, json={"message": "Not found"})
        return httpx.Response(200, json={"data": {"id": pid, "activity_name": "X"}})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    found, probed = await client.discover_hidden(max_probe=10, delay=0)
    assert found == [11410, 11411]
    assert probed == [11410, 11411, 11412]
    assert seen == [11410, 11411, 11412]


@pytest.mark.asyncio
async def test_discover_hidden_no_found() -> None:
    """Verify discover_hidden returns empty lists when everything 404s."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not found"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    found, probed = await client.discover_hidden(max_probe=3, delay=0)
    assert found == []
    assert probed == [11410]


# ── Test: IdrdClientPort protocol is satisfied ────────────────────────────

def test_client_satisfies_port() -> None:
    """Verify IdrdClient conforms to IdrdClientPort (structural typing)."""
    from typing import cast
    token = AuthToken(access_token="x", token_type="Bearer")
    client: IdrdClientPort = cast(IdrdClientPort, IdrdClient(token=token))
    assert isinstance(client, IdrdClientPort)
