# IDRD CLI — Portal Ciudadano

CLI + MCP server for the IDRD (Bogotá Recreation & Sports Institute) Portal
Ciudadano API.

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

# Search results are cached on disk (see "Response cache" below)
uv run idrd search --no-cache   # bypass the cache for one run
uv run idrd cache stats         # show cache location / entry count
uv run idrd cache clear         # drop all cached responses

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

## Response cache

The IDRD API is rate-limited (`X-Ratelimit-Limit: 300`), so read/search
commands cache successful responses on disk:

- Cached: `search`, `activities show`, `programs list`, `categories list`,
  `stages list`
- Never cached: auth/write calls (`login`, `enroll`, `my-bookings`,
  `whoami`) and `search --hidden` probing

Entries live in `~/.idrd/cache/` (override with `IDRD_CACHE_DIR`), keyed by
a hash of the exact query, with a TTL of `IDRD_CACHE_TTL` seconds (default
300). Writes are atomic (temp file + rename), so concurrent CLI runs never
see a half-written entry. When output comes from the cache, the CLI prints a
dim `⚡ served from cache` line (table output only — `--json` stays pure).

```bash
uv run idrd cache stats    # cache dir, entry count, oldest entry, default TTL
uv run idrd cache clear    # delete everything; next run refetches from the API
uv run idrd search --no-cache
uv run idrd activities show 11409 --no-cache
```

## Auth note

The API uses Bearer token auth. After `idrd login` succeeds, the token is
persisted to `~/.idrd/session.json`. Writes (enroll, my-bookings, whoami)
require a valid token. The token auto-loads from disk on any command.

Since no real IDRD credentials are available for CI testing, write commands
are verified to hit the correct endpoint shape (URL + method) and correctly
reject unauthenticated requests with a clear message.

## MCP server (idrd-mcp)

An MCP (Model Context Protocol) server exposes the IDRD API plus a **local
bookmark tool** to LLM agents (Claude Code, Cursor, Hermes, etc.).

```bash
# Run over stdio (default MCP transport)
uv run idrd-mcp

# Inspect/validate with the FastMCP CLI
uv run fastmcp inspect src/idrd/mcp_server.py:mcp
uv run fastmcp list src/idrd/mcp_server.py --json
```

### Tools

| Tool                | Description                                              |
|---------------------|----------------------------------------------------------|
| `search_activities` | Search public schedules (category / program / locality)  |
| `get_activity`      | Full details for one schedule by ID                      |
| `bookmark_activity` | Save a schedule locally, with an optional note           |
| `list_bookmarks`    | List locally bookmarked activities                       |
| `remove_bookmark`   | Remove a bookmark by schedule ID                         |
| `is_bookmarked`     | Check whether a schedule is bookmarked                   |

Bookmarks are stored in `~/.idrd/bookmarks.json` (the IDRD API has no
bookmark endpoint). Override the location with the `IDRD_BOOKMARKS_PATH`
environment variable — useful for tests or per-machine stores:

```bash
IDRD_BOOKMARKS_PATH=./bookmarks.json uv run idrd-mcp
```

### Registering with an MCP client

```bash
# Claude Code
uv run fastmcp install claude-code src/idrd/mcp_server.py

# Cursor (editable install so local code changes apply)
uv run fastmcp install cursor src/idrd/mcp_server.py -e .

# Any other client: point it at `uv run idrd-mcp` (stdio)
```

End-to-end smoke check against the live API (needs network):

```bash
uv run python tests/e2e_stdio_check.py
```

## Architecture

```
src/idrd/
├── cli.py       — Typer CLI commands (thin handlers)
├── client.py    — IdrdClient (httpx.AsyncClient, async)
├── cache.py     — CachedClient decorator + TTL cache backends (FileCache, MemoryCache)
├── models.py    — Pydantic models (Schedule, Program, Category, etc.)
├── ports.py     — IdrdClientPort (Protocol for testability)
├── service.py   — Service layer (business logic)
├── session.py   — Token persistence (~/.idrd/session.json, atomic writes)
├── bookmarks.py — Local bookmark store (~/.idrd/bookmarks.json)
└── mcp_server.py — FastMCP server: activities + bookmark tools

tests/
├── conftest.py  — pytest config (--run-network flag)
├── test_unit.py — request-shape tests (mocked transport, no network)
├── test_cache.py — caching layer tests (no network)
├── test_bookmarks.py — bookmark store unit tests
├── test_mcp_server.py — MCP tool tests (fake service, no network)
├── e2e_stdio_check.py — manual E2E check: real stdio client + live API
└── test_live.py — live tests (require --run-network)
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
- **Search caching layer**: `CachedClient` wraps `IdrdClient` and caches
  successful read/search responses (schedules, activity detail, reference
  lists) in a TTL JSON cache under `~/.idrd/cache/`. The `Cache` Protocol
  lets tests inject an in-memory backend; failed calls are never cached,
  and auth/write calls always pass through.

## Tests

```bash
# Unit tests only (no network, fast)
uv run pytest tests/test_unit.py -v

# All tests including live API smoke tests
uv run pytest tests/ -v --run-network
```
