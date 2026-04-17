# 014 — Fahrbericht on Event: Tasks

## Phase 1: Backend — Data Model

### T1.1 — Move `CrewRef` into the Fahrbericht model
**File:** `backend/app/models/fahrbericht.py`, `backend/app/models/tour.py`
**Details:**
- Copy the `CrewRef` submodel from `tour.py` into `fahrbericht.py` (top of file, above `FahrberichtBase`)
- Do not delete `tour.py` yet (done in T1.3); keep it valid until the service is removed

### T1.2 — Add Tour-derived fields to Fahrbericht
**File:** `backend/app/models/fahrbericht.py`
**Details:**
- Extend `FahrberichtBase` with: `duration_hours: Decimal | None`, `guest_count: int | None`, `charterer: str | None`, `funker: CrewRef | None`, `skipper: CrewRef | None`, `crew: list[CrewRef] = Field(default_factory=list)`
- Extend `FahrberichtPatch` with Optional variants of the same six fields

### T1.3 — Delete the Tour model + exports
**File:** `backend/app/models/tour.py` (delete), `backend/app/models/__init__.py`
**Details:**
- Delete `backend/app/models/tour.py`
- In `__init__.py`: drop all Tour/TourCreate/TourPatch/TourResponse/TourStatus/CrewRef imports from `from .tour import ...`
- Re-export `CrewRef` from `.fahrbericht` so existing importers (`admin_service`, routes) keep working

---

## Phase 2: Backend — Services

### T2.1 — Delete TourService
**File:** `backend/app/services/tour_service.py` (delete)
**Details:**
- Remove the file entirely
- Any residual imports surface as test failures in T5 — fix there

### T2.2 — Update `config.py` key constants
**File:** `backend/app/services/config.py`
**Details:**
- Delete: `get_tours_table()` accessor, `TOUR_PK_PREFIX`, `TOUR_SK_META`, `TOUR_SK_FAHRBERICHT`, `TOUR_SK_REPORT_POINTER`, `TOURS_LIST_PK`, `EVENT_TOUR_PK_PREFIX`, `EVENT_TOUR_SK`
- Add: `EVENT_PK_PREFIX = "EVENT#"` (if not already), `EVENT_SK_FAHRBERICHT = "FAHRBERICHT"`, `EVENT_SK_REPORT_POINTER = "REPORT"`
- The Fahrbericht + Report-pointer items will live alongside Event items in the existing events table

### T2.3 — Rewrite FahrberichtService to key by Event
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- Swap `get_tours_table()` → `get_events_table()`
- All `pk`/`sk` writes use `EVENT#{event_id}` / `FAHRBERICHT`
- All method signatures rename `tour_id` → `event_id`
- `_fahrbericht_to_item` / `_item_to_fahrbericht` get the six new Tour-derived fields
- `create_draft`, `upsert_draft`, `delete_draft`, `get`, `build_response`, `reopen` — straight parameter rename
- `submit`:
  - Fetch Event via `event_service.get_event(org_id, event_id)` instead of `tour_service.get_tour(...)`
  - Do **not** call `tour_service.transition_to_completed` — remove that step entirely; do not mutate `event.status`
  - Pass the Event (not a Tour) into `booking_text.build_booking_text` and `report_service.create_or_update_report`
- `reapply_side_effects` — same rename; no Tour lookup

### T2.4 — Rename consumption ledger parameter
**File:** `backend/app/services/bar_service.py`
**Details:**
- `apply_consumption(tour_id, ...)` → `apply_consumption(event_id, ...)`
- `apply_consumption_delta(tour_id, ...)` → `apply_consumption_delta(event_id, ...)`
- Ledger row `sk` key changes from `CONSUMPTION#{tour_id}#v{version}` to `CONSUMPTION#{event_id}#v{version}` — same shape, different variable name
- Update all log statements

### T2.5 — Rename ship-state marker parameter
**File:** `backend/app/services/ship_service.py`
**Details:**
- `apply_ship_status(tour_id, ...)` → `apply_ship_status(event_id, ...)`
- `apply_ship_status_versioned(tour_id, ...)` → `apply_ship_status_versioned(event_id, ...)`
- `_marker_exists` / `_write_marker` keys: `STATE#{event_id}#v{version}`

