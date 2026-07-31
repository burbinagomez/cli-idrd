"""Unit tests for token storage (keyring primary, hardened file fallback).

All tests run against a temp session path and a mocked/unavailable keyring via
the autouse _isolate_session_store fixture in conftest.py. Individual tests
re-patch the idrd.session._keyring_* helpers to simulate a working credential
store.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import idrd.session as session_mod
from idrd.models import AuthToken
from idrd.session import clear_token, load_token, save_token

TOKEN = AuthToken(access_token="tok-123", token_type="Bearer")
EXPECTED_PAYLOAD = json.dumps(TOKEN.model_dump(), indent=2)


@pytest.fixture
def session_file(tmp_path) -> Path:
    return tmp_path / ".idrd" / "session.json"


# ── Roundtrip (fallback file, keyring unavailable) ────────────────────────


def test_save_load_roundtrip_fallback(session_file: Path) -> None:
    """With no keyring backend, save writes the file and load reads it back."""
    save_token(TOKEN)
    assert session_file.exists()
    assert session_file.read_text(encoding="utf-8") == EXPECTED_PAYLOAD
    loaded = load_token()
    assert loaded == TOKEN
    assert loaded.access_token == "tok-123"


def test_load_missing_returns_none() -> None:
    assert load_token() is None


def test_load_corrupt_file_returns_none(session_file: Path) -> None:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("{not json!!", encoding="utf-8")
    assert load_token() is None


# ── Keyring-vs-fallback behavior ───────────────────────────────────────────


def test_save_prefers_keyring(session_file: Path, monkeypatch) -> None:
    """When keyring works, save stores there and creates no fallback file."""
    saved: dict[tuple[str, str], str] = {}

    def fake_set(service: str, username: str, value: str) -> bool:
        saved[(service, username)] = value
        return True

    monkeypatch.setattr(session_mod, "_keyring_set", fake_set)
    save_token(TOKEN)
    assert saved == {("idrd-cli", "portal-ciudadano"): EXPECTED_PAYLOAD}
    assert not session_file.exists()


def test_save_keyring_removes_stale_fallback(
    session_file: Path, monkeypatch
) -> None:
    """A plaintext fallback left by an older version is cleaned up."""
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("stale-plaintext", encoding="utf-8")
    monkeypatch.setattr(session_mod, "_keyring_set", lambda *a, **k: True)
    save_token(TOKEN)
    assert not session_file.exists()


def test_load_prefers_keyring(monkeypatch) -> None:
    monkeypatch.setattr(
        session_mod, "_keyring_get", lambda *a, **k: EXPECTED_PAYLOAD
    )
    loaded = load_token()
    assert loaded == TOKEN


def test_load_falls_back_when_keyring_empty(
    session_file: Path, monkeypatch
) -> None:
    """Keyring available but empty → fall back to the file store."""
    save_token(TOKEN)  # keyring unavailable (autouse) → writes file
    monkeypatch.setattr(session_mod, "_keyring_get", lambda *a, **k: None)
    loaded = load_token()
    assert loaded == TOKEN


def test_load_ignores_corrupt_keyring_entry(
    session_file: Path, monkeypatch
) -> None:
    """Corrupt keyring payload is ignored; the file fallback is still read."""
    save_token(TOKEN)
    monkeypatch.setattr(session_mod, "_keyring_get", lambda *a, **k: "{nope")
    loaded = load_token()
    assert loaded == TOKEN


def test_save_falls_back_when_keyring_raises(
    session_file: Path, monkeypatch
) -> None:
    """A raising keyring backend degrades to the hardened file fallback."""
    import sys

    class FakeKeyring:
        @staticmethod
        def set_password(service: str, username: str, value: str) -> None:
            raise RuntimeError("no Secret Service")

    # The real _keyring_set catches backend failures; simulate one by making
    # the keyring module raise.
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    save_token(TOKEN)
    assert session_file.exists()
    assert load_token() == TOKEN


# ── Permissions ────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertions")
def test_posix_file_mode_0600(session_file: Path) -> None:
    save_token(TOKEN)
    assert (session_file.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertions")
def test_posix_dir_mode_0700(tmp_path: Path) -> None:
    save_token(TOKEN)
    assert ((tmp_path / ".idrd").stat().st_mode & 0o777) == 0o700


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL assertions")
def test_windows_icacls_hardens_file(session_file: Path, monkeypatch) -> None:
    """On Windows, os.chmod is a no-op for ACLs — icacls must be invoked.

    The file is hardened *before* os.replace (on the .tmp path) so the final
    file lands with the restricted ACL and there is no window where the final
    path carries inherited ACLs.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(session_mod.subprocess, "run", fake_run)
    monkeypatch.setenv("USERNAME", "tester")
    save_token(TOKEN)
    assert calls, "icacls should have been invoked for the fallback file"
    harden_cmd = calls[0]
    assert harden_cmd[0] == "icacls"
    assert harden_cmd[1] == str(session_file) + ".tmp"
    assert "/inheritance:r" in harden_cmd
    assert "/grant:r" in harden_cmd
    assert "tester:F" in harden_cmd


# ── Atomic write ───────────────────────────────────────────────────────────


def test_atomic_write_no_tmp_leftover(session_file: Path) -> None:
    save_token(TOKEN)
    save_token(TOKEN)  # overwrite path
    assert not session_file.with_name(session_file.name + ".tmp").exists()
    assert session_file.read_text(encoding="utf-8") == EXPECTED_PAYLOAD


def test_atomic_write_uses_os_replace(session_file: Path, monkeypatch) -> None:
    """The write must go through a .tmp file + os.replace (R3)."""
    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def fake_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(session_mod.os, "replace", fake_replace)
    save_token(TOKEN)
    assert len(calls) == 1
    src, dst = calls[0]
    assert src.endswith(".tmp")
    assert dst == str(session_file)


def test_atomic_write_cleans_tmp_on_failure(
    session_file: Path, monkeypatch
) -> None:
    """A failed replace must not leave a partial token file behind."""

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(session_mod.os, "replace", boom)
    with pytest.raises(OSError):
        save_token(TOKEN)
    assert not session_file.exists()
    assert not session_file.with_name(session_file.name + ".tmp").exists()


# ── clear_token ────────────────────────────────────────────────────────────


def test_clear_token_removes_file(session_file: Path) -> None:
    save_token(TOKEN)
    assert session_file.exists()
    clear_token()
    assert not session_file.exists()
    assert load_token() is None


def test_clear_token_calls_keyring_delete(monkeypatch) -> None:
    deleted: list[tuple[str, str]] = []

    def fake_delete(service: str, username: str) -> None:
        deleted.append((service, username))

    monkeypatch.setattr(session_mod, "_keyring_delete", fake_delete)
    clear_token()
    assert deleted == [("idrd-cli", "portal-ciudadano")]


def test_clear_token_no_file_is_noop() -> None:
    clear_token()  # must not raise when nothing is stored
