# Vercel entrypoint: Vercel's Python runtime serves the ASGI `app` exported here.
#
# vercel.json rewrites every URL to this function, and depending on the runtime the
# app may see the rewritten path (/api/index) instead of the one the client used.
# The server only has one endpoint, so send every request except "/" to /mcp.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app as mcp_app, mcp  # noqa: E402

INFO = json.dumps(
    {
        "name": mcp.name,
        "endpoint": "/mcp",
        "transport": "streamable-http",
        "about": "Read-only MCP server with Ashar Farooq's trips, travel trackers and Things Done.",
        "source": "https://github.com/farooqashar/ashar-mcp",
    }
).encode()


async def app(scope, receive, send):
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path in ("", "/") and scope.get("method") == "GET":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": INFO})
            return
        if path != "/mcp":
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
    await mcp_app(scope, receive, send)
