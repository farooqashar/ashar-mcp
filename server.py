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
import re
import sys
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

__version__ = "1.0.0"

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
    version=__version__,
    instructions=(
        "Facts about Ashar Farooq from his own public sites: trips he has taken, "
        "countries, cities and airports he has visited, his travel trackers "
        "(continents, wonders, US states and similar challenges), and 'Things Done', "
        "a month-by-month log of accomplishments and life events since 2017. "
        "ask_notes searches his Obsidian vault of saved web clippings (AI agents, companies, "
        "infra, reading) by meaning. "
        "Start with about_ashar for an overview, or search_everything for a keyword. "
        "Everything here is read-only."
    ),
)


# ---------------------------------------------------------------- helpers ---

def _norm(s: str) -> str:
    return s.strip().lower()


# Common names that differ from the dataset's country names, keyed by _norm() form.
COUNTRY_ALIASES = {
    **dict.fromkeys(["usa", "u.s.", "u.s.a.", "america", "united states of america"], "US"),
    **dict.fromkeys(["uk", "u.k.", "england", "scotland", "wales", "great britain", "britain"], "GB"),
    **dict.fromkeys(["uae", "emirates"], "AE"),
    **dict.fromkeys(["turkey", "turkiye"], "TR"),
    **dict.fromkeys(["czech republic"], "CZ"),
    **dict.fromkeys(["holland"], "NL"),
    **dict.fromkeys(["korea"], "KR"),
}

# Spellings of one city that differ between the city records and trips' city lists, keyed by
# _norm() form: the records say "Madinah" and "Makkah" while a trip lists "Medina" and "Mecca".
CITY_ALIASES = {
    **dict.fromkeys(["medina", "madinah"], ("medina", "madinah")),
    **dict.fromkeys(["mecca", "makkah"], ("mecca", "makkah")),
}


# US states (and DC) by name and postal code, so "Houston, TX" can narrow a match to the US.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
US_STATE_KEYS = {_k.lower() for _k in US_STATES} | {_norm(_v) for _v in US_STATES.values()}


def _required(text: str, name: str) -> str:
    """The stripped text, or a tool error if it's blank (an empty pattern matches everything)."""
    text = text.strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _word_match(q: str, text: str) -> bool:
    """True if q appears in text as whole words ("uk" is not in "montauk")."""
    return re.search(rf"(?<!\w){re.escape(q)}(?!\w)", _norm(text)) is not None


def _names_match(names: tuple[str, ...], text: str) -> bool:
    """True if any of a place's spellings (see CITY_ALIASES) is in text as whole words."""
    return any(_word_match(n, text) for n in names)


def _place_names(place: str) -> tuple[str, ...]:
    """The _norm() form of place and its other spellings, if CITY_ALIASES has any."""
    q = _norm(place)
    return CITY_ALIASES.get(q, (q,))


def _country_code(query: str) -> str | None:
    """Accept a 2-letter code, a country name or a common alias (case-insensitive).
    A partial name only counts if it starts a word of exactly one country name."""
    q = _norm(query)
    if len(q) == 2 and q.upper() in COUNTRY_NAMES:
        return q.upper()
    for code, name in COUNTRY_NAMES.items():
        if _norm(name) == q:
            return code
    if q in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[q]
    if len(q) < 3:
        return None
    prefix = re.compile(rf"(?<!\w){re.escape(q)}")
    hits = [code for code, name in COUNTRY_NAMES.items() if prefix.search(_norm(name))]
    return hits[0] if len(hits) == 1 else None


def _qualifier_countries(qualifier: str) -> set[str]:
    """Country codes a qualifier like "Japan", "TX" or "Georgia" can mean. Ambiguous ones
    ("GA" is Georgia or Gabon, "CA" is California or Canada) allow every country they name."""
    codes = {code} if (code := _country_code(qualifier)) else set()
    if _norm(qualifier) in US_STATE_KEYS:
        codes.add("US")
    return codes


def _month_name(value: str) -> str:
    """Canonical month name for a full name, 3-letter abbreviation, "Sept" or 1-12 (case-insensitive)."""
    v = _norm(value)
    if v.isdigit() and 1 <= int(v) <= 12:
        return MONTHS[int(v) - 1]
    for name in MONTHS:
        if v in (name.lower(), name[:3].lower()):
            return name
    if v == "sept":
        return "September"
    raise ValueError(f"Unknown month {value!r}. Use a month name like 'March', 'Mar' or a number 1-12.")


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


