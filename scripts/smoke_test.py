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
from fastmcp.exceptions import ToolError  # noqa: E402

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


async def check_place_qualifiers(client: Client) -> None:
    """"City, country/state" finds the city in that country only; a blank query is an error."""
    for place, city in [
        ("Tokyo, Japan", "Tokyo"), ("Paris, France", "Paris"), ("Houston, TX", "Houston"),
        ("Houston, Texas", "Houston"), ("Houston, USA", "Houston"), ("Tokyo, Narnia", "Tokyo"),
    ]:
        res = await call(client, "has_visited", {"place": place})
        cities = [m["name"] for m in res["matches"] if m["type"] == "city"]
        assert res["visited"] and city in cities, f"has_visited({place!r}): {res['matches']}"
        assert res["query"] == place, res["query"]

    houston = await call(client, "has_visited", {"place": "Houston, TX"})
    assert houston["trips"], "has_visited('Houston, TX') found no trips"

    texas = await call(client, "has_visited", {"place": "Paris, Texas"})
    assert not texas["visited"] and not texas["trips"], f"Paris, Texas matched France: {texas}"

    # A qualified trip needs the place at a stop in that country, not just both on one itinerary.
    cairo_bh = await call(client, "has_visited", {"place": "Cairo, Bahrain"})
    assert not cairo_bh["visited"] and not cairo_bh["trips"], f"Cairo, Bahrain matched: {cairo_bh}"
    cairo_eg = await call(client, "has_visited", {"place": "Cairo, Egypt"})
    assert "trip-17" in [t["id"] for t in cairo_eg["trips"]], cairo_eg["trips"]

    # The result says how the qualifier was read: a state narrows to the US only, unknowns are ignored.
    alaska = await call(client, "has_visited", {"place": "Houston, Alaska"})
    assert alaska["qualifier"]["countries"] == ["United States"], alaska["qualifier"]
    assert "isn't checked" in alaska["qualifier"]["note"], alaska["qualifier"]
    narnia = await call(client, "has_visited", {"place": "Tokyo, Narnia"})
    assert narnia["qualifier"]["countries"] == [] and "ignored" in narnia["qualifier"]["note"], narnia

    for tool, arg in [("has_visited", "place"), ("search_everything", "query")]:
        for blank in ("", "   "):
            try:
                await client.call_tool(tool, {arg: blank})
            except ToolError as e:
                assert "must not be empty" in str(e), e
            else:
                raise AssertionError(f"{tool}({blank!r}) should be an error")


async def check_search(client: Client) -> None:
    """search_everything finds trips by country name, ignores JSON keys, and returns the
    newest 50 Things Done matches with their total."""
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

    common = await call(client, "search_everything", {"query": "and"})
    matches = [y for y, _, t in server._done_entries() if "and" in server._norm(t)]
    assert len(matches) > 50, f"expected more than 50 Things Done matches for 'and', got {len(matches)}"
    assert len(common["thingsDone"]) == 50, len(common["thingsDone"])
    years = [e["year"] for e in common["thingsDone"]]
    assert years[0] == max(matches) and years == sorted(years, reverse=True), years
    assert common["thingsDoneTotal"] == len(matches), common["thingsDoneTotal"]
    assert common["thingsDoneTruncated"] is True, common
    assert houston["thingsDoneTotal"] < 50 and houston["thingsDoneTruncated"] is False, houston


async def check_things_done(client: Client) -> None:
    """things_done accepts month abbreviations and numbers, and rejects an unknown month."""
    september = (await call(client, "things_done", {"month": "September"}))["total"]
    assert september, "no Things Done entries for September"
    for month in ("Sep", "sept", "9", "09"):
        res = await call(client, "things_done", {"month": month})
        assert res["total"] == september, f"things_done(month={month!r}) total {res['total']} != {september}"
    try:
        await client.call_tool("things_done", {"month": "Marhc"})
    except ToolError as e:
        assert "Unknown month 'Marhc'" in str(e), e
    else:
        raise AssertionError("things_done(month='Marhc') should fail")


class _FakeNotes:
    """Stands in for the Atlas collection: records the pipeline and call count, returns one canned hit."""

    def __init__(self) -> None:
        self.pipeline: list = []
        self.calls = 0

    def aggregate(self, pipeline: list) -> list:
        self.pipeline = pipeline
        self.calls += 1
        return [{"path": "AI-Agents/Agents in the cloud.md", "title": "Agents in the cloud",
                 "folder": "AI-Agents", "heading": "Setup", "source": "https://example.com/a",
                 "tags": ["clippings", "agents"], "text": "Run coding agents remotely.", "score": 0.91234}]


