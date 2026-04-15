from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict

from fastmcp import Client


async def main() -> None:
    # Ensure we import the server module from the repo, not an installed package.
    repo_backend = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env: Dict[str, str] = dict(os.environ)
    env["PYTHONPATH"] = repo_backend

    # Prefer MAPBOX_ACCESS_TOKEN; fall back to common variants.
    token = (env.get("MAPBOX_ACCESS_TOKEN") or env.get("MAPBOX_TOKEN") or env.get("mapbox_access_token") or "").strip()
    if not token:
        raise SystemExit("Missing MAPBOX_ACCESS_TOKEN (or mapbox_access_token) in environment.")
    env["MAPBOX_ACCESS_TOKEN"] = token

    # Pass an MCP config dict (same shape as `.cursor/mcp.json`).
    transport: Dict[str, Any] = {
        "mcpServers": {
            "mapbox": {
                "command": sys.executable,
                "args": ["-m", "app.mcp_servers.mapbox.server"],
                "env": env,
            }
        },
        "defaultServer": "mapbox",
    }

    async with Client(transport, name="mapbox-stdio-test") as c:
        tools = await c.list_tools()
        print("tools:", [t.name for t in tools])

        result = await c.call_tool(
            "geocode_forward",
            {"query": "Paris", "limit": 1, "language": "fr", "country": "fr"},
        )
        print("call_tool(geocode_forward) result:")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())

