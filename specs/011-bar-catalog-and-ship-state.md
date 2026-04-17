# 011 — Bar Catalog & Ship State

## Summary

Introduce two persistent entities the Schaluppe crew rely on between trips:

1. A **Bar Catalog** of drinks with admin-managed CRUD. Each item carries its price data (Einkaufspreis, Unkostenbeitrag) plus stock counts (`expected_amount` baseline, `current_amount` live).
2. A **Ship State** singleton holding the current state of the vessel — fuel, water, CO₂, battery, toilets, persennig, open notes, open todos.

Both entities are **consumed and mutated by the Fahrbericht submission flow** (spec 012). This spec defines the data model, admin UI, and the idempotent `apply_consumption` contract that spec 012 calls into.

## Problem

1. The HTML prototype (`~/Downloads/schaluppe-fahrbericht.html`) hardcodes 23 drinks with their EK/KB prices. Real life: prices change, items come and go, non-technical crew need to edit. Requiring a deploy is not viable.
2. There is no place in the app today to see **how much of each drink is currently on board**. The only way to know is to go to the boat and count.
3. The ship's technical state (fuel level, when the water tank was filled, CO₂ level, damage notes, open maintenance todos) lives only on paper or in WhatsApp threads. No single source of truth.
4. Without persisted stock + ship state, the Fahrbericht has nothing to mutate — every tour would be a standalone number with no cumulative meaning.

## Scope

This spec is prerequisite to spec 012. It introduces:

- The `BarItem` model, CRUD API, admin UI, and a seed of the 23 HTML drinks.
- The `ShipState` singleton model, GET/PATCH API, and admin dashboard UI.
- The `apply_consumption(tour_id, kiosk_tally, crew_tally)` service contract used by spec 012.

Out of scope:

- The Fahrbericht itself (spec 012).
- PDF/email of closing reports (spec 013).
- Opening/closing delta-based loss analytics (deferred — captured in Offene Fragen).
- Reorder suggestions from consumption history (deferred).

## Data Model

### BarItem

DynamoDB keys: `pk = BAR#{bar_item_id}`, `sk = META`.

Bar items support **two inventory units**: a serving unit (Becher, Flasche, Glas, Shot — what guests buy and the Fahrbericht counts) and an optional packaging unit (Kiste / Kasten / Karton — how the bar is restocked). Stock is always stored in **serving units** so consumption math is simple; the packaging unit is a convenience layer for display and restock entry.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | Bar item id |
| `name` | str | Display name (e.g. "Dithmarscher vom Faß") |
| `category` | enum | `BIER_FASS`, `BIER_FLASCHE`, `ALKOHOLFREI`, `SEKT_WEIN`, `SOFTES`, `HARTES`, `SHOTS` |
| `serving_unit` | str | Free text (e.g. "Becher 0,4l", "Glas ~0,15l", "Shot 2cl") — what's counted in the Fahrbericht tally. Synonym of the old `unit` field |
| `package_unit` | str \| None | Free text (e.g. "Kiste", "Karton", "Faß 50L") or None if the item is sold/tracked only as singles |
| `servings_per_package` | int \| None | Number of `serving_unit` in one `package_unit`. Required when `package_unit` is set. Example: Estrella Damm `serving_unit = "Flasche 0,33l"`, `package_unit = "Kiste"`, `servings_per_package = 24`. Fass items use `package_unit = "Faß 50L"`, `servings_per_package = 125` (approx.) |
| `ek` | Decimal | Einkaufspreis **per serving unit** in €, net, no deposit |
| `kb` | Decimal | Unkostenbeitrag (kiosk price) **per serving unit** in € |
| `note` | str | Free text (e.g. "bio", "Moskovskaya") |
| `expected_amount` | int | Baseline stock in **serving units**, set by admin. Used for low-stock warning |
| `current_amount` | int | Live stock in **serving units**. Decremented by Fahrbericht submissions, adjusted manually in the admin UI |
| `active` | bool | When false, the item is hidden from Fahrbericht counter lists but preserved for historical reports |
| `sort_order` | int | For manual ordering inside a category (defaults to creation time) |
| `created_at` | datetime | UTC |
| `updated_at` | datetime | UTC |

**Display helpers** (computed, not stored):
- `current_packages = current_amount // servings_per_package`
- `current_singles = current_amount % servings_per_package`
- Rendered as "5 Kisten + 3 Flaschen · 123 gesamt" when `package_unit` is set, or simply "123 Becher" otherwise.

Seeded at deploy time from the 23 HTML items (see T1.4 in tasks). Idempotent seed: insert only if no BarItem with the same slug already exists.

### ShipState (singleton)

DynamoDB keys: `pk = SHIP#schaluppe`, `sk = STATE`.

