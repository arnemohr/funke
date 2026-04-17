# 011 — Bar Catalog & Ship State: Tasks

## Phase 1: Data Model

### T1.1 — Create BarItem model
**File:** `backend/app/models/bar_item.py` (new)
**Details:**
- Pydantic v2 classes:
  - `BarItemCategory` enum: `BIER_FASS`, `BIER_FLASCHE`, `ALKOHOLFREI`, `SEKT_WEIN`, `SOFTES`, `HARTES`, `SHOTS`
  - `BarItem` — all fields per spec, including two-unit fields: `serving_unit: str`, `package_unit: str | None`, `servings_per_package: int | None`. Use `Decimal` for `ek` and `kb`
  - Validator: if `package_unit` is set, `servings_per_package` must be a positive int; if `package_unit` is None, `servings_per_package` must be None
  - Computed property methods: `current_packages`, `current_singles`, `expected_packages`, `expected_singles` (all None-safe when there is no package unit)
  - `BarItemCreate`, `BarItemPatch`, `BarItemResponse`
  - `StockAdjustment` input model: `delta_packages: int = 0`, `delta_servings: int = 0`, `reason: str`
  - `BarItemStockChange` (response helper: `id`, `name`, `delta`, `new_current`, `went_negative`)
  - `ConsumptionResult` (`updated_items: list[BarItemStockChange]`, `warnings: list[str]`)
- Follow the model-shape conventions in `backend/app/models/event.py`

### T1.2 — Create ShipState model
**File:** `backend/app/models/ship_state.py` (new)
**Details:**
- Enums: `Co2Level`, `KloLevel`, `PersennigStatus` — each with the labelled members per spec
- Submodels: `Note` (`id`, `text`, `author`, `created_at`), `Todo` (`id`, `text`, `author`, `created_at`, `done`, `done_at`, `done_by`), `NoteInput` (just `text`), `TodoInput` (just `text`), `ShipStatusSnapshot` (all scalar fields, all Optional)
- `ShipState` top-level class with everything from the spec including `last_updated_from_tour_id`, `updated_at`
- `ShipStatePatch` (Optional versions of scalar fields)

### T1.3 — DynamoDB key helpers
**File:** `backend/app/services/config.py`
**Details:**
- Add constants:
  - `BAR_PK_PREFIX = "BAR#"`, `BAR_SK_META = "META"`
  - `BAR_CONSUMPTION_SK_PREFIX = "CONSUMPTION#"`, `BAR_ADJUSTMENT_SK_PREFIX = "ADJUSTMENT#"`
  - `SHIP_PK = "SHIP#schaluppe"`, `SHIP_SK_STATE = "STATE"`, `SHIP_SK_TOUR_MARKER_PREFIX = "STATE#"` (idempotency markers)
- Align with existing constant style

### T1.4 — Ship the 23-item seed
**File:** `backend/app/data/bar_seed.json` (new)
**Details:**
- Extract the `DRINKS` constant from `~/Downloads/schaluppe-fahrbericht.html` lines 276–313
- Map each HTML entry to a BarItem JSON object:
  - `id` → deterministic uuid5 from the HTML `id` slug (so re-seeds are stable)
  - `name`, `note` → 1:1
  - `serving_unit` ← HTML `unit` field (e.g. "Becher 0,4l", "Flasche 0,33l", "Glas ~0,15l")
  - `package_unit` + `servings_per_package` — seeded with sensible defaults derived from the HTML `note` field:
    - Fass items (`fass50` → `"Faß 50L"`/125, `fass30` → `"Faß 30L"`/75)
    - Bottle beer (Estrella, Corona, Störtebeker) → `"Kiste"`/24
    - Wine (Müller Thurgau, Rosé, Rotwein) → `"Flasche 0,75l"`/5 (the bottle is the package, servings are glasses)
    - Sekt → `"Flasche 0,75l"`/5
    - Softes bottles → `"Kiste"`/24 for 0,33l, `"Kiste"`/12 for 0,5l/0,7l
    - Hartes/Shots → `package_unit = null`, `servings_per_package = null` (poured from a house bottle — tracked as servings only)
  - `ek`, `kb` → string decimals (per serving, same as HTML)
  - `category` → derive from the HTML `cat` emoji prefix (🍺 Bier vom Faß → `BIER_FASS`, 🥂 Sekt & Wein → `SEKT_WEIN`, etc.)
  - `expected_amount`: 0 for MVP (admin sets real baselines after the first real stock-take)
  - `current_amount`: 0
  - `active`: true
  - `sort_order`: source-file order

