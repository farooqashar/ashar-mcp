"""Smoke test: every tool in the README table is served, a few of them run, and
country lookups resolve to the right country.

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


async def call(client: Client, tool: str, args: dict) -> dict:
    return (await client.call_tool(tool, args)).structured_content


async def check_country_lookup(client: Client) -> None:
    """Exact names, ISO codes and common aliases hit the right country; substrings don't."""
    oman = await call(client, "has_visited", {"place": "Oman"})
    assert not oman["visited"], f"Oman should not be visited: {oman['matches']}"

    for place, country in [
        ("Japan", "Japan"), ("JP", "Japan"), ("South Korea", "South Korea"),
        ("UK", "United Kingdom"), ("England", "United Kingdom"), ("USA", "United States"),
        ("UAE", "United Arab Emirates"), ("Turkey", "Türkiye"), ("Czech Republic", "Czechia"),
    ]:
        res = await call(client, "has_visited", {"place": place})
        countries = [m["name"] for m in res["matches"] if m["type"] == "country"]
        assert countries == [country], f"has_visited({place!r}) countries: {countries}"
        if place == "UK":
            names = [m["name"] for m in res["matches"]]
            assert not any("Montauk" in n or "Phuket" in n for n in names), names

    in_ = await call(client, "has_visited", {"place": "in"})
    assert not any(m["type"] == "country" for m in in_["matches"]), in_["matches"]

    oman_cities = await call(client, "list_places", {"kind": "cities", "country": "Oman"})
    assert oman_cities["items"] == [], oman_cities
    uk_cities = await call(client, "list_places", {"kind": "cities", "country": "UK"})
    assert uk_cities["items"] and all(i.endswith(", United Kingdom") for i in uk_cities["items"]), uk_cities
    assert await call(client, "list_trips", {"country": "Oman"}) == {"result": []}


async def main() -> None:
    expected = readme_tools()
    assert expected, "no tools found in the README Tools table"
    async with Client(server.mcp) as client:
        served = {t.name for t in await client.list_tools()}
        missing = expected - served
        assert not missing, f"tools in README but not served: {sorted(missing)}"
        await client.call_tool("about_ashar", {})
        await client.call_tool("has_visited", {"place": "Japan"})
        await check_country_lookup(client)
    print(f"ok: {len(expected)} README tools served; about_ashar and has_visited ran; country lookups resolve")


if __name__ == "__main__":
    asyncio.run(main())
