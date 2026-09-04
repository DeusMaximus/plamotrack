# plamotrack — Design Notes

**Status:** Living document · **First written:** 05/08/2026 · **Last revised:** 02/09/2026

---

## How to read this

This is **not a specification**, and nothing here is a contract. It's the record of
why plamotrack is shaped the way it is — the decisions taken, the alternatives
rejected, and the reasoning that would otherwise evaporate the moment it left
someone's head.

Two things follow from that:

- **Where this document and the code disagree, the code is right** and this document
  is behind. Several sections already describe a design that development improved on;
  those are marked rather than quietly rewritten, because the *change* is usually the
  interesting part.
- **Sections can be revisited.** If a decision here turns out to be wrong, the fix is
  to change it and say why — not to treat the document as something to be complied
  with.

Section and feature markers used throughout:

| Marker | Meaning |
|---|---|
| ✅ **Built** | Implemented and working in the app today |
| 🔨 **Planned (Mn)** | Decided, not yet written — the milestone it belongs to |
| 💭 **Open** | Still genuinely undecided |

The roadmap and current milestone live in §11. `HANDOFF.md` in the repo root carries
the recent session-by-session build log; older entries are archived under
`.agents/handoff/`.

---

## 1. Overview

A self-hosted, open-source web application for tracking a Gunpla (or general model-kit)
collection end to end: pre-order → order → arrival → build pipeline → completion,
alongside the tools, consumables, and third-party upgrades used along the way. It is
being packaged as a Docker Compose stack with a web UI, a REST API, and an embedded MCP
server so Claude and other agents can query and update the data directly.

It exists because the obvious alternatives don't fit. Spreadsheets can't model the
one-order-becomes-several-kits relationship without either duplicating everything or
giving up on it. General-purpose database/app-builder tools handle the data fine but
tend to put the features you want most — a genuinely draggable Kanban board, unlimited
rows — behind a paywall, and you're still building the app yourself, just in someone
else's UI. This is the same app, owned outright.

### 1.1 Goals

- ✅ A drag-and-drop Kanban board for build status (Pre-ordered → Ordered → In Transit
  → Backlog → Building → Complete), not a static view.
  *(Revised 06/08/2026: the original design had separate In Hand and Backlog statuses.
  They turned out to be the same pile with two names, and were merged — Backlog now
  means "in hand, not started" and occupies In Hand's old pipeline position. The board
  defaults to a Build view of Backlog/Building/Complete; an Orders view shows the
  ordering states with everything received rolled into one aggregate column.)*
- ✅ Full CRUD via the web UI, without touching a database or an app-builder tool
- ✅ MCP-native: agents can add orders, update build status, and adjust stock without a
  human touching the UI
- ✅ Data that can leave: CSV export and import, so the collection is never trapped (§12)
- ✅ **M5** `docker compose up` → ready-to-use local instance, no manual runtime or
  schema setup; reference currency is configurable, and every historical conversion
  stores the currency code it was captured under
- ✅ **M5.1** Instance-wide settings and internationalisation foundations: `en-AU`
  source catalogue and fallback, reviewed language contributions, locale-aware
  presentation, a Settings page, structured REST/import diagnostics, and logical RTL
  layout utilities. No non-English translation is required to complete the foundation
- 🔨 **Planned (M6)** Authenticated remote access for the web UI, REST API, and MCP,
  including OAuth-compatible MCP clients and a tested VPS deployment path
- 🔨 **Planned (M6.1)** Dual-era MCP compatibility, adding `2026-07-28` without
  dropping clients on the current protocol generation
- 🔨 **Planned (M7)** Photo gallery per kit
- 🔨 **Planned (M8)** A public-facing, read-only showcase page suitable for linking
- Genuinely reusable by someone who isn't the author — this is a public repo, not a
  personal script

### 1.2 Non-goals

- Multi-tenant / multi-household support (single collection per instance)
- Build-stage photo timelines (single gallery per kit only — see §4.6)
- Built-in email parsing for order import. Handled instead by MCP plus whatever mail
  connector the operator already has, at query time — not a first-class feature
- Price/currency conversion via live FX rates (see §6)

---

## 2. Architecture

```
┌──────────────┐               ┌─────────────────────────────┐      ┌────────────┐
│  Frontend    │──── /api ────▶│  FastAPI — a single process │─────▶│  Postgres  │
│  React + Vite│               │   ├─ REST routers           │      │            │
└──────────────┘               │   ├─ FastMCP, mounted /mcp  │      └────────────┘
                               │   └─ shared service layer   │
┌──────────────┐               │        (all business logic) │
│  MCP clients │──── /mcp/ ───▶│                             │
│ (Claude, …)  │               └──────────────┬──────────────┘
└──────────────┘                              │
                                     ┌────────┴─────────┐
                                     │  Photo storage   │ 🔨 M7
                                     │  (volume or S3)  │
                                     └──────────────────┘
```

- ✅ **The API and the MCP server share one FastAPI process.** FastMCP mounts as an ASGI
  sub-application at `/mcp` on the same port the REST API serves. Business logic lives
  in exactly one place — the service layer — and both the UI and agents call it, so REST
  and MCP cannot drift apart. It also means one deployment unit instead of two.
  *(Revised 06/08/2026: the original sketch gave MCP its own port. Mounting it as a
  route is simpler, needs no extra firewall or proxy rule, and nothing has yet wanted
  them operated separately. Splitting later is a routing change, not a redesign.)*
- ✅ **Postgres, not SQLite.** SQLite under concurrent writers means WAL contention and
  `busy_timeout` tuning — a well-trodden source of pain. plamotrack has three concurrent
  writer types by design (web UI, REST clients, MCP agents), so Postgres is the boring
  correct answer. It costs one more container in the compose file; worth it.
- ✅ **Frontend: React + Vite**, to be served as a static build behind a lightweight
  nginx container (M5). Kanban via `dnd-kit` — maintained, accessible, no jQuery-era
  baggage.

---

## 3. Data Model

Serialised (unique) and fungible (quantity-tracked) items are modelled as genuinely
separate tables rather than one polymorphic "item" table. They behave too differently to
unify cleanly, and four honest tables are easier to reason about and query than one
table with half its columns null.

### 3.1 `kits`

