# 012 — Fahrbericht Form: Tasks

## Phase 1: Data Model

### T1.1 — Fahrbericht model
**File:** `backend/app/models/fahrbericht.py` (new)
**Details:**
- Pydantic v2:
  - `FahrberichtStatus` enum: `DRAFT`, `SUBMITTED`
  - `ExpenseLine` submodel: `description: str`, `amount: Decimal`
  - `Fahrbericht` — all fields per spec, including:
    - `version: int = 0`
    - `kiosk_tally: dict[UUID, int]`, `crew_tally: dict[UUID, int]`
    - `applied_kiosk_tally: dict[UUID, int] = {}`, `applied_crew_tally: dict[UUID, int] = {}`
    - `applied_ship_notes_ids: list[UUID] = []`, `applied_ship_todos_ids: list[UUID] = []`
    - `ship_status: ShipStatusSnapshot` (reuse from spec 011)
    - `new_notes: list[str]`, `new_todos: list[str]`
    - `expenses: list[ExpenseLine]`
  - `FahrberichtPatch` — Optional versions of every editable field. Does NOT include `version` or `applied_*` — those are server-only
  - `FahrberichtResponse` — Fahrbericht + `computed` block (`kiosk_total`, `crew_cost`, `expenses_total`, `soll`, `cash_diff`) + `diff` block (populated on GET when status=DRAFT and version>=1, showing delta vs applied_*_tally)
- Decimal for all money fields, UTC datetimes, uuid fields

### T1.2 — DynamoDB keys
**File:** `backend/app/services/config.py`
**Details:**
- Add `FAHRBERICHT_SK = "FAHRBERICHT"`. Fahrberichte share the Tour partition (`TOUR#{tour_id}`) already defined in spec 010 (T1.2)

---

## Phase 2: Service Layer

### T2.1 — FahrberichtService skeleton
**File:** `backend/app/services/fahrbericht_service.py` (new)
**Details:**
- Singleton + lazy init per project convention
- Methods:
  - `get(tour_id)` → `Fahrbericht | None`
  - `create_draft(tour_id)` — 409 if exists
  - `upsert_draft(tour_id, patch)` — 409 if current is SUBMITTED
  - `delete_draft(tour_id)` — 409 if SUBMITTED
  - `submit(tour_id, submitted_by)` — see T2.2 (handles both first submit and re-submit based on `version`)
  - `reopen(tour_id)` — SUBMITTED → DRAFT, does not bump `version`. 409 if already DRAFT
  - `reapply_side_effects(tour_id)` — see T2.3
  - Internal helper `_compute(bericht, bar_catalog)` → totals
  - Internal helper `_diff(bericht)` → per-item delta view for DRAFTs with `version >= 1`

### T2.2 — Submission pipeline (first submit + re-submit)
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- Branch on current `version`:
  - `version == 0` → first-submit path
  - `version >= 1` → re-submit path (applies delta semantics)
- Both paths validate per spec's Validation section
- `TransactWriteItems`:
  - Update Fahrbericht: status=SUBMITTED, `version = current + 1`, submitted_at, submitted_by, condition `status = DRAFT`
  - On first submit only: update Tour status=COMPLETED, condition `status IN (PLANNED, IN_PROGRESS)`
- On transaction success, call in sequence (each best-effort with retry):
  - First submit (`version` now 1):
    1. `bar_service.apply_consumption(tour_id, version=1, kiosk_tally, crew_tally)` — collect warnings
    2. `ship_service.apply_ship_status(tour_id, version=1, ship_status, new_notes, new_todos)` — capture returned `note_ids`, `todo_ids`
    3. `report_service.create_or_update_report(tour_id, version=1)` (spec 013) — capture `report_id`
  - Re-submit (`version` now N+1):
    1. `bar_service.apply_consumption_delta(tour_id, version=N+1, previous=applied_kiosk+applied_crew, next=kiosk+crew)`
    2. `ship_service.apply_ship_status_versioned(tour_id, version=N+1, snapshot, applied_ship_notes_ids, applied_ship_todos_ids, new_notes, new_todos)` — capture new id lists
    3. `report_service.create_or_update_report(tour_id, version=N+1)`
