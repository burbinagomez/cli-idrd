# IDRD CLI — Portal Ciudadano

CLI for the IDRD (Bogotá Recreation & Sports Institute) Portal Ciudadano API.

## Setup

```bash
uv sync
```

## Usage

Run commands via `uv run idrd <command>`. All read endpoints work without auth.

```
Usage: idrd [OPTIONS] COMMAND [ARGS]...

 Commands:
   login           Authenticate and store session token
   logout          Remove stored session token
   search          Search public activity schedules
   whoami          Show current authenticated user
   enroll          Enroll a profile in an activity (auth)
   my-bookings     List your bookings/subscriptions (auth)
   activities      Activity commands (show <id>)
   programs        Program commands (list)
   categories      Category commands (list)
   stages          Stage commands (list)
```

### Read commands (no auth required)

```bash
# Search activities (paginated, default 10 per page)
uv run idrd search
uv run idrd search --category ATLETISMO --page 2
uv run idrd search --program-id 12,27 --locality 5
uv run idrd search --json

# Activity details
uv run idrd activities show 11409
uv run idrd activities show 11409 --json

# Reference data
uv run idrd programs list
uv run idrd categories list
uv run idrd stages list
```

### Auth commands (require `idrd login` first)

```bash
# Login stores token in ~/.idrd/session.json
uv run idrd login --email your@email.com --password yourpass

# View your user info
uv run idrd whoami

# Enroll in a free activity (--profile-id from /api/profiles)
uv run idrd enroll 11409 --profile-id 1

# View your bookings
uv run idrd my-bookings

# Clear stored token
uv run idrd logout
```

### Output formats

- Default: Rich tables (human-readable)
- `--json`: Raw JSON (machine-parseable)

## Auth note

The API uses Bearer token auth. After `idrd login` succeeds, the token is
stored in the OS credential store via `keyring`:

- Windows: Credential Manager (DPAPI-backed; `WinVaultKeyring`)
- macOS: Keychain
- Linux: Secret Service (dbus)

`~/.idrd/session.json` is used **only as a fallback** when no keyring backend
is available (e.g. headless Linux/CI without Secret Service). The fallback
file is created with restrictive permissions (0o600 on POSIX, current-user-only
ACL on Windows) and written atomically, and a warning is logged whenever it is
used. Writes (enroll, my-bookings, whoami) require a valid token. The token
auto-loads on any command.

Since no real IDRD credentials are available for CI testing, write commands
are verified to hit the correct endpoint shape (URL + method) and correctly
reject unauthenticated requests with a clear message.

## Architecture

```
src/idrd/
├── cli.py       — Typer CLI commands (thin handlers)
├── client.py    — IdrdClient (httpx.AsyncClient, async)
├── models.py    — Pydantic models (Schedule, Program, Category, etc.)
├── ports.py     — IdrdClientPort (Protocol for testability)
├── service.py   — Service layer (business logic)
└── session.py   — Token persistence (~/.idrd/session.json)

tests/
├── conftest.py  — pytest config (--run-network flag)
├── test_unit.py — 17 unit tests (mocked transport, no network)
└── test_live.py — 6 live tests (require --run-network)
```

### Design decisions

- **Async-first**: httpx.AsyncClient for all I/O; CLI sync bridge via
  `asyncio.run()` per command.
- **Port/Adapter**: `IdrdClientPort` Protocol enables unit testing with
  MockTransport — real HTTP never touched in unit tests.
- **Auto-load token**: `IdrdClient()` constructor loads from disk;
  `IdrdClient(token=None)` skips disk (for tests and explicit control).
- **Dependency injection**: Service layer takes the port interface, not
  the concrete client.

## Tests

```bash
# Unit tests only (no network, fast)
uv run pytest tests/test_unit.py -v

# All tests including live API smoke tests
uv run pytest tests/ -v --run-network
```
