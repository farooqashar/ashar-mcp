"""Ashar's personal MCP server.

Read-only tools over public data from Ashar's travel site and Things Done site,
so any Claude (or other MCP client) can answer questions about his trips,
travel trackers and timeline.

Run locally:   python server.py            -> http://localhost:8000/mcp
Deployed:      Vercel serves `app` from api/index.py (stateless HTTP).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

DATA_DIR = Path(__file__).parent / "data"
TRAVEL_SITE = "https://ashar-travel.vercel.app"
DONE_SITE = "https://done.asharfarooq.xyz"


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text())


TRAVEL = _load("travel.json")
DONE = _load("things-done.json")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
COUNTRY_NAMES = {c["code"]: c["name"] for c in TRAVEL["countries"]}

mcp = FastMCP(
    name="Ashar",
    instructions=(
        "Facts about Ashar Farooq from his own public sites: trips he has taken, "
        "countries, cities and airports he has visited, his travel trackers "
        "(continents, wonders, US states and similar challenges), and 'Things Done', "
        "a month-by-month log of accomplishments and life events since 2017. "
        "Start with about_ashar for an overview, or search_everything for a keyword. "
        "Everything here is read-only."
    ),
)


# ---------------------------------------------------------------- helpers ---

def _norm(s: str) -> str:
    return s.strip().lower()


def _country_code(query: str) -> str | None:
    """Accept a 2-letter code or a country name (case-insensitive, partial ok)."""
    q = _norm(query)
    if len(q) == 2 and q.upper() in COUNTRY_NAMES:
        return q.upper()
    for code, name in COUNTRY_NAMES.items():
        if _norm(name) == q:
            return code
    for code, name in COUNTRY_NAMES.items():
        if q in _norm(name):
            return code
    return None


def _trip_view(t: dict, detail: bool = False) -> dict:
    out = {
        "id": t["id"],
        "name": t["name"],
        "startDate": t["startDate"],
        "endDate": t["endDate"],
        "countries": [COUNTRY_NAMES.get(c, c) for c in t.get("countries", [])],
        "description": t.get("description", ""),
    }
    if detail:
        if t.get("cities"):
            out["cities"] = t["cities"]
        out["photos"] = [
            p if p.startswith("http") else TRAVEL_SITE + p for p in t.get("photos", [])
        ]
    return out


def _item_label(item: Any) -> str:
    if isinstance(item, str):
        return item
    label = item.get("name", "")
    if item.get("code"):
        label = f"{label} ({item['code']})"
    if item.get("countryCode"):
        label = f"{label}, {COUNTRY_NAMES.get(item['countryCode'], item['countryCode'])}"
    return label


def _done_entries():
    """Yield (year, month, text) for every Things Done entry, oldest first."""
    for year in sorted(DONE["byYear"], key=int):
        months = DONE["byYear"][year]
        for month in sorted(months, key=lambda m: MONTHS.index(m) if m in MONTHS else 99):
            for text in months[month]:
                yield int(year), month, text


# ------------------------------------------------------------------ tools ---

@mcp.tool(annotations={"readOnlyHint": True})
def about_ashar() -> dict:
    """Overview: headline travel stats, the most recent trips, tracker progress,
    and how many Things Done entries exist per year. Good first call."""
    trips = sorted(TRAVEL["trips"], key=lambda t: t["startDate"], reverse=True)
    return {
        "travel": {
            **TRAVEL["stats"],
            "totalAirports": len(TRAVEL["airports"]),
            "mostRecentTrips": [_trip_view(t) for t in trips[:3]],
            "site": TRAVEL_SITE,
        },
        "trackers": [
            {"id": c["id"], "name": c["name"], "progress": c["progress"], "total": c.get("total")}
            for c in TRAVEL["challenges"]
        ],
        "thingsDone": {
            "entriesPerYear": {
                y: sum(len(v) for v in m.values()) for y, m in DONE["byYear"].items()
            },
            "site": DONE_SITE,
        },
    }


@mcp.tool(annotations={"readOnlyHint": True})
def list_trips(
    year: Annotated[int | None, Field(description="Only trips that started in this year")] = None,
    country: Annotated[str | None, Field(description="Country name or 2-letter code")] = None,
) -> list[dict]:
    """Ashar's trips, newest first, optionally filtered by year and/or country."""
    code = _country_code(country) if country else None
    if country and not code:
        return []
    trips = sorted(TRAVEL["trips"], key=lambda t: t["startDate"], reverse=True)
    return [
        _trip_view(t)
        for t in trips
        if (year is None or t["startDate"].startswith(str(year)))
        and (code is None or code in t.get("countries", []))
    ]


