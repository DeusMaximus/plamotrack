# plamotrack

**Track every kit, tool, and terrible financial decision from pre-order to panel-lined masterpiece.**

A self-hosted Gunpla/plamo collection and build tracker. Kits move across a drag-and-drop
Kanban board from *pre-ordered* to *complete*; orders know which kits they turned into;
nippers, cement and decal sheets get counted; and an embedded MCP server means you can
just tell Claude "the Sinanju arrived" instead of clicking things.

Your data lives in your Postgres, on your hardware, and leaves as plain CSV whenever you
want it to.

> ### ⚠️ This is a public alpha
>
> **There is a single owner login and personal access tokens, but no TLS yet.** A fresh
> install comes up unclaimed and prints a one-time setup token to the API log; you claim
> it in the browser, every REST route then needs that session, and scripts and **MCP
> clients** authenticate with an access token minted under Settings. Still missing until
> the rest of Milestone 6: a tested HTTPS path. Run it on a network you trust — your LAN,
> a VPN, or plain old localhost — and don't put it on the internet yet.
>
> The database schema is also still moving. Migrations are provided and tested in both
> directions, but export an archive before you upgrade. It takes one click, and that's
> exactly why it exists.

---

![The build pipeline — drag a card, the kit's status follows](docs/screenshots/board.png)

## What it actually does

### A board that admits you have a backlog

Six statuses — pre-ordered, ordered, in transit, backlog, building, complete — with two
views over them. **Build** shows the three that matter on a Sunday afternoon
(backlog → building → complete). **Orders** shows the money still in flight, with
everything that's arrived collapsed into one Received column so it doesn't fill your
screen with things you already own.

"Backlog" means *in hand, not started*. There is no polite word for this pile. We tried.

![The orders view — money in flight on the left, everything that landed on the right](docs/screenshots/board-orders.png)

### Orders that know what they turned into

Order a Zaku ×2 and plamotrack creates **two kit rows**, because you own two physical
plastic objects, not "a quantity of 2". Each one remembers which order line it came
from, so fixing a typo in the order fixes it everywhere, and deleting an order cleanly
undoes the whole thing.

Orders are *pending* until you mark them received. That matters more than it sounds:
stock only lands in your inventory when the box does. No more being told you have five
Gundam markers while they're demonstrably still in Osaka.

They know when they shipped, too. Mark an order shipped and its kits ride along in
In Transit with the days counting; mark it received and everything arrives at once.
Both dates backdate — you log the box when you find the time, not when it lands —
and completed builds carry start/finish dates, a rating, and a series you name
yourself, so "everything Iron-Blooded Orphans" is a filter, not an archaeology dig.

![Orders, with one expanded to show its lines](docs/screenshots/orders.png)

If you look closely at the inventory below, Mr. Color Thinner sits at **0 on hand** —
it's on that pending Mecha Supply Co order. It'll count itself the moment you hit
Receive.

### Tools, consumables, upgrades and display gear, counted

Four quantity-tracked catalogs. Consumables can also carry an optional low-stock
threshold, so you find out you're nearly out of Extra Thin *before* the hobby shop
closes. Upgrade parts can be applied to a specific kit, which decrements stock and
records what went where.

**Display gear** — action bases, system stands, diorama scenery, backdrop panels — is
counted and categorised but deliberately *not* linked to particular kits. A stand under
one model this month is under another the next, so recording where each one currently
lives would be wrong more often than right; how many you own is the part worth knowing.
Each carries a category and an optional scale, so "1/144 bases" is a question with an
answer. It's also the least Gunpla-specific thing here: a model-railway or 1/35 armour
collection fills that table with exactly the same shape of thing.

Adding items to an order uses a search-and-pick typeahead, never a free text box. This
is deliberate: give a naming-things-at-11pm hobbyist a text field and within a month
you'll own "GM02 Gundam Marker", "Gundam Marker GM02", and three units of stock split
between them.

![Consumables, with low-stock thresholds](docs/screenshots/inventory.png)

### A report card for every retailer

Rating, packing quality, shipping speed, and a blunt would-you-order-again field.
Because six months later you *will not remember* which one sent a $200 Perfect Grade
loose in a bag.

![Retailers, rated](docs/screenshots/retailers.png)

*Everything in these screenshots is invented demo data, ratings included. Mecha Supply
Co isn't a real shop, and the ones that are haven't been graded by anyone — go form your
own opinions, that's what the field is for.*

### Your data, genuinely yours

Export the entire collection as a zip of plain CSVs with a manifest, or pull any single
table as a spreadsheet. Import it back to restore, merge, or move instances — with a
**full preview of every change before anything is written**, and no duplicating what's
already there.

Coming from a spreadsheet, Notion, or Baserow? Grab the starter sheet: one row per kit,
and plamotrack works out the retailers, orders, and order lines for you.

Full details in [docs/import-export.md](docs/import-export.md).

![Data management in Settings — export, templates, and a preview-before-you-commit import](docs/screenshots/data.png)

### An MCP server, so you can stop clicking

The API ships with a [Model Context Protocol](https://modelcontextprotocol.io) server
built in — same process, same business logic, no separate thing to run. Point Claude at
it and the conversation goes roughly:

> **You:** grab that Gundam Express order confirmation from my email and add it
> **Claude:** *(reads the email, calls `create_order`)* Added — 2 kits and a pack of
> sanding sponges, A$104.90, pending.
>
> **You:** the Sinanju arrived
> **Claude:** *(calls `list_orders`, then `mark_order_received`)* Marked received. The
> Sinanju Stein is now in your backlog and the markers are on hand.

There is no email-parsing feature in plamotrack and there never will be. Your agent
already has a mail connector; it just needed somewhere to write.

[Setup instructions below.](#wiring-up-the-mcp-server)

---

## What isn't built yet

Being honest up front beats you finding out at 11pm:

| | Status |
|---|---|
| Kits, orders, inventory, retailers, Kanban board | ✅ Built |
| CSV import / export | ✅ Built |
| MCP server | ✅ Built |
| Bundled `docker compose up` for the whole local stack | ✅ Built |
| **Internationalisation foundations** | ✅ Milestone 5.1: instance-wide language, formatting locale, time zone, date/hour style, and reference currency; the `en-AU` source catalogue and fallback; a reviewed [translation workflow](docs/translating.md); locale-aware dates, times, numbers, counts, money, and file sizes; structured REST/import diagnostics with translated known identifiers and an English compatibility fallback; and RTL-aware layout utilities. No non-English catalogue ships yet. Upgrades default existing instances to `en-AU`/UTC; naive CSV timestamps are read prospectively in the configured instance zone, stored history is never reinterpreted, and downgrading past the settings migration loses its settings row. |
| **Authentication + OAuth-compatible remote MCP** | 🔨 Milestone 6 — yes, really, see the warning above |
| **MCP `2026-07-28` compatibility** | 🔨 Milestone 6.1 — dual-era, without dropping current clients |
| **UI redesign** | 🔨 Milestone 6.5 — moving off the stock-component look, so the gallery and showcase get built in the new one; direction still being explored, and opinions are welcome on the tracker |
| **Photo gallery per kit** | 🔨 Milestone 7 |
| **Public read-only showcase page** | 🔨 Milestone 8 — after the admin and MCP paths are protected |

---

## Installing it

**You'll need:** [Docker](https://docs.docker.com/get-started/get-docker/) and about
three minutes. Nothing else — the images build from this repo.

```bash
git clone https://github.com/DeusMaximus/plamotrack.git && cd plamotrack
cp .env.example .env
# open .env, replace change-me with a real password
docker compose up -d --build --wait
```

Open **http://localhost:8080**. That's an empty collection — head to
**Settings → Data management → Starter sheet** to pour an existing spreadsheet
in, or just add an order.

The first run builds two images and takes a couple of minutes; after that it's
seconds. `.env` is the whole configuration: Compose reads it to start the database
and the API reads it to connect, so there's nothing to keep in sync.

### What you just started

Four containers, but only one open port:

| | |
|---|---|
| **http://localhost:8080** | the app |
| `http://localhost:8080/api/…` | REST API — e.g. `/api/kits`, or `/api/docs` for the interactive docs |
| `http://localhost:8080/mcp/` | MCP endpoint |

The API and database aren't published — they talk over Compose's internal network,
so an instance has exactly one door, and it's bound to `127.0.0.1`. A `migrate`
container runs the database migrations and exits before the API starts; seeing it
as `Exited (0)` is success, not a failure.

Running it on a server and want to reach it from your laptop? That door stays on
loopback by default for a reason — there's a login now, but no TLS yet — so see
[Reaching it from another machine](docs/operations.md#reaching-it-from-another-machine)
rather than just widening the bind.

Backups, restores, upgrading, and the full configuration reference live in
**[docs/operations.md](docs/operations.md)**.

### Something went wrong

- **`POSTGRES_PASSWORD` error from compose** — you skipped `cp .env.example .env`.
- **Port 8080 already in use** — set `WEB_PORT` in `.env` to something free.
- **`up --wait` failed** — `docker compose ps` shows which service is unhealthy.
  If it's `migrate`, `docker compose logs migrate` has the reason, and the API
  deliberately won't have started.
- **Password authentication failed** — you changed `POSTGRES_PASSWORD` after the
  database volume was already created. Postgres only reads it when initialising an empty
  data directory. Either set it back, or `docker compose down -v` to start clean, which
  **deletes the database**.
- **Pointing at a Postgres you already run** — uncomment `DATABASE_URL` in `.env`.
- **`421 Misdirected Request`** — you reached the instance by a name it doesn't
  know (a LAN hostname, a container name). Add it to `ALLOWED_HOSTS` in `.env` and
  `docker compose up -d`. Nothing is lost while it's wrong; see
  [Names it answers to](docs/operations.md#names-it-answers-to).

---

## Wiring up the MCP server

plamotrack speaks MCP over streamable HTTP at:

```
http://localhost:8080/mcp/
```

**Keep the trailing slash.** The bundled stack serves both spellings, but the API
run straight from source (see *Developing on it*) answers a bare `/mcp` with 404 —
it no longer redirects, because a redirect built from the request's own `Host` is
the kind of thing the ingress hardening removed.

Reaching the instance by anything other than `localhost` — a LAN hostname, a
container name — needs that name in `ALLOWED_HOSTS` in `.env`, or the server
answers `421 Misdirected Request`. `docs/operations.md` → *Names it answers to*.

### First, mint a token

The MCP endpoint takes a **personal access token** and nothing else — your browser
session never authenticates it, so a page in your browser can't drive an agent's tools.
In the app, open **Settings → Access tokens** and create one. *Read-only* is enough for
an agent that looks things up; *read and write* lets it record orders, move kits along
the pipeline and adjust stock. Neither level can change settings, import or export, or
manage tokens — those stay with the owner login. The token is shown **once**; copy it
into the client configuration below, and revoke it from the same page if it ever leaks.
The list shows when each token was last used.

Every client sends it the same way: an `Authorization: Bearer <token>` header, on the
REST API and on `/mcp/` alike. Never put one in a URL — it is ignored as a credential,
and request URIs end up in access logs.

### Claude Desktop

Edit the config file directly — Claude Desktop's **Add custom connector** dialog only
accepts publicly reachable URLs, and a self-hosted plamotrack on your own network isn't
one. Nor should it be at this stage; see the alpha warning above.

So bridge the HTTP endpoint into a stdio server with
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote), which passes the header
through. Open `claude_desktop_config.json` — on macOS at
`~/Library/Application Support/Claude/claude_desktop_config.json`, on Windows at
`%APPDATA%\Claude\claude_desktop_config.json` — and add, with your token in place of
`ptk_…`:

```json
{
  "mcpServers": {
    "plamotrack": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8080/mcp/",
        "--header",
        "Authorization:${PLAMOTRACK_AUTH}"
      ],
      "env": {
        "PLAMOTRACK_AUTH": "Bearer ptk_…"
      }
    }
  }
}
```

The header goes through an environment variable because Claude Desktop splits `args`
on spaces on some platforms, and `Bearer ptk_…` contains one. Restart Claude Desktop.
If it complains about the URL not being HTTPS, add `"--allow-http"` to the end of the
`args` array.

### Claude Code

```bash
claude mcp add --transport http plamotrack http://localhost:8080/mcp/ \
  --header "Authorization: Bearer ptk_…"
```

### Anything else

It's a standard streamable-HTTP MCP server, so any client that can point at a local URL
and send a bearer header will work — give it `http://localhost:8080/mcp/` and
`Authorization: Bearer ptk_…`. Clients that only speak stdio, or that (like Claude
Desktop) only accept publicly reachable URLs, can use the `mcp-remote` bridge shown
above. Instructions for other specific clients are welcome as PRs; open an issue if
yours needs something unusual.

### The tools it exposes

| Tool | What it does |
|---|---|
| `get_meta` | App version and the instance's reference currency — what an omitted `currency_code` means |
| `list_kits` | Filter by status, grade or series |
| `list_kit_series` | Series names already in use — check before writing a new spelling |
| `get_kit` | One kit, in full |
| `create_kit` | Add a kit that *wasn't* bought — a gift, a trade, a carry-over from before tracking; purchases go through `create_order` |
| `update_kit_status` | Move a kit along the pipeline |
| `update_kit` | Edit a kit's details — name, grade, series, rating, notes, build dates |
| `search_catalog` | Search every catalog — the same search the UI typeahead uses, so agents hit the same de-duplication a human does |
| `list_catalog_items` | One whole catalog table, optionally filtered by category — the listing `search_catalog` isn't |
| `list_catalog_categories` | Category names already in use on a table — check before writing a new spelling |
| `create_catalog_tool` / `_consumable` / `_upgrade` / `_display` | Add a catalog row without a purchase — a first stocktake, a gift, a hand-me-down |
| `update_catalog_tool` / `_consumable` / `_upgrade` / `_display` | Edit a catalog row — one tool per catalog, each taking that table's own fields |
| `list_retailers` | Every shop on record, report card included |
| `create_retailer` / `update_retailer` | Add a shop; rate it, note the crushed box, fill in the report card |
| `create_order` | Full order with lines; kits fan out, retailers are matched by name or created |
| `list_orders` | Optionally pending-only — how an agent finds the order a shipping email belongs to |
| `get_order` | One order in full — the read an edit starts from |
| `update_order` | Correct an order: header fields and/or the line set; refuses to silently drop lines you didn't restate |
| `mark_order_received` | Applies stock, advances that order's kits to backlog — with an optional arrival date, for deliveries logged after the fact |
| `mark_order_shipped` | Moves that order's waiting kits to in-transit — with an optional ship date, for shipping notifications logged after the fact; never touches stock |
| `adjust_stock` | Nudge a quantity, with a reason |
| `apply_upgrade` | Record an upgrade part going onto a kit |
| `withdraw_upgrade_application` | Undo an application — you say whether the part goes back into stock |

Import and export deliberately have **no** MCP tools. An agent that can silently replace
your entire collection is not a feature.

> ⚠️ The MCP endpoint takes only a personal access token (see *First, mint a token*
> above) — never the browser session — and a token's reach is fixed when it is minted.
> There is no tested TLS path yet, so keep the instance on localhost or a trusted
> network for now.

### Teach your agent your hobby's conventions

The tools above are generic on purpose — nothing in plamotrack knows what a grade
bucket or a P-Bandai suffix is. That knowledge ships separately as **agent skills**:
packaged convention files your agent loads alongside the MCP connection, so records
come out consistent instead of spelled three ways. The first one covers Gunpla —
kit naming, Bandai kit numbers, Gundam Markers, decals, the lot. See
[`skills/`](skills/) for what's available and how to install one.

---

## Developing on it

Running the containers is the install path; for development you want hot reload, so
run the database in Docker and the app from source.

**You'll need:** Docker · [uv](https://docs.astral.sh/uv/getting-started/installation/) ·
Node 20.19+ (or 22+).

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db --wait
# just Postgres, on fixed loopback and POSTGRES_PORT (5432 by default)

cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --no-proxy-headers       # REST on :8000, MCP at :8000/mcp/

cd ../frontend && npm install && npm run dev         # Vite on :5173, proxies /api to :8000
```

Open **http://localhost:5173**. The API serves at the root here rather than under
`/api` — the Vite dev proxy strips the prefix exactly as nginx does in the container,
so the app's own fetch paths are identical either way.

The development overlay and full stack are the same Compose project, so they share
one database container. Starting the full stack without the overlay recreates the
database container without its host port; the named volume and its data survive.
What you get if both APIs are running is the container's on `:8080` and yours from
source on `:8000`. Harmless, but confusing when a change doesn't show up where you
expected. `docker compose stop web api` leaves just the database.

Already have a Postgres on 5432? Set `POSTGRES_PORT` in `.env` — the development
overlay publishes on it and the source-run API connects to it. The bind stays fixed
to `127.0.0.1`; deliberately remote database access requires your own override.

Tests follow the same configured connection by default, but use a sibling
`<database>_test` database that they create if needed and destructively reset. Set
`TEST_DATABASE_URL` in the test process only when tests need a different connection.

```bash
cd backend
uv run pytest                                        # real Postgres, migrations both ways
uv run ruff check --fix . && uv run ruff format .

cd ../frontend
npm run build                                        # type-check + production build
npm run lint
npm run test:e2e                                     # Playwright (npx playwright install chromium);
                                                     #   claims a fresh instance itself — on one you
                                                     #   claimed, set E2E_OWNER_PASSWORD
```

Two documents are worth reading before you change anything structural:

- **[docs/design.md](docs/design.md)** — why the app is shaped this way. It's a record
  of decisions, not a spec; where it disagrees with the code, the code is right.
- **[AGENTS.md](AGENTS.md)** — the rules that actually bind, for both human and AI
  contributors. The important one: all business logic lives in `app/services/`, and REST
  routers and MCP tools are thin wrappers over it, so the two can never drift apart.

## Contributing

Issues and PRs welcome, especially: other MCP clients, non-Gunpla model kit
taxonomies (the schema deliberately hedges — see design notes §9.1), anyone who has
opinions about grade-to-scale defaults, and interface translations —
[docs/translating.md](docs/translating.md) is the how-to.

Please run the lint/build/test commands above before opening a PR. A contribution guide
with more ceremony arrives at Milestone 9.

## License

MIT — see [LICENSE](LICENSE). Build what you like with it.

---

Not affiliated with Bandai, Bandai Spirits, Sunrise, or anyone else who owns the things
you're gluing together. "Plamo" (プラモ) is the Japanese hobbyist shorthand for plastic
models, which is what this tracks, whether or not it happens to be a robot.