One row per **physical** kit. Duplicate purchases of the same product create separate
rows.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "RX-79(G) Ground Type" |
| grade | text/enum | HG/RG/MG/PG/SD/etc — see §9.1 |
| scale | text | derived default from grade, overridable |
| kit_number | text | manufacturer product code |
| status | enum | Pre-ordered / Ordered / In Transit / Backlog / Building / Complete — Backlog = in hand, not started (In Hand merged into it, 06/08/2026) |
| status_updated_at | timestamp | |
| rating | int (nullable) | out of 5, set on completion |
| build_notes | text | freeform |
| order_item_id | uuid FK | provenance — which order line spawned this kit |
| created_at / updated_at | timestamp | |
| build_started_at | timestamp (nullable) | stamped on first entering `building`, only when null; user-editable (#94) |
| build_completed_at | timestamp (nullable) | same rule on entering `complete` (#94) |
| series | text (nullable) | free text like `grade`; one value; typeahead over existing values, no lookup table (#96) |

**Build dates (#94, decided 18/08/2026):** two nullable columns, not a status-event
table. An event table arrives with the whole §12.2 registry surface — natural key,
re-import de-dup, a `TABLE_SPECS` position, blank templates, a backfill migration — to
answer stage-duration questions nobody has asked, and it turns the two dates people
actually want into something reconstructed rather than set. **The dates belong to the
user, not to the state machine.** A transition stamps a default only when the column
is null and never overwrites a value the user set; both stay editable through the UI,
REST and MCP, because that is how a collection migrated from another tool gets its real
dates. Accepted going in: the pair measures elapsed time, not time at the bench (a build
shelved for three months reads as a long build — not a bug), and there is no
paused/shelved status (declined, not deferred). The migration does not backfill from
`status_updated_at` — a backfilled date is indistinguishable from an asserted one, and
wrong for a kit that went complete → building → complete. The importer never invents
these timestamps (rule 10 by analogy), and they stay out of the order line's `kit_*`
mirror (§12.2) so a price correction on the line cannot revert a completion date set
from MCP. **Considered and deferred (owner, 20/08/2026): an arrival date on the kit.**
A kit does not store one — it is derivable only through the spawning order
(`order_item_id` → `orders.received_at`), and a hand-added kit has none. Showing it
on the kits list would mean a read-side join and a new API field; for now arrival
lives on the order side (#93 made it backdatable there), and the kit-side display is
deliberately postponed rather than missed.

**Series (#96):** free text, one value, the same shape as `grade` and `scale`. An enum
would settle §9.1 by accident — "series" is Gunpla-specific in a way "grade" is not —
and a lookup table means an agent cannot record a series nobody has listed yet, which
is the failure the owner's previous tracker had. A distinct-values typeahead in the kit
form, also surfaced to MCP, is what keeps `IBO` and `Iron-Blooded Orphans` from becoming
two series by accident. Shares a migration with #94.

### 3.2 `kit_photos`

One-to-many gallery per kit. ✅ The table exists and is registered for export; 🔨 the
upload endpoints and UI land in M7.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| kit_id | uuid FK | |
| file_path | text | storage-backend-relative path |
| caption | text (nullable) | optional now; cheap insurance if a build-stage timeline is ever wanted |
| taken_at | timestamp (nullable) | same reasoning — lets photos sort meaningfully without committing to a staged-build model |
| created_at | timestamp | |

### 3.3 `tools`

Fungible, durable. Catalog and on-hand quantity in one row — no separate catalog/stock
split is warranted at this scale.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "Godhand Ultimate Nippers" |
| category | text | cutting / filing / gluing / etc |
| quantity_on_hand | int | |
| unit_cost_reference_minor | int (nullable) | last known price, informational only |
| unit_cost_reference_currency | text(3) (nullable) | the code that price was recorded in |
| condition_notes | text (nullable) | |

The cost pair is null-or-present together, enforced by a CHECK constraint. It was a
single `numeric(10, 2)` with no currency until #19: a bare 45.00 could not be compared
or converted, and scale 2 could not represent a KWD tool at all. Created from an order
line, the row takes **that line's** currency rather than the instance default — the
purchase already states what it was bought in (§6).

### 3.4 `consumables`

Fungible, depletable. Partial-state tracking is deliberately not attempted — decrement
on use, discard row-level detail. Nobody wants to record that a paint pot is 40% empty.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "Gundam Marker GM02" |
| category | text | paint / cement / blades / sanding / etc |
| quantity_on_hand | int | |
| low_stock_threshold | int (nullable) | optional reorder flag |

### 3.5 `upgrades`

Fungible stock **plus** a relationship to the kits they're applied to — structurally
different from consumables, so it keeps its own table rather than being merged in.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "G-Rework Decal Sheet #4" |
| manufacturer | text | |
| quantity_on_hand | int | |

The only catalog table without a `category` column, and as of #127 that is a decision
rather than a gap (owner's call, 24/08/2026): `manufacturer` plus the name is how
upgrades are actually told apart, an honest backfill for existing rows is impossible,
and a nullable category would be the lone nullable one of four. The filter,
distinct-values and canonicalisation machinery is generic over whichever tables carry
the column, so if this is revisited the column is the whole cost.

### 3.5a `display_items` ✅ (#126, 21/08/2026)

Fungible and durable, like `tools` — stands, system bases, diorama scenery, backdrop
panels. Bought to *display* models rather than to become part of one.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "D-CM01 Diocom Destroyed Factory" |
| category | text | stand / base / scenery / structure / figures / backdrop |
| scale | text (nullable) | which kit scale it suits — "1/144". Null = non-scale or unrecorded |
| manufacturer | text (nullable) | "Tomytec". Nullable, unlike `upgrades` |
| quantity_on_hand | int | |
| notes | text (nullable) | |

Until this existed the spend was simply invisible: a stand is not a tool (not
equipment), not a consumable (nothing depletes), and not an upgrade (see below). One
$260 order of Tomytec diorama sets prompted it, and that is not an unusual order.

**Why not just extend `upgrades`.** Structurally they look identical — fungible rows,
a quantity, and `upgrade_applications` is already M:N to kits, so an upgrade with no
applications is stock on a shelf exactly as a spare base would be. The difference is
that `upgrade_applications.quantity_used` **decrements stock**, because an applied
upgrade is *spent*: a decal sheet is consumed, metal thrusters stay installed. Display
gear is the opposite — the stand under one kit this month is under another the next.
Merging the two would leave one table where some rows consume when linked and others
don't, i.e. `quantity_on_hand` meaning two things depending on the row, which is the
class of defect rule 2.1 exists to prevent.

**No join table to kits, deliberately.** The same impermanence: the relationship is
genuinely ephemeral, so a stored link would be wrong most of the time, and each link
row would still need everything `upgrade_applications` carries (progressed-kit checks,
delete refusals, importer child-row handling) to protect a fact with no durability.
Quantity is the whole of what is worth knowing. If that turns out to be wrong the join
is an additive migration onto a table that already exists.

**No build status.** A row reading `quantity_on_hand: 5` cannot carry one honestly —
which is exactly why `kits` is one row per physical item (§3.1). Something needing
individual build state is kit-shaped and belongs in `kits`.

**`category` is required**, and is the one column here doing real work beyond
bookkeeping: it is what lets "how many display stands do I have" be answered by a
filter rather than by an agent guessing stand-ness from product names. Free text like
every other category in this schema. What makes it properly answerable landed as #127:
a case-insensitively folded `category` filter on each list surface, a per-table
distinct-values endpoint (most frequent first — the #96 series device), and one lean
`series` does not have — a written category matching an existing one
case-insensitively is stored under that existing spelling, on all three live writers
(create, edit, and an order line's `new_item`). The CSV importer folds exactly one
case — an id-less row classified CREATE (stubs included), which states no prior
spelling to preserve; the fold happens at plan time, so the fingerprint binds it and
the preview announces the spelling apply will store. Everything that *restores*
stays verbatim: an UPDATE and an id-bearing create-is-a-restore each assert a stored
fact, and rewriting one would make a re-imported archive a rewrite (#130 review,
P2-3; §12.5a spirit). Matching, the filter and the vocabulary all read the *trimmed*
stored spelling, so a legacy padded row is found and folded onto by its trimmed form
without the padding ever propagating (#130 review, P2-2). Vocabularies are
per-table: a tool category and a consumable category are separate namespaces, exactly
as their names are.

### 3.6 `upgrade_applications`

Join table: which upgrades have been used on which kits.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| upgrade_id | uuid FK | |
| kit_id | uuid FK | |
| quantity_used | int | |
| applied_at | timestamp | |

**Withdrawal (#61, 25/08/2026).** An application can be removed again —
`DELETE /upgrades/{id}/applications/{application_id}`, or the
`withdraw_upgrade_application` MCP tool — and the caller states **`restore_stock`**,
required, with no default on any surface. The question is not "was this a mistake";
it is whether the part still physically exists, and nothing stored can answer that:
recorded against the wrong kit means the part never left the box (stock returns),
while a decal applied and then torn off is destroyed (crediting it back would invent
inventory that isn't in the room). Both are ordinary. *Always restore* and *never
restore* were each rejected for being silently wrong in one of those halves; a
default was rejected because the caller who didn't think about it is exactly the
caller who gets it wrong — a required field forces the judgement at the one moment
the answer is known, on the MCP surface too, where an agent must not be allowed to
guess. A withdrawal removes the whole application (it is one event, not a running
balance), so restoring returns all of `quantity_used`; a restore that would overflow
the stock column is refused with the application intact (the #74 family). Withdrawal
is also what releases the two guards that reference applications — the kit delete
(#37) and the upgrade delete — which until #61 were permanent freezes: one mis-click
while applying froze the kit, its order line, and the upgrade for good. The read
side, `GET /kits/{id}/applications` (embedded in the MCP `get_kit`), exists for the
same reason — the guards pointed at records no surface could show.

### 3.7 `retailers`

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | |
| url | text (nullable) | |
| rating | int (nullable) | overall, out of 5 |
| packing_quality | text/enum (nullable) | excellent / good / average / below_average / poor |
| shipping_speed | text/enum (nullable) | very_fast / fast / average / slow / very_slow |
| would_order_again | text/enum (nullable) | yes / maybe / no |
| notes | text (nullable) | anything else goes here |

The report-card fields (rating through would_order_again) are all optional, filled in
after actually dealing with a retailer. Ordering from overseas hobby shops is enough of
a gamble that remembering which ones pack properly has real value.

### 3.8 `orders`

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| retailer_id | uuid FK | |
| order_date | date | |
| order_number | text (nullable) | the retailer's own reference, kept for support contact ("order lost", "item missing"). **Deliberately not unique** — it's only unique per retailer at best, so it's never used as an identifier internally; ids are ids |
| delivery_service | text (nullable) | null = local pickup/purchase |
| tracking_number | text (nullable) | |
| tracking_url | text (nullable) | |
| shipping_cost_minor | int (nullable) | see §6 for currency handling |
| currency_code | text | ISO 4217 |
| shipped_at | timestamp (nullable) | null = not marked shipped; a pure timeline record plus the in_transit kit advance — **never** a stock proxy (#95) |
| received_at | timestamp (nullable) | null = pending (not yet arrived) — see §3.9 |

### 3.9 `order_items`

The dispatch point between orders and the catalog tables.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| order_id | uuid FK | |
| item_type | enum | kit / tool / consumable / upgrade / display |
| catalog_ref_id | uuid (nullable) | points at a row in one of the catalog tables (null for kit-type, since kits are spawned fresh) |
| quantity | int | **semantics differ by item_type** — see below |
| unit_price_minor | int | |
| currency_code | text | ISO 4217 |
| converted_price_minor | int (nullable) | snapshot amount at entry time, see §6 |
| converted_currency_code | text (nullable) | ISO 4217 code for the snapshot; null-or-present with `converted_price_minor` |

**Quantity semantics.** These differ by item type, which is the kind of thing that has
to be explicit in code and not merely documented:

- `item_type = kit` → quantity **fans out**: creates N new rows in `kits`, each linked
  back to this order item, at entry time
- `item_type = tool/consumable/upgrade/display` → quantity **increments**
  `quantity_on_hand` on the referenced catalog row, **when the order is received** —
  not at entry

**Order lifecycle (revised 06/08/2026).** Orders are pending → received. The original
design incremented stock at entry, which meant plamotrack would cheerfully report five
Gundam markers on hand while they were still in a warehouse in Osaka. Quantity means
*physically on hand*, not *on order*. So:

- catalog stock applies when the order is marked received (`received_at`); kits fan out
  at entry regardless, since they have their own pipeline states to sit in
- receiving also advances that order's kits still in pre_ordered/ordered/in_transit to
  backlog (in hand, unbuilt)
- a received-at-entry flag covers over-the-counter purchases; split shipments are
  entered as separate orders — deliberately no per-line receiving lifecycle
- **edit** re-runs the dispatch diff: kit detail fixes propagate to the spawned kits
  (names live on the kits, the line just re-syncs them), and quantity or target changes
  spawn/remove kits and adjust applied stock. An id-bearing kit line may omit `kit`
  entirely (#67, 25/08/2026): the server-side comparison cannot tell a typed value
  from one echoed off a stale read — both arrive as a field that differs from what is
  stored — so a client that didn't touch the kit fields says nothing, and what it
  cannot state it cannot revert. The browser does exactly that (kit details ride only
  when their fields are dirty, and the editor hydrates from a fresh per-order read
  rather than the page's cached list); a quantity increase sent without details
  clones the line's current first kit. A *stated* value still restates — REST and
  MCP callers keep the comparison as their protection, which is why #36's optimistic
  version columns stay unbuilt for kits too: the two cheap layers close the browser's
  window, and the honest fix stays priced for the day a second writer needs it
- **delete = undo the entry**: spawned kits removed, applied stock reversed. One
  tolerance (#63, decided 25/08/2026): a line left dangling by the pre-0.2.4
  unlocked catalog delete — `catalog_ref_id` is polymorphic with no FK — has
  nothing real to reverse, so the undo skips it and logs rather than refusing;
  the item and its `quantity_on_hand` went together. *Only* the undo: a receive
  would apply stock for a row that doesn't exist, and a retarget adopts a new
  target while shrugging at the old one, so both keep the strict 409 (which now
  names the delete-and-re-enter escape). Always-tolerant and document-the-SQL
  were considered and declined: the first teaches every path to shrug at a state
  we haven't fully explained, the second leaves a dead end in an API that has a
  safe way to express the recovery
- guards throughout: kits that are building/complete, rated, or carrying photos, and
  stock that's already been consumed, block destructive edits with a 409 rather than
  silently losing history
- every order mutation loads the order row `FOR UPDATE`, so concurrent
  receive/edit/delete calls serialise instead of double-applying stock — three writer
  types (§2) makes this a real race, not a theoretical one

**Backdatable receipts (#93, 20/08/2026).** Orders are normally logged after the box
arrived — unpacking, or batch-entering a backlog of past purchases — so the arrival
instant is supplied rather than always stamped "now":

- entry takes an optional `received_at` (requires the `received` flag — a date on a
  pending order is a contradiction, refused rather than ignored); the receive call
  takes an optional one; both default to now
- the kits a receipt lands in backlog are stamped with the same instant as the order,
  including kits spawned later into an already-received order by a line edit — or by
  an import (§12.5: both of the importer's arrival sites borrow the same instant); a
  kit whose status the entry itself asserts (building, complete) keeps entry time —
  the receipt is not when that status began
- **correction:** `PATCH /orders/{id}` adjusts a `received_at` that is already set,
  and 409s on a pending order — the pending → received transition stays in the receive
  path, where the stock dispatch lives. Explicit null is refused: un-receiving is not
  a supported operation. A correction follows exactly the kits whose stamp equals the
  old receipt (their last transition *was* the receipt); a kit moved since keeps its
  own date. The MCP `update_order` tool carries the same correction (#97). A
  correction arriving by CSV moves only the order — the importer never rewrites kit
  rows the upload doesn't name (#116)
**Shipped (#95, 21/08/2026)** is the same machinery one stage earlier, minus the
stock. `shipped_at` is suppliable at entry (date-or-nothing — with no separate
"shipped" boolean anywhere, the instant is the whole assertion), a transition
(`POST /orders/{id}/ship`, `mark_order_shipped`) that advances pre_ordered/ordered
kits to in_transit stamped with the ship instant, and a correction of the same
PATCH shape reusing the same restamp. It never applies stock — `received_at` stays
the sole "stock was applied" proxy — which is also why shipping imports freely on
every order where receiving by import is refused on catalog-bearing ones (§12.5).
Receiving an unshipped order is legal and backfills nothing; shipping an
already-received order records the date and moves nothing; un-shipping is refused
everywhere; and there is deliberately **no cross-field check** against
`order_date` (not comparable, above) or `received_at` (#113's rule — the user
owns the values, and a service check would diverge from the importer). The
pending pre-order distinction is *derived* in the browser from the kits already
in the payload — once an order ships nobody cares it was a pre-order, so nothing
is persisted; a catalog-only order carries no signal, accepted until pre-ordering
consumables stops being rare. Entry mirrors that reading (#120, 21/08/2026): the
browser sets pre-order once per order — one toggle applied to every kit line —
because a retailer splitting a shipment becomes two plamotrack orders; the API
keeps per-line status, which REST, MCP and CSV can still write.

- **the future is refused, judged as a calendar date in the instant's own offset** —
  not as an instant against the server clock, which would refuse an honest "today"
  over clock skew. A receipt *earlier than `order_date`* is deliberately allowed:
  `order_date` is a plain date with no offset, so the comparison isn't well-defined
  across time zones (a same-day purchase entered in UTC+10 holds an instant that is
  "yesterday" in UTC), and backfilled collections carry approximations. Accepted
  cost (found in #111's review): an honest "today" in a behind offset can be a
  stored future *instant* — up to ~36 h ahead — and the Board's columns order by
  `status_updated_at` descending, so such a kit sits at the top of Backlog until
  the wall clock catches up. Harmless for a single-owner collection; recorded so
  the cost sits next to the rule
- **time-zone decision, revisited at M5.1 (#23, #114):** REST/MCP accept a full
  ISO 8601 datetime *with offset* (naive is refused), and the browser sends midnight
  local in its own offset for a picked date. The CSV side, which has no offset to
  borrow, reads a naive cell in the **instance's** time-zone setting — attached once
  per plan by the import planner, so preview and apply agree and a settings change
  between them stales the hash. An explicit offset in a cell always wins, exports
  always write `+00:00`, and stored instants are never rewritten — so old archives
  re-import as the same instants and only naive cells parsed after #114 read
  differently. At a DST boundary, a nonexistent gap wall time maps forward and an
  ambiguous one takes the earlier occurrence (PEP 495 fold-0), so the typed
  calendar day always lands (#173 review, P3-1)

**One lock order, application-wide.** Every writer that touches catalog stock takes
its rows through a single locked-read helper, and takes them in one agreed sequence:
**catalog rows first, in uuid order, then kits.** Order writes are the only place that
holds more than one row lock at once, so they are the only place that can deadlock —
and they were doing it two ways. Locking in payload order let two edits naming the same
two items in opposite orders each hold what the other wanted; and taking kit locks
before catalog locks put order edits head-on against `apply_upgrade`, which locks the
upgrade and then needs the kit to record an application. Neither could corrupt
anything — Postgres breaks a cycle by aborting one side — but the owner saw a 500 on an
edit that was never wrong. So order writes drain their catalog locks up front, before
the first kit lock, which is also `apply_upgrade`'s order.

The same helper is where the read is refreshed under the lock. `SELECT … FOR UPDATE`
through the ORM will happily serve the attribute values the session already had, which
is worse than not locking at all: the delta is computed from a number another writer has
since moved, and both the row and the response look right. Optimistic version columns
were considered instead and rejected — three models, a mapper change and every catalog
write path, to close a hole that locking plus a dirty-field PATCH already closes for a
single-owner application. Worth revisiting only when that stops being true.

**One gate for every writer, taken before the read it decides from.** Row locks
serialise writers touching the *same* rows; they say nothing about a decision made from
rows the write never names — and that is the shape of an import apply, which plans
against the whole collection and then writes. Five consecutive review rounds on #79 each
closed the interleaving the previous round had reported and left the next one open,
until the fix moved one level up: every mutating service function takes a
collection-wide advisory lock (`pg_advisory_xact_lock`, `services/write_gate.py`)
*before* reading the state it will act on, and holds it to commit or rollback.
Transaction-scoped, so there is nothing to release and no error path can strand it.
Reads never take it — import preview, every list and detail path, and export stay
concurrent — so the cost is that writers queue behind one another for the length of one
transaction, which for a single-owner collection with three writer types is the right
trade. The row locks and lock order above still apply inside the gate: they keep an
agent and a browser honest about the same row; the gate keeps them honest about rows
neither of them named. *(Added 15/08/2026, #80; rule 7.1 in `AGENTS.md`.)*

**Duplicate-catalog prevention.** Order entry uses search-and-select-or-create (a
typeahead against the existing catalog tables) rather than a free-text name
field. This is a deliberate constraint rather than a UX nicety: free-text entry
fragments the catalog within weeks — "GM02 Gundam Marker" and "Gundam Marker GM02" as
two rows with split stock — and once fragmented it takes manual merging to fix. The
constraint matters more, not less, for people who haven't been maintaining the
collection long enough to have a consistent naming habit.

The typeahead is the experience; the service layer is the guarantee. Since #107
every path that writes a retailer's or catalog item's name — `POST`, `PATCH`, the MCP
tools, and `new_item` on an order line — refuses, with a 409 naming the existing row,
a name that folds to one another row of the same table already holds (trimmed,
case-insensitive: the importer's natural key, §12.4). A refusal rather than a silent
merge, because a caller that asked to *create* and got back someone else's row could
not tell the two apart. Names are stored trimmed; a whitespace-only name is invalid
input. Near-misses ("Iron-Blooded Orphans" / "IBO") are not the same key and are not
refused — that is what the search is still for. The schema carries no unique index
yet: one would refuse to build on an instance that already holds a pair, so it waits
for a repair story (#54). *(Added 20/08/2026, #107.)*

### 3.10 `instance_settings` ✅ (#23, 27/08/2026)

The one-row settings singleton (§6.1). Integer primary key with `CHECK (id = 1)`,
so "a second settings row" is a constraint violation rather than a state.

| column | type | notes |
| --- | --- | --- |
| id | int PK, CHECK id = 1 | always 1 |
| interface_language | text | BCP 47; membership-tested against shipped catalogues (`en-AU`) |
| formatting_locale | text | BCP 47; shape-tested only — `Intl` resolves the rest |
| time_zone | text | IANA name, validated against the tz database |
| date_style | text + CHECK | locale / short / medium / long / full |
| hour_cycle | text + CHECK | locale / h12 / h23 |
| reference_currency | text(3) | default currency for new entries (§6) |

Created and seeded by its migration; nothing at runtime creates or deletes it.
All reads and writes go through `services/instance_settings.py` (§6.1 has the
seeding, validation, and portability semantics).

---

## 4. API Design (REST)

Standard CRUD plus a few purpose-built endpoints.

**Built ✅**

- `GET/POST /kits`, `GET/PATCH/DELETE /kits/{id}` — PATCH handles Kanban drag (status
  change). Order-spawned kits refuse direct deletion (409) — undo happens at the order
  line, so purchase records and the collection can't drift apart
- `GET /kits/series` — distinct series spellings, most frequent first, for the
  select-or-create control
- `GET/POST /tools|/consumables|/upgrades|/display-items` + `PATCH/DELETE /{id}` on each — deletes are
  blocked (409) when the item appears in order history or upgrade applications; edit
  instead, history is fact. The list routes (upgrades aside — no category column, §3.5)
  take `?category=`, folded case-insensitively server-side, and each categorised table
  has a `GET .../categories` distinct-values route (most frequent first) feeding the
  form typeaheads (#127, the `/kits/series` shape)
- `POST /upgrades/{id}/apply` — body: kit_id, quantity → creates an
  `upgrade_applications` row, decrements stock
- `DELETE /upgrades/{id}/applications/{application_id}?restore_stock=` — withdraws the
  application; `restore_stock` is required (422 when omitted) and states whether the
  part physically returns to stock (§3.6). `GET /kits/{id}/applications` lists a
  kit's applications, upgrade embedded, oldest first
- `GET/POST /retailers`, `PATCH/DELETE /retailers/{id}` — delete blocked when the
  retailer has orders
- `GET/POST /orders`, `GET /orders/{id}` — POST body includes nested order items; the
  server handles fan-out/increment dispatch per §3.9
- `PATCH /orders/{id}` — header fields and/or full line-set replacement (dispatch diff
  per §3.9; the `converted_*` snapshot is the one field pair an omission preserves
  rather than clears — see §6)
- `POST /orders/{id}/receive`, `POST /orders/{id}/ship`, `DELETE /orders/{id}` —
  receive, ship, and undo per §3.9
- `GET /catalog/search?q=` — powers the typeahead, searches every catalog table
- `POST /catalog/{id}/adjust` — body: signed `delta`, optional `reason` → resolves the
  id across every catalog table and moves stock by that much. The delta form
  exists because the absolute `quantity_on_hand` on the PATCH routes has to be read
  before it can be written, and three writer types can move it in between; "one fewer"
  is what a consumable running out actually is. 409 below zero or past the column
  ceiling. Same service call as the MCP `adjust_stock` tool
- `GET /export/archive`, `GET /export/{table}.csv`, `GET /export/templates`,
  `GET /export/starter-sheet.csv`, `POST /import/preview`, `POST /import/apply` — see §12
- `GET /settings`, `PATCH /settings` — the instance-settings singleton (§6.1, #23):
  language, region, time zone, date style, hour cycle, reference currency. PATCH
  updates only the supplied fields, refuses nulls (nothing is nullable), and
  serializes on the write gate
- `GET /meta` — app version, reference currency, and the interface languages this
  build supports; shared with the MCP `get_meta` tool
- `GET /healthz` — process liveness; `GET /readyz` — readiness including a database
  query (the Compose healthcheck)

**Planned 🔨**
- `GET /kits/{id}/photos`, `POST /kits/{id}/photos` (multipart upload) — **M7**, blocked
  on the §9.2 storage decision. Not implemented; the `kit_photos` table exists but
  nothing writes to it
- `GET /auth/session`, `POST /auth/setup`, `POST /auth/login`, `POST /auth/logout`,
  `/auth/oidc/*`, `/auth/tokens*` — **M6**, the route families in §5.5. The same
  milestone moves `GET /meta`, `/openapi.json` and the docs pages behind
  `collection:read` and hides `/readyz` from the ingress. Not implemented
- `GET /public/kits`, `GET /public/kits/{id}` — **M8**, read-only, no auth, powers the
  showcase page (§5). Not implemented; there is currently no `/public/*` namespace at all

### 4.6 Photo model note

Single gallery per kit, confirmed. `caption` and `taken_at` are retained on
`kit_photos` as low-cost future-proofing (§3.2) — this does **not** imply a build-stage
timeline is planned, only that the columns are cheap now and expensive to retrofit.

---

## 5. Auth, Remote Access & Public Mode 🔨 **In progress (M6 + M8) — threat model recorded 02/09/2026; §5.9 items 1–4 implemented (ingress identity #186 03/09; auth foundation #187, local owner auth #188 and personal access tokens #189 04/09/2026), plus item 3(b)'s deferred family-13 hardening (#204)**

Of this section §5.9 items 1–4 are built: the Host/Origin guard, the ingress
topology and the proxy-trust posture (#186); the principal model, the route policy
registry and the default-deny dependency (#187); the owner's setup, login, session
cookie and CSRF controls, with the shipped app enforcing (#188); and personal access
tokens as the bearer on REST and MCP with per-tool scope (#189). §5.1 records the
pre-M6 state the model started from, and §10 says what running an alpha means. The
rest of the section is the M6 threat model and route
authorization matrix (#29): the actors, the trust boundaries, the deployment modes
that will be supported, what every route family requires from whom, which layer
enforces it, how it fails, and the tests that have to exist before the documentation
may recommend widening `WEB_BIND`. The credential architecture — which login
mechanisms, the token format, the OAuth machinery — is #30's decision and appears
here only where the threat model constrains it.

Why this exists before any code: the SPA, the REST API and the MCP endpoint share one
ingress and one process, so a login screen bolted onto the SPA would leave every other
door open. The matrix in §5.5 is what an implementation issue is checked against, and
the enumeration test in §5.8 is what stops a new router or tool quietly landing outside
it.

### 5.1 What exists today (02/09/2026)

Recorded so the matrix reads as a diff against reality rather than a description of it.

> **Superseded in part by M6-1 (#186, 03/09/2026).** The first three bullets below
> describe the tree before item 1 of §5.9 shipped. Since then: `app/ingress.py`
> derives one `IngressPolicy` from `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`,
> `ALLOWED_ORIGINS`, `TRUSTED_PROXIES` and `WEB_BIND`; the REST middleware and
> FastMCP's guard in strict mode both read it (421 / 403 with the envelope);
> `redirect_slashes=False` on both routers; uvicorn runs with `--no-proxy-headers`
> and the forwarded address lands in `request.state.client_address`; `/readyz`
> answers the raw loopback peer only; nginx is an envsubst template
> (`frontend/nginx/`) with a default-deny 421 server whose names come from the same
> keys, the `/api/mcp`, `/api/.well-known`, `/api/openapi.json` and `/api/readyz`
> rejections ahead of the generic location, exact root `.well-known` locations, the
> security headers and a CSP for the bundle, forwarding `$http_host` so the app's
> same-origin rule sees the port. The remaining bullets — no authentication, four
> writers with no principal, the incidental cross-origin picture — still describe the
> code.

- **One process, one port.** FastAPI serves the REST routers at `/` and FastMCP is
  mounted as an ASGI sub-application at `/mcp` (§2). There is no middleware of any
  kind: no authentication, no CORS policy, no Host or Origin validation, no rate
  limiting, no security headers. FastMCP 3.4.5 ships a Host/Origin guard, but it is
  opt-in (`host_origin_protection` defaults to `False`) and `mcp.http_app()` is
  called without it (#39). FastAPI's generated `/openapi.json`, `/docs`, `/redoc` and
  `/docs/oauth2-redirect` are plain Starlette routes installed with `add_route`; an
  app-level `dependencies=[…]` never runs for them (probed on the pinned FastAPI
  0.141.1: 401 with one dependency call for an ordinary route, 200 with zero calls for
  all four), and `/api/docs/oauth2-redirect` — Swagger's unused OAuth helper — answers
  200 HTML through the ingress today. The route table declares nothing about exposure:
  15 top-level entries, eight of them FastAPI's `_IncludedRouter` wrappers without a
  `path`, expanding to 57 effective routes plus the MCP mount; `/docs` and
  `/openapi.json` are the same route type with the same flags yet have different
  external spellings, and so are `/healthz` and `/readyz` (Codex's findings 8 and 9 on
  PR #185).
- **Redirects are request-derived.** Both routers keep Starlette's default
  `redirect_slashes=True`, and Starlette 1.4.0 builds that redirect's `Location` from
  the request's scheme and Host, query string included: `GET /kits/` answers 307 to
  `http://<Host>/kits`, which through the ingress drops the `/api` prefix and lands on
  the SPA (probed in-process, 03/09/2026; Codex's finding 6 on PR #185).
- **The packaged ingress is nginx** (`frontend/nginx.conf`), the only published
  service. `server_name _` accepts any Host and forwards it verbatim. `location /` is
  the SPA fallback, so *any* unknown path — `/.well-known/anything` included — returns
  `index.html` with a 200. `location /api/` proxies to the API with the prefix
  stripped, which makes `/api/docs`, `/api/redoc`, `/api/healthz` and `/api/readyz`
  reachable from outside; `location = /openapi.json` proxies the schema at the root.
  Because that `/api/` rewrite is generic, `/api/mcp/` reaches the MCP handler and
  returns a fresh session id — as do `/api//mcp/`, `//api/mcp/`, `/api/%6dcp/` and
  `/api/mcp%2f` once nginx has merged slashes and percent-decoded — and
  `/api/openapi.json` serves the schema byte-for-byte (replayed against the packaged
  stack, 02/09/2026; Codex's finding 1 on PR #185) — the rewrite makes **every** root
  path of the API process reachable under `/api/`, which is the class both aliases
  belong to. `/mcp` and `/mcp/` proxy to the
  MCP app with buffering off. nginx sets `X-Forwarded-For` and `X-Forwarded-Proto`.
  Nothing in the app reads them, but uvicorn 0.52.1's proxy-headers middleware is on
  by default and trusts `127.0.0.1` only, so today it ignores nginx's headers and
  would start rewriting `request.client` from them the moment nginx's address were
  added to its trust list (§5.6, proxy trust).
- **Binding.** `WEB_BIND:WEB_PORT` → nginx:80, default `127.0.0.1:8080`. `api` and
  `db` are not published. The compose file's own comment calls `WEB_BIND` "the whole
  access-control story until M6", which is accurate.
- **Source-run development** is uvicorn on `127.0.0.1:8000` and Vite on
  `localhost:5173`; Vite proxies `/api` with `changeOrigin: true`, so the API sees
  `Host: 127.0.0.1:8000` and `Origin: http://localhost:5173` on the same request. MCP
  in development is reached directly at `:8000/mcp/`. The Playwright suite runs
  through that proxy.
- **Four writers, no principal.** The UI, REST clients, MCP agents and the CSV importer
  all reach the service layer with no identity attached; no service takes a caller
  argument. `POST /import/apply` with `mode=replace_all` deletes the collection. Since
  #41 the `plan_hash` from a preview is mandatory on apply (`importing.py` refuses an
  empty one), which closes the blind cross-origin drive-by #39 found — a page on
  another origin can *send* the multipart request but cannot *read* the preview
  response that carries the hash. That is a data-integrity control that happens to
  help; §5.6 does not let CSRF protection rest on it.
- **Cross-origin, incidentally.** With no CORS middleware, every JSON write fails the
  browser's preflight, and a JSON body smuggled in as `text/plain`, as a form, or with
  no `Content-Type` at all is not parsed as JSON by FastAPI and 422s (probed on
  02/09/2026). `multipart/form-data` is CORS-safelisted, which makes
  `POST /import/preview` and `POST /import/apply` the only two routes a hostile page
  can reach with a body the handler accepts. Preview is read-only and does not take
  the write gate (rule 7.1).

### 5.2 Assets

What an attacker would want, roughly in the order the owner would mind losing it:

1. **The collection's integrity and availability** — kits, orders, catalog stock,
   retailers, applications, settings. A hobby collection is not secret; its purchase
   history is mildly private (prices, retailer accounts, order and tracking numbers).
   Destruction and silent corruption matter more than disclosure, which is why the
   destructive paths get their own tier in §5.5.
2. **Credentials, once they exist** — the owner's password hash or OIDC binding,
   session records, personal-token digests, the MCP OAuth proxy's client
   registrations and refresh tokens, the signing and encryption keys, and the Postgres
   password already in `.env`.
3. **The owner's browser** as a vehicle — any page the owner visits can make their
   browser send requests to a loopback or LAN instance. This is the one attacker class
   that reaches a default install today.
4. **The host.** No code path evaluates input (CSV cells are stored and exported
   verbatim, §12.8; nothing templates user data server-side), so the realistic
   host-level threat is resource exhaustion, not code execution. Out of scope beyond
   rate limiting.
5. **Backups and archives.** The full CSV archive is the whole collection in one file;
   after M6 a `pg_dump` also holds credential digests. Neither holds the env secrets.

### 5.3 Actors and trust boundaries

| Actor | Trust | Notes |
|---|---|---|
| **The owner, in a browser** | Trusted human, untrusted context | Exactly one owner (§9.4). The browser also runs other sites' pages, so "the owner's browser" and "the owner" are different principals — the gap CSRF lives in. |
| **Scoped REST clients** | Hold a credential the owner minted | Scripts, spreadsheets, home automation. Damage is bounded by scope, not by trust in the code. |
| **Remote MCP clients** (Claude, ChatGPT, agents) | Trusted credential, untrusted decision-maker | The model reads retailer names, order emails and CSV cells it did not write, and can be steered by them. Scope is the bound; import and export have no tools (§12.7) and never will. |
| **Anonymous showcase visitors** (M8) | Untrusted | Reach only `/public/*` handlers that do not exist yet. Listed so the matrix reserves the namespace. |
| **The TLS / reverse proxy** | Trusted only when declared | Forwarded headers are believed only from `TRUSTED_PROXIES`, and the app never derives its own origin from them (§5.6, proxy trust). The bundled nginx is a trusted hop by construction: it is the API's only peer on the compose network. |
| **Compose-network neighbours** (`api`, `db`, `migrate`) | Trusted | Same host, same operator, private network. |
| **The host operator** (`docker compose exec`, the log stream, `.env`) | Root of trust | Break-glass recovery lives here and nowhere reachable over the network. |
| **A network client** that can reach the published port | Adversary | The LAN in mode P, the internet in mode R. |
| **A page in the owner's browser** | Adversary | Reaches loopback and LAN instances the network client cannot. |

Adversary classes the controls are designed against: **(A)** a network attacker with
reachability and no credential; **(B)** a web attacker — a page in the owner's browser
— whose tools are CSRF, DNS rebinding and clickjacking; **(C)** a credential-holding
attacker — a leaked or stolen token, a compromised MCP client; **(D)** a
prompt-injected agent holding a legitimate credential; **(E)** a failed or hostile
upstream identity provider (OIDC mode only).

Out of scope, explicitly: compromise of the host, the container runtime or Postgres
itself; a malicious owner; physical access; supply-chain attacks on images or
dependencies (M9 territory); and denial of service beyond per-client rate limits.

### 5.4 Deployment modes

The model is defined per mode because the live adversaries differ. Every mode
authenticates — §5.6 (route bypass) says why no unauthenticated mode ships.

| Mode | Configuration | Reachable by | Live adversaries | Supported for |
|---|---|---|---|---|
| **L — loopback** (default) | `WEB_BIND=127.0.0.1`, plain HTTP, `PUBLIC_BASE_URL` unset or `http://localhost:8080` | The host only | B | Everything, local MCP clients included. The install path stays `docker compose up -d --build --wait` followed by one setup form (§5.7). |
| **P — private network** | `WEB_BIND=<VPN or LAN address>` (or `0.0.0.0` on a network the owner trusts), plain HTTP, `PUBLIC_BASE_URL=http://<name>:<port>`, `ALLOWED_HOSTS` naming every name it is reached by | Every device on that network | A (on that network), B | Home use over a WireGuard-class mesh, where the tunnel supplies confidentiality. On a raw LAN the session cookie and bearer tokens cross the wire in clear; the docs say so and leave it the operator's call. The credential itself is required since #188/#189; confidentiality on the wire is what this mode lacks. |
| **R — remote, behind TLS** | `WEB_BIND=127.0.0.1` on the same host as a TLS-terminating proxy (the reference configuration is Caddy → nginx → api), `PUBLIC_BASE_URL=https://…`, `TRUSTED_PROXIES` naming the proxy | The internet | A, B, C, D, E | The only mode the README may describe as internet deployment, and only once every test in §5.8 passes against it. |
| **Dev — source-run** | uvicorn on `127.0.0.1:8000`, Vite on `:5173`, no nginx | The developer's machine | B | Development and the e2e suite. Loopback origins are accepted against loopback hosts (§5.6, host and origin), so the Vite proxy trap recorded on #29 needs no permanent exception. |

**Unsupported, and the docs will say so:** `WEB_BIND=0.0.0.0` on a public interface
without TLS; publishing `api:8000` directly (the ingress's route separation and
default-deny are part of the control set, and the API's own controls assume nginx is
its peer); a proxy in front of the stack that is not named in `TRUSTED_PROXIES`
(forwarded headers are then ignored — rate limits key on the proxy's address and the
audit log records it: a degradation, not a bypass); and changing `PUBLIC_BASE_URL` on an
instance with linked MCP clients without relinking them (§5.6, safe failure).

### 5.5 Route families and the authorization matrix

**Principals.** Every request resolves to exactly one:

| Principal | How it arrives | Scopes held |
|---|---|---|
| `anon` | No credential | none |
| `owner` | Session cookie, **plus** the CSRF token on unsafe methods | `collection:read`, `collection:write`, `instance:admin` |
| `pat:read` / `pat:write` | `Authorization: Bearer` personal access token | `collection:read` / `collection:read` + `collection:write` |
| `mcp` | `Authorization: Bearer` access token issued by the MCP OAuth path (OIDC mode only), audience-bound to `/mcp` | `collection:read` and, if granted, `collection:write`; never `instance:admin` |
| `internal` | A request whose **raw TCP peer** — the socket's, read before any forwarded-header processing — is loopback inside the API's own network namespace: the container healthcheck, source-run development | Readiness only; grants nothing else |

Three scopes, one implication (`write` implies `read`). `instance:admin` is held by the
owner's browser session and by nothing else in M6: no admin tokens are minted, so a
leaked bearer cannot erase or reconfigure the instance, and there is no third token
tier to build UI, tests and a footgun for. Everything that needs it — `replace_all`
import, settings, credential management, recovery — is something a person does in
Settings, not something a script needs. If a scripted admin action ever has a real
case, it is a scope added deliberately, with the "conspicuous opt-in" Codex proposed
on #30. A personal access token is valid on both REST and MCP because it is the
owner's own credential; an MCP OAuth token is a delegated grant with the MCP resource
as its audience and is refused by REST. A credential that is *presented* and fails —
expired, revoked, malformed, or valid for another audience — is 401 on every route the
app's dependency covers, the anonymous families included; only an *absent* credential
resolves to `anon`. Nothing is silently downgraded: a stale bearer on
`POST /api/auth/login` is 401, and retrying without it enters the normal login flow. The
dependency covers families 2–7 and 9–13. Family 8 is FastMCP's and authenticates OAuth
*clients* its own way — the resource-bearer dependency does not wrap it, and its
handlers ignore a stray bearer (the pinned token handler answers `invalid_grant` for a
bad code with or without one).

**Route families.** Paths are as a client sees them at the ingress; the app sees
`/api/…` with the prefix stripped, and the MCP app sees `/mcp/…` as `/…`.

| # | Family | Paths | `anon` | `owner` | `pat:read` | `pat:write` | `mcp` | App enforces | Ingress adds |
|---|---|---|---|---|---|---|---|---|---|
| 1 | SPA shell and assets | `/`, `/board`, `/kits`, `/orders`, `/inventory`, `/retailers`, `/settings/*`, `/data`, `/assets/*`, `/favicon*`; `/setup` and `/login` from M6 | allow | allow | — | — | — | nothing: static files, served by nginx (by Vite in dev) | security headers — `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, a CSP for the bundle |
| 2 | Auth bootstrap | `GET /api/auth/session` | allow | allow | allow | allow | 401 (presented, wrong audience) | returns `{state: unclaimed \| anonymous \| owner, interface_language, formatting_locale}` and, for `owner`, the CSRF token. No version, no collection data. `Cache-Control: no-store`. | rate limit |
| 3 | Auth actions | `POST /api/auth/setup` (until claimed, then 410), `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/oidc/start`, `GET /api/auth/oidc/callback` | allow, by necessity | logout only | 403 | 403 | 401 | Origin check on every unsafe method even with no session; failure budget; audit event on every outcome; `state` and `nonce` on OIDC; a wrong password or setup token is **403** (`auth.login_failed` / `auth.setup_token_invalid`), not 401 — a 401 owes a challenge and these routes accept no HTTP scheme | rate limit |
| 4 | Collection reads | `GET` on `/api/kits*`, `/api/orders*`, `/api/tools*`, `/api/consumables*`, `/api/upgrades*`, `/api/display-items*`, `/api/retailers*`, `/api/catalog/search`, `/api/settings`, `/api/meta`, `/api/export/*` | 401 | allow | allow | allow | 401 | `collection:read`; `Cache-Control: no-store` | — |
| 5 | Collection writes | `POST`/`PATCH`/`DELETE` on the family-4 resources; `POST /api/catalog/{id}/adjust`, `/api/upgrades/{id}/apply`, `/api/orders/{id}/receive`, `/api/orders/{id}/ship`; `POST /api/import/preview`; `POST /api/import/apply` with `mode=merge` or `mode=add_only` when the plan's mutations touch collection tables only | 401 | allow (+ CSRF + Origin) | 403 | allow | 401 | `collection:write`; Origin check when the principal is cookie-borne | — |
| 6 | Instance administration | `PATCH /api/settings`; `POST /api/import/apply` with `mode=replace_all`, or in **any** mode when the plan updates `instance_settings`; `/api/auth/tokens*` (mint, list, revoke); credential change and OIDC rebind | 401 | allow (+ CSRF + Origin) | 403 | 403 | 401 | `instance:admin`; an import's privilege is decided on the **plan's mutations** — an `UPDATE` action on `instance_settings`, not the presence of a settings sheet, so an archive whose settings row is unchanged or skipped needs no admin — checked after the re-plan and before any row is written; `replace_all` keeps `confirm=REPLACE` and the mandatory `plan_hash` on top | — |
| 7 | MCP transport | `POST`/`GET`/`DELETE` `/mcp/`; bare `/mcp` is an **ingress-only** spelling — nginx rewrites it to `/mcp/` internally (§8), and with slash redirects off the source-run app treats it as family 13: 404 to a signed-in caller, 401 to `anon` (#204) | 401 + `WWW-Authenticate: Bearer` | **401** — a cookie is never a credential here, a valid one included | allow; write tools refused | allow | allow per scope | bearer only; Host/Origin guard (421/403); per-tool scope check in the tool wrapper; no tool holds `instance:admin` | buffering off, long timeouts (§8); the Host allowlist; **one spelling** — `/api/mcp` and `/api/mcp/*` return 404 from an exact-prefix `location` placed before the generic `/api/` one, matched after nginx's normalisation (slashes merged, percent-decoded), so the alias cannot shed these settings or family 8's limits |
| 8 | OAuth / OIDC protocol routes (OIDC mode only; 404 in local mode) | at the root, **installed by the parent app** with FastMCP's `get_well_known_routes(...)` — for `base_url=…/mcp` the helper emits exactly `/.well-known/oauth-protected-resource/mcp/` (trailing slash — the resource is `…/mcp/`), `/.well-known/oauth-authorization-server/mcp`, `/.well-known/openid-configuration/mcp` and the bare `/.well-known/openid-configuration` — **pruned too**: FastMCP adds it for root deployments and prefix-stripping proxies, and this installation is neither; its document declares `issuer=…/mcp`, which a bare-root lookup cannot match (RFC 8414 §3.3, OIDC Discovery §4.3), so it stays off unless the spike shows a client that needs it, and the spike records each named client's version and the discovery URLs it actually requests — and **not** the bare `oauth-authorization-server`, so three root documents are served; under the mount, generated by the child: `/mcp/authorize`, `/mcp/token`, `/mcp/register`, `/mcp/consent`, `/mcp/auth/callback`, and `/mcp/revoke` when the upstream offers revocation. The child also generates `/mcp/.well-known/oauth-authorization-server` and `/mcp/.well-known/oauth-protected-resource/mcp/`; those are **pruned before mounting** and never forwarded. Read by mounting a probe on FastMCP 3.4.5 / MCP SDK 1.29.0 (02/09/2026); the spike snapshots the raw route set and the set nginx exposes, trailing slashes included | allow, by protocol | allow | — | — | — | FastMCP's handlers; PKCE; exact redirect-URI matching; the upstream identity must equal the bound owner | **exact** `location` blocks at the root for the `.well-known` paths — today the SPA fallback answers them with HTML — and rate limits on `authorize`, `token`, `register`; the family-7 `/api/mcp/*` rejection covers their aliases, and `/api/.well-known` is rejected the same way — the parent-root registration is otherwise reachable under `/api/`, which pruning the child cannot prevent |
| 9 | Liveness | `GET /api/healthz` | allow | allow | allow | allow | 401 | `{"status":"ok"}` and nothing else | rate limit |
| 10 | Readiness | `GET /readyz` in-container; `GET /api/readyz` at the ingress | `internal` only; any other peer 404 | 404 | 404 | 404 | 404 | the raw TCP peer must be loopback — the healthcheck is `python -c … 127.0.0.1:8000/readyz` inside the container, and nginx arrives from the compose network | `location = /api/readyz { return 404; }` — the same decision, duplicated |
| 11 | Schema and docs | `/openapi.json`, `/api/docs`, `/api/redoc`; `/api/docs/oauth2-redirect` (Swagger's OAuth helper) is **disabled** — 404 everywhere | 401 | allow | allow | allow | 401 | `collection:read` — FastAPI's generated handlers are disabled (`openapi_url`, `docs_url`, `redoc_url` set to `None`) and re-registered through the route policy registry as guarded routes, because the app-level dependency never runs for `add_route` handlers (§5.1); the OAuth2 helper is not registered | passes; `/openapi.json` keeps its root location and is the only spelling — `/api/openapi.json` returns 404 at the ingress |
| 12 | Public read (M8) | `/api/public/*` | allow | allow | allow | allow | — | separate handlers (rule 8); **absent until M8** — an M6 test asserts no route under `/public` | its own `location`, so it can be the only thing a showcase proxy forwards |
| 13 | Everything else under `/api/` | unrouted paths, wrong verbs | 401 | 404 / 405 | 404 / 405 | 404 / 405 | 401 | an anonymous client gets 401 for an unrouted path, not 404, so the route table cannot be enumerated without a credential | the default `server` block answers 421 for a Host outside the allowlist before any `location` is considered |

Notes on the table:

- **The application is authoritative; the ingress duplicates and never grants.**
  Nothing is "protected by nginx". Development runs without nginx, a careless override
  could publish `api:8000`, and an operator may put a different proxy in front — so
  every deny in the table exists in FastAPI or FastMCP, and nginx repeats the ones that
  are cheap to repeat (the Host default-deny, `/api/readyz`, rate limits) or that only
  it can do (security headers on static files, the `.well-known` routing). Family 10
  is the one place the two layers reason differently, and both conclusions are "deny
  from outside". An ingress *alias* is the one shape this rule does not catch on its
  own: `/api/mcp/` reaches the very same handler as `/mcp/` under the very same
  app-level policy, so the app cannot tell them apart and nothing is granted — what the
  alias sheds is the per-family ingress configuration (buffering, timeouts, rate
  limits). So the ingress owns a second rule, **one spelling per family**: the paths in
  the table are the only ones nginx forwards to that handler, every other spelling is
  404 before the generic `location`, and T2 proves it with the doubled-slash and
  percent-encoded forms as well as the literal one. The class is every root namespace
  of the API process whose canonical spelling is not under `/api/` — `/mcp`,
  `/.well-known`, `/openapi.json`, `/readyz` — and the rejection list is not
  hand-maintained: it is generated from the route policy registry's declared
  spellings, so a new root route without a declaration fails the enumeration test
  rather than waiting for a reviewer. T2 carries the positive controls beside the
  negative ones — `/api/docs` and `/api/healthz` stay usable by their principals while
  `/api/openapi.json`, `/api/.well-known/*` and `/api/readyz` are rejected — because
  rejecting every parent-root path under `/api/` would take the docs and liveness
  down with them. Since the default-deny flip those positives want the owner, so
  T2 signs in first — in CI with the setup token read from the API container's
  log, which makes the first-run claim itself part of what the packaged stack
  proves — and keeps an anonymous row beside them: the dependency's 401 through
  nginx, distinct from the ingress's own 403/404/421. The externally observable surface is five things — parent routes,
  child routes, the `/api/` rewrite's aliases, router-generated redirects, and nginx's
  own prefix redirect — so T2 snapshots *responses*, status and `Location` both, never
  a route table alone. And it snapshots them **per layer**: one registry drives both
  T1 and T2, but the URLs and expected responses differ by layer — `/api/kits/` is 404
  at the ingress while `/kits/` there is the SPA's 200; bare `/mcp` reaches the bearer
  challenge through nginx and is 404 source-run — so T2's rows are the ingress
  spellings, not T1's copied across.
- **Default deny, explicit allow, declared once, enumerated by test.** Authentication
  is a single app-level dependency, not a per-route decoration a new router can forget
  (the #25 envelope lesson, applied to auth). What it reads is a **route policy
  registry** — the rule-9 shape, declare once and everything reads it, applied to
  routes. For every effective route and mount (FastAPI's included-router wrappers
  expanded, the MCP mount traversed) the registry declares: the family; the
  credential policy — anonymous, principal plus scope, `internal`, or for family 8 a
  **protocol role** (transport bearer; public discovery; registration; authorization
  with client and PKCE validation; consent transaction with its own cookie and form
  token; callback transaction with binding cookie and upstream result; token with
  client, grant and PKCE validation; revocation) — "FastMCP-owned" names who
  implements a route, not what it accepts, so each child route carries its own role;
  the effective **methods**, declared so that a library release adding `OPTIONS` or
  `HEAD` fails the test instead of being accepted; the **modes** in which the route
  exists — local, OIDC, or both; the permitted external spellings — `/api/<path>`,
  root, an ingress-only alias, or internal-only; the serving layer; the allowed
  redirect destinations — none, self, the configured provider endpoint, or a client
  URI bound by its client kind's declared rule (§5.6, proxy trust); and the
  **response profile** — cookie emission and attributes, caching, authentication
  challenge, CORS and HTML security headers. The dependency
  enforces the credential policy, matched on the **resolved endpoint**, never on the
  URL string, so no encoding, doubled slash or traversal can select a different policy
  than the handler it reaches; scope is a second dependency on the route or tool; the
  ingress template's rejection list is generated from the declared spellings; T1 and
  T2 are generated from the registry and assert the response profile as well as
  status and `Location`. The enumeration test walks the effective route
  table and the MCP tool registry and fails on anything undeclared — which is what
  makes the M8 `/public/*` handlers a deliberate act. "Root-canonical" and
  "internal-only" are declarations, not properties an unannotated route table can
  infer (§5.1); the registry is where that policy lives. FastAPI's generated schema and
  docs handlers sit outside the dependency (§5.1), so they are disabled and
  re-registered through the registry as guarded routes, and the Swagger OAuth2 helper
  is not registered at all. Routes that are *meant* to answer 404 in some mode —
  family 8 in local mode — are registered and return 404 themselves, so the anonymous
  fallback does not turn them into 401 and leak the mode.
- **Family 4 includes `GET /meta` and `GET /export/*`.** `/meta` moves from public to
  `collection:read`: the SPA's anonymous bootstrap becomes `GET /auth/session`
  (family 2), which carries what a login page needs — the instance's interface
  language and formatting locale — and nothing else. Version disclosure is a small
  thing (the repo is public and the bundle is inspectable) and still not worth
  advertising to a scanner. The export archive is the whole collection in one request,
  but a `collection:read` principal can page through every list route and assemble
  the same thing, so it is not a new class and does not earn a scope of its own.
- **Family 5 puts `import/preview` and `mode=merge` under `collection:write`, not
  admin.** Preview parses an untrusted file and writes nothing; merge is a bulk write
  that never invents stock (rule 10) and is bound to its preview by `plan_hash`. A
  write token doing a nightly merge from a spreadsheet is a legitimate automation.
  `replace_all` is the wipe, and it is admin-only. The mode is not the whole
  authorization, though: the archive's `instance_settings` sheet is importable (§6.1)
  and `apply_import` applies every planned update in every mode, so a write token
  could reconfigure the instance through a merge — the family-6 boundary crossed by a
  side door (Codex, PR #185). Authorization is therefore decided on the **plan's
  content**: a plan whose mutations include an `UPDATE` of `instance_settings` requires
  `instance:admin` whatever the mode, refused after the re-plan and before any row is
  written; a collection-only `merge` or `add_only` stays `collection:write`, and so
  does an archive whose settings sheet is present but unchanged or skipped — the
  privilege follows the mutation, not the sheet. Preview is unaffected — it writes nothing, and a
  write token seeing a settings diff it cannot apply learns nothing the same token
  cannot `GET /settings`.
- **Family 7's 401 for a session cookie is the design, not a limitation.** MCP clients
  are bearer-only by contract; a cookie that could authenticate `/mcp` would make every
  MCP write CSRF-able and would let a page in the owner's browser drive an agent's tool
  surface. The handler does not parse cookies.
- **Family 8 keeps the OAuth operations under the MCP namespace** and reserves only
  the RFC 8414 / RFC 9728 discovery documents at the root (Codex's qualification on
  #30). `/authorize`, `/token` and `/register` do not leave the SPA's path space. The
  browser OIDC login callback (family 3, `/api/auth/oidc/callback`, Authlib) and the
  MCP proxy's upstream callback (family 8, `/mcp/auth/callback`, FastMCP) are
  different routes for different flows and stay different. The discovery topology has
  two halves and both are explicit: the parent FastAPI app installs the root discovery
  routes with FastMCP's `get_well_known_routes(...)` — an nginx `location` can route to
  them but cannot create them, and a child mounted at `/mcp` does not put them at the
  root on its own — and the child's generated `/mcp/.well-known/*` aliases are pruned
  before mounting, so there are fewer public spellings and the `/api/mcp/.well-known/*`
  alias dies with them.
- **What changes for existing clients.** `/api/meta`, `/openapi.json` and the docs
  pages stop answering anonymously; `/api/readyz` stops answering from outside; `/api/mcp/` and `/api/openapi.json` stop answering at all (use `/mcp/` and `/openapi.json`); trailing-slash spellings of REST paths answer 404 instead of a 307 that already led to the SPA; `/api/docs/oauth2-redirect` goes away; a source-run MCP client must use `/mcp/` with the slash (through nginx both spellings keep working); every
  REST and MCP call needs a credential; an MCP client configured as
  `http://localhost:8080/mcp/` needs a token added (the `mcp-remote` bridge passes
  headers). Release notes lead with the `ALLOWED_HOSTS` lockout risk (§5.6) and then
  with this list.

### 5.6 Threats and controls

Each row names the control, the layer that owns it, and the §5.8 tests that prove it.
"Both" means FastAPI/FastMCP enforce and nginx duplicates.

| Threat | Modes | Control | Layer | Tests |
|---|---|---|---|---|
| **CSRF** against cookie-authenticated writes, the CORS-safelisted multipart routes included | all | Three independent controls, any one of which defeats a simple request: (1) the session cookie is `SameSite=Lax`; (2) every unsafe method whose principal is cookie-borne — and every family-3 action, session or not — requires an `Origin` header (`Referer` as the fallback) matching the canonical origin from `PUBLIC_BASE_URL` or an entry in `ALLOWED_ORIGINS`, and a missing one is denied; (3) a session-bound CSRF token in `X-CSRF-Token`, obtained from `GET /auth/session`. Bearer-borne requests skip (2) and (3): a browser never attaches a bearer to a cross-site request without a CORS preflight, and no CORS allow-origin will ever be emitted for families 2–7. **CSRF protection does not rest on `plan_hash`**; the multipart routes get their own hostile-origin tests. | app | T3, T4 |
| **Host spoofing and DNS rebinding** — a page whose hostname resolves to the instance, so `Origin` and `Host` are both the attacker's | L, P, Dev | A Host allowlist: the host of `PUBLIC_BASE_URL`, the loopback names, the bind address, and `ALLOWED_HOSTS`. A miss is `421 Misdirected Request` with a body naming the setting. Applied to REST and MCP alike; FastMCP's guard runs in `strict` mode with the same lists, because the MCP transport specification requires Origin validation on the MCP app itself. Loopback origins are accepted against loopback hosts — the rule FastMCP already applies — which is what lets the Vite proxy (`Origin: localhost:5173` against `Host: 127.0.0.1:8000`) work with no permanent development exception. The REST middleware applies the same three-way rule as that guard — an origin in the list, loopback-to-loopback, or an `Origin` equal to the request's own origin for any allowed Host — and the canonical origin from `PUBLIC_BASE_URL` is always in the list: behind TLS the app sees `http` while the browser sends `https://…`, which is exactly the entry the canonical origin supplies (probed on the pinned guard: an allowed `https://app.example` passes with an `http` ASGI scheme). `ALLOWED_ORIGINS` is needed only for a non-canonical alias reached over a scheme the app does not see. **This is the one control that can lock an operator out** (#39): anything reached by a LAN hostname, a container name or a proxy has to be in the list. The setting, a default that covers the loopback names and the bind address, the 421 body and the release note ship together, and the change ships as its own release so nobody upgrading for a data fix meets it by surprise. | both — nginx's default `server` returns 421 before any `location`; the app repeats it | T3 |
| **Clickjacking** of the SPA | P, R | `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` on the SPA; the API sets both on the few HTML responses it has (docs pages, OAuth consent) | ingress for static files, app for its own HTML | T2 |
| **Brute force** against login, setup and token endpoints | P, R | Argon2id for the local password; a per-IP rate limit at the ingress; at the app a global failure budget with exponential delay rather than a lockout an attacker could use against the owner; identical response and timing for "no such user" and "wrong password" (there is one user); a high-entropy single-use setup token; an audit event per attempt. The app's limiter is in-process, which is correct while the API runs one worker, as it does; more workers means a shared store, and the Dockerfile is where that is pinned. | both | T8 |
| **Credential and token leakage** | all | Bearer tokens only in the `Authorization` header — never a query parameter, which lands in access logs and `Referer`; PATs shown once, stored as digests, looked up by a public prefix, compared with `hmac.compare_digest`; session ids opaque, only a digest stored; `Cache-Control: no-store` on every authenticated response and on every OAuth transaction and credential response — the consent page and its form result, the callback, the token endpoint, failures included: the MCP SDK sets it on token, revoke and authorize-error responses, but FastMCP's consent page, consent redirect and callback redirect carry no `Cache-Control` at all (read from the pinned handlers, 03/09/2026), so plamotrack adds it as a thin response middleware on the mount, while public discovery keeps its declared `public, max-age=3600`; no credential or token in any log line, enforced by a test that greps captured logs; the setup token printed to the API's log at startup while the instance is unclaimed and nowhere else (the log stream is the host operator's, §5.3); the CSV archive **never** carries auth tables — rule 9's registry does not gain them, so an export cannot become a credential dump; a backup of auth state is three things — the database, the OAuth proxy's state store wherever the spike puts it (FastMCP's default is an encrypted file tree under its home directory, so a named volume unless the spike chooses a Postgres adapter), and the matching env secrets; restoring without the secrets yields intact data with credentials to re-mint, and restoring without the store yields intact data, sessions and PATs with MCP links to re-establish. | app | T10, T11, T13 |
| **Session fixation and theft** | P, R | Session id rotated on login; `HttpOnly`; `Secure` and the `__Host-` prefix when `PUBLIC_BASE_URL` is `https`. On plain HTTP — modes L and P — the cookie cannot be `Secure` (Chrome 152 and Firefox 153 store a `Secure` cookie set over `http://localhost` and `http://127.0.0.1`; WebKit 26.5 does not — WebKit bug 232088, still open), so its name changes with the scheme and its confidentiality rests on the network being the owner's own; the startup log says which it is. Idle and absolute expiry; logout, credential change and OIDC rebind revoke every session. | app | T7 |
| **Proxy-header trust** | R | The app's own identity — scheme and host for cookies, redirect URIs, the OAuth issuer and resource — comes from `PUBLIC_BASE_URL` and never from `X-Forwarded-*` or `Host`. Forwarded headers influence only the client address used for rate limiting and audit, and are honoured only from `TRUSTED_PROXIES`; the bundled nginx is a trusted hop by construction. `PUBLIC_BASE_URL` is installation identity: changing it invalidates every linked MCP client (the issuer changed) and is documented as a migration, not a config edit. uvicorn is started with `--no-proxy-headers`: its default middleware is on, trusts `127.0.0.1`, and replaces `request.client` from `X-Forwarded-For` for any address added to its trust list — so wiring `TRUSTED_PROXIES` through it would let a trusted proxy forge the loopback peer that `internal` reads. The app's own middleware resolves the forwarded client address into a separate scope key and leaves the raw peer alone. Router-generated slash redirects are **off** on both the parent and the child (`redirect_slashes=False`): Starlette 1.4.0 builds a slash redirect's `Location` from the request's scheme and Host and keeps the query string, so `/mcp/auth/callback/?code=…` would otherwise bounce an authorization code to `http://…` from behind TLS. A non-canonical spelling is 404, never 3xx; the redirects that remain are classified by destination, and only *request-derived* ones are forbidden: **self** URLs — consent, callbacks, a login return — are built from `PUBLIC_BASE_URL`; the **provider's** authorization endpoint comes from configuration validated at startup (discovery or explicit), never from a request; a **client's** redirect URI is bound **per client kind**, and that binding is a plamotrack policy constraint on FastMCP, not something registration supplies on its own: a DCR client may be sent only to a URI it registered — exact match, with RFC 8252 §7.3's loopback-port exception for native clients; an operator allowlist, if configured, narrows what may be registered and does **not** replace the registration binding (FastMCP 3.4.5 checks the patterns *instead of* the registration once patterns are set); the client FastMCP synthesises for the **upstream client id** — created with `allow_unregistered_redirect_uris=True`, so anyone who knows the public upstream id can be sent to an arbitrary destination carrying `error=access_denied` and their state (probed at `9e72a77`: 302 to consent for an unregistered URI, where an unknown client id is 400) — is refused or given an explicitly configured callback; CIMD and any static client get their own declared binding, subject to #30's compatibility ceiling. An unbound `redirect_uri` is 400 with no `Location`. The two producers of request-derived redirects — Starlette's slash fallback and uvicorn's forwarded-scheme rewriting — are both off. nginx's own prefix redirect (`/api` → `/api/`, 301) is relative (`absolute_redirect off`) and is retained deliberately as the one ingress-produced redirect, listed as such in T2. | both | T9 |
| **Route bypass and exposed admin** | all | Default deny with an enumerated allowlist (§5.5); policy matched on the resolved endpoint; `api:8000` unpublished; the `.well-known` and `/api/readyz` locations exact; **no unauthenticated mode in the shipped image** — there is no `AUTH_MODE=disabled`, and the test suites use an in-process principal injection the packaged image does not contain (the alternative, "refuse to start when auth is off and the bind is not loopback", still ships the bypass and relies on a check being right); auth configuration is env-only and never a settings row, so the Settings page cannot grow a "disable auth" toggle; `/public/*` absent until M8. | both | T1, T2 |
| **Scope escalation** | R, and any leaked token | One principal shape for REST and MCP; scope checks in the route dependency and the tool wrapper through the same helper, so a tool cannot be more permissive than its REST twin; a PAT cannot mint a PAT; MCP OAuth grants never include `instance:admin`; the enumeration test pairs every write tool with `collection:write`; an import's required privilege is read off its plan's content, so the mode cannot smuggle an admin-owned table past a write token. | app | T1, T6 |
| **Prompt injection through an agent** (adversary D) | any mode with MCP | Not solvable in the server; bounded instead: scope, no import or export tools ever (§12.7), no admin tools, the rule-2 guards on destructive order edits, `remove_missing_lines` (§7), and audit lines naming the credential so a rogue session can be found and revoked. | app | T6 |
| **Open redirect and code interception** in OIDC flows | R | Authlib's `state` and `nonce`; exact redirect-URI matching; PKCE on the MCP proxy path; the upstream identity required to equal the bound `(issuer, subject)`; a non-owner identity refused with an audit event and no session. | app | T6, T7 |
| **Version and topology disclosure** | R | `/meta`, the OpenAPI schema and the docs pages behind `collection:read`; anonymous unrouted paths answer 401 rather than 404; `/healthz` says only `ok`. | app | T2 |
| **Log and audit hygiene** | all | Audit events for: setup claimed, login success and failure, logout, session revoked, PAT minted, revoked and used after revocation, OIDC rebind, recovery run, Host/Origin rejection. Each carries the principal id, credential kind, client address and route or tool — never a secret, never a request body. Retention is a table with a documented prune. Collection-change auditing is not M6. | app | T10 |
| **Denial of service** | P, R | Out of scope beyond: per-IP `limit_req` at the ingress on families 2, 3, 8 and 9; the app's failure budget; `client_max_body_size` as today; readiness hidden from outside so strangers cannot probe the database. | both | T2 |

**Safe failure.** The first rule is that a failure denies; the second is that it denies
*new* things and leaves the owner's existing access alone where it can.

- **Identity provider unavailable** (OIDC mode): new browser logins fail with a clear
  message; existing sessions, PATs and issued MCP access tokens continue; MCP refresh
  may fail and require relinking after a long outage. The auth mode does not fall back
  to local on its own — a mode change is an explicit operator action.
- **Database unavailable:** `/readyz` fails, and every authenticated route returns 503,
  because a session or token that cannot be looked up is not a session or token. No
  cached allow.
- **Unclaimed instance** (a fresh install, or an upgrade onto M6): every collection
  route is 401, `GET /auth/session` reports `unclaimed`, the SPA shows the setup form,
  and the API log prints the setup token at each start until it is claimed, so an
  operator who missed it restarts the container rather than editing the database.
- **Host not in the allowlist:** 421 with the setting named in the body. Recoverable by
  editing `.env` and `docker compose up -d`; nothing is written.
- **Secrets lost or rotated** (the session secret, the OAuth signing key): every
  session and MCP link invalid, all data intact, PATs survive (they are digests, not
  signatures).
- **OAuth state store lost** (the volume, or the adapter's rows): MCP clients must
  relink; data, sessions and PATs are untouched.
- **Credentials lost:** a host-side command resets the local password or rebinds the
  OIDC identity and revokes every session; it is never an HTTP endpoint.

### 5.7 What the loopback install keeps

The low-friction path survives M6 as: `docker compose up -d --build --wait`, then
`docker compose logs api` to read a one-time setup link, one form to set the owner's
credential, done. No TLS, no identity provider, no extra container, no certificate
authority. Sessions are long-lived on the owner's own machine. A local MCP client —
Claude Code, or Claude Desktop through `mcp-remote` — pastes a personal access token
minted in Settings; that paste is the whole cost. The LAN and mesh cases (mode P) add
`PUBLIC_BASE_URL` and `ALLOWED_HOSTS` to `.env` and nothing else.

### 5.8 The tests that gate the documentation

The README and `docs/operations.md` may recommend a `WEB_BIND` other than loopback, and
may describe mode R at all, only when every one of these exists and passes. They are
listed so the implementation issues can be checked against them rather than against a
feeling.

| # | Test | Where it runs |
|---|---|---|
| T1 | **The matrix, app layer.** One table of (family, method, principal, mode) → status and response profile (cookies, caching, challenge, security headers), driven by injected principals through the ASGI client, with each route's effective methods compared against its declaration and local-versus-OIDC as an explicit axis; family 8's rows drive each protocol role with its own state — a transaction, a binding cookie, a registered client — because one injected `anon` cannot exercise them; plus the enumeration test: every route in `app.routes` and every registered MCP tool is allowlisted or scoped, or the test fails naming it — the rows are generated from the route policy registry, and an undeclared effective route or mount (included routers expanded) fails before any row runs. Imports carry a plan-mutation axis across all three modes: a collection-only `merge` and an `add_only` upload succeed for `pat:write`, as does an archive whose settings sheet is present but unchanged; a plan with an `instance_settings` `UPDATE` is refused for `pat:write` before any row is written and succeeds for `owner`. | pytest |
| T2 | **The matrix, ingress layer.** The same table through the packaged nginx: `/api/readyz` 404, `/openapi.json` 401 anonymous, `/.well-known/oauth-*` 404 in local mode, the SPA fallback still 200 for `/orders`, security headers present, `/api/../mcp` and `//api` normalised, one spelling per family — `/api/mcp/`, `/api//mcp/`, `//api/mcp/`, `/api/%6dcp/`, `/api/mcp%2f` and `/api/openapi.json` all 404 while `/mcp/` and `/openapi.json` answer; in OIDC mode the three root discovery documents answer and the bare `/.well-known/openid-configuration` is 404, while `/mcp/.well-known/*`, `/api/mcp/.well-known/*`, `/api/.well-known/oauth-protected-resource/mcp/`, `/api/%2ewell-known/…` and `/api//.well-known/…` are 404; the rejection list is generated from the registry's declared spellings, with positive controls (`/api/docs` and `/api/healthz` answer for their principals) beside the negative ones; `/api/docs/oauth2-redirect` 404; bare `/mcp` reaches the bearer challenge as an ingress-only spelling; no response in the matrix carries a `Location` header except the auth flows' own and nginx's relative `/api` → `/api/` 301, and `/api/kits/` and `/mcp/auth/callback/?code=x&state=y` are 404 with none; the rows are the ingress spellings, not T1's copied across, and they assert the response profile and the declared methods as T1 does; collection-route and MCP positives sit beside `/api/docs` and `/api/healthz`, since two positives are not exhaustive protection against an over-broad `location`; and the CI job's existing MCP `tools/list` probe now carrying a token. | CI Integration, against `docker compose up` |
| T3 | **Hostile Host and Origin.** For MCP initialize, a JSON write, `POST /import/preview` and `POST /import/apply` (multipart, both modes): hostile Host → 421; hostile Origin → 403; missing Origin on a cookie-borne write → 403; loopback origin against a loopback host → 200; a name in `ALLOWED_HOSTS` → 200. At both layers. | pytest + CI Integration |
| T4 | **CSRF.** A valid session without the CSRF token → 403; the token with a hostile Origin → 403; a bearer with a hostile Origin → 200; the multipart routes named individually. | pytest |
| T5 | **MCP never takes a cookie.** A valid session cookie and no bearer → 401 with `WWW-Authenticate: Bearer` and the resource-metadata pointer; the same request with a PAT → 200; an MCP OAuth token on a REST route → 401. | pytest |
| T6 | **Scope.** `pat:read` on every family-5 and family-6 route → 403 and on every write tool → tool error; `pat:write` on every family-6 route → 403; an MCP grant requesting `instance:admin` is not issued; a non-owner OIDC identity is refused; a `pat:write` merge whose plan updates `instance_settings` → 403 with the settings row unchanged. | pytest |
| T7 | **Lifecycle.** Logout, PAT revocation, credential reset and OIDC rebind each invalidate exactly what §5.6 says; an expired session or token is 401; an unclaimed instance is 401 on every collection route; the setup token works once and 410s after. | pytest + e2e (real login and logout) |
| T8 | **Brute force.** N failures → delay or 429 and audit rows; identical body and status for the two failure kinds; the setup token's length asserted. | pytest |
| T9 | **Proxy trust.** A spoofed `X-Forwarded-For` from an untrusted peer is ignored for rate-limit keying and audit; from a `TRUSTED_PROXIES` peer it is honoured; `X-Forwarded-Host` never changes a redirect or a cookie; a `TRUSTED_PROXIES` peer sending `X-Forwarded-For: 127.0.0.1` still gets 404 from `/readyz`; every **self** `Location` names `PUBLIC_BASE_URL`'s scheme and host; a provider redirect names the configured endpoint and carries the canonical callback as its `redirect_uri`; a client redirect obeys its kind's binding, each kind its own row — a DCR client to a registered URI only (a different port on a registered loopback URI allowed, a different host refused), a DCR client under an operator allowlist needing both the allowlist and its registration, the synthesised upstream-id client refused or held to its configured callback, CIMD per its declaration; a forged `X-Forwarded-Host` changes none of them; an unbound `redirect_uri` is 400 with no `Location`; and a trailing-slash spelling of a callback or authorize path is 404 with no `Location` and no query string echoed. | pytest |
| T10 | **Leakage.** Captured logs contain no token, password or session id across a full login, PAT and MCP run; `Cache-Control: no-store` on families 2–7 and on family 8's transaction and credential responses — consent GET and POST, callback, token, revoke, and their failure paths — with discovery asserted to carry its declared public caching instead; the archive's table registry contains no auth table (a rule-9 spec test); `GET /auth/session` and `/healthz` carry no version. | pytest |
| T11 | **Timing shape.** An unknown token prefix and a wrong secret produce identical status and body; the compare is `compare_digest` by construction, and the test asserts the code path, not a stopwatch. | pytest |
| T12 | **The deployment path.** The documented Caddy + compose configuration on a fresh VM: TLS, setup, login, a PAT REST call, MCP initialize through the proxy with a stream held open past 60 s, OAuth discovery through Caddy → nginx → api, `/api/readyz` 404 from outside, an `ALLOWED_HOSTS` lockout and its recovery. Scripted where possible; results recorded in the release notes. | release gate |
| T13 | **Recovery.** The break-glass reset revokes sessions and restores access; a restore from the complete set — database, OAuth state store, `.env` — brings back sessions, PATs and an *existing* MCP link — proved through public behaviour: the old client's refresh token returns 200 from `POST /mcp/token`, the access token completes an MCP initialize, and zero registrations occur after the restore; a restore without the env secrets leaves data intact and credentials re-mintable; a restore without the store leaves data, sessions and PATs intact and MCP links to re-establish, as documented. | release gate |

### 5.9 Implementation split

The bounded issues this model produces, in dependency order. Each closes against the
matrix rows and tests it names; the credential decisions inside them are #30's.

1. **Ingress identity and the Host/Origin guard** — `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`,
   `ALLOWED_ORIGINS`, `TRUSTED_PROXIES`; the 421/403 guard on REST and on FastMCP in
   strict mode; nginx moved to the `envsubst` template mechanism with a default-deny
   `server`, the `/api/readyz` block, the `.well-known` locations and the security
   headers; one spelling per family (`/api/mcp`, `/api/mcp/*`, `/api/.well-known` and
   `/api/openapi.json` rejected before the generic `/api/` location — typed in this
   item, generated from the route policy registry once item 2 lands, with the positive
   controls for `/api/docs`, `/api/healthz`, the collection routes and `/mcp/` from the start — the release ships its own ingress tests: the four forbidden namespaces with their normalised variants, and the permitted canonical routes); `redirect_slashes=False`
   on both routers, nginx's relative `/api` → `/api/` 301 retained; uvicorn
   started with
   `--no-proxy-headers` and the app-side forwarded-address middleware that keeps the
   raw peer; `/readyz` restricted to `internal`. Absorbs #39. **Its own release**, for
   the lockout reason. No authentication yet, so the only client-visible change is the
   alias spellings going dark. (T2, T3, T9.)
   **Shipped 03/09/2026 (#186)**, with two calls the item's wording left open,
   recorded so a later item does not re-derive them. (a) An unsafe request carrying
   *neither* `Origin` nor `Referer` passes. What carries this is browser behaviour,
   not the absence of cookies: a browser cannot omit `Origin` on a cross-origin unsafe
   request — the Fetch algorithm sends `null` at worst, from a sandboxed or
   no-referrer page, and `null` is refused — so the omission can only come from a
   non-browser client, and refusing it would refuse every script and MCP client for
   no gain (the PR #196 review probed 36 multipart shapes across Chromium 151,
   Firefox 153 and WebKit 26.5, including forms, beacons, workers, sandboxed frames,
   307/308 redirects and an extension, and every one carried an `Origin`). §5.6's
   CSRF row conditions the missing-`Origin` denial on a cookie-borne principal, and
   item 3 tightens the absent case when the session cookie arrives; the claim is not
   proved for every legacy engine or privileged extension, which is one more reason
   the credential-aware rule follows. (b) `TRUSTED_PROXIES` ships as the mechanism alone — the
   compose file sets no value for the bundled nginx, because nothing consumes the
   resolved address until item 8 and the compose network's range is not known
   statically; item 8 decides how the bundled hop declares itself, and until then the
   client address the app records behind nginx is nginx's own, which is a degradation
   in a value nobody reads, not a bypass. Also: T2's rows are typed in
   `backend/ingress_matrix.py` (CI Integration runs it against the packaged stack)
   until item 2's registry generates them.
2. **Auth foundation** — owner, credential, session, personal-token and audit tables;
   the principal model; the app-level default-deny dependency with the anonymous
   allowlist; the route policy registry — family, credential policy, external spellings, serving layer and redirect destinations per effective route and mount — that the dependency, the ingress template and T1/T2 all read; the response profile applied adjacent to the router that selects the route — by the innermost middleware for the app's own routes, and by a binding on each mounted route (landed here rather than with item 7) that also enforces the transport's declared verbs in front of the SDK; the scope helper shared by routes and tools; the import-apply privilege check on plan content; the enumeration test, which also refuses a route graph no declaration can describe (a shadowed dispatch entry, a shared endpoint, an unknown route type) and pins the raw transport's accepted verbs behaviourally;
   in-process principal injection for pytest; an e2e bootstrap that claims the owner
   and reuses storage state. (T1, T10.)
3. **Local owner authentication** — setup token and claim, login and logout, session
   cookie and CSRF token, the failure budget, `/auth/session`, the SPA's setup and
   login screens, the host-side recovery command, `/meta` and the docs moved behind
   `collection:read` — FastAPI's generated schema/docs handlers disabled and
   re-registered as guarded routes, the Swagger OAuth2 helper dropped. (T4, T7, T8,
   T11.) **Shipped (#188):** the shipped `app` is default-deny (`create_app(
   authorization=True)`); `Principal.via` distinguishes cookie-borne from bearer, and
   the CSRF controls (Origin presence + session-bound `X-CSRF-Token`) apply to a
   cookie-borne unsafe request only; `apply_import` reads `plan_requires_admin` off the
   re-planned outcome. Two calls the item left open, recorded so a later item does not
   re-derive them. (a) **A non-resolving session cookie resolves to `anon`, not 401**
   (a deliberate narrowing of §5.5's "presented-and-failed → 401"): the cookie is
   `HttpOnly`, so a browser cannot clear a stale one, and a 401 on a cookie the client
   cannot drop would wedge `GET /auth/session` — the endpoint the SPA bootstraps and
   recovers through — in a loop; treating a stale cookie as absent keeps recovery
   automatic and the next login overwrites it. The strict rule stands for the **bearer**
   (#189), where the client owns the header. (b) **Two disclosure-hardening items from
   the family-13 row were deferred to a follow-up:** an unrouted `/api/*` path answered
   `404` for everyone (not `401` for `anon`), and a malformed body to a protected route
   was parsed to `422` before the dependency ran — both need auth to run *ahead of*
   Starlette routing / FastAPI body parsing (a middleware-level check), which the
   app-level dependency cannot do. **Shipped as M6-3b (#204):** the pre-routing gate
   (`app/auth/prerouting.py`), one middleware directly above the response-profile
   layer and inside the ingress guards, resolves the principal **once** per request the
   REST app owns — stashed on the request state, so the dependency reads it rather than
   resolving again (a second lookup and `last_used_at` touch per request; the count is
   pinned by test) — and refuses `anon` before the router runs wherever the router would have
   answered 404, 405 or the dependency's 401, reading what the request *would* reach
   from the registry's own dispatch walk, never the URL string. It never grants: the
   dependency stays the authority on every matched route, so a disagreement between the
   gate's view of dispatch and the router's could only cost disclosure, and a test pins
   the two agree route by route. Calls the item's wording left open, recorded here: (i)
   **the anonymous families keep their own 405 and 422** — a wrong verb on `/healthz`, a
   malformed login body — because there is no credential to gate on; a path is passed
   through when *every* route matching it is `ANONYMOUS`. (ii) **`INTERNAL` is admitted
   on a full match and refused on a partial one**: `GET /readyz` still self-guards on
   the raw peer (family 10) and answers the outside peer 404, while `DELETE /readyz` is
   401 to `anon` — a 405 there would name the route. (iii) **The `/mcp` mount is the
   child's**: the gate resolves no principal for a request the mount claims, so a
   cookie still never reaches FastMCP and `/mcp/<unrouted>` stays the child's 404. (iv)
   **Bare `/mcp` at the source-run app is a family-13 spelling** — the mount does not
   claim it, so it now reads 401 to `anon` and 404 to a signed-in caller (the family-7
   row); through nginx it is still rewritten to `/mcp/` and reaches the bearer
   challenge. (v) The wrong-verb refusal carries **no `Allow`**, and every gate refusal
   carries the family-13 profile (`no-store`) stamped by the gate itself, since the
   innermost middleware has no endpoint to read when the router never ran. (vi) **Family
   8's namespace is the protocol's**: under `/.well-known/` with no route registered —
   local mode — the router's 404 stands for everyone and no principal is resolved,
   because discovery is anonymous by protocol and a `Bearer` challenge on a discovery URL
   would be a claim about the resource; the namespace is `PROTOCOL_NAMESPACES`, derived
   from the same family-8 declaration the ingress alias rejection reads, and the T2 rows
   for the three root documents (404 until M6-7) are what found the first head's 401. What the
   gate does not change: a presented-and-failed bearer is still the resolver's 401
   `auth.bearer_invalid` on an unrouted path as on a routed one, and a stale cookie is
   still `anon` (call (a)). The **e2e suite and CI Integration** need the auth
   adaptation the flip requires (a Playwright global-setup that claims the owner and
   reuses storage state, and auth on the specs' own API contexts); until that lands the
   Integration job is red by construction.
4. **Personal access tokens** — mint, list and revoke under Settings; bearer validation
   on REST and MCP; per-tool scope enforcement; `mcp-remote` documentation. (T5, T6.)
   **Shipped (#189):** `ptk_<12 hex>_<secret>`, digest of the whole token stored,
   looked up by the public id, compared with `compare_digest` — against a dummy digest
   when the id names no row (T11); one helper, `services/tokens.resolve_bearer`, behind
   both the REST resolver and the FastMCP `TokenVerifier` on the mount; the per-tool
   check is one FastMCP middleware on `tools/call` reading `MCP_TOOL_SCOPES`, refusing
   before arguments are parsed; management is family 6 (`/auth/tokens`, the
   `auth-tokens` tag); audit events `auth.token_minted`, `auth.token_revoked`,
   `auth.token_use_after_revoke`; `WWW-Authenticate` on **every** 401 the app produces
   (bare `Bearer` for an absent credential on a scoped route, `error="invalid_token"`
   for a presented one, on REST and MCP alike) — which is why the family-3 form failures
   (a wrong password, a wrong setup token) are now **403**, `CredentialRejectedError`:
   RFC 9110 §15.5.2 makes a 401 owe a challenge applicable to the resource, those routes
   refuse the only scheme the app speaks, and a challenge-less 401 was the round-1
   narrowing Codex overruled (rounds 1–2, f2/f4). The codes are unchanged. Calls the
   item's wording left open, recorded here: (a) **no
   `resource_metadata` pointer in local mode** — there is no protected-resource
   document until M6-7 (family 8 is OIDC-only), and a pointer at a 404 would be worse
   than none; T5's "resource-metadata pointer" lands with item 7. (b) **A bearer on a
   family-3 action is 403** by a route-policy flag (`bearer_refused`), not by a change
   to the anonymous credential policy: the actions stay anonymous for browsers and
   refuse tokens; `GET /auth/session` admits a token and reports the instance state
   with no CSRF token. (c) **The tool list is not filtered by scope** — a `pat:read`
   client sees the write tools and is refused at the call, with a message naming the
   scope; hiding them would make an agent's failure silent. (d) **Revoked rows are
   kept and listed**, so the owner can see when a leaked token was last used; nothing
   deletes a token row. (e) **A wrong secret or an unknown id writes no audit row** —
   it is a guess, and a row per bad request would be write amplification an
   unauthenticated caller controls; a revoked token presented with its *correct*
   secret does (that is a leak or an un-rotated client). The login failure budget
   does not cover bearers — item 8's ingress `limit_req` is the brute-force control
   for a 256-bit secret. (f) **The mount is built through
   `create_streamable_http_app` directly**, because `FastMCP.http_app` reads the
   provider off the shared server object and the pre-auth app (`create_app()`, the
   harnesses) must keep an open mount in the same process; and the transport route's
   `methods` — which FastMCP declares once a provider is set — are cleared, so the
   registry's `RouteBinding` stays the one verb boundary (item 2's round-3 design)
   rather than a Starlette 405 in a different shape without the profile. (g) T5's
   "an MCP OAuth token on a REST route → 401" has no token to present until item 7;
   the resolver's strictness on *every* failed bearer is what will make it true.
   (h) The in-memory MCP client the tests use carries no header, so the tool-scope
   middleware reads an injected principal off the server object **only when no HTTP
   request is in flight** — the `app.state` seam's twin, unreachable from the wire.
   (i) **The token value is normalised in the shared helper** (`resolve_bearer` strips
   it): the REST parser and FastMCP's bearer backend cut the header differently
   (`Bearer  <token>` reached the verifier with a leading space), and the one-helper
   invariant has to hold at the value, not the call (round 1, f1). (j) **A live token
   travels only in headers, in the tests and the matrix too**: request URIs are what
   uvicorn's and nginx's access logs record, so the matrix's query-string row carries a
   fake token — as does the unit query-string test — and CI scans the packaged stack's
   `api` and `web` output for the real one after the run, refusing a vacuous scan by
   first requiring an access record from each service (rounds 1–2, f3/f5); the unit
   T10 attaches its capture to every logger, propagating or not, and says what it
   cannot see (no access log exists under ASGITransport).
5. **MCP OAuth compatibility spike** — the pinned FastMCP against Google and one
   self-hosted OIDC provider, Claude web, ChatGPT web and MCP Inspector; the exact
   generated route table snapshotted; each named client's version and the discovery
   URLs it requests recorded; proxy-state persistence (a named volume or an
   adapter) and the explicit signing key decided on evidence, and whichever store is
   chosen joins the documented backup set — the backup contract is storage-independent.
   Spike before schema; the failure rule from #30 applies verbatim.
6. **Browser OIDC** — the Authlib discovery flow, `state` and `nonce`, owner binding to
   `(issuer, subject)`, rebind recovery, the mutually exclusive `local`/`oidc` mode
   switch. (T6, T7.)
7. **MCP OAuth** — the FastMCP proxy wired with the spike's decisions, owner
   restriction, scope mapping, persistence, the root discovery routes installed on the
   parent app, the child's `/mcp/.well-known/*` aliases pruned, the per-route
   protocol-role, method, mode and response-profile declarations for the child's
   routes (the `no-store` stamp on the mount already lands with item 2; the
   protocol routes' own profiles are declared there as they arrive), the client-redirect
   binding per client kind (DCR exact with the loopback-port exception, an allowlist
   narrowing registration rather than replacing it, the synthesised upstream-id client
   refused or pinned to a configured callback, CIMD declared), and snapshots of both
   the raw route set and the set nginx exposes, trailing slashes included. (T2, T5,
   T6, T9, T10, T12.)
8. **Audit, rate limiting and log hygiene** — the event table and its prune, ingress
   `limit_req`, the app's budget, the log-grep test. (T8, T10.)
9. **Reference TLS deployment and documentation** — the Caddy configuration,
   `docs/operations.md` rewritten around the modes and its backup section around the
   three-part set (database, OAuth state store, `.env`), the README's alpha warning
   rewritten, the `.env.example` keys. (T12, T13.)
10. **Release** — notes leading with `ALLOWED_HOSTS`, then the client-visible changes
    in §5.5; the upgrade path for existing instances (they come up unclaimed and fail
    closed until the setup token is used).

M6.1's protocol work stays separate (§7.1). Where a target MCP client turns out to need
the newer protocol before it can be tested, that is recorded as a dependency, not folded
in.

**Superseded by this section:** the earlier §5 statement that remote MCP clients
authenticate "via the MCP OAuth contract" is narrowed — token-capable clients use a
personal access token in any mode, and the OAuth path exists only in OIDC mode, per
#30's product boundary; §8's "M6 supplies a tested VPS deployment path" now means mode
R exactly as §5.4 defines it; and the compose file's "`WEB_BIND` is the whole
access-control story" stops being true at item 1 above.

---

## 6. Currency Handling

- `unit_price_minor` — integer, minor units (cents), never float. Avoids the classic
  floating-point money bug
- `currency_code` — ISO 4217 (AUD, USD, JPY, …), stored per order item
- ✅ `converted_price_minor` + `converted_currency_code` — the conversion snapshot,
  captured **at entry time** and never recalculated on view.
  What a kit cost is a historical fact; re-deriving it from a live FX API on every page
  load would make spend history drift underneath the person reading it. If a live-rate
  lookup at entry time is wanted (a nice-to-have, not built), it's a one-shot call at
  creation, result stored, done
- ✅ the reference currency — the instance's own currency (default `AUD`). Order
  forms, starter-sheet templates, and the MCP `create_order` default all read it —
  since #23 from the `instance_settings` row (§6.1), which the `REFERENCE_CURRENCY`
  env var only seeds on first run. A CHECK constraint keeps the amount and its code
  null-or-present together

✅ **The AUD assumption is gone** (shipped ahead of M5.1, alongside M5). The amount
column was `converted_price_aud_minor` — a name that asserted a currency the schema
never stored. It is now a neutral amount with its code beside it, and the code is
written **at entry time**, not read from config on the way out: an amount whose meaning
can be changed by editing an env var is not a snapshot. Moving the reference currency
later therefore changes what *new* entries default to and nothing else.

✅ **That runtime default now lives in the singleton instance-settings record** (#23):
the owner changes it through `PATCH /settings` (or the Settings page's General
section, #24) and every
REST, MCP, and browser client sees the same value. The environment value is a
first-run/upgrade bootstrap — the migration that created the table seeded it and it has
been inert since. That changed where the default lives, not the historical rule: stored
amounts keep their recorded currency and are never restated when the default moves.

Two compatibility notes for anyone who used the 0.1.0 alpha:

- the migration renames the column rather than replacing it, and backfills `AUD` for
  every existing snapshot — which is what those rows always meant
- CSVs exported by 0.1.0 still import. `converted_price_aud_minor` is a registered
  alias of the current column and carries `AUD` in with it, so an old archive is read
  as the AUD it was even on an instance whose reference currency is something else.
  Exports only ever emit the current name

The same instinct — recorded facts stay recorded — runs through the order guards in
§3.9 and the delete blocks in §4.

✅ **An edit only touches the snapshot when it says so.** A line in `PATCH /orders/{id}`
otherwise replaces the stored one field for field; the `converted_*` pair is the single
exception. Omit it and the stored snapshot survives; clearing takes an explicit `null`.
Restating the amount alone doesn't relabel the currency either — on an update the code
falls back to the one already recorded before it falls back to the instance default, or
a typo fix on a GBP amount would quietly reissue it as AUD.

The CSV importer reaches the same conclusion from its own rule (§12): a column left out
of a sheet is left alone. A sheet carrying an amount and no currency column had been
stamping the instance default over whatever was recorded; it now defers to the stored
code, and the preview shows the currency untouched because the deferral happens while
the row is being diffed against its target rather than at write time. A blank *cell* in
a column the sheet does include still means the instance default — that one is a
documented instruction rather than silence.
The reason it can't follow the rule its neighbours follow: no client holds the
entry-time rate, so nobody editing a quantity is in a position to restate the
conversion — and treating "absent" as "clear" meant a foreign-currency snapshot,
imported from a spreadsheet or written by an agent, died on the first unrelated edit.

The browser follows from the same premise. It derives a snapshot only for a line it is
*creating* in the instance's own currency, where the converted amount is the price and
no rate is involved. For a line that already exists it shows what was recorded — in the
currency it was recorded in — and sends that back untouched. Notably, "the purchase
currency equals the reference currency" is **not** grounds to recompute: a yen purchase
carrying an AUD snapshot on an instance that later moved to `JPY` would be silently
restamped as yen, which is precisely the drift this section exists to prevent. Nor is
"the amount differs from the unit price" — an imported AUD 95 against an AUD 100 line
is a record, not a rounding error. Correcting or removing a snapshot is a thing the
operator does on purpose, in a field put there for it.

### 6.1 Instance settings & internationalisation ✅ **Complete (M5.1)**

The first localisation milestone is infrastructure, not a promise to ship a particular
translation. It also supplies the settings surface the localisation controls need.

✅ **One owner, one settings record** (#23). Plamotrack remains a single-owner
application after authentication lands, so interface language, formatting locale, IANA
time zone, date style, hour cycle, and reference currency belong to the instance rather
than one browser's local storage. Every device reads the same values. `en-AU` is the
deterministic language and formatting fallback; the time zone also has one explicit
instance value rather than being inferred independently by each browser.

How that landed: a one-row `instance_settings` table (a CHECK pins the primary key to
1), created and seeded by its migration — `en-AU` language and formatting, `UTC` time
zone, locale-default date style and hour cycle, and the reference currency read from
`REFERENCE_CURRENCY` at upgrade time so an existing installation keeps what it
configured. From then on the env var is inert bootstrap input. `GET /settings` and
`PATCH /settings` are thin over `services/instance_settings.py`; updates take the write
gate and the row `FOR UPDATE` (rules 7/7.1), and validation predicates (supported
language, BCP 47 well-formedness, IANA zone membership, currency shape) are module
functions the CSV importer's cell parsers share (rule 1). `date_style` is
`locale`/`short`/`medium`/`long`/`full` and `hour_cycle` is `locale`/`h12`/`h23` — the
`Intl.DateTimeFormat` vocabularies, since that is the formatter that will consume them.
The interface language is a membership test (only shipped catalogues), while the
formatting locale is shape-only — `Intl` resolves any well-formed tag to its nearest
supported locale, the same accept-the-unknown reasoning `KNOWN_CURRENCIES` records.

In the portability layer the table is a **singleton spec**: exported in the archive,
and on import only ever *updated* — never created, never deleted, exactly one row. A
`replace_all` restore does not truncate it (the restore replaces the collection, not
the instance's identity) and counts no settings row among its deletions; an upload
without the sheet leaves settings untouched in every mode; the preview shows a settings
change field-by-field like any other update. Starter sheets never carry settings.

Language and regional presentation are separate settings. Selecting Japanese may suggest
`ja-JP`, for example, but it does not silently replace a formatting locale the owner chose
on purpose. Presentation settings may change what a value looks like; they never change
the canonical API value or what is stored.

**Catalogues ship with the repository.** `en-AU` is the canonical source catalogue and
fallback. Each additional catalogue carries a BCP 47 tag, native name, direction, and
readiness metadata in a small manifest. Languages arrive through reviewed PRs, with
automated checks for known keys, interpolation parameters, plural shapes, and coverage.
An incomplete catalogue may exist in-tree, but is not offered as finished until it meets
the documented review/coverage bar. Adding a language should normally change catalogue
and manifest data, not application logic. Runtime language uploads are out of scope.

How that landed ✅ (#22, 27/08/2026): `frontend/src/i18n/` holds the runtime
(i18next + react-i18next — chosen for dynamic key lookup, which the enum labels
use today and the structured REST/import diagnostics will use later), the
`manifest.json` registry, and `catalogues/en-AU.json`. Init is synchronous with
inline resources; `en-AU` is the boot language, and once the settings row
arrives the Layout effect applies the stored interface language — falling back
to `en-AU`, visibly, when the saved tag isn't shipped (#27). Catalogue-backed
label helpers in `src/lib/labels.ts` resolve
canonical wire values (`kitStatus.*`, `itemType.*`) at render time — never at
module scope, so a language change re-resolves rather than serving frozen
strings. The automated checks are `src/i18n/catalogue.test.ts` (known keys,
placeholder parity, plural shapes against each language's own CLDR categories,
and the 100%-coverage bar for enabled languages — each check proven against
inline bad fixtures before judging the real files), plus a parity test in
`backend/tests/test_settings.py` holding `SUPPORTED_INTERFACE_LANGUAGES` to
exactly the manifest's enabled tags. CI appends `npm run i18n:report`'s
coverage table to the job summary. The contribution contract — proposing,
reviewing, and enabling a language — is `docs/translating.md`. The extraction ran as four
staged PRs keeping every en-AU string byte-identical — the unchanged Playwright
suite is the standing proof — and every page's copy is served from the
catalogue.

The presentation boundary follows from that contract:

- move every user-facing frontend string into semantic catalogue keys with interpolation
  and plural rules
- route dates, times, numbers, counts, and money through formatters that receive the
  instance's explicit regional settings; the stored ISO 4217 exponent still decides what
  an integer monetary value means
- set document language and direction from catalogue metadata, and use logical layout
  properties where direction carries meaning
- keep API enum values, MCP tool names, database values, canonical CSV headers, and
  user-entered kit names, notes, retailers, and categories stable and untranslated

✅ REST errors carry stable codes and parameters alongside useful English `detail`
(#25): every failed response is the envelope `{detail, code, params}` — `detail`
byte-identical to the pre-#25 body (a string when the service refused, FastAPI's
findings list when the schema spoke — that shape distinction is load-bearing and
kept), `code` a `<domain>.<condition>` identifier from `backend/app/error_codes.py`,
`params` the values it involves. The browser renders known codes through the
catalogue (`api.<code>`, wire params camelized into `{{placeholders}}`) and falls
back to `detail` for anything it doesn't know; MCP `ToolError` text stays the bare
English sentence. The registry, the catalogue, and the guaranteed params are held
together by a shared fixture (`frontend/src/lib/__fixtures__/api-error-codes.json`),
the same device as the money cases. Import preview is a separate case because its
warnings, row failures, and blocking diagnostics live inside successful responses;
with #26 those are the same code/params/detail shape (`Diagnostic`), drawn from the
same registry and rendered through the same `api.<code>` catalogue path — a row may
carry several, one per problem, and the blocked apply's 409 carries them verbatim in
its params. Neither wording nor active language participates in the import
`plan_hash`.

The frontend exposes all of this at `/settings`: General, Language & region, Data
management, and About. ✅ The page shipped with #24 — General edits the reference
currency, the import/export workflow moved under Data management with its preview,
confirmation, and destructive-operation warnings intact, About reports the version
from `/meta`, and `/data` redirects to the section it became. ✅ #27 delivered
the Language & region controls and the presentation plumbing: the five regional
settings edit through one form (a language's usual locale is offered, never
imposed), `src/lib/presentation.ts` holds the resolved preferences the
date/number/money helpers in `src/lib/format.ts` read, the document carries
`lang`/`dir` from the manifest's language metadata, `/meta` advertises the
supported interface languages, and a save re-renders the visible UI in place. A
plain calendar date always renders as the day it names; only instants render in
the instance zone (#114's presentation twin). Shipping this foundation before photos,
authentication screens, or the showcase prevents each new surface from creating another
pile of embedded copy.

---

## 7. MCP Tools ✅

Exposed via FastMCP alongside the REST API, sharing the same service layer. The endpoint
is `/mcp/` on the API port (streamable HTTP).

- `get_meta()` (#99) — the app version and the instance's reference currency,
  served by the same function as REST's `GET /meta` so the two cannot disagree.
  What `create_order`'s "omit currency_code" advice used to point at as a `meta`
  resource that never existed
- `list_kits(status?, grade?, series?)`
- `list_kit_series()` — the series spellings in use, most frequent first; the
  select-or-create device for a free-text column (#96) — agents check it before
  writing a spelling nobody uses
- `get_kit(id)` — embeds the kit's upgrade applications (id, upgrade name,
  quantity, date), which is where withdrawal gets its application ids (§3.6)
- `update_kit_status(id, status)` — the status-only shortcut for `update_kit`, kept
  because moving a card is the frequent case and removing a tool a client may already
  call is a visible break
- `update_kit(id, changes)` — name, grade, scale, kit_number, series, status, rating,
  build_notes, and the two build dates (#94: a transition stamps one only when null,
  so a value set here is never overwritten by a later move)
- `create_kit(kit)` (#98) — a kit acquired *without* a purchase to record: a gift, a
  trade, a carry-over from before tracking. Its description steers agents to
  `create_order` for anything bought — inventing an order to smuggle a kit in would
  be a permanent wrong entry in the purchase history (§6) — and the service derives
  scale from grade exactly as the REST route does (§3.1)
- `search_catalog(query)` — the same backing search as the UI typeahead, so an agent
  adding an order hits the same de-dup logic a human would
- `list_catalog_items(item_type, category?)` (#98) — one catalog table in full, with
  its own per-type schema. `search_catalog` takes a query and caps results per type;
  it was never a listing, and "what am I low on?" needs the whole table. The
  `category` filter is folded server-side (#127) so the counting isn't left to the
  model
- `list_catalog_categories(item_type)` (#127) — the category spellings in use on one
  table, most frequent first; the #96 device applied to the catalog's own free-text
  column. Agents check it before writing a category
- `create_catalog_tool(tool)`, `create_catalog_consumable(consumable)`,
  `create_catalog_upgrade(upgrade)`, `create_catalog_display(display_item)` (#98) —
  the create half of the same parity sweep that produced the update tools; per-table
  for the same reason (each takes the REST route's own create schema unchanged).
  First stocktakes, gifts and hand-me-downs; purchases go through `create_order`,
  and every description says to `search_catalog` first (§3.9)
- `list_retailers()`, `create_retailer(retailer)`, `update_retailer(id, changes)` —
  rating, packing quality, shipping speed, would-order-again, notes (§3.7). A retailer
  named on `create_order` is created holding nothing but a name; this is how the rest
  of the report card gets filled in. `create_retailer` and a rename *refuse* a name an
  existing shop already holds, where `create_order` *reuses* it — the same
  case-insensitive key, two deliberate answers (§3.9, #107)
- `update_catalog_tool(id, changes)`, `update_catalog_consumable(id, changes)`,
  `update_catalog_upgrade(id, changes)`, `update_catalog_display(id, changes)` — one
  per table rather than one tool dispatching on `item_type`, because each then takes
  the REST route's own PATCH schema unchanged instead of a hand-written union of all
  of them that every new column would have to be added to twice. `update_catalog_display`
  says in its description that display items carry no kit link, so an agent doesn't go
  looking for one or improvise a structured note (§3.5a)
- `create_order(retailer, date, items[], order_number?, tracking?, received?,
  received_at?, shipped_at?)` — the items array drives the same fan-out/increment
  dispatch as the REST endpoint; retailer matched by name case-insensitively,
  created if new; `received_at` backdates an arrival logged after the fact (§3.9);
  `shipped_at` (#95) needs no flag and lands spawned kits in_transit
- `list_orders(pending_only?)` — find the order a shipping or arrival email belongs to
- `get_order(id)` — one order in full, line ids and spawned kits included; the read an
  edit starts from (#97)
- `update_order(id, changes, remove_missing_lines?)` — header corrections and/or the
  line set, over the same service as `PATCH /orders/{id}` (rule 2 dispatch re-runs,
  same 409 guards, #93's `received_at` correction included). `changes.items` keeps
  REST's full-replacement semantics, but an items list that *omits* stored lines is
  refused — naming them — unless `remove_missing_lines` is passed: an agent
  reconstructing an order from a listing is the writer most likely to send a partial
  set, and an omitted line silently deletes purchase records. The gate lives in the
  service under the order's `FOR UPDATE` lock, not in the wrapper, so it cannot race
  a concurrent line addition (#97). A restated kit line may omit `kit` (#67): stated
  details are compared against the live first kit and differences applied, so an
  agent echoing details from an earlier `get_order` can revert a newer edit —
  omit them unless changing them, and the tool's docstring says so
- `mark_order_received(order_id, received_at?)` — applies stock, advances pipeline kits
  to backlog, stamped with the (optionally backdated) arrival (§3.9)
- `mark_order_shipped(order_id, shipped_at?)` — advances pre_ordered/ordered kits to
  in_transit, stamped the same way; applies no stock (#95)
- `adjust_stock(catalog_id, delta, reason?)`
- `apply_upgrade(upgrade_id, kit_id, quantity)`
- `withdraw_upgrade_application(application_id, restore_stock)` — the undo of
  apply_upgrade; the required `restore_stock` states whether the part physically
  survived (§3.6), and the docstring tells an agent to ask rather than guess.
  Application ids come from `get_kit`, which embeds a kit's applications

Status arguments are normalised for agents ("In Transit" → `in_transit`), including
aliases for the retired `in_hand` vocabulary, because an agent's idea of the status
names will always lag the schema.

The edit tools take a **patch object** rather than one optional argument per field.
An MCP tool is a function signature, so the flat spelling cannot distinguish "leave
the notes alone" from "erase the notes" — both arrive as `None` — and a partial edit
would silently clear everything it didn't mention. Taking the same `*Update` schema
the REST PATCH takes keeps `model_fields_set` intact, so absent and null mean on this
surface exactly what they mean on the other one.

This is what makes "grab the latest order confirmation from my email and add those" work
without an email-parsing feature existing anywhere in the app. It's one agent session
with this MCP server and a mail connector both active, reading one and writing the
other. Building that as a feature would mean owning IMAP credentials, per-retailer
parsers, and a support burden — for something the agent layer already does better.

Hobby-specific conventions ride the same separation: `skills/` ships packaged agent
skills (the first covers Gunpla) that teach an agent the naming and classification
conventions plamotrack deliberately doesn't encode. The app stays generic (§9.1);
the genre knowledge lives with the agent that applies it.

### 7.1 Protocol modernisation 🔨 **Planned (M6.1)**

The current server uses the handshake/session-era MCP implementation. The `2026-07-28`
revision changes the transport substantially: a stateless core, discovery in place of a
required initialize handshake, standard routing headers, cache hints, and hardened OAuth
behaviour. Plamotrack's tool handlers are already application-stateless — each call gets
its durable state from Postgres — so the product architecture does not need to change.

M6.1 adds the modern protocol only through an SDK/framework release that serves modern
and legacy clients from the same endpoint. Completion means conformance coverage plus a
small client matrix, not merely raising a dependency version. Tasks, multi-round-trip
requests, subscriptions, and MCP Apps are not roadmap items: the current short,
transactional tools do not need them.

---

## 8. Docker Compose Layout ✅ (Milestone 5, 10/08/2026)

```yaml
services:
  web:      # nginx: static Vite build; /api and /mcp proxied to api
  api:      # FastAPI + FastMCP, one process, one port (REST at /, MCP at /mcp)
  migrate:  # alembic upgrade head, then exits — a gate, not a service
  db:       # postgres:16
  # photo storage: local named volume by default;
  # optional S3-compatible (MinIO or external) via env var, not required for v1
```

Only `web` is published; the API and database stay on the Compose network, so an
instance has one door and it binds to `127.0.0.1` — a convenient install is not
accidentally an internet deployment. `docker compose up -d --build --wait` is the
supported empty-instance path, and it exits non-zero if anything fails to come up.

Images build from source in-repo. Publishing to a registry belongs with the rest of
release automation in M9; until then an install needs no registry, no tags, and no
multi-architecture story — the machine doing the installing builds for itself.

**Migrations are their own container**, gating the API through
`service_completed_successfully`. Running them from the API's entrypoint would turn a
failed migration into a crash-looping API; this way it's a stopped deploy with the
error in `docker compose logs migrate`, and the API never starts against a database it
doesn't match.

**The API's healthcheck is `/readyz`, which touches the database.** `/healthz` stays a
pure liveness check. If the healthcheck didn't hit Postgres, Compose would report a
healthy stack that cannot serve a single request.

Two nginx details are load-bearing rather than incidental, both found by testing
rather than reasoning:

- **`proxy_buffering off` on the MCP routes.** MCP is streamable HTTP; with buffering
  on, nginx holds the response and the client waits for bytes the proxy already has.
  It presents as a hang, not an error, which makes it expensive to diagnose later.
- **The upstream is resolved through a variable, with `resolver 127.0.0.11`.** A
  literal hostname in `proxy_pass` is resolved once at startup and cached for the life
  of the process, so recreating the api container onto a new address — exactly what
  upgrading does — 502s every request until `web` is restarted too. Verified by
  forcing the api container onto a different address with `web` left running: 502
  before, 200 after.

`/mcp` without the trailing slash is served rather than redirected. A 307 in answer to
a POST is a real hazard, not a cosmetic one, because not every client re-sends the body.

M5 does **not** make the stack internet-safe. M6 supplies a tested VPS deployment path
with authentication and a reference TLS/reverse-proxy configuration (for example Caddy),
while leaving operators free to use Traefik, nginx, or a tunnel. The base Compose file
does not bundle a certificate authority or a heavyweight identity platform.

---

## 9. Open Decisions 💭

1. **§9.1 — Generic "hobby build tracker" vs Gunpla-specific.** Still under consideration. The
   schema hedges reasonably well either way — `grade` and `category` are free text or
   text-enum rather than hardcoded logic, so the harder call (configurable taxonomy vs
   fixed enum) can be deferred without a schema rewrite. Needs deciding before a
   taxonomy/config UI is built, not before the core schema. This is also why enums are
   text + CHECK constraint rather than native Postgres enums: changing the taxonomy
   stays a data migration.

   **Evidence, not a decision (#126, 21/08/2026).** `display_items` arrived as a whole
   new category without forcing the call: free-text `category` plus a nullable `scale`
   is hobby-neutral by construction, and model-railway scenery, 1/35 armour and
   wargaming terrain all land in it unmodified — the Tomytec Diorama Com line that
   prompted it is sold into the military-model and railway markets, not the Gunpla one.
   Taken as support for "stay generic until something forces specificity" rather than
   as settling the question. `category` was kept free text over a fixed text enum for
   the same reason: an enum would be definitive, but acrylic cases, lighting kits and
   turntables would each then be a migration and a release.

   **More evidence, same direction (skills, 24/08/2026).** The genre knowledge found a
   home that isn't the schema at all: `skills/` ships packaged agent skills — the
   first covers Gunpla naming, grade buckets, Bandai kit numbers, Gundam Markers —
   that an agent loads alongside the MCP connection. The conventions live with the
   layer that applies them, each hobby can carry its own, and the application stays
   generic without anyone losing the specificity. If the taxonomy question is ever
   forced, this is the pressure valve that has to fail first.
2. **§9.2 — Photo storage backend default.** A local volume is the safe v1 default, with
   S3/MinIO as an opt-in env var. Worth confirming before the upload handler is written,
   because it also decides the backup story — a Docker volume is covered by whatever
   already backs up the host, whereas an external object store is a second thing to
   remember to back up.
3. ~~**§9.3 — License**~~ — **Settled: MIT.**
4. **§9.4 — Multi-user / multi-collection.** Out of scope for v1, but worth a one-line decision
   on whether the schema should avoid single-owner assumptions now, since retrofitting
   multi-tenancy later is a real migration and not a toggle.

---

## 10. Repository & Release Strategy

**Revised 06/08/2026.** The original plan held the repo private until milestones 1–6
were finished. It's going public earlier than that — at Milestone 4.5, as a **public
alpha**, with the remaining milestones built in the open.

What changed the calculus: Milestone 4.5 (import/export) removed the thing that made
early exposure irresponsible. Before it, data went in through the UI and MCP and had no
way out — a one-way door, which is not something to invite anyone else through. With a
full CSV archive in and out, an early adopter can back up, migrate, or walk away, and
the remaining gaps become things to disclose rather than things to hide.

**What "alpha" honestly means here — the things to disclose:**

- **Authentication without transport security** (M6, in progress). The owner login
  gates the browser and a personal access token gates every REST script and MCP
  client (§5.9 items 3–4), but there is no tested TLS path yet: on plain HTTP a device
  on the network path can read the session cookie or a token in transit. Run it on a
  network you trust — localhost, a VPN, a LAN you control. Do not put it on the public
  internet until the reference TLS deployment (§5.9 item 9) ships.
- **The packaged stack binds to loopback by default** (M5). `docker compose up -d`
  brings up the whole thing, but that default is a convenience, not a security
  boundary — moving the published port does not make a plain-HTTP instance safe to
  expose.
- **Only `en-AU` ships today** (M5.1). The interface, diagnostics, direction metadata,
  and locale-aware presentation are ready for reviewed catalogues, but no non-English
  catalogue has been contributed. Amounts still use plamotrack's ISO 4217 exponent,
  independent of locale, so formatting never changes what stored minor units mean.
- **No photos** (M7) and **no public showcase page** (M8).
- **The schema will still move.** Migrations are provided and tested in both directions,
  but breaking changes are possible while it's alpha. Export an archive before upgrading
  — that is exactly what §12 is for.

Unchanged from the original plan:

- `.gitignore` and `.env.example` in place from commit #1, so the private→public flip
  carries the full commit history with no secrets to scrub out of it
- License: MIT

### 10.1 Naming & README tone

- **Repo name:** `plamotrack` — chosen over a generic "gunpla-tracker" name for
  community authenticity ("plamo" is the hobbyist term) and to hedge the still-open
  generic-vs-Gunpla-specific question (§9.1)
- **GitHub "About" description** (functional, carries search/SEO weight): *"Self-hosted
  Gunpla/plamo collection & build tracker — Docker Compose, Kanban build pipeline, and
  an MCP server so you can manage it via Claude or ChatGPT."*
- **README tagline** (self-deprecating, hobby-community tone — it lands as a joke once
  someone has already found the repo, and doesn't need to do discovery work): *"Track
  every kit, tool, and terrible financial decision from pre-order to panel-lined
  masterpiece."*
- General principle for README and docs: functional copy where it needs to be found
  (About field, package descriptions, docs headers), joke copy where it already has an
  audience (README body, contribution guide intro). Don't make the humour carry search
  weight.

---

## 11. Milestones

1. ✅ Schema + Postgres migrations + FastAPI CRUD (no auth, no UI) — prove the data model
2. ✅ MCP tools wired to the same service layer
3. ✅ Frontend: table views + basic forms *(grew into the full order lifecycle and CRUD
   along the way — §3.9)*
4. ✅ Kanban board (drag-and-drop)
5. ✅ **4.5** Import/export — CSV archive + manifest, preview, templates (§12), inserted
   ahead of the rest to make a public alpha honest (§10)
6. → **Public alpha here.** Everything below happens in the open.
7. ✅ **M5 — Installability:** full local Docker Compose stack, controlled migrations,
   safe loopback defaults, health checks, and backup/upgrade documentation (§8,
   `docs/operations.md`). This improves adoption without claiming the unauthenticated
   stack is internet-safe. The configurable reference currency was pulled forward from
   M5.1 and shipped here — it is a schema migration, not translation work, and its
   compatibility cost grows with every archive exported under the old column name
8. ✅ **M5.1 — Instance settings & internationalisation foundation:** singleton
   instance-wide preferences, `en-AU` source catalogue and fallback, reviewed language
   contributions, locale-aware presentation, a Settings page that absorbs Data, and
   structured REST/import diagnostics. No non-English translation is required
9. 🔨 **M6 — Secure remote access:** single-owner browser authentication, scoped
   REST/MCP bearer tokens, OAuth-compatible MCP access, and a tested TLS/VPS deployment
   path. This is the gate for deliberately exposing an instance. The threat model and
   route authorization matrix are in §5 (02/09/2026, #29); the implementation split
   is §5.9
10. 🔨 **M6.1 — MCP modernisation:** dual-era compatibility for the existing protocol
    generation and `2026-07-28`, with conformance and real-client coverage
11. 🔨 **M6.5 — UI redesign:** move off the stock Tailwind look; direction still
    under exploration, deliberately undecided (21/08/2026). Sequenced after M5.1 so
    the Settings surface isn't styled twice, and before M7/M8 so the gallery and
    the showcase are built in the new look once. Board interaction gaps deferred
    from the #120 consolidation (#122) land here
12. 🔨 **M7 — Photos:** local-volume upload + gallery, archive integration, and the
    §9.2 storage decision closed before implementation
13. 🔨 **M8 — Public showcase:** genuinely separate anonymous read routes and a
    shareable frontend, built only after the admin and MCP surfaces are protected
14. 🔨 **M9 — Open-source operations:** contribution guide, release automation,
    compatibility/support matrix, and deployment documentation polish

**Between M5 and M5.1 — the hardening passes (complete).** An external review of
v0.2.3-alpha (11/08/2026) was triaged into a run of small GitHub milestones named
`M5 hardening — v0.2.N-alpha`, each its own release, all inside M5 so the numbering
above stands, and all of them have shipped. What they were, in order: **v0.2.4** —
a write changes only what it was asked to change; **v0.2.5** — the importer reads
what it is given (apply bound to the previewed plan, numeric grammar, archive
integrity, budgets); **v0.2.6** — the importer *stable and usable*, defined as "no
bug corrupts data silently" rather than "the importer is finished"; **v0.2.7** — the
workflow release (MCP write parity, board-move ordering, keyboard-operable dialogs,
backdatable receipt and ship dates, build dates and series, retailer matching, the
#120 status-editing consolidation); **v0.2.8** — everything that was neither a
corruption path nor coupled to the workflow work. **No v0.2.6 tag exists and none
will:** most of the 0.2.7 work merged first, so a separate v0.2.6 release would have
been fiction, and the two milestones shipped together as the single **v0.2.7-alpha**
(owner's call, 21/08/2026). M5.1 followed them and is itself complete; the open work
now starts at M6. This paragraph is history — the live issue list is on GitHub.

---

## 12. Import & Export ✅ (Milestone 4.5, 06/08/2026)

Added ahead of milestones 5–9 because the app was a one-way door: data went in via the
UI and MCP and could not come back out. That's a hard blocker for handing it to anyone
else — nobody should trust a collection to a self-hosted tool they can't back up,
migrate, or seed from the spreadsheet they already keep.

### 12.1 Format

CSV, one file per table, zipped with a `manifest.json` carrying `format`,
`export_version`, `schema_version` (the live Alembic revision), `app_version`,
`exported_at`, and per-table row counts. An archive from a **newer** `export_version` is
refused rather than mangled; a `schema_version` mismatch is a warning.

The CSVs are deliberately human-readable as well as machine-restorable: every uuid FK
carries a readable twin column (`retailer_name`, `catalog_name`), and every integer
minor-unit money column a major-unit twin (`unit_price` beside `unit_price_minor`). The
canonical column always wins when both are present. This costs a few columns and buys a
file that opens in any spreadsheet and makes sense — which is most of what "your data is
yours" means in practice.

An archive is read in **one transaction under `REPEATABLE READ READ ONLY`**
(`services/read_snapshot.py`), so every CSV in it comes from the same instant. Under
the default isolation each table is its own snapshot, and a write landing between two
of them produced an archive whose files contradicted each other — a kit whose order
line no CSV in the zip contained (#48). The database was never damaged; the artifact
was, and the artifact is what gets kept as a backup and restored from. A snapshot is
not a lock: row-level writes and an export never delay each other in either direction;
only a `replace_all` import's `TRUNCATE` queues behind an in-flight export, and the
reverse. *(Added 16/08/2026; rule 7.2 in `AGENTS.md`.)*

### 12.2 The spec registry

`services/portability/spec.py` declares each table once — columns, parsers, roles
(`DATA` / `ID` / `REF` / `ALT_REF` / `ALT_MONEY`), natural key, FK dependency order.
Export, import, and blank-template generation all read it, so they cannot drift; a test
asserts template headers are byte-identical to export headers. Adding a model column is
one `col(...)` line.

M5.1 extends the full archive with the singleton instance-settings record through this
same registry. Restoring a setting is an explicit previewed change; starter sheets and
partial table imports never silently replace instance defaults.

`virtual=True` marks CSV columns with no backing model attribute — the `order_items`
`kit_*` columns mirror the kits a line spawned (kit details live on the kits, not the
line). They're exported for legibility and consumed on import only when the upload
doesn't supply the kits itself.

### 12.3 Plan, then apply

`POST /import/preview` returns an `ImportPlan`: per-row action (create / update /
unchanged / skip / error), what it matched and how, field-level diffs, warnings, and
derived effects. Row problems, plan warnings, blocking errors and the stock note are
`{code, params, detail}` diagnostics (#26, §6.1) — stable codes for clients and the
catalogue, English `detail` as the fallback. `POST /import/apply` **re-parses and
re-plans**, then compares a `plan_hash` against the one previewed — a mismatch is a
409.

The hash is **required**: applying without one is a 422, not an unchecked apply. It
covers the resolved value set of every row, the spawn, removal and advance
descriptors and the identity of what a `replace_all` would destroy — not merely the
shape of the plan. Two files that plan the same *actions* at the same *positions* are
otherwise indistinguishable, so a hash taken against one would authorise the other.
The advance descriptors (#119) bind the derived side of a ship/receive flip the same
way `_Spawn` binds created kits: each pre-existing kit the flip moves is resolved at
plan time — kit id, before-status, landing status, stamp — shown in the preview
(a derived count plus per-order messages), and consumed verbatim by the apply. A kit
progressed between preview and apply changes the re-plan's descriptors and the stale
hash 409s, instead of the apply silently moving a different set of kits than the
preview implied.

Two things are excluded by necessity rather than oversight. Uuids minted during
planning — every id-less create, every catalog or retailer stub conjured from a
reference — are freshly random per run and are replaced by a positional token, so a
foreign key still records *which planned row* it resolves to. Clock-derived column
defaults are applied at write time and never reach a planned row at all. Hash either
directly and preview and apply can never agree on a sheet that supplies no ids.

Nothing is cached server-side. The plan can't go stale, it survives a container restart,
and the recheck closes the window between the *user's* look and the apply. It is not
what makes the apply safe against a concurrent writer — apply re-plans and writes under
the collection write gate (§3.9), so nothing can move between its own re-plan and its
writes; the hash catches what changed while a human was reading the preview. The
frontend just holds the `File` and posts it twice.

### 12.4 Not duplicating things

Ids are preserved on create, so restoring into an empty instance reproduces every
internal reference exactly. When a row *matches* an existing record under a different
uuid, that mapping goes into an id-remap and all later references are rewritten through
it — an archive lands in an instance that already knows a retailer without creating a
second copy of it.

Rows without an id fall back to natural keys: case-insensitive name for retailers and
every catalog table — equality after trimming and case-folding, never a pattern
match; `get_or_create_retailer` applies the same rule (#49 — a `%` in a shop's name is
a character, not a wildcard), and since #107 so does every create and rename of a
retailer or catalog item, which refuses a second row under a key that is already
taken (`services/names.py`, one predicate). The §3.9 typeahead is a different thing:
a substring *find*, already escaped, that offers rows for the human to pick by id —
it does not decide identity; `(retailer, order_number)` for orders, falling back
to `(retailer, order_date, line fingerprint)` when there's no number; line fingerprint
within the parent for order lines. Ambiguous multi-matches become an error row asking
for an explicit id rather than a guess — a state that, after #107, only rows written
before it or an archive that carries the pair itself can produce.

**Kits are excluded from natural-key matching by design.** A kit row is one *physical*
kit (§3.1), so duplicates are legitimate; matching on name would silently merge real
purchases. The preview flags look-alikes instead and lets the human decide. In
replace-all mode the flag is suppressed — everything is being deleted first, so it would
be misleading.

### 12.5 Two invariants

- **Stock is stated, never derived.** `quantity_on_hand` comes only from the catalog
  CSVs. Importing orders — even received ones — never adjusts it. Deriving it from
  received orders would double stock on every re-import, which is precisely the bug the
  §3.9 lifecycle revision already fixed once.
- **Kits are hybrid-dispatched.** An order line spawns kits only for the shortfall
  nothing else supplies: `quantity − (kits.csv rows for this line) − (kits already on a
  matched line)`. An archive round-trips with zero spawns; a bare orders sheet builds the
  collection. Same diff arithmetic as `_update_line` — and, since #44, in both
  directions: a surplus gives kits up, under `_update_line`'s own progression guard.
  The arithmetic runs only for a line whose quantity the upload *writes* (a create,
  or an update that changes it): a restated line — every line of a full archive —
  describes and never instructs, so a kit move against one is refused until the
  quantity is changed alongside it, and a re-imported archive is a no-op whatever
  the collection holds. (An earlier reading, "any stated quantity", let an
  unchanged archive row turn a refused move into a delete.)

### 12.5a The importer is the third writer (#44, 16/08/2026)

`apply_import` writes model rows by direct `setattr`, so for a while every column was
freely mutable and an import could do things REST and MCP refuse. Rule 1 says the
writers share a service layer; it was written when there were two of them.

The fix is **not** to route import through `services/orders.py` — `receive_order`
applies stock, which the invariant above forbids, and `_update_line` fights the hybrid
dispatch. What is shared is the *predicates*: `kit_progressed`, `PROGRESSED_STATUSES`
and `IMMUTABLE_LINE_COLUMNS` live in `services/orders.py`, and
`services/portability/invariants.py` reads them to refuse a plan at preview time. One
parametrised matrix drives both writers over the same edits and asserts they agree.

**Receipt is the one place the ambiguity was deleted rather than represented.**
`received_at is not None` is the proxy for "stock was applied" in four separate stock
mutators. An import that flipped the flag without restating stock created a state none
of them could read: the real receive 409'd, a delete became impossible, and an edit
moved stock by the wrong amount — while clearing the flag re-armed the increment and
double-counted a delivery. Telling "received" from "received, stock outstanding" apart
needs a column, and that column has no correct backfill, no answer in the CSV (rule 9),
and four call sites to teach. So an import may not move `received_at` into or out of
null on an order holding a catalog line, and — the same state reached from the
line's side (#87) — a new catalog line may not join an order whose stored
`received_at` is already set: there is no transition to refuse there, so the line's
create is what gets refused, with the app edit (which applies stock) as the named
remedy. Kit-only orders move freely in both
directions (that is the starter-sheet path), and a *create* is untouched — a full
archive carries the received order and its post-receipt `quantity_on_hand` together,
which is how the invariant survives a restore today (the line-join guard likewise
skips lines whose parent order the same upload creates, and skips the stored lookup
entirely under `replace_all`, where the database it would consult is about to go).

The two arrivals an import *does* perform borrow the order's receipt instant, exactly
as the live writers stamp it (#93): a kit-only receive-by-import stamps the kits it
advances with the value the sheet states, and a kit the apply spawns into a received
order carries the same instant — each resolved at plan time (the `_Advance`
descriptors of #119 for pre-existing kits; `_order_receipt`, the post-write value,
on the spawn descriptor) and bound by the plan hash, so a
receipt this same upload sets is honoured, backdated included, and a correction
landing between preview and apply stales the hash instead of stamping a value the
operator never saw. The value is stated, not invented, and neither site fires on a
re-import. Corrections deliberately do not cascade a restamp the way REST's do
(#116). And the instant has to be *possible*: a `received_at` an upload writes —
arrival or correction — onto a future calendar date is refused at preview with the
same own-offset judgment every other writer applies (`receipt_is_future`, #93).
The refusal reads the change, not the cell: a stored legacy future value restates
as a no-op, and a create is a restore (the create rule above, applied to the date),
so an archive carrying one stays importable — stated policy, with the accepted cost
that a hand-written CSV can still create a future order.

`shipped_at` (#95) rides the same rails: the ship arrival advances
pre_ordered/ordered kits to in_transit stamped with the sheet's instant, freely on
every order because shipping carries no stock semantics; clearing it is refused
(un-shipping exists nowhere); the future is refused through the same shared
predicate under the same change-not-cell reading; and the spawn descriptor carries
the post-write ship instant, hash-bound beside the receipt.

A blank cell in an *included* column means null; a column omitted from the file entirely
is left alone. That's needed for archive fidelity, but it makes partial sheets dangerous
— so the starter sheet emits only the columns it actually knows about. Otherwise
importing a kit list would wipe the report card off a rated retailer, which it did once
before a regression test started guarding it.

### 12.6 What this milestone does and doesn't make safe

This is the milestone that makes a public alpha reasonable: the data can now leave.

It does **not** make an exposed instance safe, and the two shouldn't be conflated. The
code going public is not the same as an instance going on the internet. M6 (secure
remote access and auth on the write path) is still the gate for the latter — see §10.

### 12.7 Deliberately not done

No MCP tools for import/export. The operations are file-upload-shaped and fit tool calls
badly, and an agent that can silently replace an entire collection is not a feature.
The services stay callable if that ever changes. The REST/MCP parity rule is about logic
living in the service layer, which it does.

### 12.8 Formula-looking cells export verbatim (#53, 25/08/2026)

CSV exports write cell values byte-faithfully, including text beginning `=`, `+`, `-`
or `@` that a spreadsheet will read as a formula. Decided and kept that way. Escaping
on export — the usual CSV-injection prescription of a leading apostrophe or tab —
breaks the round-trip contract §12.1 rests on: the escape comes back through the
importer as part of the value, a kit named `=RX-78` stops being one, and re-importing
your own archive stops being a no-op. Fidelity is the property the format exists to
provide, and it protects the common case: this is a single-owner application exporting
the owner's own data, so there is no untrusted author in the normal path. The risk
case — opening an archive somebody *else* sent you — is the ordinary caution about
files from strangers, not a property of this format, and is documented where a person
meets it: the archive's bundled `README.txt` and `docs/import-export.md`. An
escape-and-strip pair (fidelity dependent on both halves staying in sync forever) and
a second "spreadsheet-safe" export variant (two formats, guaranteed drift) were both
considered and declined.
