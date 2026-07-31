"""Pydantic models for IDRD Portal Ciudadano API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# ── Auth ──────────────────────────────────────────────────────────────────

class AuthToken(BaseModel):
    """Token response from POST /api/login.

    The server only returns ``access_token`` + ``token_type`` today, but
    ``expires_in`` / ``expires_at`` are accepted if the API starts sending
    them (or callers construct them). ``is_expired()`` lets the client fail
    fast instead of discovering a dead token via a 401 mid-command.
    """
    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _derive_expiry(self) -> AuthToken:
        if self.expires_at is None and self.expires_in is not None:
            self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.expires_in)
        return self

    def is_expired(self, now: Optional[datetime] = None, skew_seconds: int = 30) -> bool:
        """True if the token has an expiry and it has passed (with clock skew)."""
        if self.expires_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now >= exp - timedelta(seconds=skew_seconds)


class LoginError(BaseModel):
    """Error response from login. Fields optional — the API shape is not
    guaranteed to include both, and we never want a parse error to mask
    the real auth failure."""
    message: Optional[str] = None
    code: Optional[int] = None


class ValidationError(BaseModel):
    """422 validation error."""
    message: str
    errors: dict[str, list[str]]


# ── Schedule / Activity ──────────────────────────────────────────────────

class Schedule(BaseModel):
    """A single public schedule item (search result / single view)."""
    id: int
    icon: Optional[str] = None
    program_name: Optional[str] = None
    activity_name: Optional[str] = None
    stage_name: Optional[str] = None
    park_code: Optional[str] = None
    park_name: Optional[str] = None
    park_address: Optional[str] = None
    weekday_name: Optional[str] = None
    daily_name: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    quota: Optional[int] = None
    is_paid: Optional[bool] = None
    rate_id: Optional[int] = None
    rate_name: Optional[str] = None
    rate_value: Optional[float] = None
    is_initiate: Optional[bool] = None
    start_date: Optional[str] = None
    final_date: Optional[str] = None
    is_activated: Optional[bool] = None
    is_teams: bool = False
    min_team_participants_quota: int = 0
    max_team_participants_quota: int = 0
    team_quota: int = 0
    disability: bool = False
    taken: int = 0
    users_schedules_count: int = 0
    teams_schedules_count: int = 0
    consent: list = []
    regulations: list = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Program ───────────────────────────────────────────────────────────────

class Program(BaseModel):
    """A program from GET /api/citizen-portal/programs."""
    id: int
    name: Optional[str] = None
    composed_name: Optional[str] = None
    schedules_count: Optional[int] = 0


# ── Category ──────────────────────────────────────────────────────────────

class Category(BaseModel):
    """An activity category from GET /api/citizen-portal/schedules/categories."""
    name: Optional[str] = None
    value: Optional[str] = None
    icon: Optional[str] = None


# ── Stage ─────────────────────────────────────────────────────────────────

class Stage(BaseModel):
    """A stage/scenario from GET /api/citizen-portal/stages."""
    id: int
    name: Optional[str] = None
    park_id: Optional[int] = None
    park_code: Optional[str] = None
    park_name: Optional[str] = None
    schedules_count: Optional[int] = 0


# ── Links / Meta (paginated envelope) ────────────────────────────────────

class PaginationLinks(BaseModel):
    first: Optional[str] = None
    last: Optional[str] = None
    prev: Optional[str] = None
    next: Optional[str] = None


class PaginationMeta(BaseModel):
    current_page: int = 1
    from_: Optional[int] = Field(default=None, alias="from")
    last_page: int = 1
    path: Optional[str] = None
    per_page: int = 10
    to: Optional[int] = None
    total: int = 0


# ── API response envelope ─────────────────────────────────────────────────

class ApiResponse(BaseModel):
    """Generic API response envelope for paginated endpoints."""
    data: list[dict[str, Any]]
    links: Optional[PaginationLinks] = None
    meta: Optional[PaginationMeta] = None
    code: int = 200
    details: Optional[dict] = None


class SingleResponse(BaseModel):
    """Envelope for single-item responses (activities show)."""
    data: Optional[dict[str, Any]] = None
    code: int = 200
    details: Optional[dict] = None
    requested_at: Optional[str] = None


# ── User ──────────────────────────────────────────────────────────────────

class User(BaseModel):
    """Current user from GET /api/user."""
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    document: Optional[str] = None
    document_type: Optional[str] = None
    phone: Optional[str] = None
    profiles: Optional[list[dict]] = []


class Profile(BaseModel):
    """Beneficiary profile."""
    id: int
    name: Optional[str] = None
    document: Optional[str] = None
    document_type: Optional[str] = None
    relationship: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None


# ── Booking ──────────────────────────────────────────────────────────────

class Booking(BaseModel):
    """A subscription/booking from /api/profiles/subscriptions."""
    id: int
    schedule_id: Optional[int] = None
    profile_id: Optional[int] = None
    status: Optional[str] = None
    schedule: Optional[Schedule] = None
    profile: Optional[Profile] = None
    created_at: Optional[str] = None