- Persist `report_id` (first submit only — stable afterwards), `applied_kiosk_tally`, `applied_crew_tally`, `applied_ship_notes_ids`, `applied_ship_todos_ids` via a follow-up `UpdateItem` on the Fahrbericht
- Return a `SubmitResult`: updated Fahrbericht, consumption warnings, report_id, per-step success/failure
- On a step failure, log + increment `submission_side_effect_failures` metric, surface in the response — do NOT revert the SUBMITTED state

### T2.2b — Reopen implementation
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- `reopen(tour_id)`:
  - Conditional `UpdateItem` on the Fahrbericht: sets status=DRAFT, condition `status = SUBMITTED`
  - Returns the updated Fahrbericht
  - Does not modify Tour status, Bar catalog, Ship state, or Report — those stay at the previously-applied version until the user re-submits

### T2.3 — Reapply side effects
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- `reapply_side_effects(tour_id)`:
  - Requires the Fahrbericht is in SUBMITTED state
  - Re-runs the same three calls as T2.2's post-commit, relying on their idempotency markers to skip already-applied writes
  - Returns the same `SubmitResult` shape

### T2.4 — Booking text builder (server-side mirror)
**File:** `backend/app/services/booking_text.py` (new)
**Details:**
- Pure function: `build_booking_text(bericht, tour, bar_catalog) -> str`
- Format exactly per spec's template
- Used by spec 013 for the email body and for contract tests

---

## Phase 3: API Routes

### T3.1 — Fahrbericht router
**File:** `backend/app/api/admin/fahrbericht.py` (new)
**Details:**
- `APIRouter(prefix="/tours/{tour_id}/fahrbericht", tags=["admin.fahrbericht"])`
- Endpoints per spec (GET, POST create, PUT upsert, DELETE, POST submit, POST reopen, POST reapply-side-effects)
- Response models include the `computed` block from T2.1 and a `diff` block when the Fahrbericht is a reopened DRAFT (`version >= 1`)

### T3.2 — Register router
**File:** `backend/app/main.py`
**Details:**
- `app.include_router(fahrbericht_router, prefix="/api/admin")`

---

## Phase 4: Frontend — API & Composables

### T4.1 — Fahrbericht API client
**File:** `frontend/src/services/api.js`
**Details:**
- `adminApi.fahrbericht`:
  - `get(tourId)`, `createDraft(tourId)`, `put(tourId, patch)`, `submit(tourId)`, `reopen(tourId)`, `reapply(tourId)`, `delete(tourId)`

### T4.2 — useFahrberichtActions composable
**File:** `frontend/src/composables/useFahrberichtActions.js` (new)
**Details:**
- Encapsulates load + autosave debounce + submit flow
- Exposes reactive refs: `bericht`, `computed`, `status`, `saveStatus` ('idle' | 'saving' | 'saved' | 'error'), `lastSavedAt`
- Accepts the bar catalog (loaded once) to compute totals locally when the server's `computed` block is stale (e.g. between autosaves)
- Autosave: debounced 1500ms via a shared utility; triggers on any field change and on blur
- Handles conflict refetch (spec: server returns 409 with fresh version on stale write)

### T4.3 — Booking text builder (frontend)
**File:** `frontend/src/utils/bookingText.js` (new)
**Details:**
- Pure function matching T2.4's format
- Unit-testable

---

## Phase 5: Frontend — Page & Tabs