@mcp.tool(annotations={"readOnlyHint": True})
def get_trip(trip_id: Annotated[str, Field(description="Trip id from list_trips, e.g. 'trip-15'")]) -> dict:
    """Full details for one trip, including cities and photo URLs."""
    for t in TRAVEL["trips"]:
        if t["id"] == trip_id:
            return _trip_view(t, detail=True)
    raise ValueError(f"No trip with id {trip_id!r}. Call list_trips to see ids.")


@mcp.tool(annotations={"readOnlyHint": True})
def countries_visited() -> dict:
    """Every country Ashar has visited (name and ISO code), alphabetical."""
    visited = sorted(
        ({"code": c["code"], "name": c["name"]} for c in TRAVEL["countries"] if c.get("visited")),
        key=lambda c: c["name"],
    )
    return {"count": len(visited), "countries": visited}


@mcp.tool(annotations={"readOnlyHint": True})
def has_visited(place: Annotated[str, Field(description="A country, city or airport code/name")]) -> dict:
    """Check whether Ashar has been to a country, city or airport, and which trips mention it."""
    q = _norm(place)
    result: dict[str, Any] = {"query": place, "visited": False, "matches": []}

    code = _country_code(place)
    if code and any(c["code"] == code and c.get("visited") for c in TRAVEL["countries"]):
        result["matches"].append({"type": "country", "name": COUNTRY_NAMES[code]})
    for city in TRAVEL["cities"]:
        if q in _norm(city["name"]):
            result["matches"].append(
                {"type": "city", "name": city["name"], "country": COUNTRY_NAMES.get(city["countryCode"])}
            )
    for ap in TRAVEL["airports"]:
        if q == _norm(ap["code"]) or q in _norm(ap["name"]):
            result["matches"].append({"type": "airport", "name": f"{ap['name']} ({ap['code']})", "city": ap["city"]})

    trips = [
        t for t in TRAVEL["trips"]
        if (code and code in t.get("countries", []))
        or q in _norm(t["name"]) or q in _norm(t.get("description", ""))
        or any(q in _norm(c) for c in t.get("cities", []))
    ]
    result["trips"] = [_trip_view(t) for t in sorted(trips, key=lambda t: t["startDate"], reverse=True)]
    result["visited"] = bool(result["matches"])
    return result


@mcp.tool(annotations={"readOnlyHint": True})
def list_places(
    kind: Annotated[str, Field(description="'cities' or 'airports'")] = "cities",
    country: Annotated[str | None, Field(description="Country name or 2-letter code")] = None,
) -> dict:
    """Cities or airports Ashar has been to, optionally in one country."""
    if kind not in ("cities", "airports"):
        raise ValueError("kind must be 'cities' or 'airports'")
    code = _country_code(country) if country else None
    rows = [r for r in TRAVEL[kind] if code is None or r["countryCode"] == code]
    if kind == "cities":
        items = sorted(f"{r['name']}, {COUNTRY_NAMES.get(r['countryCode'], r['countryCode'])}" for r in rows)
    else:
        items = sorted(f"{r['code']} – {r['name']} ({r['city']})" for r in rows)
    return {"kind": kind, "count": len(items), "items": items}


@mcp.tool(annotations={"readOnlyHint": True})
def travel_trackers() -> list[dict]:
    """All of Ashar's travel trackers/challenges (continents, wonders, US states, airlines…)
    with progress. Use get_tracker for what's done and what's left in one."""
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "emoji": c.get("emoji"),
            "description": c.get("description"),
            "progress": c["progress"],
            "total": c.get("total"),
            "completed": c.get("completed", False),
        }
        for c in TRAVEL["challenges"]
    ]