---

## Phase 2: Service Layer — Bar

### T2.1 — BarService skeleton
**File:** `backend/app/services/bar_service.py` (new)
**Details:**
- Singleton + lazy init matching `registration_service.py`
- Methods: `create_bar_item`, `get_bar_item`, `list_bar_items(category, active)`, `patch_bar_item`, `delete_bar_item`, `adjust_stock(bar_item_id, delta, reason, author)`, `seed_from_file(path)`

### T2.2 — Implement `apply_consumption` and `apply_consumption_delta`
**File:** `backend/app/services/bar_service.py`
**Details:**
- Signatures per spec:
  - `apply_consumption(tour_id, version, kiosk_tally, crew_tally) -> ConsumptionResult`
  - `apply_consumption_delta(tour_id, version, previous, next) -> ConsumptionResult`
- Versioned idempotency: conditional `PutItem` on `BAR#{bar_item_id}` / `CONSUMPTION#{tour_id}#v{version}` per affected item (short-circuit if exists — return cached result). Earlier versions remain in place as an audit trail
- Decrement: `UpdateItem` with `ADD current_amount :delta`
  - `apply_consumption`: delta = `-(kiosk + crew)` per item
  - `apply_consumption_delta`: delta = `-(next - previous)` per item (zero entries skipped)
- Per-item warning when `new_current < 0`: append to `ConsumptionResult.warnings`
- Raise `ValueError` for unknown `bar_item_id`
- Ledger row stores: `version`, `kiosk` / `crew` (or `previous` / `next` for the delta variant), resolved `delta`, `applied_at`

### T2.3 — Implement `adjust_stock`
**File:** `backend/app/services/bar_service.py`
**Details:**
- Signature: `adjust_stock(bar_item_id, delta_packages, delta_servings, reason, author) -> BarItem`
- Loads the item to get `servings_per_package`; if `delta_packages != 0` and the item has no `package_unit`, raises `ValueError("item has no package unit")`
- Computed `delta = delta_packages * servings_per_package + delta_servings`
- Writes a ledger row `ADJUSTMENT#{iso_timestamp}` with `delta_packages`, `delta_servings`, `delta`, `reason`, `author` (audit trail preserves the human-entered breakdown as well as the resolved delta)
- Uses `ADD current_amount :delta` atomically

### T2.4 — Implement seed
**File:** `backend/app/services/bar_service.py`
**Details:**
- Reads the JSON from T1.4
- For each entry: attempt `PutItem` with `ConditionExpression="attribute_not_exists(pk)"` — silently skip if already present
- Returns summary `{inserted: int, skipped: int}`

---

## Phase 3: Service Layer — Ship

### T3.1 — ShipService skeleton
**File:** `backend/app/services/ship_service.py` (new)
**Details:**
- Singleton + lazy init
- Methods: `get_state() -> ShipState`, `patch_state(patch: ShipStatePatch)`, `append_note(text, author)`, `remove_note(note_id)`, `append_todo(text, author)`, `toggle_todo(todo_id, done, author)`, `edit_todo(todo_id, text)`, `remove_todo(todo_id)`
- `get_state` must lazy-init the singleton item on first call (empty state)

### T3.2 — Implement `apply_ship_status` and `apply_ship_status_versioned`
**File:** `backend/app/services/ship_service.py`
**Details:**
- Signatures per spec:
  - `apply_ship_status(tour_id, version, snapshot, new_notes, new_todos) -> ShipState`
  - `apply_ship_status_versioned(tour_id, version, snapshot, previously_applied_note_ids, previously_applied_todo_ids, new_notes, new_todos) -> ShipState`
- Versioned idempotency: conditional `PutItem` on `SHIP#schaluppe` / `STATE#{tour_id}#v{version}` marker; skip apply if marker exists
- Both: overwrite scalar fields from `snapshot`; update `last_updated_from_tour_id` and `updated_at`
- `apply_ship_status` (first submit): generate fresh ids, append all `new_notes` and `new_todos`, return the generated id lists
- `apply_ship_status_versioned` (re-submits):
  - For notes: drop from the Ship state any note whose id is in `previously_applied_note_ids` but not in the current `new_notes` (the crew removed it on edit). Append any note in `new_notes` whose id is not in `previously_applied_note_ids`
  - Same algorithm for todos
  - Return the new complete id lists (spec 012 persists these as `applied_ship_*_ids`)

---

## Phase 4: API Routes