### T5.1 — FahrberichtPage
**File:** `frontend/src/pages/admin/FahrberichtPage.vue` (new)
**Details:**
- Route: `/admin/tours/:tourId/fahrbericht`
- On mount: parallel fetch of tour, fahrbericht (create if missing), bar catalog (spec 011), ship state (spec 011)
- Layout: PageHeader + tab nav + tab content + sticky total bar
- Tab nav implementation mirrors `EventDetailPage.vue`; five tabs (Fahrt / Kiosk / Crew / Schiff / Abschluss)
- Sticky total bar pinned bottom (mobile-safe, respects the existing `has-bottom-nav` padding class — this page hides the app's bottom nav via `meta: { hideTabBar: true }`)

### T5.2 — Tab: FahrtTab
**File:** `frontend/src/pages/admin/fahrbericht/FahrtTab.vue` (new)
**Details:**
- Form fields per spec
- Crew subsection reuses the crew-list widget from spec 010 (extract into `frontend/src/components/tour/CrewList.vue` if not already done in spec 010 — see note in Execution Order)
- Writes to both Fahrbericht (boarding_fee, bar_surcharge, guest_count, duration_hours) and Tour (name, date, funker, skipper, crew)

### T5.3 — Tab: KioskTab
**File:** `frontend/src/pages/admin/fahrbericht/KioskTab.vue` (new)
**Details:**
- Grouped list of `CounterRow` (`frontend/src/components/bar/CounterRow.vue` from spec 011 T7.3) with `emphasis="kiosk"`
- Fed from the active bar catalog
- Edits to `kiosk_tally` bubble up via composable
- Section header shows live kiosk total
- Infobox matching spec text

### T5.4 — Tab: CrewTab
**File:** `frontend/src/pages/admin/fahrbericht/CrewTab.vue` (new)
**Details:**
- Same shape as KioskTab, `emphasis="crew"`, shows EK instead of KB as primary price
- Edits to `crew_tally`

### T5.5 — Tab: SchiffTab
**File:** `frontend/src/pages/admin/fahrbericht/SchiffTab.vue` (new)
**Details:**
- Tile grid for scalars (fuel, water, CO₂, battery, klos, persennig)
- Pre-fills from the current ShipState (spec 011) on first DRAFT load
- Two textareas: Anmerkungen, Noch zu erledigende Aufgaben — each line appended to `new_notes` / `new_todos` on blur
- Reuses styling from spec 011's `ShipStatePage` (extract shared subcomponents if needed)

### T5.6 — Tab: AbschlussTab
**File:** `frontend/src/pages/admin/fahrbericht/AbschlussTab.vue` (new)
**Details:**
- Kasse fields
- Ausgaben dynamic list with `+ Ausgabe hinzufügen`
- Zusammenfassung block (read-only)
- Buchungstext block with copy button
- Primary submit button → opens SubmitConfirmationSheet

### T5.7 — TotalBar component
**File:** `frontend/src/components/fahrbericht/TotalBar.vue` (new)
**Details:**
- Sticky bottom bar showing live Kiosk-Soll / Crew-Kosten / Kasse-Ist
- Reactive to the composable's computed refs
- Matches HTML `#totalbar` visuals (navy background, white text)

### T5.8 — SubmitConfirmationSheet
**File:** `frontend/src/components/fahrbericht/SubmitConfirmationSheet.vue` (new)
**Details:**
- Uses `ActionSheet` as base
- Summarises tour name, date, soll vs ist, number of counters non-zero
- Displays warnings: cash_diff > 5€, tally referencing inactive bar items, forecast of negative stock per item (computed client-side from current_amount vs tally)
- **Re-submit variant**: when `version >= 1`, show a diff list — for every bar item whose `next` differs from `applied`, render a row "{name}: {previous} → {next} (Δ {signed_delta})"; also list notes/todos that would be appended or removed
- Primary button label: "Endgültig einreichen" on first submit, "Aktualisierung bestätigen" on re-submit; loading state

### T5.9 — SubmittedView
**File:** `frontend/src/pages/admin/fahrbericht/SubmittedView.vue` (new)
**Details:**
- Read-only mirror of the AbschlussTab summary
- "Bearbeiten" button — calls `reopen(tourId)` and navigates back to the editable FahrberichtPage. Confirmation sheet before reopen: "Der Bericht wurde bereits eingereicht. Beim nächsten Speichern wird eine Aktualisierung erzeugt und das Finance-Team wird erneut benachrichtigt."
- Version badge in the header: "Version N · Eingereicht am {submitted_at} von {submitted_by}"
- Links: "Bericht ansehen" (spec 013) and "Seiteneffekte erneut anwenden" (if the submit result carried warnings about failed side effects)

### T5.10 — Router integration
**File:** `frontend/src/router/index.js`
**Details:**
- Register the Fahrbericht route with `meta: { hideTabBar: true }` (full-screen focused flow)
- Add `beforeEnter` guard that creates a DRAFT if none exists (optional — or handle in the page's mount logic per T5.1)

### T5.11 — Link from TourDetailPage's Fahrbericht tab
**File:** `frontend/src/pages/admin/TourDetailPage.vue`
**Details:**
- Replace the placeholder introduced in spec 010 (T4.3) with:
  - When a Fahrbericht exists (DRAFT or SUBMITTED): "Bericht öffnen" → `/admin/tours/{id}/fahrbericht`
  - When not: "Bericht starten" → calls `createDraft` then routes
- Show the Fahrbericht status badge next to the link

---

## Phase 6: UX Details

### T6.1 — Autosave indicator
**File:** `frontend/src/components/fahrbericht/SaveIndicator.vue` (new)
**Details:**
- Small pill rendered in the PageHeader right-slot
- States: Gespeichert vor N Sek. / Ungespeicherte Änderungen / Speichern fehlgeschlagen
- Reactive to `useFahrberichtActions`'s `saveStatus`

### T6.2 — Counter hold-to-repeat (optional)
**File:** `frontend/src/components/bar/CounterRow.vue`
**Details:**
- Add pointerdown/up handlers to `+` / `−` buttons — repeat at 50ms after a 400ms hold
- Only on mobile (pointer: coarse media query) — desktop keeps single-click
- If complex to implement well, defer per spec's Offene Fragen point 6

### T6.3 — Booking text copy toast
**File:** `frontend/src/pages/admin/fahrbericht/AbschlussTab.vue`
**Details:**
- Reuse existing `useToast` from spec 008
- On copy success: "Buchungstext kopiert"

### T6.4 — Conflict refetch toast
**File:** `frontend/src/composables/useFahrberichtActions.js`
**Details:**
- When autosave returns 409: show toast "Ein anderer Crew-Member hat gerade gespeichert. Neueste Version wird geladen." and refetch
- Warn user if they had unsaved local changes that are now overwritten

---

## Phase 7: Tests

### T7.1 — Fahrbericht service unit tests
**File:** `backend/tests/unit/test_fahrbericht_service.py` (new)
**Details:**
- `moto[dynamodb]` + `mock_aws`
- Cases:
  - DRAFT create → 409 on duplicate
  - Upsert partial patch
  - First submit: Tour becomes COMPLETED, bar/ship/report services called with `version=1`, applied_* fields populated afterwards
  - Submit with inactive bar_item_id in tally → rejected
  - Submit side-effect failure → Fahrbericht is SUBMITTED, warnings populated
  - Reopen: status=DRAFT, version unchanged
  - Re-submit after reopen: calls `apply_consumption_delta` with correct `previous`/`next`, calls `apply_ship_status_versioned` with correct `applied_*_ids`, creates a new Report version
  - Reapply-side-effects at current version: idempotent, does not double-apply
  - Delete DRAFT works; delete SUBMITTED → 409

### T7.2 — Booking text unit tests
**File:** `backend/tests/unit/test_booking_text.py` (new)
**Details:**
- Given a fixture Fahrbericht + Tour + catalog → produces expected text
- Snapshot-test-friendly single-string output

### T7.3 — API contract tests
**File:** `backend/tests/contract/test_fahrbericht_routes.py` (new)
**Details:**
- Auth guard
- Upsert, submit, reapply routes
- 409s on status-mismatch cases

### T7.4 — Frontend unit tests (if test harness present)
**File:** `frontend/src/utils/__tests__/bookingText.spec.js`
**Details:**
- Mirror T7.2 on the frontend to catch divergence

### T7.5 — Manual end-to-end walkthrough
**File:** (no file — checklist in PR description)
**Details:**
- Per project convention (AGENTS.md), UI changes include a manual smoke test at mobile viewport
- Steps: create Tour → open Fahrbericht → tally a few items → submit → verify bar catalog stock decreased, ship state updated, report exists (spec 013)

---

## Execution Order

```
T1.1 → T1.2                                        (Model + keys)
  ↓
T2.1 → T2.2 → T2.2b → T2.3 → T2.4                   (Service + submission pipeline + reopen)
  ↓
T3.1 → T3.2                                         (API)
  ↓
T4.1 → T4.2 → T4.3                                  (Frontend API + composable + booking text)
  ↓
T5.1 → T5.2 → T5.3 → T5.4 → T5.5 → T5.6 → T5.7 → T5.8 → T5.9 → T5.10 → T5.11   (Pages & tabs)
  ↓
T6.1 → T6.2 → T6.3 → T6.4                          (UX polish)
  ↓
T7.1 → T7.2 → T7.3 → T7.4 → T7.5                   (Tests + smoke)
```

Note: T5.2's crew-list and T5.5's tile components should ideally land as reusable components in spec 010 / spec 011 respectively. If they haven't been extracted there, extract them as part of this spec's work and update the earlier specs' tasks to reference the shared component.
