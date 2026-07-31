# Token Storage Audit — IDRD CLI

Audit date: 2026-07-31
Auditor: backend profile (kanban task t_55a63e1f)
Scope: how the CLI persists and loads the Portal Ciudadano bearer token
Code audited: `src/idrd/session.py`, `src/idrd/client.py`, `src/idrd/models.py`, `src/idrd/cli.py`
Host evidence collected on: Windows 10 (git-bash/MSYS), Python 3.11.15

## Summary

The CLI stores the raw bearer `access_token` in **plaintext** at
`~/.idrd/session.json`. The code attempts to restrict file permissions with
`os.chmod(path, 0o600)`, but that call is **verified to be a no-op on Windows**
— the token file on this machine sits at mode `0o666` with only inherited,
default ACLs. The token is a bearer credential equivalent to the user's
password for API purposes (it can enroll in activities, read bookings, and
fetch `/api/user`). Storage is currently protected only by the accident of
Windows user-profile ACL inheritance, not by anything the code enforces.

## How the token flows

1. `idrd login` → `IdrdClient.login()` → `POST /api/login` →
   `AuthToken` (`access_token`, `token_type`) → `save_token()` →
   `~/.idrd/session.json` (plaintext JSON, `indent=2`) — `client.py:95-111`,
   `session.py:17-27`.
2. Every other command constructs `IdrdClient()` with no token → `load_token()`
   reads the file back → `AuthToken.model_validate()` — `client.py:39-42`,
   `session.py:30-39`.
3. `idrd logout` → `clear_token()` unlinks the file — `session.py:42-46`.

## Findings

### F1 — HIGH: Token stored in plaintext at rest
`session.py:21-22` writes `token.model_dump()` verbatim as JSON. A bearer token
is a password-equivalent for this API. Anyone who can read the file — a backup
agent, sync tool, malware running as the user, or another local user on a
permissive system — can impersonate the account without ever seeing the
password. Plaintext-at-rest is the single biggest gap.

### F2 — HIGH: `os.chmod(path, 0o600)` is a no-op on Windows (verified)
`sessions.py:24-27`:
```python
try:
    os.chmod(path, 0o600)
except OSError:
    pass
```
Python's `os.chmod` on Windows only toggles the read-only attribute; it does
not change ACLs. Verified on this host:

```
after write_text (before chmod): 0o666
after os.chmod(0o600):           0o666
readonly attr set? False
real session.json mode:          0o666
```
The comment "Restrict permissions on POSIX; best-effort on Windows" is wrong —
on Windows it is not best-effort, it is *nothing*. The `except OSError: pass`
also hides any real failure. The live file's ACL is purely inherited
(`SYSTEM:(I)(F)`, `BUILTIN\Administrators:(I)(F)`, `<user>:(I)(F)`) — the file
relies entirely on the profile directory's default ACL, so exposure changes
whenever that directory's ACL changes (shared machines, relaxed profile ACLs,
mapped-home setups).
Note: on Windows, `os.stat().st_mode` does not reflect ACLs — `0o666` is what
Python always reports; the ACL listing above is the real security surface.
On POSIX there is a second, smaller flaw in the same function: the chmod runs
*after* `write_text`, so the file exists briefly with umask-derived perms
(typically `0o644`) before being tightened.

### F3 — MEDIUM: Session directory permissions not hardened
`session.py:20` `mkdir(parents=True, exist_ok=True)` creates `~/.idrd` with
default perms (`0o777` as reported on this host; `0o755`-ish on POSIX). The
directory should be `0o700` so other local users cannot even traverse it.
On Windows the inherited profile ACL masks this today; on POSIX multi-user
systems it is a real (if low-severity) gap.

### F4 — MEDIUM: No token expiry or refresh handling
`AuthToken` (`models.py:13-16`) captures only `access_token` + `token_type`.
The live login response (checked against the real session file, values not
printed) contains exactly those two fields, so nothing is dropped by the API —
but the CLI has no way to know when the token expires. No expiry check at load
time; an expired token is used until the server 401s. The client already emits
clear "token may be invalid or expired — re-run idrd login" messages
(`client.py:256-260, 267-270, 281-284`), so this is a lifecycle gap, not a
storage vulnerability.

### F5 — LOW: Non-atomic write can corrupt the session file
`session.py:22` `path.write_text(...)` truncates in place. A crash or power
loss mid-write leaves a truncated file; `load_token()` then returns `None`
(silent logout). Trivial to fix: write a temp file in the same directory, then
`os.replace()`.

### F6 — LOW: No defense against backups/sync of the plaintext file
`~/.idrd` sits in the user profile, so anything that backs up or syncs the
profile copies the bearer token. Encrypting at rest (recommendation R1)
removes this whole class of exposure.

### F7 — INFO (adjacent, out of token-storage scope): duplicates + CLI password
- `client.py` defines `discover_hidden()` twice (lines ~139 and ~193, byte-for-
  byte identical); the second definition shadows the first. Dead code / hazard.
- `cli.py:84` accepts `--password` as a CLI argument. `hide_input=True` stops
  echo but the value can still appear in shell history / process listings.
  Prefer `getpass` prompt when `--password` is omitted.

## Recommendations

### R1 — Encrypt the token at rest via the OS credential store (primary fix)
Use `keyring` (or platform APIs) instead of a plaintext file:
- Windows: DPAPI / Credential Manager (keyring `win32` backend) — the token
  becomes a per-user, machine-bound secret that no other user can read even
  with file access.
- macOS: Keychain; Linux: Secret Service (`keyring`).
- Keep `~/.idrd/session.json` only as a **fallback** for headless/CI
  environments with no keyring, and mark the fallback (fixed perms, atomic
  write, warning on load).
This also resolves F6 (backups no longer leak usable tokens) and F1.

### R2 — Enforce real file permissions (do regardless, keeps the fallback safe)
- POSIX: create the file with mode `0o600` from the very first open
  (`os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)` — no `0o644` window), and
  `chmod` the `~/.idrd` directory to `0o700`.
- Windows: do not rely on `chmod`. If plaintext fallback is kept, strip ACL
  inheritance and grant the current user only (icacls
  `/inheritance:r /grant:r "%USERNAME%:F"`) — or better, use DPAPI (R1).
- Remove the silent `except OSError: pass`.

### R3 — Atomic write
Write to `~/.idrd/session.json.tmp` then `os.replace()` (same directory, so
rename is atomic on both POSIX and Windows NTFS).

### R4 — Session metadata (optional)
Record `issued_at` (and `expires_in` if the API ever returns it) in the session
payload; warn on load when the token is likely stale. Low value until the API
returns real expiry info.

## Evidence log

- `uv run pytest tests/test_unit.py -q` → 17 passed (baseline; requires
  `PYTHONPATH=src` in a fresh worktree because the project is not packaged).
- `git ls-files` / `git log --all` → no token/session/credential files ever
  committed to the repo (only `src/idrd/session.py`, which is code, not data).
- Live `~/.idrd/session.json` inspected: keys only `access_token`, `token_type`;
  token value never printed; file mode `0o666`, ACL inherited
  (SYSTEM/Administrators/user, all Full, inherited).

## Files audited

- `src/idrd/session.py` (all)
- `src/idrd/client.py` (login, `_auth_header`, auto-load)
- `src/idrd/models.py` (`AuthToken`)
- `src/idrd/cli.py` (`login`, `logout`)

Severity tally: 2 High, 2 Medium, 2 Low, 1 Info.
