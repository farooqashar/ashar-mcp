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
| `ask_notes(question, folder?, limit?)` | Semantic search over my Obsidian vault of web clippings, returning the most relevant passages with source links (see [Notes search](#notes-search)) |

The full datasets are also exposed as resources: `ashar://travel.json` and `ashar://things-done.json`.

## Notes search

`ask_notes` searches my [Obsidian vault](https://github.com/farooqashar/ashar-obsidian-vault)
(public web clippings) by meaning rather than keywords.

- The vault's `.github/scripts/ingest_notes.py` splits each note into chunks and syncs them into
  MongoDB Atlas (`vault.notes`) on every push. Only changed chunks are rewritten.
- Atlas [Automated Embedding](https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding/)
  embeds them with Voyage AI `voyage-4` through the `notes_vector` index, which the ingest script creates.
- This server sends the question as plain text (`query: {text: ...}`) in a `$vectorSearch` query;
  Atlas embeds it and returns the closest passages. The Claude calling the tool writes the answer.
- Mongo calls are capped at 10 seconds (`timeoutMS`), so a slow cluster returns an `error` instead
  of hanging the request.
- Questions are limited to 1,000 characters, and `folder` must name one of the vault's folders
  (case, spaces and punctuation are ignored). Errors give the error's class name only; the full
  message is logged to stderr.

Set `MONGODB_URI` (the Atlas connection string) wherever the server runs. Without it, `ask_notes`
returns a "not configured" message and every other tool works as before.

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py          # serves http://localhost:8000/mcp
```

To poke at it with the MCP Inspector, run `npx @modelcontextprotocol/inspector`, choose the
"Streamable HTTP" transport, and use the URL `http://localhost:8000/mcp`.

## Update the data

The JSON in `data/` is generated from the two site repos. To refresh it you need Node, the two
site repos checked out next to this one, and the [GitHub CLI](https://cli.github.com) signed in
(`gh auth login`) with push access to this repo. The script checks for `gh` before it does anything.

```bash
npm install
npm run refresh -- --pr
```

This regenerates `data/*.json` from `../ashar-travel` and `../ashar-things-done` (override with
`TRAVEL_REPO=… DONE_REPO=… npm run refresh -- --pr`) and compares it with `origin/main`:

- **Nothing changed:** it says so and exits.
- **Something changed:** it commits only the two data files on a fresh `data-refresh/<date>-<hash>`
  branch cut from `origin/main` (your current branch and any other local changes are left alone),
  pushes it and opens a PR labelled `data-refresh` with a one-line summary, e.g.
  `trips 41→43, countries 52→55, Things Done entries +6`. If other `data-refresh` PRs are still
  open, it lists them so you can close any this one replaces. `.github/release.yml` lists that label under **📦 Data refreshes** in the release notes.
- **A previous run failed partway** (say the push or PR step): run it again. Same data gives the
  same branch name, so it finishes that refresh instead of starting a new one.

Merge the PR and Vercel redeploys. Without `--pr`, the script only rewrites `data/`.

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


## Releases

Release notes are on the [Releases page](https://github.com/farooqashar/ashar-mcp/releases).
Changes go through labeled pull requests, and the labels group them in the generated notes (see `.github/release.yml`).

To cut a release:

```bash
# bump __version__ in server.py via a PR, merge it, then:
git tag v1.1.0 && git push origin v1.1.0
```

The tag runs `.github/workflows/release.yml`. It fails before creating anything if the tag (minus the `v`)
does not equal `server.__version__`, runs the smoke test (`python scripts/smoke_test.py`), then publishes
the release with generated notes. Pull requests run the same smoke test in `.github/workflows/ci.yml`.

## Layout

```
server.py                  FastMCP server: tools, resources, ASGI `app` (GET / = info, everything else = MCP)
api/index.py               Alternate entrypoint (re-exports `app`)
data/*.json                Generated data
scripts/export-data.mjs    Regenerates data/ from the site repos
scripts/smoke_test.py      In-memory smoke test run by CI and the release workflow
```