### T4.1 — Bar routes
**File:** `backend/app/api/admin/bar_items.py` (new)
**Details:**
- `APIRouter(prefix="/bar-items", tags=["admin.bar"])`
- Endpoints per spec (list/create/get/patch/delete/adjust-stock/seed)
- `DELETE` returns 409 when at least one ledger row under the pk exists (count via `Query` with `Limit=1`)

### T4.2 — Ship routes
**File:** `backend/app/api/admin/ship.py` (new)
**Details:**
- `APIRouter(prefix="/ship", tags=["admin.ship"])`
- Endpoints per spec for state + notes + todos

### T4.3 — Register routers
**File:** `backend/app/main.py`
**Details:**
- `app.include_router(bar_router, prefix="/api/admin")`
- `app.include_router(ship_router, prefix="/api/admin")`

---

## Phase 5: Frontend — Bar Catalog

### T5.1 — Bar admin API client
**File:** `frontend/src/services/api.js`
**Details:**
- Add `adminApi.bar`: `list`, `create`, `get`, `patch`, `delete`, `adjustStock`, `seed`

### T5.2 — BarCatalogPage
**File:** `frontend/src/pages/admin/BarCatalogPage.vue` (new)
**Details:**
- Route: `/admin/bar`
- Grouped list by category (use collapsible section headers — `<details>` or accordion)
- Each row: name, unit, EK, KB, current/expected, low-stock badge
- Filter tabs Alle/Aktiv/Inaktiv
- FAB "Neues Getränk"
- Toolbar button "Kiosk-Stand aktualisieren" toggles bulk-adjust mode (inline `+/−` counters using the same 32px circular buttons as spec 012's counter component)

### T5.3 — BarItemFormPage
**File:** `frontend/src/pages/admin/BarItemFormPage.vue` (new)
**Details:**
- Route: `/admin/bar/new` and `/admin/bar/:id`
- Form fields per spec
- Save + delete actions
- Reuse project form styling

### T5.4 — Stock adjustment ActionSheet
**File:** `frontend/src/components/bar/AdjustStockSheet.vue` (new)
**Details:**
- Reuse `frontend/src/components/ActionSheet.vue`
- Fields side-by-side: "Kisten (±)" (`delta_packages`, hidden when `package_unit` is null) and "Einzel (±)" (`delta_servings`)
- Live preview below the fields: "Ergebnis: {current_amount + resolved_delta} (= X Kisten + Y Einzel)"
- Reason textarea (required)
- Calls `adminApi.bar.adjustStock` with `{ delta_packages, delta_servings, reason }`

### T5.5 — Router + Nav
**File:** `frontend/src/router/index.js`, `frontend/src/App.vue` (or BottomNav)
**Details:**
- Register new routes behind admin guard
- Nav: do NOT add Bar to the bottom bar (not a daily crew action) — instead add a menu entry in SettingsPage (`frontend/src/pages/admin/SettingsPage.vue`) under a new "Schaluppe" section

---

## Phase 6: Frontend — Ship State

### T6.1 — Ship admin API client
**File:** `frontend/src/services/api.js`
**Details:**
- Add `adminApi.ship`: `getState`, `patchState`, `appendNote`, `removeNote`, `appendTodo`, `patchTodo`, `removeTodo`

### T6.2 — ShipStatePage
**File:** `frontend/src/pages/admin/ShipStatePage.vue` (new)
**Details:**
- Route: `/admin/ship`
- Top section: 2-column tile grid for scalar fields
- Each tile: label + value + edit icon; tap opens `EditShipFieldSheet` ActionSheet
- Middle section: Open Todos (`ListItemButton` with checkbox + trash)
- Bottom section: Notes (newest first, trash per entry)
- Footer: "Zuletzt aktualisiert durch Fahrbericht vom {date} ({tour name})"

### T6.3 — EditShipFieldSheet
**File:** `frontend/src/components/ship/EditShipFieldSheet.vue` (new)
**Details:**
- Generic component: takes `{ field, currentValue, type }` and renders appropriate input (number 0–100, date picker, enum select)
- Calls `adminApi.ship.patchState({ [field]: newValue })`

### T6.4 — Nav entry
**File:** `frontend/src/pages/admin/SettingsPage.vue`
**Details:**
- Under the new "Schaluppe" section: entries for "Bar-Katalog", "Schiff-Status"
- Uses `ListItemButton` with `Beer` and `Anchor` icons

---

## Phase 7: Shared Frontend Pieces

### T7.1 — Category label + icon map
**File:** `frontend/src/utils/barCategories.js` (new)
**Details:**
- Export `CATEGORY_LABELS` (German) and `CATEGORY_ICONS` (lucide names) per spec
- Used by both BarCatalogPage and spec 012's counter list

### T7.2 — Low-stock badge style
**File:** `frontend/src/assets/design-tokens.css`
**Details:**
- Add `.status-low-stock` reusing the existing warning token colours — or reuse `.status-warning` directly and style via component

### T7.3 — Counter row component (shared with spec 012)
**File:** `frontend/src/components/bar/CounterRow.vue` (new)
**Details:**
- Props: `name`, `servingUnit`, `note`, `price`, `qty`, `priceLabel`, `emphasis` ('kiosk' | 'crew' | 'admin')
- The counter always counts in **servings** (matching how the HTML prototype works). Packaging is irrelevant at the Fahrbericht tally row — crew count bottles/Becher
- Emits `increment`, `decrement`, `set(qty)`
- Matches the HTML prototype visuals: 32px circular `+` / `−` buttons, qty number centred, subtotal right-aligned
- Uses `IconButton`-style minus/plus buttons with green/red colour accents per the HTML
- Will be reused by spec 012 for the Fahrbericht Kiosk and Crew tabs

### T7.4 — Stock display helper
**File:** `frontend/src/utils/barStock.js` (new)
**Details:**
- Pure helpers: `formatStock(item) -> "5 Kisten + 3 Flaschen · 123 gesamt"` when `package_unit` is set, or `"123 Becher"` otherwise
- `splitServings(amount, servingsPerPackage) -> { packages, singles }`
- Used by BarCatalogPage, BarItemFormPage, AdjustStockSheet

---

## Phase 8: Tests

### T8.1 — BarService unit tests
**File:** `backend/tests/unit/test_bar_service.py` (new)
**Details:**
- `moto[dynamodb]` + `mock_aws`
- Cases:
  - CRUD happy paths
  - `apply_consumption` decrements atomically
  - Duplicate `tour_id` → no double decrement, returns cached result
  - Unknown `bar_item_id` → ValueError
  - Negative `current_amount` → warning in result
  - Seed idempotency: running seed twice inserts only the first time

### T8.2 — ShipService unit tests
**File:** `backend/tests/unit/test_ship_service.py` (new)
**Details:**
- Cases:
  - Initial `get_state` lazy-creates empty state
  - `apply_ship_status` overwrites scalars, appends notes and todos
  - Duplicate tour_id marker → skipped, state unchanged
  - Todo lifecycle: append, toggle, edit, remove

### T8.3 — API contract tests
**File:** `backend/tests/contract/test_bar_routes.py`, `backend/tests/contract/test_ship_routes.py` (new)
**Details:**
- Auth guard, CRUD happy paths, 409 on delete with ledger rows

### T8.4 — Seed integration test
**File:** `backend/tests/integration/test_bar_seed.py` (new)
**Details:**
- Load `backend/app/data/bar_seed.json`, call seed service, verify 23 items exist with expected ids and prices

---

## Phase 9: Docs & Deploy

### T9.1 — Document seed endpoint + JSON file
**File:** `AGENTS.md`
**Details:**
- Short note: "To reset the drinks catalog to the shipped 23 items, call `POST /api/admin/bar-items/seed`. JSON source is `backend/app/data/bar_seed.json`."

### T9.2 — Post-deploy runbook
**File:** `README.md` or deployment doc
**Details:**
- After first deploy of spec 011, run the seed endpoint once (or wire to a one-shot Lambda hook if the team prefers)

---

## Execution Order

```
T1.1 → T1.2 → T1.3 → T1.4                         (Models + keys + seed file)
  ↓
T2.1 → T2.2 → T2.3 → T2.4                         (Bar service)
T3.1 → T3.2                                         (Ship service — can be parallel with Bar)
  ↓
T4.1 → T4.2 → T4.3                                 (API routes)
  ↓
T7.1 → T7.2 → T7.3 → T7.4                          (Shared frontend — ship early, spec 012 needs CounterRow)
  ↓
T5.1 → T5.2 → T5.3 → T5.4 → T5.5                   (Bar frontend)
T6.1 → T6.2 → T6.3 → T6.4                          (Ship frontend — parallel with Bar frontend)
  ↓
T8.1 → T8.2 → T8.3 → T8.4                          (Tests)
  ↓
T9.1 → T9.2                                         (Docs)
```
