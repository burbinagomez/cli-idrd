# IDRD Portal Ciudadano — API Recon (verified live, 2026-07-30)

This file is the source of truth the backend CLI must implement against.
All endpoints below were probed live with curl against the production backend.

## Base URL
```
https://portalciudadano-back.idrd.gov.co
```
This is the JSON API host for the SPA at https://portalciudadano.idrd.gov.co/
(direct URL paths on the SPA 404 because routing is client-side).

## Auth
- `POST /api/login`  body: `{"email": "...", "password": "..."}`
  - Success: returns JSON with `access_token` (and `token_type`).
  - Failure (wrong creds): `401 {"message":"Usuario o contraseña incorrectos","code":401}`
  - Missing fields: `422 {"message":"Por favor completa todos los datos del formulario.","errors":{...}}`
- `POST /api/register` (`multipart`, `registerWithFiles`) — account creation (optional for MVP).
- `POST /api/logout`, `POST /api/logout-all-devices`
- `GET  /api/user`  — current user (requires auth, else 401).
- `GET  /api/profiles`, `/api/profiles/list`, `/api/profiles/verified` — list beneficiary profiles.
  The inscription endpoint needs a `profile_id` (id of the beneficiary profile).

### Authorization header
The SPA interceptor sets: `Authorization: <token_type> <access_token>`
where `token_type` comes from the login response. `token_type` default observed as
null in the store, but a successful login response likely populates it (typically "Bearer").
The Python client MUST:
  1. Default to sending `Authorization: Bearer <access_token>`.
  2. Make the prefix configurable / fall back to raw token if a 401 suggests it.
Never hardcode a guess without a fallback.

Rate limit headers present: `X-Ratelimit-Limit: 300`, `X-Ratelimit-Remaining: N`.

## Search activities (READ — no auth required, VERIFIED)
- `GET /api/citizen-portal/public-schedules`  (paginated, Laravel-style)
  - Query params confirmed:
    - `page=N` (pagination; `per_page` default 10, `last_page` in meta ~13, `total` ~127)
    - `program_id[]=12`  (ARRAY — server requires it as an array; `program_id=12` returns
      error `programa debe ser un conjunto.`)
    - `category=ATLETISMO`  (string filter; values from /schedules/categories `value` field)
    - `locality=1`  (integer locality id)
  - Single item: `GET /api/citizen-portal/public-schedules/{id}` works (returns `data` object).
  - Response shape (each item in `data`):
    ```json
    {
      "id": 11409,
      "icon": "mdi-walk",
      "program_name": "BOGOTÁ FELIZ",
      "activity_name": "CAMINATAS RECREATIVAS",
      "stage_name": "PLAZA CULTURAL SANTA MARIA ...",
      "park_code": "03-039",
      "park_name": "INDEPENDENCIA-BICENTENARIO",
      "park_address": "CALLE 24 N 6A 01",
      "weekday_name": "VIERNES 31 DE JULIO DE 2026",
      "daily_name": "06:00 P.M. A 08:00 P.M.",
      "min_age": 6, "max_age": 100,
      "quota": 40,
      "is_paid": false,
      "rate_id": null, "rate_name": null, "rate_value": null,
      "is_initiate": true,
      "start_date": "2026-07-29 18:00:00",
      "final_date": "2026-07-31 14:00:00",
      "is_activated": true,
      "is_teams": false,
      "min_team_participants_quota": 0,
      "max_team_participants_quota": 0,
      "team_quota": 0,
      "disability": false,
      "taken": 32,
      "users_schedules_count": 32,
      "teams_schedules_count": 0,
      "consent": [], "regulations": [],
      "created_at": "...", "updated_at": "..."
    }
    ```
  - Envelope: `{data:[...], links:{first,last,prev,next}, meta:{current_page,from,last_page,path,per_page,to,total}, code:200, details:{headers,expanded}, requested_at:"..."}`

- `GET /api/citizen-portal/programs` — list of programs
  (`id`, `name`, `composed_name`, `schedules_count`). Used to resolve `program_id`.

- `GET /api/citizen-portal/schedules/categories` — activity categories
  (`name`, `value`, `icon`). Use `value` as the `category` filter for public-schedules.

- `GET /api/citizen-portal/stages` — stages/scenarios
  (`id`, `name`, `park_id`, `park_code`, `park_name`, `schedules_count`).

- `GET /api/citizen-portal/bookings` — list current user's bookings/subscriptions (auth).
- `GET /api/citizen-portal/pending-to-pay` — pending payments (auth).
- `GET /api/citizen-portal/payments/activities/{id}` — payment info for an activity (auth).

## Register to an activity (WRITE — requires auth, VERIFIED 401 without token)
Inscription flow used by the SPA "Inscribirme":
- `PUT /api/profiles/{profile_id}/schedules/{schedule_id}`
  - `profile_id`: id of the beneficiary profile (from /api/profiles or /api/user).
  - `schedule_id`: the activity schedule id (the `id` from public-schedules).
  - Body: `{}` (empty) in the SPA call; server may accept empty or ignore.
  - This is the endpoint that actually enrolls a profile into a schedule.
- Listing your enrollments: `GET /api/profiles/subscriptions` (or /api/profiles/{id}/schedules).
- Unenroll: the SPA also has `DELETE /api/profiles/subscriptions/{id}` style — confirm by probing.
- Paid activities: after subscribe, `POST /api/citizen-portal/payments/activities/{id}` +
  PSE/bank flow. MVP: only handle free (`is_paid=false`) activities.

## Notes / pitfalls
- Always send `Accept: application/json` and `Content-Type: application/json`.
- The API is Laravel (paginated resources, `code` field, `details` field).
- `program_id` MUST be passed as an array query param (`program_id[]=`).
- Write endpoints return 401 without a valid token — do not assume any write works
  without first logging in with REAL credentials. The CLI should support reading the
  token from a stored session file and only attempt writes when authenticated.
- Because we have no real IDRD credentials, the build must be verified against the
  READ endpoints (which work unauthenticated). The write/inscription path must be
  implemented and, where possible, validated for correct request shape (e.g. that it
  reaches the 401/auth stage with the right URL/method), but full enrollment can only be
  confirmed by the user with their own account.

## Suggested CLI surface (Python, backend profile)
- `idrd login --email E --password P`  → stores token in `~/.idrd/session.json`
- `idrd search [--category CAT] [--program ID] [--locality ID] [--page N]`
- `idrd activities list` (alias of search)
- `idrd activities show <id>`
- `idrd programs list`
- `idrd categories list`
- `idrd stages list`
- `idrd enroll <schedule_id> [--profile-id ID]`  → PUT subscribe (auth)
- `idrd my bookings`  → list subscriptions (auth)
- Output: table (rich) or `--json` for machine use.
- Use `httpx` (async) + `pydantic` models + `typer`/`click` for the CLI.
- Keep a `IdrdClient` class with a clean port (Protocol) so the API layer is testable.
