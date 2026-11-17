"""Smoke test: every tool in the README table is served, a few of them run, and
country lookups resolve to the right country.

Uses FastMCP's in-memory client, so no server or network is needed.
Run from the repo root:   python scripts/smoke_test.py
"""

import asyncio
import os
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


async def check_search(client: Client) -> None:
    """search_everything finds trips by country name and ignores JSON keys."""
    japan = await call(client, "search_everything", {"query": "Japan"})
    assert "trip-4" in [t["id"] for t in japan["trips"]], japan["trips"]
    assert "Tokyo" in japan["cities"], japan["cities"]

    trips, airports = len(server.TRAVEL["trips"]), len(server.TRAVEL["airports"])
    for key in ("name", "id", "photos", "startDate", "lat"):
        res = await call(client, "search_everything", {"query": key})
        assert len(res["trips"]) < trips and len(res["airports"]) < airports, (
            f"search_everything({key!r}) matched every trip or airport"
        )

    houston = await call(client, "search_everything", {"query": "Houston"})
    assert houston["trips"] and "Houston" in houston["cities"], houston


class _FakeNotes:
    """Stands in for the Atlas collection: records the pipeline, returns one canned hit."""

    def __init__(self) -> None:
        self.pipeline: list = []

    def aggregate(self, pipeline: list) -> list:
        self.pipeline = pipeline
        return [{"path": "AI-Agents/Agents in the cloud.md", "title": "Agents in the cloud",
                 "folder": "AI-Agents", "heading": "Setup", "source": "https://example.com/a",
                 "tags": ["clippings", "agents"], "text": "Run coding agents remotely.", "score": 0.91234}]


async def check_ask_notes(client: Client) -> str:
    """ask_notes without Atlas: the unconfigured and bad-URI error shapes, and the query it builds.
    Skipped when MONGODB_URI is set, so the test never talks to a real cluster. Returns a summary."""
    if os.environ.get("MONGODB_URI"):
        return "ask_notes SKIPPED (MONGODB_URI is set; this test does not touch a real cluster)"

    notes = await call(client, "ask_notes", {"question": "coding agents"})
    assert notes["results"] == [] and "MONGODB_URI is not set" in notes["error"], notes

    real_notes = server._notes
    try:
        # A malformed URI fails while building the client; that must come back as an error field.
        os.environ["MONGODB_URI"] = "mongodb://"
        notes = await call(client, "ask_notes", {"question": "coding agents"})
        assert notes["results"] == [] and "InvalidURI" in notes["error"], notes

        fake = _FakeNotes()
        server._notes = lambda: fake
        notes = await call(client, "ask_notes", {"question": "coding agents", "folder": "ai-agents", "limit": 3})
        search = fake.pipeline[0]["$vectorSearch"]
        assert search["query"] == {"text": "coding agents"}, search
        assert search["filter"] == {"folder": {"$eq": "AI-Agents"}} and search["limit"] == 3, search
        hit = notes["results"][0]
        assert hit["tags"] == ["agents"] and hit["score"] == 0.912, hit
        assert hit["note"].endswith("/AI-Agents/Agents%20in%20the%20cloud.md"), hit
    finally:
        os.environ.pop("MONGODB_URI", None)
        server._notes = real_notes
        server._notes_client = None
    return "ask_notes ran (unconfigured, bad URI and query shape against a fake collection)"


async def main() -> None:
    expected = readme_tools()
    assert expected, "no tools found in the README Tools table"
    async with Client(server.mcp) as client:
        served = {t.name for t in await client.list_tools()}
        missing = expected - served
        assert not missing, f"tools in README but not served: {sorted(missing)}"
        await client.call_tool("about_ashar", {})
        await client.call_tool("has_visited", {"place": "Japan"})
        for kind in ("cities", "airports"):
            unknown = await client.call_tool("list_places", {"kind": kind, "country": "Narnia"})
            assert unknown.data["count"] == 0, f"list_places({kind!r}, 'Narnia') returned {unknown.data['count']} items"
        await check_country_lookup(client)
        await check_search(client)
        notes_checked = await check_ask_notes(client)
    print(
        f"ok: {len(expected)} README tools served; about_ashar, has_visited and list_places ran; "
        f"country lookups and search resolve; {notes_checked}"
    )


if __name__ == "__main__":
    asyncio.run(main())
