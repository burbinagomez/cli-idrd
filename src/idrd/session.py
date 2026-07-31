"""Token persistence via the OS credential store, with a hardened file fallback.

Primary storage is ``keyring`` (R1 — encrypt at rest):
- Windows: DPAPI-backed Credential Manager (requires pywin32; keyring raises
  ``NoKeyringError`` without it and the CLI falls back to the file store).
- macOS: Keychain (``security`` CLI).
- Linux: Secret Service via dbus/secretstorage — not available in headless/CI
  sessions, in which case the CLI falls back to the file store.

``~/.idrd/session.json`` is used ONLY when no keyring backend is available
(headless/CI). Every use of the fallback logs a warning. The fallback file is
created with restrictive permissions from the very first open (0o600 on POSIX;
no inherited ACLs on Windows via icacls) and written atomically (R2/R3).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from idrd.models import AuthToken

logger = logging.getLogger(__name__)

# keyring service/username pair, scoped to this application.
_SERVICE_NAME = "idrd-cli"
_USERNAME = "portal-ciudadano"

_FALLBACK_FILE_MODE = 0o600
_DIR_MODE = 0o700


def _session_path() -> Path:
    return Path.home() / ".idrd" / "session.json"


# ── keyring helpers ────────────────────────────────────────────────────────


def _keyring_get(service: str, username: str) -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(service, username)
    except Exception:
        # No usable backend (e.g. headless Linux without Secret Service) or a
        # backend failure → caller falls back to the hardened file store.
        return None


def _keyring_set(service: str, username: str, value: str) -> bool:
    try:
        import keyring

        keyring.set_password(service, username, value)
        return True
    except Exception:
        return False


def _keyring_delete(service: str, username: str) -> None:
    try:
        import keyring

        keyring.delete_password(service, username)
    except Exception:
        # Deleting a non-existent credential is not an error worth surfacing.
        pass


# ── file-fallback helpers ──────────────────────────────────────────────────


def _ensure_dir(directory: Path) -> None:
    """Create ~/.idrd; on POSIX restrict it to 0o700 (no traversal by others)."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(directory, _DIR_MODE)


def _harden_file_posix(path: Path) -> None:
    os.chmod(path, _FALLBACK_FILE_MODE)


def _harden_file_windows(path: Path) -> None:
    """Restrict the fallback file to the current user on Windows.

    os.chmod only toggles the read-only attribute on Windows — it does not
    touch ACLs. Strip inheritance and grant the current user full control only.
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            check=True,
            capture_output=True,
            text=True,
        )


def _atomic_write(
    path: Path,
    payload: str,
    harden: Optional[Callable[[Path], None]] = None,
) -> None:
    """Write payload to path atomically (tmp file in same dir + os.replace).

    The temp file is opened with mode 0o600 from the first open, so there is
    no umask-derived 0o644 window on POSIX. If a ``harden`` callback is given
    it runs on the tmp file *before* the replace, so the final file is already
    restricted (Windows: icacls before the file lands at its final path).
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FALLBACK_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if harden is not None:
            harden(tmp)
        os.replace(tmp, path)
    finally:
        # Never leave a partial/plaintext tmp file behind on failure.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _save_fallback(token: AuthToken) -> None:
    """Persist token to the hardened fallback file (headless/CI only)."""
    path = _session_path()
    _ensure_dir(path.parent)
    harden = _harden_file_posix if os.name == "posix" else _harden_file_windows
    _atomic_write(path, json.dumps(token.model_dump(), indent=2), harden=harden)


def _load_fallback() -> Optional[AuthToken]:
    path = _session_path()
    if not path.exists():
        return None
    logger.warning(
        "No OS credential store available; reading token from fallback file %s.",
        path,
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AuthToken.model_validate(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("Corrupt session file at %s; ignoring it.", path)
        return None


# ── public API (source-compatible) ─────────────────────────────────────────


def save_token(token: AuthToken) -> None:
    """Persist token to the OS credential store, or the hardened fallback file.

    The fallback file is only written when no keyring backend is available
    (headless/CI); that path logs a warning. When keyring succeeds, any stale
    fallback file is removed so no plaintext copy lingers.
    """
    payload = json.dumps(token.model_dump(), indent=2)
    if _keyring_set(_SERVICE_NAME, _USERNAME, payload):
        stale = _session_path()
        if stale.exists():
            stale.unlink()
        return
    logger.warning(
        "No OS credential store available (no keyring backend); storing token "
        "in fallback file %s. The file is created with restrictive "
        "permissions, but consider installing a keyring backend "
        "(e.g. pywin32 on Windows, Secret Service on Linux).",
        _session_path(),
    )
    _save_fallback(token)


def load_token() -> Optional[AuthToken]:
    """Load token from the OS credential store, falling back to the file store."""
    raw = _keyring_get(_SERVICE_NAME, _USERNAME)
    if raw is not None:
        try:
            data = json.loads(raw)
            return AuthToken.model_validate(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "Stored credential for %s/%s is corrupt; ignoring it.",
                _SERVICE_NAME,
                _USERNAME,
            )
    return _load_fallback()


def clear_token() -> None:
    """Remove the stored token from both the credential store and the file."""
    _keyring_delete(_SERVICE_NAME, _USERNAME)
    path = _session_path()
    if path.exists():
        path.unlink()