### T2.6 — Update ReportService to key by Event
**File:** `backend/app/services/report_service.py`
**Details:**
- `create_or_update_report(tour_id, version)` → `create_or_update_report(event_id, version)`
- `get_report_for_tour(tour_id)` → `get_report_for_event(event_id)`
- Pointer row write: `pk = EVENT#{event_id}`, `sk = REPORT` — writes to the **events** table, not the (deleted) tours table
- Update `self.tours_table` references to `self.events_table`; swap `get_tours_table()` → `get_events_table()`
- `create_or_update_report`:
  - Fetch the Event (not the Tour) for the `tour_snapshot` construction (rename the internal var to `event_snapshot`) — preserves the same JSON shape that `report.html` renders
  - Preserve existing fields in the snapshot (date, name, duration_hours, guest_count, charterer, funker_name, skipper_name, crew_names) — pull them now from `(event, fahrbericht)` instead of `(tour, fahrbericht)`. `duration_hours`, `guest_count`, `charterer`, and crew come from the Fahrbericht; `name` and `date` come from the Event (`event.start_at.date().isoformat()`, `event.name`)
- `list_reports` stays (if kept — see T4.4)

### T2.7 — Update booking-text builder
**File:** `backend/app/services/booking_text.py`
**Details:**
- Signature: `build_booking_text(bericht, event, bar_catalog)` — second parameter changes from Tour to Event
- `tour.date.isoformat()` → `event.start_at.date().isoformat()`
- `tour.name` → `event.name`
- `tour.guest_count` → `bericht.guest_count`
- `tour.funker.display_name` → `bericht.funker.display_name if bericht.funker else None`

---

## Phase 3: Backend — API

### T3.1 — Move Fahrbericht router under Events
**File:** `backend/app/api/admin/fahrbericht.py`
**Details:**
- Prefix: `/tours/{tour_id}/fahrbericht` → `/events/{event_id}/fahrbericht`
- All path params `tour_id` → `event_id`
- `_check_access` now looks up the Event via `event_service.get_event(org_id, event_id)` instead of `tour_service.get_tour(tour_id)`. 404 on missing or cross-org access.

### T3.2 — Delete the Tours router
**File:** `backend/app/api/admin/tours.py` (delete), `backend/app/main.py`
**Details:**
- Delete `backend/app/api/admin/tours.py` (kills both `/tours/**` and the `/events/{id}/tour` convenience routes)
- In `main.py`: remove the `from .api.admin import tours as admin_tours` import and the two `app.include_router` loops that registered `admin_tours.routers`

### T3.3 — Move Report convenience lookup to Event
**File:** `backend/app/api/admin/reports.py`
**Details:**
- `GET /tours/{tour_id}/report` → `GET /events/{event_id}/report`
- Service call: `get_report_for_tour` → `get_report_for_event`
- `tour_report_router`'s prefix changes from `/tours` to `/events`

### T3.4 — Decide fate of the Reports list route
**File:** `backend/app/api/admin/reports.py`
**Details:**
- Per spec: **remove `GET /api/admin/reports`** (the list endpoint). Keep per-report and per-version endpoints for deep-linked access from the Event detail page.
- Delete `list_reports` handler. Leave `ReportListResponse` model defined if other code references it — otherwise drop.

---

## Phase 4: Infra

### T4.1 — Delete the ToursTable from CDK
**File:** `infra/cdk/stacks/database_stack.py`
**Details:**
- Remove the entire `self.tours_table = dynamodb.Table(...)` block (including the `list-by-date-index` GSI)
- Leave the other three new tables (`bar_items_table`, `ship_state_table`, `reports_table`) in place

### T4.2 — Drop tours-table grant from Lambda
**File:** `infra/cdk/stacks/api_stack.py`
**Details:**
- Delete the `database_stack.tours_table.grant_read_write_data(self.api_function)` line
- Delete the `TOURS_TABLE` env var injection
- Same cleanup for the worker Lambda block (if it still references tours)

---

## Phase 5: Frontend — API client & router

### T5.1 — Rewrite `adminApi.fahrbericht` URLs
**File:** `frontend/src/services/api.js`
**Details:**
- All `/tours/${tourId}/fahrbericht` → `/events/${eventId}/fahrbericht`
- Function parameter `tourId` → `eventId` for every method (`get`, `createDraft`, `put`, `submit`, `reopen`, `reapply`, `delete`)

### T5.2 — Rewrite `adminApi.reports.getForTour`
**File:** `frontend/src/services/api.js`
**Details:**
- Rename `getForTour(tourId)` → `getForEvent(eventId)`, path `/tours/${tourId}/report` → `/events/${eventId}/report`
- Remove `adminApi.reports.list` (list endpoint is gone in T3.4)

### T5.3 — Delete `adminApi.tours` block
**File:** `frontend/src/services/api.js`
**Details:**
- Remove the entire `tours: { ... }` nested object from the `adminApi` export