class _RaisingNotes:
    """An Atlas collection whose every query fails with the given exception."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def aggregate(self, pipeline: list) -> list:
        raise self.exc


async def check_ask_notes(client: Client) -> str:
    """ask_notes without Atlas: the unconfigured and bad-URI error shapes, and the query it builds.
    Skipped when MONGODB_URI is set, so the test never talks to a real cluster. Returns a summary."""
    if os.environ.get("MONGODB_URI"):
        return "ask_notes SKIPPED (MONGODB_URI is set; this test does not touch a real cluster)"

    notes = await call(client, "ask_notes", {"question": "coding agents"})
    assert notes["results"] == [] and "MONGODB_URI is not set" in notes["error"], notes

    real_notes = server._notes
    real_per_minute = server.NOTES_CALLS_PER_MINUTE
    server._notes_cache.clear()
    server._notes_calls.clear()
    try:
        # A malformed URI fails while building the client; that must come back as an error field.
        os.environ["MONGODB_URI"] = "mongodb://"
        notes = await call(client, "ask_notes", {"question": "coding agents"})
        assert notes["results"] == [] and "InvalidURI" in notes["error"], notes
        assert "mongodb://" not in notes["error"], notes

        fake = _FakeNotes()
        server._notes = lambda: fake
        notes = await call(client, "ask_notes", {"question": "coding agents", "folder": "ai-agents", "limit": 3})
        search = fake.pipeline[0]["$vectorSearch"]
        assert search["query"] == {"text": "coding agents"}, search
        assert search["filter"] == {"folder": {"$eq": "AI-Agents"}} and search["limit"] == 3, search
        hit = notes["results"][0]
        assert hit["tags"] == ["agents"] and hit["score"] == 0.912, hit
        assert hit["note"].endswith("/AI-Agents/Agents%20in%20the%20cloud.md"), hit

        await call(client, "ask_notes", {"question": "  coding agents  ", "folder": "AI agents"})
        search = fake.pipeline[0]["$vectorSearch"]
        assert search["query"] == {"text": "coding agents"}, search
        assert search["filter"] == {"folder": {"$eq": "AI-Agents"}}, search

        # Bad input is rejected before any Atlas call.
        fake.pipeline = []
        for args, needle in [
            ({"question": "coding agents", "folder": "Recipes"}, "Unknown folder 'Recipes'. Use one of: AI-Agents"),
            ({"question": "x" * (server.QUESTION_MAX_CHARS + 1)}, "too long"),
            ({"question": "   "}, "empty"),
        ]:
            notes = await call(client, "ask_notes", args)
            assert notes["results"] == [] and needle in notes["error"], (args, notes)
        assert fake.pipeline == [], fake.pipeline

        from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

        # A repeat (after trimming, case and spacing) comes from the cache; another folder or limit searches again.
        server._notes_cache.clear()
        fake.calls = 0
        for args in [
            {"question": "coding agents"},
            {"question": " Coding  AGENTS "},
            {"question": "coding agents", "folder": "Reading"},
            {"question": "coding agents", "limit": 2},
        ]:
            notes = await call(client, "ask_notes", args)
            assert notes["results"] and notes["question"] == args["question"].strip(), (args, notes)
        assert fake.calls == 3, fake.calls

        # Errors are never cached: once Atlas recovers, the same question searches again.
        server._notes = lambda: _RaisingNotes(OperationFailure("rate limited"))
        notes = await call(client, "ask_notes", {"question": "agent sandboxes"})
        assert notes["results"] == [] and "failed (OperationFailure)" in notes["error"], notes
        server._notes = lambda: fake
        notes = await call(client, "ask_notes", {"question": "agent sandboxes"})
        assert notes["results"] and fake.calls == 4, (fake.calls, notes)

        # Past the per-minute limit an uncached question is turned away without a search; cached ones still answer.
        server.NOTES_CALLS_PER_MINUTE = len(server._notes_calls)
        notes = await call(client, "ask_notes", {"question": "something new"})
        assert notes == {"error": "Notes search is busy. Try again in a minute.", "results": []}, notes
        assert fake.calls == 4, fake.calls
        notes = await call(client, "ask_notes", {"question": "coding agents"})
        assert notes["results"] and fake.calls == 4, (fake.calls, notes)
        server.NOTES_CALLS_PER_MINUTE = real_per_minute
        server._notes_cache.clear()
        server._notes_calls.clear()

        # Database errors keep their class name but not their message (host names, server documents).
        for exc, needle in [
            (ServerSelectionTimeoutError("cluster0-shard-00-00.abc.mongodb.net:27017: timed out"), "timed out (ServerSelectionTimeoutError)"),
            (OperationFailure("index not found", 291, {"errmsg": "secret", "host": "cluster0.abc.mongodb.net"}), "failed (OperationFailure)"),
        ]:
            server._notes = lambda exc=exc: _RaisingNotes(exc)
            notes = await call(client, "ask_notes", {"question": "coding agents"})
            assert notes["results"] == [] and needle in notes["error"], notes
            assert "mongodb.net" not in notes["error"] and "index not found" not in notes["error"], notes
    finally:
        os.environ.pop("MONGODB_URI", None)
        server._notes = real_notes
        server._notes_client = None
        server.NOTES_CALLS_PER_MINUTE = real_per_minute
        server._notes_cache.clear()
        server._notes_calls.clear()
    return ("ask_notes ran (unconfigured, bad URI, input checks, cache, rate limit, hidden error text "
            "and query shape against a fake collection)")


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
        await check_place_qualifiers(client)
        await check_search(client)
        await check_things_done(client)
        notes_checked = await check_ask_notes(client)
    print(
        f"ok: {len(expected)} README tools served; about_ashar, has_visited and list_places ran; "
        f"country lookups, place qualifiers and search resolve; {notes_checked}"
    )


if __name__ == "__main__":
    asyncio.run(main())