def _place_matches(place: str, allowed: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Countries, cities and airports matching place, and the trips that mention it.
    With allowed, only places in one of these country codes count, and a trip counts only
    if the place is at one of its stops in an allowed country (see _stop_allowed)."""
    q = _norm(place)
    names = _place_names(place)
    ok = lambda c: allowed is None or c in allowed
    matches: list[dict] = []
    homes: set[str] = set()  # countries that have a city or airport matching place

    code = _country_code(place)
    if code and not ok(code):
        code = None
    if code and any(c["code"] == code and c.get("visited") for c in TRAVEL["countries"]):
        matches.append({"type": "country", "name": COUNTRY_NAMES[code]})
    for city in TRAVEL["cities"]:
        if _names_match(names, city["name"]):
            homes.add(city["countryCode"])
            if ok(city["countryCode"]):
                matches.append(
                    {"type": "city", "name": city["name"], "country": COUNTRY_NAMES.get(city["countryCode"])}
                )
    for ap in TRAVEL["airports"]:
        if q == _norm(ap["code"]) or _names_match(names, ap["name"]):
            homes.add(ap["countryCode"])
            if ok(ap["countryCode"]):
                matches.append({"type": "airport", "name": f"{ap['name']} ({ap['code']})", "city": ap["city"]})

    trips = [
        t for t in TRAVEL["trips"]
        if (code and code in t.get("countries", []))
        or ((_names_match(names, t["name"]) or _names_match(names, t.get("description", ""))
             or any(_names_match(names, c) for c in t.get("cities", [])))
            and _stop_allowed(set(t.get("countries", [])), homes, allowed))
    ]
    return matches, trips


def _stop_allowed(trip_countries: set[str], homes: set[str], allowed: set[str] | None) -> bool:
    """Whether a trip's mention of a place can be pinned to a stop in an allowed country.
    Trips list their countries and cities separately, so a qualified match goes by where the
    place is: a country that has a city or airport of that name, that the trip went to and
    that the qualifier allows. For a name with no city or airport record, every country on
    the trip must be allowed, since the mention could be at any of its stops."""
    if allowed is None:
        return True
    if homes:
        return bool(homes & trip_countries & allowed)
    return bool(trip_countries) and trip_countries <= allowed


def _qualifier_view(qualifier: str, allowed: set[str]) -> dict:
    """How has_visited read the part after the comma, so callers don't assume more precision."""
    view: dict[str, Any] = {"text": qualifier, "countries": sorted(COUNTRY_NAMES.get(c, c) for c in allowed)}
    if not allowed:
        view["note"] = "Not a country or US state this server knows, so it was ignored."
    elif _norm(qualifier) in US_STATE_KEYS:
        view["note"] = (
            "As a US state this only narrows the match to the United States: the travel data doesn't "
            "record which state a city or airport is in, so the state itself isn't checked."
        )
    else:
        view["note"] = "Only places, and trip stops, in these countries count."
    return view


@mcp.tool(annotations={"readOnlyHint": True})
def has_visited(
    place: Annotated[str, Field(description=(
        "A country, city or airport code/name, optionally followed by a comma and a country, "
        "e.g. 'Tokyo, Japan', to only count places in that country. A US state or postal code "
        "after the comma ('Houston, TX') only narrows to the United States; the state isn't checked."
    ))],
) -> dict:
    """Check whether Ashar has been to a country, city or airport, and which trips mention it.
    With a 'Place, Country' query, the result's qualifier field says how the part after the
    comma was read; a US state there narrows to the United States, not to that state."""
    text = _required(place, "place")
    searched = text
    matches, trips = _place_matches(text)
    qualifier_view = None
    if not matches and "," in text:
        # "Tokyo, Japan" or "Houston, TX": match the place, keep what's in the qualifier's country.
        name, qualifier = text.split(",", 1)[0].strip(), text.rsplit(",", 1)[1].strip()
        if name:
            allowed = _qualifier_countries(qualifier)
            matches, trips = _place_matches(name, allowed or None)
            searched = name
            qualifier_view = _qualifier_view(qualifier, allowed)

    # A trip that lists the place itself among its cities counts; a mention in its description,
    # or a longer city name containing it ("New Atlantis" for "Atlantis"), doesn't.
    names = _place_names(searched)
    listed = any(_norm(c) in names for t in trips for c in t.get("cities", []))
    result = {
        "query": place,
        "visited": bool(matches) or listed,
        "matches": matches,
        "trips": [_trip_view(t) for t in sorted(trips, key=lambda t: t["startDate"], reverse=True)],
    }
    if qualifier_view:
        result["qualifier"] = qualifier_view
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
    if country and not code:
        return {"kind": kind, "count": 0, "items": []}
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
    month: Annotated[str | None, Field(description="Month: full name ('March'), 3-letter abbreviation ('Mar', also 'Sept') or number 1-12, any case")] = None,
    query: Annotated[str | None, Field(description="Keyword to filter entries")] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict:
    """Ashar's 'Things Done' log: month-by-month accomplishments and life events since 2017.
    Filter by year, month and/or keyword."""
    if month:
        month = _month_name(month)
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
    """Keyword search across trips, places, trackers and Things Done in one call.
    Things Done matches are newest first and capped at 50; thingsDoneTotal and
    thingsDoneTruncated say how many matched. Call things_done(query=...) for more."""
    query = _required(query, "query")
    q = _norm(query)
    code = _country_code(query)
    country = lambda c: COUNTRY_NAMES.get(c, c)
    # Match readable values only, never JSON keys, ids or photo paths.
    hit = lambda *texts: any(q in _norm(t) for t in texts if isinstance(t, str))

    def trip_hit(t: dict) -> bool:
        countries = t.get("countries", [])
        return (code in countries) or hit(
            t["name"], t.get("description"), *t.get("cities", []), *map(country, countries)
        )

    def place_hit(p: dict, *texts: str) -> bool:
        return p["countryCode"] == code or hit(*texts, country(p["countryCode"]))

    def tracker_hit(c: dict) -> bool:
        data = c.get("data") or {}
        items = data.get("visited", []) + data.get("remaining", [])
        return hit(c["name"], c.get("description"), *map(_item_label, items))

    done = [
        {"year": y, "month": m, "entry": t} for y, m, t in reversed(list(_done_entries())) if q in _norm(t)
    ]
    return {
        "trips": [_trip_view(t) for t in TRAVEL["trips"] if trip_hit(t)],
        "cities": [c["name"] for c in TRAVEL["cities"] if place_hit(c, c["name"])],
        "airports": [
            f"{a['code']} – {a['name']}"
            for a in TRAVEL["airports"]
            if place_hit(a, a["code"], a["name"], a["city"])
        ],
        "trackers": [c["name"] for c in TRAVEL["challenges"] if tracker_hit(c)],
        "thingsDone": done[:50],
        "thingsDoneTotal": len(done),
        "thingsDoneTruncated": len(done) > 50,
        "lifeHighlights": [x for k in ("lifeHappenings", "funFacts") for x in DONE[k] if q in _norm(x)]
        + [e for k in ("hackathons", "conferences") for g in DONE[k] for e in g["events"] if hit(*e.values())],
    }


# ------------------------------------------------------------ notes search ---
# Ashar's Obsidian vault (public web clippings) lives in MongoDB Atlas, kept in sync by
# .github/scripts/ingest_notes.py in github.com/farooqashar/ashar-obsidian-vault.
# Atlas Automated Embedding (voyage-4) embeds both the notes and the question, so this
# server only sends text. Needs the MONGODB_URI environment variable.

VAULT_REPO = "https://github.com/farooqashar/ashar-obsidian-vault"
NOTES_DB = os.environ.get("NOTES_DB", "vault")
NOTES_COLLECTION = os.environ.get("NOTES_COLLECTION", "notes")
NOTES_INDEX = "notes_vector"
NOTE_FOLDERS = [
    "AI-Agents", "Companies-Products", "Infra-DevOps", "Fun-Curiosities",
    "Reading", "NYC-Local", "Misc", "Clippings",
]
_notes_client = None
# Finite bounds so a slow or hung Atlas can't stall a (serverless) request. timeoutMS caps each
# whole operation, including server selection, connection checkout, retries and reading the reply.
NOTES_TIMEOUT_MS = 10_000
# Atlas embeds every question with Voyage AI, so cap its size; the server has no auth.
QUESTION_MAX_CHARS = 1_000


def _folder_key(s: str) -> str:
    """Folder names compared without case, spaces or punctuation: 'ai agents' == 'AI-Agents'."""
    return re.sub(r"[\W_]+", "", s.lower())


def _notes():
    """The notes collection, or None when MONGODB_URI isn't configured. The client is
    created once per process and reused across requests (and warm serverless calls)."""
    global _notes_client
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    if _notes_client is None:
        from pymongo import MongoClient

        _notes_client = MongoClient(
            uri,
            appname="ashar-mcp",
            timeoutMS=NOTES_TIMEOUT_MS,
            serverSelectionTimeoutMS=5_000,
            connectTimeoutMS=5_000,
        )
    return _notes_client[NOTES_DB][NOTES_COLLECTION]


@mcp.tool(annotations={"readOnlyHint": True})
def ask_notes(
    question: Annotated[str, Field(description=f"What to look for, in plain language (up to {QUESTION_MAX_CHARS} characters), e.g. 'tools for running coding agents in the cloud'")],
    folder: Annotated[str | None, Field(description=f"Only search one folder: {', '.join(NOTE_FOLDERS)}")] = None,
    limit: Annotated[int, Field(ge=1, le=10, description="How many passages to return")] = 5,
) -> dict:
    """Search Ashar's Obsidian vault by meaning, not just keywords. The vault is web clippings
    he saved about AI agents, companies and products, infra/DevOps, things he's reading, NYC
    and curiosities. Returns the most relevant passages with their note titles, source URLs
    and links, so you can answer from them and cite which notes you used."""
    question = question.strip()
    if not question:
        return {"error": "question is empty.", "results": []}
    if len(question) > QUESTION_MAX_CHARS:
        return {"error": f"question is too long ({len(question)} characters; the limit is {QUESTION_MAX_CHARS}).", "results": []}
    match = None
    if folder:
        match = next((f for f in NOTE_FOLDERS if _folder_key(f) == _folder_key(folder)), None)
        if match is None:
            return {"error": f"Unknown folder {folder!r}. Use one of: {', '.join(NOTE_FOLDERS)}.", "results": []}

    if not os.environ.get("MONGODB_URI"):
        return {"error": "Notes search isn't configured on this server (MONGODB_URI is not set).", "results": []}

    search: dict[str, Any] = {
        "index": NOTES_INDEX,
        "path": "text",
        "query": {"text": question},  # Automated Embedding: Atlas embeds query.text with the index's model
        "numCandidates": limit * 20,
        "limit": limit,
    }
    if match:
        search["filter"] = {"folder": {"$eq": match}}

    try:
        coll = _notes()  # inside the try: a malformed MONGODB_URI raises here
        hits = list(coll.aggregate([
            {"$vectorSearch": search},
            {"$project": {"_id": 0, "path": 1, "title": 1, "folder": 1, "heading": 1,
                          "source": 1, "tags": 1, "text": 1, "score": {"$meta": "vectorSearchScore"}}},
        ]))
    except Exception as e:  # bad URI, network, timeout, auth, index still building, rate limit
        # The message can hold cluster host names and server error documents: log it, don't return it.
        print(f"ask_notes: {type(e).__name__}: {e}", file=sys.stderr)
        kind = type(e).__name__
        if getattr(e, "timeout", False):  # pymongo marks timeout errors with .timeout
            return {"error": f"Notes search timed out ({kind}). Try again later.", "results": []}
        return {"error": f"Notes search failed ({kind}). Try again later.", "results": []}

    from urllib.parse import quote

    return {
        "question": question,
        "results": [
            {
                "title": h.get("title"),
                "section": h.get("heading") or None,
                "folder": h.get("folder"),
                "tags": [t for t in h.get("tags") or [] if t != "clippings"],
                "score": round(h.get("score", 0), 3),
                "source": h.get("source"),
                "note": f"{VAULT_REPO}/blob/main/{quote(h['path'])}",
                "text": h.get("text", "")[:3000],
            }
            for h in hits
        ],
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
        "version": __version__,
        "endpoint": "/mcp",
        "transport": "streamable-http",
        "about": "Read-only MCP server with Ashar Farooq's trips, travel trackers, Things Done and notes search.",
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
