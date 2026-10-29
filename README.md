# ashar-mcp

A personal [MCP](https://modelcontextprotocol.io) server built with [FastMCP](https://gofastmcp.com).
It lets Claude, or any other MCP client, answer questions about my trips, travel trackers and "Things Done" timeline.

All of its data is already public on [ashar-travel.vercel.app](https://ashar-travel.vercel.app) and
[done.asharfarooq.xyz](https://done.asharfarooq.xyz). The server is read-only and has no auth.

## Tools

| Tool | What it answers |
|---|---|
| `about_ashar` | Overview: travel stats, latest trips, tracker progress, Things Done per year |
| `list_trips(year?, country?)` | Trips, newest first |
| `get_trip(trip_id)` | One trip with cities and photo URLs |
| `countries_visited()` | All visited countries |
| `has_visited(place)` | "Has Ashar been to X?" across countries, cities, airports and trips |
| `list_places(kind, country?)` | Cities or airports, optionally by country |
| `travel_trackers()` / `get_tracker(id)` | Continents, countries, airlines, airports, "Stans" and other challenges, with done and remaining items |
| `things_done(year?, month?, query?)` | The month-by-month accomplishments log since 2017 |
| `life_highlights()` | Major life happenings, hackathons, conferences, fun facts |
| `search_everything(query)` | Keyword search across all of the above |

The full datasets are also exposed as resources: `ashar://travel.json` and `ashar://things-done.json`.

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py          # serves http://localhost:8000/mcp
```

To poke at it with the MCP Inspector, run `npx @modelcontextprotocol/inspector`, choose the
"Streamable HTTP" transport, and use the URL `http://localhost:8000/mcp`.

## Update the data

The JSON in `data/` is generated from the two site repos. After updating either site, refresh it:

```bash
npm install
node scripts/export-data.mjs ../ashar-travel ../ashar-things-done
git commit -am "Refresh data" && git push   # Vercel redeploys
```

## Deploy (Vercel, free Hobby plan)

1. Import this repo at vercel.com/new. There is no build step: Vercel detects the ASGI `app` in `server.py` and installs `requirements.txt`.
2. Optionally add the domain `mcp.asharfarooq.xyz` to the project.
3. Check that it's live:
   ```bash
   curl -s -X POST https://<domain>/mcp \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```
4. In Claude, add a custom connector with the URL `https://<domain>/mcp`.

The server runs in stateless HTTP mode with JSON responses, so each request is self-contained.
That is what serverless hosting needs.

## Layout

```
server.py                  FastMCP server: tools, resources, ASGI `app` (GET / = info, everything else = MCP)
api/index.py               Alternate entrypoint (re-exports `app`)
data/*.json                Generated data
scripts/export-data.mjs    Regenerates data/ from the site repos
```
