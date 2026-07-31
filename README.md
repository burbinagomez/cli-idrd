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

# Safer: omit --password — the CLI uses $IDRD_PASSWORD, else prompts hidden
uv run idrd login --email your@email.com
IDRD_PASSWORD=yourpass uv run idrd login --email your@email.com

# View your user info
uv run idrd whoami

# Enroll in a free activity (--profile-id from /api/profiles)
uv run idrd enroll 11409 --profile-id 1

# View your bookings
uv run idrd my-bookings

# Clear stored token
uv run idrd logout
```

Password resolution order: `--password` flag > `$IDRD_PASSWORD` > hidden interactive
prompt. Prefer the env var or prompt so the password never appears in shell
history or process listings. If no password is available and stdin is not a
terminal, login fails with a clear message (exit code 1).

Session file location defaults to `~/.idrd/session.json`; override with
`IDRD_SESSION_PATH` (useful for tests and CI). Writes are atomic (temp file +
rename) and the file is chmod 600 on POSIX.

If the server returns `expires_in`/`expires_at` in the login response, the token
records its expiry and auth-gated commands fail fast with a clear
"token has expired — re-run idrd login" message instead of hitting the API with
a dead token.

### Output formats

- Default: Rich tables (human-readable)
- `--json`: Raw JSON (machine-parseable)

## Auth note

The API uses Bearer token auth. After `idrd login` succeeds, the token is
persisted to `~/.idrd/session.json`. Writes (enroll, my-bookings, whoami)
require a valid token. The token auto-loads from disk on any command.

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
└── session.py   — Token persistence (~/.idrd/session.json, atomic writes)

tests/
├── conftest.py  — pytest config (--run-network flag)
├── test_unit.py — 38 unit tests (mocked transport, no network)
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