### T5.4 — Update router entries
**File:** `frontend/src/router/index.js`
**Details:**
- Delete: `/admin/tours`, `/admin/tours/new`, `/admin/tours/:id`
- Change: `/admin/tours/:tourId/fahrbericht` → `/admin/events/:eventId/fahrbericht` (component stays `FahrberichtPage.vue`, props change)
- Add: `/admin/schaluppe` → `ShipStatePage.vue` (same component, new path)
- Keep: `/admin/ship` as a redirect: `redirect: '/admin/schaluppe'`
- Delete: `/admin/reports` (list route removed)
- Keep: `/admin/reports/:id` for deep-linked detail (accessed from Event detail)

---

## Phase 6: Frontend — Bottom navigation & pages

### T6.1 — Rewrite the bottom nav
**File:** `frontend/src/App.vue`
**Details:**
- Replace the existing three-entry nav with four: Events (Calendar), Schaluppe (Anchor), Bar (Beer), Einstellungen (Settings)
- Debug link stays appended, dev-mode-only (same trigger as today)
- Verify active-route highlighting works on all four entries (the existing `.router-link-active` CSS should just work)

### T6.2 — Clean out the Schaluppe section in Einstellungen
**File:** `frontend/src/pages/admin/SettingsPage.vue`
**Details:**
- Delete the entire "Schaluppe" `<div class="section-heading">` block and its `<div class="list-group">` with the five entries (Profil / Touren / Bar-Katalog / Schiff-Status / Fahrberichte)
- Add a new section at the top of the page: heading "Mein Profil", containing a single `ListItemButton` → `/admin/profile` with the `User` icon
- Remove the `User, Anchor, Beer, Ship, FileText` imports that are no longer used (keep `User`)

### T6.3 — Rewrite the Fahrbericht section on EventDetailPage
**File:** `frontend/src/pages/admin/EventDetailPage.vue`
**Details:**
- Delete the `refreshTour`, `createTour`, `tourCrewSummary`, `tour` reactive state
- Replace the "Tour & Fahrbericht" section with a new "Fahrbericht" section:
  - State A (no Fahrbericht) → `ListItemButton` "Fahrbericht starten" that calls `adminApi.fahrbericht.createDraft(eventId)` then routes to `/admin/events/${eventId}/fahrbericht`
  - State B (DRAFT) → `ListItemButton` with chevron → same route; trailing slot shows "Entwurf" pill
  - State C (SUBMITTED) → `ListItemButton` → read-only view; below it two rows:
    - "PDF öffnen" (anchor → `adminApi.reports.pdfUrl(reportId)` in a new tab)
    - "Bericht erneut senden" (calls `adminApi.reports.resend(reportId)`, toast on result)
- Fetch once on mount: `adminApi.fahrbericht.get(eventId)` with try/catch, then `adminApi.reports.getForEvent(eventId)` if the Fahrbericht exists

### T6.4 — Update FahrberichtPage to use event_id
**File:** `frontend/src/pages/admin/FahrberichtPage.vue`
**Details:**
- Route param `:tourId` → `:eventId`; `const tourId = route.params.tourId` → `const eventId = route.params.eventId`
- All `adminApi.fahrbericht.*(tourId)` → `(eventId)`
- Remove the `tour.value = await adminApi.tours.get(tourId)` load step
- Replace with `event.value = await adminApi.getEvent(eventId)` (existing admin API method)
- Header title comes from `event.name`
- `saveTour` emit is removed — everything lands as Fahrbericht PATCH in T6.5

### T6.5 — Consolidate crew editing inside FahrtTab
**File:** `frontend/src/pages/admin/fahrbericht/FahrtTab.vue`
**Details:**
- Remove `save-tour` emit; the tab no longer writes to a Tour
- `name` and `date` fields become **read-only display rows** — they reflect `event.name` and `event.start_at`, not editable here (admins edit them on the Event edit page)
- Editable Fahrbericht fields: `duration_hours`, `guest_count`, `boarding_fee`, `bar_surcharge`, `charterer`, `funker`, `skipper`, `crew[]`
- Crew add/remove emit `save` events that trigger the parent's debounced save of the Fahrbericht

### T6.6 — Relabel Schaluppe + Bar page headers
**File:** `frontend/src/pages/admin/ShipStatePage.vue`, `frontend/src/pages/admin/BarCatalogPage.vue`
**Details:**
- `ShipStatePage`: `<PageHeader title="Schaluppe" />` (was "Schiff-Status"). Remove the `back` prop since the page is now a top-level destination.
- `BarCatalogPage`: `<PageHeader title="Bar" />` (was "Bar-Katalog"). Remove the `back` prop.

