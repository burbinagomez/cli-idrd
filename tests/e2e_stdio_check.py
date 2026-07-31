"""E2E check: run the MCP server as a stdio subprocess with env vars set
(what a real MCP client like Hermes does) and exercise the bookmark flow.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

SERVER_FILE = Path(__file__).resolve().parents[1] / "src" / "idrd" / "mcp_server.py"
BOOKMARKS = Path(tempfile.gettempdir()) / "idrd-e2e-bookmarks.json"


async def main() -> None:
    if BOOKMARKS.exists():
        BOOKMARKS.unlink()

    env = dict(os.environ)
    env["IDRD_BOOKMARKS_PATH"] = str(BOOKMARKS)

    transport = StdioTransport("python", [str(SERVER_FILE)], env=env)
    async with Client(transport) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        print("tools:", sorted(names))

        # 1. bookmark an activity (live fetch from IDRD API)
        res = await client.call_tool(
            "bookmark_activity",
            {"schedule_id": 11410, "note": "e2e via stdio client"},
        )
        payload = json.loads(res.content[0].text)
        print("bookmark_activity:", payload["bookmarked"], payload["bookmark"]["schedule_id"])

        # 2. is_bookmarked
        res = await client.call_tool("is_bookmarked", {"schedule_id": 11410})
        print("is_bookmarked:", json.loads(res.content[0].text))

        # 3. list_bookmarks
        res = await client.call_tool("list_bookmarks", {})
        listed = json.loads(res.content[0].text)
        print("list_bookmarks count:", listed["count"])

        # 4. remove_bookmark
        res = await client.call_tool("remove_bookmark", {"schedule_id": 11410})
        print("remove_bookmark:", json.loads(res.content[0].text))

    print("bookmarks file:", BOOKMARKS)
    print("file contents:", BOOKMARKS.read_text(encoding="utf-8") if BOOKMARKS.exists() else "MISSING")


if __name__ == "__main__":
    asyncio.run(main())