| Field | Type | Notes |
|-------|------|-------|
| `tank1_pct` | int 0–100 \| None | Front tank fill in % |
| `tank2_pct` | int 0–100 \| None | Rear tank fill in % |
| `kanister_aboard` | int \| None | Full canisters on board |
| `kanister_garage` | int \| None | Full canisters in the garage |
| `water_filled_at` | date \| None | Last time the water tank was filled |
| `co2_level` | enum \| None | `VOLL`, `DREIVIERTEL`, `HALB`, `VIERTEL`, `LEER` |
| `battery_pct` | int 0–100 \| None | Main battery level |
| `klo1_level` | enum \| None | `LEER`, `VIERTEL`, `HALB`, `DREIVIERTEL`, `VOLL` |
| `klo2_level` | enum \| None | Same |
| `persennig_status` | enum \| None | `VOLLSTAENDIG`, `TEILWEISE`, `OFFEN` |
| `general_notes` | list[Note] | Append-only. Each: `{id, text, author, created_at}` |
| `open_todos` | list[Todo] | Each: `{id, text, author, created_at, done: bool, done_at, done_by}` |
| `last_updated_from_tour_id` | UUID \| None | Reference to the Tour whose Fahrbericht last overwrote the state |
| `updated_at` | datetime | UTC |

All sensor-style fields are nullable — a new deployment starts empty until the first Fahrbericht fills them in.

`general_notes` and `open_todos` **accumulate** across Fahrberichte. A submitted Fahrbericht appends its new notes/todos rather than overwriting — this way the admin can see a running log of open items regardless of which tour surfaced them. Notes and todos are not deleted automatically on submission; admins mark todos done in the Ship admin UI.

### Categories

The seven categories are persisted as string enums. Display labels:

| Enum | German label |
|------|-------------|
| `BIER_FASS` | Bier vom Faß |
| `BIER_FLASCHE` | Flaschenbier |
| `ALKOHOLFREI` | Alkoholfrei |
| `SEKT_WEIN` | Sekt & Wein |
| `SOFTES` | Softes |
| `HARTES` | Hartes |
| `SHOTS` | Shots |

Icons from `lucide-vue-next`: `Beer`, `Wine`, `GlassWater`, `CupSoda`, `Martini` (best-effort — use whichever exist).

## Service Contract: `apply_consumption` / `apply_consumption_delta`

Called by spec 012 on Fahrbericht submission. Lives in `bar_service.py`. Two methods — one for first-time application, one for re-submissions.

```python
async def apply_consumption(
    tour_id: UUID,
    version: int,                   # Fahrbericht version this call belongs to
    kiosk_tally: dict[UUID, int],
    crew_tally: dict[UUID, int],
) -> ConsumptionResult: ...

async def apply_consumption_delta(
    tour_id: UUID,
    version: int,
    previous: dict[UUID, int],      # previously applied kiosk+crew combined per bar_item_id
    next: dict[UUID, int],          # new kiosk+crew combined
) -> ConsumptionResult: ...
```

Contract:

1. **Atomic per item**: each BarItem update uses `ADD current_amount :delta`. In `apply_consumption` the delta is `-(kiosk + crew)`; in `apply_consumption_delta` it is `-(next - previous)` — positive when the crew corrected an over-count, negative otherwise.
2. **Versioned idempotency**: the caller passes `(tour_id, version)`. The service writes a sidecar ledger row (`pk = BAR#{bar_item_id}`, `sk = CONSUMPTION#{tour_id}#v{version}`) with a conditional write. If the row already exists, the consumption is **not re-applied** — the method returns the previous `ConsumptionResult` unchanged. This makes retries and the `reapply-side-effects` endpoint safe. Different versions write different rows — a re-submit at `v=2` does not collide with the `v=1` row from the first submit.
3. **Negative current_amount is allowed** — it surfaces as a warning (see below) but does not fail the consumption. The rationale: the crew may have restocked mid-tour without updating the catalog, so forcing a clamp would mask real usage data.
4. **Unknown bar_item_id** in either tally → raises `ValueError` before any write; the caller is expected to have validated against the catalog.
5. **Re-submission semantics**: spec 012's re-submit pipeline calls `apply_consumption_delta`. The service does **not** need to read prior ledger rows to compute the delta — spec 012 passes `previous` directly from the Fahrbericht's `applied_*_tally` fields. The v+1 ledger row stores both `delta` (what was applied this time) and the effective `previous` / `next` for audit.

`ConsumptionResult` carries:

- `updated_items: list[BarItemStockChange]` — for each affected item: id, name, delta, new_current, `went_negative: bool`.
- `warnings: list[str]` — human-readable warnings (e.g. "Estrella Damm wurde negativ (−3). Stock in der Bar-Verwaltung prüfen.").