@mcp.tool(annotations={"readOnlyHint": True})
def get_tracker(tracker_id: Annotated[str, Field(description="Tracker id from travel_trackers")]) -> dict:
    """One travel tracker in full: which items are done and which remain."""
    for c in TRAVEL["challenges"]:
        if c["id"] == tracker_id:
            data = c.get("data") or {}
            return {
                "id": c["id"],
                "name": c["name"],
                "progress": c["progress"],
                "total": c.get("total"),
                "done": [_item_label(i) for i in data.get("visited", [])],
                "remaining": [_item_label(i) for i in data.get("remaining", [])],
            }
    raise ValueError(f"No tracker {tracker_id!r}. Call travel_trackers to see ids.")


@mcp.tool(annotations={"readOnlyHint": True})
def things_done(
    year: Annotated[int | None, Field(description="e.g. 2019")] = None,
    month: Annotated[str | None, Field(description="Month name, e.g. 'March'")] = None,
    query: Annotated[str | None, Field(description="Keyword to filter entries")] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict:
    """Ashar's 'Things Done' log: month-by-month accomplishments and life events since 2017.
    Filter by year, month and/or keyword."""
    if month:
        month = month.strip().capitalize()
    q = _norm(query) if query else None
    hits = [
        {"year": y, "month": m, "entry": text}
        for y, m, text in _done_entries()
        if (year is None or y == year)
        and (month is None or m == month)
        and (q is None or q in _norm(text))
    ]
    return {"total": len(hits), "entries": hits[:limit], "truncated": len(hits) > limit}


@mcp.tool(annotations={"readOnlyHint": True})
def life_highlights() -> dict:
    """Major life happenings (in order), hackathons, conferences and fun facts."""
    return {
        "lifeHappenings": DONE["lifeHappenings"],
        "hackathons": DONE["hackathons"],
        "conferences": DONE["conferences"],
        "funFacts": DONE["funFacts"],
    }


@mcp.tool(annotations={"readOnlyHint": True})
def search_everything(query: Annotated[str, Field(description="Keyword or phrase")]) -> dict:
    """Keyword search across trips, places, trackers and Things Done in one call."""
    q = _norm(query)
    blob = lambda x: q in _norm(json.dumps(x, ensure_ascii=False))
    return {
        "trips": [_trip_view(t) for t in TRAVEL["trips"] if blob(t)],
        "cities": [c["name"] for c in TRAVEL["cities"] if q in _norm(c["name"])],
        "airports": [f"{a['code']} – {a['name']}" for a in TRAVEL["airports"] if blob(a)],
        "trackers": [c["name"] for c in TRAVEL["challenges"] if blob(c)],
        "thingsDone": [
            {"year": y, "month": m, "entry": t} for y, m, t in _done_entries() if q in _norm(t)
        ][:50],
        "lifeHighlights": [x for k in ("lifeHappenings", "funFacts") for x in DONE[k] if q in _norm(x)]
        + [e for k in ("hackathons", "conferences") for g in DONE[k] for e in g["events"] if blob(e)],
    }


@mcp.resource("ashar://travel.json", mime_type="application/json")
def travel_dataset() -> dict:
    """The full travel dataset behind the travel site."""
    return TRAVEL


@mcp.resource("ashar://things-done.json", mime_type="application/json")
def things_done_dataset() -> dict:
    """The full Things Done dataset."""
    return DONE


# ------------------------------------------------------------------- app ---

# Stateless + JSON responses: every request stands alone, which is what serverless needs.
mcp_app = mcp.http_app(stateless_http=True, json_response=True)

_INFO = json.dumps(
    {
        "name": mcp.name,
        "endpoint": "/mcp",
        "transport": "streamable-http",
        "about": "Read-only MCP server with Ashar Farooq's trips, travel trackers and Things Done.",
        "source": "https://github.com/farooqashar/ashar-mcp",
    }
).encode()


async def app(scope, receive, send):
    """ASGI entrypoint (Vercel, uvicorn). GET / returns a small JSON description.
    Every other path goes to the MCP endpoint, so /mcp, /mcp/ and whatever path a
    host rewrites to all work."""
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path in ("", "/") and scope.get("method") == "GET":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": _INFO})
            return
        if path != "/mcp":
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
    await mcp_app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
