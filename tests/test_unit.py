"""Unit tests for IdrdClient request building — no live network.

Uses httpx.MockTransport to verify exact URLs, methods, headers, and query params.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import httpx
import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from idrd.client import IdrdClient
from idrd.cli import app, resolve_password
from idrd.models import AuthToken, Booking, Category, Program, Schedule, Stage, User
from idrd.ports import IdrdClientPort
from idrd.session import clear_token, load_token, save_token


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
        await client.login("test@test.com", "x")


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


# ── Test: login hardening ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_session(tmp_path, monkeypatch):
    """Never touch the real ~/.idrd/session.json during tests.

    Prevents tests from clobbering a real stored token; login() persists via
    save_token() and would otherwise write to the user's actual session file.
    """
    session_file = tmp_path / "session.json"
    monkeypatch.setenv("IDRD_SESSION_PATH", str(session_file))
    return session_file


@pytest.mark.asyncio
async def test_login_persists_token(_isolate_session) -> None:
    """Successful login updates the client token and writes the session file."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "abc123", "token_type": "Bearer"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    tok = await client.login("test@test.com", "secret123")
    assert tok.access_token == "abc123"
    assert client._token is tok
    loaded = load_token()
    assert loaded is not None and loaded.access_token == "abc123"


@pytest.mark.asyncio
async def test_login_401_missing_code() -> None:
    """401 without the `code` field must not crash pydantic — friendly message instead."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "credenciales inválidas"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="credenciales inválidas"):
        await client.login("test@test.com", "wrong")


@pytest.mark.asyncio
async def test_login_401_bare_error_key() -> None:
    """401 with an `error` key (non-Laravel shape) still surfaces the message."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="invalid_grant"):
        await client.login("test@test.com", "wrong")


@pytest.mark.asyncio
async def test_login_422_errors_dict() -> None:
    """422 with nested errors dict is flattened into a readable message."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={
            "errors": {"email": ["El campo email es obligatorio."]},
        })

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="email: El campo email es obligatorio."):
        await client.login("test@test.com", "x")


@pytest.mark.asyncio
async def test_login_500() -> None:
    """Server errors become RuntimeError with the status code, not HTTPStatusError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "internal error"})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await client.login("test@test.com", "pw")


@pytest.mark.asyncio
async def test_login_429() -> None:
    """Rate limiting is called out explicitly."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="Rate limited"):
        await client.login("test@test.com", "pw")


@pytest.mark.asyncio
async def test_login_network_error() -> None:
    """Transport errors surface as a friendly RuntimeError, not a traceback."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = IdrdClient(token=None)
    client._client = _mock_transport(handler)
    with pytest.raises(RuntimeError, match="network error"):
        await client.login("test@test.com", "pw")


@pytest.mark.asyncio
async def test_login_empty_inputs() -> None:
    """Empty email/password are rejected client-side without any network call."""
    client = IdrdClient(token=None)
    with pytest.raises(RuntimeError, match="Email is required"):
        await client.login("  ", "pw")
    with pytest.raises(RuntimeError, match="Password is required"):
        await client.login("test@test.com", "")


# ── Test: token expiry (hardening) ────────────────────────────────────────

def test_auth_token_derives_expiry() -> None:
    tok = AuthToken(access_token="x", expires_in=3600)
    assert tok.expires_at is not None
    assert not tok.is_expired()


def test_auth_token_expired() -> None:
    tok = AuthToken(
        access_token="x",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    assert tok.is_expired()


def test_auth_token_no_expiry_never_expired() -> None:
    tok = AuthToken(access_token="x")
    assert tok.expires_at is None
    assert not tok.is_expired()


@pytest.mark.asyncio
async def test_whoami_expired_token() -> None:
    """Authed calls fail fast with an expiry message instead of hitting the API."""
    expired = AuthToken(
        access_token="x",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    client = IdrdClient(token=expired)
    with pytest.raises(RuntimeError, match="expired"):
        await client.whoami()


# ── Test: session persistence (hardening) ─────────────────────────────────

def test_session_roundtrip(_isolate_session) -> None:
    tok = AuthToken(access_token="tok", token_type="Bearer", expires_in=3600)
    save_token(tok)
    loaded = load_token()
    assert loaded is not None
    assert loaded.access_token == "tok"
    assert loaded.expires_at is not None
    clear_token()
    assert load_token() is None


def test_load_token_missing(_isolate_session) -> None:
    assert load_token() is None


def test_load_token_corrupt(_isolate_session) -> None:
    Path(_isolate_session).write_text("{not json", encoding="utf-8")
    assert load_token() is None


def test_load_token_invalid_shape(_isolate_session) -> None:
    Path(_isolate_session).write_text('{"foo": 1}', encoding="utf-8")
    assert load_token() is None


# ── Test: CLI login command (hardening) ───────────────────────────────────

class _FakeService:
    def __init__(self, error: Optional[str] = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def login(self, email: str, password: str) -> AuthToken:
        self.calls.append((email, password))
        if self.error:
            raise RuntimeError(self.error)
        return AuthToken(access_token="cli-token", token_type="Bearer")


def test_cli_login_explicit_password(monkeypatch) -> None:
    fake = _FakeService()
    monkeypatch.setattr("idrd.cli._get_service", lambda: fake)
    result = CliRunner().invoke(app, ["login", "--email", "a@b.c", "--password", "secret"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("a@b.c", "secret")]


def test_cli_login_env_password(monkeypatch) -> None:
    fake = _FakeService()
    monkeypatch.setattr("idrd.cli._get_service", lambda: fake)
    monkeypatch.setenv("IDRD_PASSWORD", "envpass")
    result = CliRunner().invoke(app, ["login", "--email", "a@b.c"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("a@b.c", "envpass")]


def test_cli_login_error_exits_nonzero(monkeypatch) -> None:
    fake = _FakeService(error="Usuario o contraseña incorrectos")
    monkeypatch.setattr("idrd.cli._get_service", lambda: fake)
    result = CliRunner().invoke(app, ["login", "--email", "a@b.c", "--password", "x"])
    assert result.exit_code == 1
    assert "Login failed" in result.output
    assert "Usuario o contraseña incorrectos" in result.output


def test_resolve_password_explicit_and_env(monkeypatch) -> None:
    monkeypatch.setenv("IDRD_PASSWORD", "envpass")
    assert resolve_password("explicit") == "explicit"
    assert resolve_password(None) == "envpass"


def test_resolve_password_missing_raises(monkeypatch) -> None:
    monkeypatch.delenv("IDRD_PASSWORD", raising=False)
    import getpass
    import sys

    class _TtyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", _TtyStdin())

    def _no_tty(prompt: str = "Password: ") -> str:
        raise EOFError()

    monkeypatch.setattr(getpass, "getpass", _no_tty)
    with pytest.raises(RuntimeError, match="No password provided"):
        resolve_password(None)


def test_resolve_password_non_interactive_raises(monkeypatch) -> None:
    monkeypatch.delenv("IDRD_PASSWORD", raising=False)
    import sys

    class _PipeStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _PipeStdin())
    with pytest.raises(RuntimeError, match="No password provided"):
        resolve_password(None)