## Service Contract: `apply_ship_status` / `apply_ship_status_versioned`

Called by spec 012 on Fahrbericht submission.

```python
async def apply_ship_status(
    tour_id: UUID,
    version: int,
    snapshot: ShipStatusSnapshot,
    new_notes: list[NoteInput],
    new_todos: list[TodoInput],
) -> ShipState: ...

async def apply_ship_status_versioned(
    tour_id: UUID,
    version: int,
    snapshot: ShipStatusSnapshot,
    previously_applied_note_ids: list[UUID],
    previously_applied_todo_ids: list[UUID],
    new_notes: list[NoteInput],
    new_todos: list[TodoInput],
) -> ShipState: ...
```

- Both: overwrite the scalar fields (tanks, water date, CO₂, battery, klos, persennig) from the snapshot.
- `apply_ship_status` (first submit): append `new_notes` and `new_todos` to the respective lists (each gets a fresh id + author + timestamp). Return the generated ids in the `ShipState` response so the caller (spec 012) can persist them as `applied_ship_notes_ids` / `applied_ship_todos_ids`.
- `apply_ship_status_versioned` (re-submits): treat the union of `previously_applied_*_ids` as already-present; append only notes/todos that aren't in those lists; remove previously-applied entries that are no longer part of the reopened draft (the crew explicitly dropped them on edit). Return the new id lists so the caller can update its `applied_*_ids` fields.
- Sets `last_updated_from_tour_id = tour_id`, `updated_at = now`.
- Idempotent: conditional write with `sk = STATE#{tour_id}#v{version}` as a seen-marker to skip on retry.

## API

All admin routes; same Auth0 guard as specs 004–010.

### Bar items

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/admin/bar-items` | List. Query: `active`, `category` |
| `POST` | `/api/admin/bar-items` | Create |
| `GET`  | `/api/admin/bar-items/{id}` | Fetch |
| `PATCH`| `/api/admin/bar-items/{id}` | Partial update (prices, amounts, active flag) |
| `DELETE`| `/api/admin/bar-items/{id}` | Hard delete — allowed only if no consumption ledger row exists; otherwise returns 409 and the UI should `PATCH active=false` instead |
| `POST` | `/api/admin/bar-items/{id}/adjust-stock` | Manual adjustment. Body: `{ "delta_packages": int, "delta_servings": int, "reason": str }`. The server resolves `delta = delta_packages * servings_per_package + delta_servings` and writes a ledger row (`sk = ADJUSTMENT#{timestamp}`) that records both the per-unit delta and the human-readable breakdown |
| `POST` | `/api/admin/bar-items/seed` | Idempotent seed from the packaged JSON of the 23 HTML drinks (used on first deploy and by the seed script) |

