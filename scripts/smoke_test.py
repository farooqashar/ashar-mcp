"""Smoke test: every tool in the README table is served, and two of them run.

Uses FastMCP's in-memory client, so no server or network is needed.
Run from the repo root:   python scripts/smoke_test.py
"""

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastmcp import Client  # noqa: E402

import server  # noqa: E402


def readme_tools() -> set[str]:
    """Tool names from the first column of the README's Tools table."""
    text = (ROOT / "README.md").read_text()
    section = text.split("## Tools", 1)[1].split("\n## ", 1)[0]
    names = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            names.update(re.findall(r"`(\w+)", first_cell))
    return names


async def main() -> None:
    expected = readme_tools()
    assert expected, "no tools found in the README Tools table"
    async with Client(server.mcp) as client:
        served = {t.name for t in await client.list_tools()}
        missing = expected - served
        assert not missing, f"tools in README but not served: {sorted(missing)}"
        await client.call_tool("about_ashar", {})
        await client.call_tool("has_visited", {"place": "Japan"})
    print(f"ok: {len(expected)} README tools served; about_ashar and has_visited ran")


if __name__ == "__main__":
    asyncio.run(main())
