"""Typer CLI for IDRD Portal Ciudadano.

All async calls wrapped with asyncio.run() since Typer uses sync handlers.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from idrd.cache import CachedClient, FileCache
from idrd.client import IdrdClient
from idrd.ports import IdrdClientPort
from idrd.service import IdrdService
from idrd.session import clear_token

app = typer.Typer(
    name="idrd",
    help="CLI for IDRD Portal Ciudadano — Bogotá recreation institute API.",
    no_args_is_help=True,
)
activities_app = typer.Typer(help="Activity commands.")
app.add_typer(activities_app, name="activities")
programs_app = typer.Typer(help="Program commands.")
app.add_typer(programs_app, name="programs")
categories_app = typer.Typer(help="Category commands.")
app.add_typer(categories_app, name="categories")
stages_app = typer.Typer(help="Stage commands.")
app.add_typer(stages_app, name="stages")
cache_app = typer.Typer(help="Local response cache commands (search results).")
app.add_typer(cache_app, name="cache")
profiles_app = typer.Typer(help="Beneficiary profile commands (auth).")
app.add_typer(profiles_app, name="profiles")

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────

def _run(coro) -> Any:
    """Run an async coroutine synchronously (one-shot CLI call)."""
    return asyncio.run(coro)


def resolve_password(explicit: Optional[str]) -> str:
    """Resolve the login password: --password flag > $IDRD_PASSWORD > hidden prompt.

    On Windows, getpass reads from the console and ignores stdin redirection, so
    prompting when stdin is not a TTY would hang scripts/CI forever — fail fast
    with a clear message instead. Kept as a module-level helper so it is
    unit-testable without driving a TTY.
    """
    if explicit:
        return explicit
    env_password = os.environ.get("IDRD_PASSWORD")
    if env_password:
        return env_password
    if not sys.stdin.isatty():
        raise RuntimeError(
            "No password provided. Pass --password, set $IDRD_PASSWORD, "
            "or run in an interactive terminal."
        )
    import getpass

    try:
        return getpass.getpass("Password: ")
    except (EOFError, OSError):
        raise RuntimeError(
            "No password provided. Pass --password, set $IDRD_PASSWORD, "
            "or run in an interactive terminal."
        ) from None


def _get_service(cache: bool = True) -> IdrdService:
    """Build service using stored token or fresh client (auto-loads from disk).

    Read/search calls go through a TTL disk cache unless cache=False.
    """
    client: IdrdClientPort = IdrdClient()
    if cache:
        client = CachedClient(client)
    return IdrdService(client)


def _print_cache_note(service: IdrdService) -> None:
    """Print a dim 'served from cache' hint when the last read was a cache hit."""
    stats = service.cache_stats
    if stats and stats[0]:
        console.print("  [dim]⚡ served from cache[/]")


async def _hidden_search(service: IdrdService) -> tuple[list[int], list[int], Optional[Any]]:
    """Discover hidden activities and fetch the first found one.

    Runs inside a single event loop so the shared httpx client is never
    reused across `asyncio.run()` boundaries (which would trip over closed
    event-loop connections).
    """
    found, probed = await service.discover_hidden()
    sched = None
    if found:
        try:
            sched = await service.get_schedule(found[0])
        except Exception:
            sched = None
    return found, probed, sched


def _print_json(data) -> None:
    """Print data as JSON."""
    import json
    console.print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _schedule_table(schedules, title: str = "Activities") -> Table:
    """Build a rich table from Schedule list."""
    table = Table(title=title)
    table.add_column("ID", style="cyan")
    table.add_column("Activity", style="green")
    table.add_column("Program")
    table.add_column("Stage", overflow="fold")
    table.add_column("Park")
    table.add_column("When")
    table.add_column("Quota", justify="right")
    table.add_column("Taken", justify="right")
    for s in schedules:
        table.add_row(
            str(s.id),
            s.activity_name or "",
            s.program_name or "",
            s.stage_name or "",
            s.park_name or "",
            s.daily_name or "",
            str(s.quota or ""),
            str(s.taken or ""),
        )
    return table


# ── Auth ──────────────────────────────────────────────────────────────────

@app.command()
def login(
    email: str = typer.Option(..., "--email", "-e", help="Email address"),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-p",
        help="Password (omit to use $IDRD_PASSWORD or be prompted)",
        hide_input=True,
    ),
) -> None:
    """Authenticate and store the session token."""
    service = _get_service()
    try:
        resolved = resolve_password(password)
        token = _run(service.login(email=email, password=resolved))
        console.print(f"[green]✓[/] Login successful. Token stored (type: {token.token_type}).")
    except RuntimeError as e:
        console.print(f"[red]✗[/] Login failed: {e}")
        raise typer.Exit(code=1)


@app.command()
def logout() -> None:
    """Remove the stored session token."""
    clear_token()
    console.print("[green]✓[/] Token cleared.")


@app.command()
def whoami(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show the current authenticated user."""
    service = _get_service()
    try:
        user = _run(service.whoami())
    except RuntimeError as e:
        console.print(f"[red]✗[/] {e}")
        raise typer.Exit(code=1)
    if user is None:
        console.print("[yellow]Not logged in (or no user data).[/]")
        raise typer.Exit(code=1)
    if json:
        _print_json(user.model_dump(mode="json"))
    else:
        table = Table(title="User")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("ID", str(user.id))
        table.add_row("Name", user.name or "")
        table.add_row("Email", user.email or "")
        table.add_row("Document", user.document or "")
        table.add_row("Document Type", user.document_type or "")
        table.add_row("Phone", user.phone or "")
        console.print(table)


