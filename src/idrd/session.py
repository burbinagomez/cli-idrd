"""Token persistence to ~/.idrd/session.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from idrd.models import AuthToken


def _session_path() -> Path:
    return Path.home() / ".idrd" / "session.json"


def save_token(token: AuthToken) -> None:
    """Persist token to ~/.idrd/session.json."""
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = token.model_dump()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Restrict permissions on POSIX; best-effort on Windows
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_token() -> Optional[AuthToken]:
    """Load token from ~/.idrd/session.json, or None."""
    path = _session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AuthToken.model_validate(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def clear_token() -> None:
    """Remove the session file."""
    path = _session_path()
    if path.exists():
        path.unlink()