### Ship state

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/admin/ship/state` | Fetch current state |
| `PATCH`| `/api/admin/ship/state` | Admin correction of scalar fields |
| `POST` | `/api/admin/ship/notes` | Append a note. Body: `{ "text": str }`; author is the authenticated admin |
| `DELETE` | `/api/admin/ship/notes/{note_id}` | Remove an obsolete note |
| `POST` | `/api/admin/ship/todos` | Append a todo |
| `PATCH`| `/api/admin/ship/todos/{todo_id}` | Toggle done / edit text |
| `DELETE`| `/api/admin/ship/todos/{todo_id}` | Remove |

## UI

### Routes

- `/admin/bar` — catalog list with inline stock edits
- `/admin/bar/new` — create form
- `/admin/bar/{id}` — edit form
- `/admin/ship` — ship state dashboard

### Bar catalog page (`/admin/bar`)

- PageHeader "Bar-Katalog" with count badge (`active` count)
- Filter tabs: "Alle", "Aktiv", "Inaktiv"
- Grouped by category (section header per category with count)
- Each row shows: name, serving unit, EK, KB, and the two-line stock display — `current_amount / expected_amount` servings with the "X Kisten + Y Einzel" breakdown underneath (when `package_unit` is set). Low-stock badge when `current_amount < 0.25 * expected_amount` (locked default)
- Tap a row → edit page; long-press / trailing menu → "Bestand anpassen" → opens ActionSheet for `adjust-stock` with two number fields side-by-side: "Kisten (±)" and "Einzel (±)" (the Kisten field is hidden when the item has no `package_unit`)
- FAB "Neues Getränk" → create form
- A subtle header button "Kiosk-Stand aktualisieren" → bulk adjust mode (toggles inline `+/−` counters, single save)

The counter UI inside bulk adjust mode mirrors the Fahrbericht tally rows from spec 012 for visual consistency — same 32px circular buttons from the HTML.

### Bar item create / edit form

Fields in a single form:

- Name, Category (select)
- Serving unit (text, required)
- Package unit (text, optional — placeholder "z.B. Kiste"); when set, reveals Servings-per-package (integer, required)
- Note (text)
- EK (number, step 0.01) — per serving, labelled "EK pro {serving_unit}"
- KB (number, step 0.01) — per serving, labelled "Kiosk-Preis pro {serving_unit}"
- `expected_amount` (servings, min 0) — with an inline hint showing the package equivalent ("entspricht 3 Kisten")
- `current_amount` (servings, min 0 but warning if negative) — same inline hint
- Active (checkbox)
- Sort order (number) — visible only when `Weiter konfigurieren` section is expanded

### Ship state dashboard (`/admin/ship`)

- PageHeader "Schiff-Status"
- Top row of tiles (grid, 2-column on mobile): Tank 1, Tank 2, Kanister an Bord, Kanister Garage
- Second row: Wassertank, CO₂, Batterie, Klo 1, Klo 2, Persennig
- Each tile shows the value large, label small, a small edit icon. Tapping opens an ActionSheet with the appropriate input (number or enum select)
- Two sections below:
  - "Offene Todos" — list of `open_todos` with checkbox to mark done; add new at bottom
  - "Notizen" — running log, newest first
- Footer note: "Zuletzt aktualisiert durch Fahrbericht vom {date} ({tour name})" when `last_updated_from_tour_id` is set

## Integration with spec 012

- Spec 012 fetches the Bar catalog (`GET /bar-items?active=true`) to render the counter lists.
- On Fahrbericht submit, spec 012 calls `bar_service.apply_consumption(tour_id, kiosk_tally, crew_tally)` and `ship_service.apply_ship_status(tour_id, snapshot, new_notes, new_todos)` as **post-commit side effects** of spec 012's submission pipeline. The idempotency markers described above make retries safe — the Fahrbericht state moves to SUBMITTED first, and any failed side effect can be re-driven via spec 012's reapply-side-effects endpoint.
- Warnings returned from `apply_consumption` are surfaced in the submission result and shown to the user in a success toast / ActionSheet.
- The Fahrbericht form's Ship tab pre-fills from the current `ShipState` so the crew only has to update what changed during the tour.

## Visual conventions

- German UI text. Status-like colours reuse existing design tokens from spec 008.
- Low-stock badge: `.status-warning` variant (amber), reused from existing tokens.
- Icons: `lucide-vue-next` — `Beer`, `Wine`, `Droplets`, `BatteryCharging`, `Fuel`, `Flame`, `ShieldAlert` (for persennig), `ClipboardList` (todos), `StickyNote` (notes).
- Empty states:
  - Bar catalog empty: "Noch keine Getränke. Starte mit dem Standard-Seed."  — button "Katalog mit Standardsortiment füllen" calls the seed endpoint.
  - Ship todos empty: "Alles abgehakt. Gute Fahrt!"

## Backward compatibility

- Pure additive feature: no existing data is modified.
- All new routes are under `/api/admin/`, protected by the same Auth0 guard.
- The seed endpoint is idempotent — re-running it will not overwrite edits the admin made.

## Testing

- `bar_service` unit tests with `moto[dynamodb]` + `mock_aws`: `apply_consumption` happy path, idempotency on duplicate tour_id, negative warning, unknown item rejection.
- `ship_service` unit tests: snapshot overwrite, notes/todos append, idempotency, history preservation across multiple tours.
- Contract tests for the routes.
- Frontend component tests for the bar catalog list's grouping and low-stock badge (best-effort, same caveat as spec 010).

## Offene Fragen

1. **Low-stock threshold**: **locked at 25% of `expected_amount`** per user decision. A per-category override could be added later if the Bier vs. Shots asymmetry becomes painful, but MVP ships one threshold.
2. **Negative stock policy**: spec records negative and flags a warning. Recommendation: keep — clamping hides real-world usage. Revisit if the admin wants hard clamping later.
3. **Pfand handling**: EK is "netto, ohne Pfand" in the HTML. Pfand is excluded from MVP; add a separate `pfand` field later if Leasy booking needs it (spec 013's booking text).
4. **Opening vs closing inventory**: the HTML only tracks consumption, not opening/closing counts. A later spec could add `opening_amount` + `closing_count` fields plus a loss computation. **Deferred** per user decision on 010-series MVP scope.
5. **Ship singleton**: hardcoded `SHIP#schaluppe`. If a second vessel ever appears, promote to a collection. Not a concern for MVP.
6. **Seed source**: ship 23 HTML items as a Python constant embedded in the seed script (simple) vs a JSON file in the repo (editable without a code change). Recommendation: JSON file under `backend/app/data/bar_seed.json` — same convention as help content in the frontend.