# ── Search ────────────────────────────────────────────────────────────────

@app.command()
def search(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category filter (value from categories list)"),
    program_id: Optional[str] = typer.Option(None, "--program-id", "-p", help="Program ID (comma-separated for multiple)"),
    locality: Optional[int] = typer.Option(None, "--locality", "-l", help="Locality ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    hidden: bool = typer.Option(False, "--hidden", help="Discover activities past the public list (probes singular public-schedules/{id})"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the response cache and hit the API"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search public activity schedules (or discover hidden ones with --hidden)."""
    service = _get_service(cache=not no_cache)
    pids: Optional[list[int]] = None
    if program_id:
        pids = [int(x.strip()) for x in program_id.split(",") if x.strip()]
    if hidden:
        # Probe singular public-schedules/{id} past the known public list,
        # stopping at the first 404 (last real id = highest reachable id).
        try:
            found, probed, sched = _run(_hidden_search(service))
        except Exception as e:
            console.print(f"[red]✗[/] Hidden discovery failed: {e}")
            raise typer.Exit(code=1)
        if not found:
            console.print("[yellow]No hidden activities found (all probed ids 404).[/]")
            return
        console.print(f"[green]✓[/] Found {len(found)} hidden activit{'y' if len(found)==1 else 'ies'} (probed {len(probed)} ids):")
        for pid in found:
            console.print(f"  • program_id {pid}")
        if sched is not None:
            if json:
                _print_json(sched.model_dump(mode="json"))
            else:
                table = _schedule_table([sched], title=f"Hidden Activity (program_id {found[0]})")
                console.print(table)
        else:
            console.print(f"[yellow]Could not fetch detail for {found[0]}.[/]")
        return
    try:
        schedules, links, meta = _run(service.search_schedules(
            category=category,
            program_id=pids,
            locality=locality,
            page=page,
        ))
    except Exception as e:
        console.print(f"[red]✗[/] Search failed: {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([s.model_dump(mode="json") for s in schedules])
    else:
        if not schedules:
            console.print("[yellow]No results.[/]")
            return
        console.print(_schedule_table(
            schedules,
            title=f"Activities (page {meta.get('current_page', '?')}/{meta.get('last_page', '?')})",
        ))
        console.print(f"  [dim]Total: {meta.get('total', '?')} items | Page {meta.get('current_page', '?')} of {meta.get('last_page', '?')}[/]")
        _print_cache_note(service)


# ── Activities ────────────────────────────────────────────────────────────

@activities_app.command(name="show")
def activities_show(
    schedule_id: int = typer.Argument(..., help="Schedule/activity ID"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the response cache and hit the API"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show details of a single activity schedule."""
    service = _get_service(cache=not no_cache)
    try:
        sched = _run(service.get_schedule(schedule_id))
    except Exception as e:
        console.print(f"[red]✗[/] Failed: {e}")
        raise typer.Exit(code=1)
    if sched is None:
        console.print("[yellow]Activity not found.[/]")
        raise typer.Exit(code=1)
    if json:
        _print_json(sched.model_dump(mode="json"))
    else:
        table = Table(title=f"Activity #{sched.id}")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for field, val in sched.model_dump(mode="json").items():
            table.add_row(field.replace("_", " ").title(), str(val) if val is not None else "[dim]null[/]")
        console.print(table)
        _print_cache_note(service)


# ── Programs ──────────────────────────────────────────────────────────────

@programs_app.command(name="list")
def programs_list(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all programs."""
    service = _get_service()
    try:
        programs = _run(service.list_programs())
    except Exception as e:
        console.print(f"[red]✗[/] Failed: {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([p.model_dump(mode="json") for p in programs])
    else:
        table = Table(title="Programs")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Composed Name")
        table.add_column("Schedules", justify="right")
        for p in programs:
            table.add_row(
                str(p.id),
                p.name or "",
                p.composed_name or "",
                str(p.schedules_count or 0),
            )
        console.print(table)


# ── Categories ────────────────────────────────────────────────────────────

@categories_app.command(name="list")
def categories_list(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List activity categories."""
    service = _get_service()
    try:
        categories = _run(service.list_categories())
    except Exception as e:
        console.print(f"[red]✗[/] Failed: {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([c.model_dump(mode="json") for c in categories])
    else:
        table = Table(title="Categories")
        table.add_column("Name")
        table.add_column("Value")
        table.add_column("Icon")
        for c in categories:
            table.add_row(c.name or "", c.value or "", c.icon or "")
        console.print(table)


# ── Stages ────────────────────────────────────────────────────────────────

@stages_app.command(name="list")
def stages_list(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List stages/scenarios."""
    service = _get_service()
    try:
        stages = _run(service.list_stages())
    except Exception as e:
        console.print(f"[red]✗[/] Failed: {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([s.model_dump(mode="json") for s in stages])
    else:
        table = Table(title="Stages")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Park")
        table.add_column("Park Code")
        table.add_column("Schedules", justify="right")
        for s in stages:
            table.add_row(
                str(s.id),
                s.name or "",
                s.park_name or "",
                s.park_code or "",
                str(s.schedules_count or 0),
            )
        console.print(table)


# ── Enroll ────────────────────────────────────────────────────────────────

@app.command()
def enroll(
    schedule_id: int = typer.Argument(..., help="Schedule/activity ID to enroll in"),
    profile_id: Optional[int] = typer.Option(None, "--profile-id", "-p", help="Beneficiary profile ID (auto-selected if you have only one)"),
) -> None:
    """Enroll a profile in an activity (requires auth)."""
    service = _get_service()
    try:
        pid, result = _run(service.enroll_for_user(schedule_id=schedule_id, profile_id=profile_id))
        console.print(f"[green]✓[/] Enrollment request sent for profile {pid}.")
        if result:
            _print_json(result)
    except RuntimeError as e:
        console.print(f"[red]✗[/] {e}")
        raise typer.Exit(code=1)


# ── Profiles ──────────────────────────────────────────────────────────────

@profiles_app.command(name="list")
def profiles_list(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List your beneficiary profiles (requires auth)."""
    service = _get_service()
    try:
        profiles = _run(service.list_profiles())
    except RuntimeError as e:
        console.print(f"[red]✗[/] {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([p.model_dump(mode="json") for p in profiles])
    else:
        if not profiles:
            console.print("[yellow]No profiles found.[/]")
            return
        table = Table(title="Profiles")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Document")
        table.add_column("Doc Type")
        table.add_column("Birthdate")
        table.add_column("Age", justify="right")
        table.add_column("Verified")
        for p in profiles:
            table.add_row(
                str(p.id),
                p.full_name or "",
                p.document or "",
                p.document_type or (str(p.document_type_id) if p.document_type_id else ""),
                p.birthdate or "",
                str(p.age or ""),
                "yes" if p.verified else ("no" if p.verified is not None else ""),
            )
        console.print(table)


# ── My Bookings ──────────────────────────────────────────────────────────

@app.command(name="my-bookings")
def my_bookings(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List your current bookings/subscriptions (requires auth)."""
    service = _get_service()
    try:
        bookings = _run(service.my_bookings())
    except RuntimeError as e:
        console.print(f"[red]✗[/] {e}")
        raise typer.Exit(code=1)
    if json:
        _print_json([b.model_dump(mode="json") for b in bookings])
    else:
        if not bookings:
            console.print("[yellow]No bookings found.[/]")
            return
        table = Table(title="My Bookings")
        table.add_column("ID", style="cyan")
        table.add_column("Schedule ID")
        table.add_column("Profile ID")
        table.add_column("Status")
        table.add_column("Activity")
        table.add_column("Created")
        for b in bookings:
            act_name = b.schedule.activity_name if b.schedule else ""
            table.add_row(
                str(b.id),
                str(b.schedule_id or ""),
                str(b.profile_id or ""),
                b.status or "",
                act_name or "",
                b.created_at or "",
            )
        console.print(table)


# ── Cache ─────────────────────────────────────────────────────────────────

@cache_app.command(name="clear")
def cache_clear() -> None:
    """Delete all cached responses (search results, activity details)."""
    cache = FileCache()
    removed = _run(cache.clear())
    console.print(
        f"[green]✓[/] Cache cleared ({removed} entr{'y' if removed == 1 else 'ies'} removed)."
    )


@cache_app.command(name="stats")
def cache_stats() -> None:
    """Show cache location, entry count, and default TTL."""
    cache = FileCache()
    info = cache.stats()
    console.print(f"Cache dir:  [cyan]{info['dir']}[/]")
    console.print(f"Entries:    [cyan]{info['entries']}[/]")
    if info["entries"]:
        console.print(f"Oldest:     [cyan]{info['oldest_seconds']:.0f}s[/] old")
    ttl = info["ttl_default"]
    console.print(f"Default TTL: [cyan]{ttl if ttl is not None else 'never'}s[/]")


# ── Main entry point ──────────────────────────────────────────────────────

def main() -> None:
    """Entry point for `uv run idrd`."""
    app()


if __name__ == "__main__":
    main()