### T6.7 — Update SubmittedView actions
**File:** `frontend/src/pages/admin/fahrbericht/SubmittedView.vue`
**Details:**
- Remove any "Zur Tour" link
- Keep "Bearbeiten" (reopen)
- Add "PDF öffnen" anchor using `adminApi.reports.pdfUrl(report.id)` when `report` prop is present
- "Bericht ansehen" link can stay (deep-links into `/admin/reports/{id}` for the read-only detail)

---

## Phase 7: Frontend — Deletions

### T7.1 — Delete Tour pages
**Files:**
- `frontend/src/pages/admin/TourListPage.vue` (delete)
- `frontend/src/pages/admin/TourDetailPage.vue` (delete)
- `frontend/src/pages/admin/TourCreatePage.vue` (delete)
- `frontend/src/composables/useTourActions.js` (delete if it exists — verify first)

### T7.2 — Delete ReportsListPage
**File:** `frontend/src/pages/admin/ReportsListPage.vue` (delete)
**Details:**
- No route references it after T5.4
- `ReportDetailPage.vue` is kept for deep-linked detail views

---

## Phase 8: Verification

### T8.1 — Backend import smoke
**File:** (run in shell)
**Details:**
- `cd backend && python -c "from app.main import app; print(len(app.routes))"` — must succeed, no `tour_service` import errors. Expect ~30 fewer routes than before (no `/tours` or `/events/{id}/tour` routes).

### T8.2 — Backend test suite
**File:** (run in shell)
**Details:**
- `cd backend && python -m pytest tests/ --ignore=tests/unit/test_email_service.py` — 26 pre-existing tests pass.
- If any existing test imports `from app.models import Tour` or `from app.services.tour_service import ...`, update it to the new shape or delete it.

### T8.3 — End-to-end happy path (moto)
**File:** one-off Python script or ad-hoc
**Details:**
- Seed bar catalog.
- Create an Event directly.
- POST `/api/admin/events/{id}/fahrbericht` → draft created.
- PUT with crew + tally + cash.
- POST `.../submit` → verify `bar_ok=True`, `ship_ok=True`, `report_ok=True`.
- Assert Event.status is unchanged (still DRAFT if that's how we created it).
- GET `/api/admin/events/{id}/report` → META with `current_version = 1`.
- GET `.../reports/{id}/pdf` → bytes start with `%PDF`.

### T8.4 — Frontend build
**File:** (run in shell)
**Details:**
- `cd frontend && npm run build` — no dead imports, no missing routes. Build succeeds.

### T8.5 — Manual UI smoke at mobile viewport (375px)
**File:** (checklist in PR)
**Details:**
- Bottom nav shows exactly four icons (plus Debug in dev mode).
- Schaluppe tab → tiles render; editing a tile persists.
- Bar tab → catalog renders; stock adjust sheet works.
- Events tab → pick an event → "Fahrbericht starten" → edit crew + counters + submit → SubmittedView with "Bearbeiten", "PDF öffnen", "Bericht erneut senden" actions.
- Einstellungen tab → "Mein Profil" at top; no Touren/Bar/Schiff/Fahrberichte entries remain.
- Deep link `/admin/ship` redirects to `/admin/schaluppe`.
- Deep link `/admin/tours` returns 404 (expected).

---

## Execution order

```
T1.1 → T1.2                                         (models — fields first)
  ↓
T2.2                                                 (config.py key constants)
  ↓
T2.3 → T2.4 → T2.5 → T2.6 → T2.7                    (services — pipeline)
  ↓
T3.1 → T3.3 → T3.4                                   (API routes, minus the tours-delete)
  ↓
T2.1 → T1.3 → T3.2                                   (deletes — safe after all callers have moved)
  ↓
T4.1 → T4.2                                          (CDK)
  ↓
T5.1 → T5.2 → T5.3 → T5.4                           (frontend API client + router)
  ↓
T6.1 → T6.2 → T6.3 → T6.4 → T6.5 → T6.6 → T6.7      (frontend pages)
  ↓
T7.1 → T7.2                                          (frontend deletes)
  ↓
T8.1 → T8.2 → T8.3 → T8.4 → T8.5                    (verification)
```

The order is specifically staged so that deletes (Tour model, TourService, tours API router) land *after* every caller has moved to the Event-keyed shape. This keeps each intermediate commit in a buildable state.
