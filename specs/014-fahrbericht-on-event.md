# 014 — Fahrbericht on Event, Schaluppe & Bar Navigation

## Summary

Remove the separate **Tour** concept introduced in spec 010. A Fahrbericht is now a direct child of an Event — one Event, optionally one Fahrbericht, period. At the same time, promote **Schaluppe** and **Bar** to top-level entries in the bottom nav so the things the crew touches most often aren't buried three levels deep under Einstellungen.

Every trip is an Event. Private charters are just Events with few or zero public registrations — no new entity, no type enum. Crew selection (Funker, Skipper, weitere Crew) moves from the Tour page onto the Fahrbericht itself, where the rest of the trip data already lives.

## Problem

1. **Two entities, one real thing.** "Event" and "Tour" describe the same trip. Users have to think "is this the event or the tour?" and the answer is always "both". That's a concept bug, and it leaks into the UI: Event detail → "Tour öffnen" → Tour detail → "Bericht öffnen" → Fahrbericht is three hops for one intent.
2. **Hidden navigation.** The current bottom nav is *Events / Einstellungen / Debug*. Every Schaluppe-specific task (update water-fill date, add a drink, view a past report, edit crew roles) lives inside a "Schaluppe" section under Einstellungen. Non-technical users have to remember that "Schaluppe" hides inside "Einstellungen" instead of just tapping a boat icon. This violates the rule of matching navigation to the user's mental model.
3. **Tour state machine adds nothing.** Tour's PLANNED/IN_PROGRESS/COMPLETED/ARCHIVED statuses duplicate Event's DRAFT/OPEN/.../COMPLETED lifecycle. Fahrbericht's DRAFT/SUBMITTED covers the part that actually matters for reporting. The Tour status layer was friction without value.
4. **Private charters forced a workaround.** Tour existed partly to handle trips without public registration. By saying "every trip is an Event" and accepting that some Events never get published, we drop that workaround.

## Scope

This spec:

- Deletes the Tour entity end-to-end (model, service, routes, pages, tables, CDK).
- Relocates the Fahrbericht onto the Events table — `pk = EVENT#{event_id}`, `sk = FAHRBERICHT`.
- Absorbs Tour's distinctive fields (duration, guest count, charterer, crew) onto the Fahrbericht.
- Restructures the admin bottom navigation to **Events / Schaluppe / Bar / Einstellungen**.
- Inlines the Fahrbericht entry point and the Report actions into the Event detail page.
- Removes the standalone cross-event Reports list; Reports are accessed per-Event only.
- Wipes existing Tour-partition data (confirmed: no real tours yet).

Out of scope:

- Any change to the Event model itself.
- Any change to the public registration flow.
- Migrating existing Tour rows (wiping is acceptable — no real data).
- Moving Profile out of Einstellungen.
- A cross-event aggregated Reports page.

## UI / Navigation

### Bottom navigation — four tabs

| Icon | Label | Route | Page |
|------|-------|-------|------|
| `Calendar` | Events | `/admin/events` | existing `EventsPage.vue` |
| `Anchor` | Schaluppe | `/admin/schaluppe` | existing `ShipStatePage.vue`, page header relabeled "Schaluppe" |
| `Beer` | Bar | `/admin/bar` | existing `BarCatalogPage.vue`, page header relabeled "Bar" |
| `Settings` | Einstellungen | `/admin/settings` | existing `SettingsPage.vue`, "Schaluppe" section removed |

`/admin/ship` redirects to `/admin/schaluppe` to keep old bookmarks working. Debug remains dev-mode-only as today.

### Why four items, not three

The user asked for "Events, Schaluppe, Bar". Einstellungen can't go away (push notifications, install prompt, profile, logout, version). A cog icon in the top header would be less obvious for non-technical users than a labeled bottom-nav entry. Four icons with German labels still fits comfortably on a 375px viewport.

### Event detail — Fahrbericht section

Inside `EventDetailPage.vue`, the old **"Tour & Fahrbericht"** section becomes a single **"Fahrbericht"** section with three possible states:

1. **No Fahrbericht yet** — one button: **"Fahrbericht starten"**. Clicking it creates a DRAFT and routes to `/admin/events/{eventId}/fahrbericht`.
2. **DRAFT exists** — row shows "Fahrbericht (Entwurf)" with a chevron, tapping opens the editor. Small status pill.
3. **SUBMITTED** — row shows "Fahrbericht eingereicht · v{N}" with a chevron to the read-only view. Secondary actions below: **"PDF öffnen"**, **"Bericht erneut senden"**. A "Bearbeiten" action sits inside the read-only view (reopens → DRAFT).

No separate Tour list. No "Tour anlegen" button.

### Schaluppe page (was Schiff-Status)

Identical page content as the current `ShipStatePage`: tile grid of fuel/water/CO2/battery/klos/persennig, open todos list, notes list. Only the `PageHeader` title changes to **"Schaluppe"** so the label matches the tab the user just tapped.

### Bar page

Identical page content as the current `BarCatalogPage`: grouped catalog with stock breakdown, low-stock badge, FAB to add items. Header relabeled to **"Bar"**. `back` prop removed since this is now a top-level destination.

### Einstellungen

The "Schaluppe" section added in spec 011 is removed entirely. The "Mein Profil & Crew-Rollen" entry moves into a renamed **"Mein Profil"** section at the top of Einstellungen (single entry). Everything else (Benachrichtigungen, App, Konto, Entwickleroptionen) stays.

### Flow summary for non-technical users

- *Report a trip* → tap **Events** → pick event → "Fahrbericht starten" → fill → submit.
- *Ship needs water tomorrow* → tap **Schaluppe** → tap "Wassertank gefüllt" tile → done.
- *Add a new drink* → tap **Bar** → FAB "Neues Getränk" → done.
- *Change my crew role* → tap **Einstellungen** → "Mein Profil" → done.

Four nouns, four obvious locations. No "Tour" jargon anywhere.

## Data Model

### Event (unchanged)

No schema change. No new fields. No new status transitions. The Event model's file `backend/app/models/event.py` is not touched.

### Fahrbericht (relocated + expanded)

**DynamoDB keys**: `pk = EVENT#{event_id}`, `sk = FAHRBERICHT` in the existing `funke-{env}-events` table.

**New fields absorbed from the deleted Tour**:

| Field | Type | Notes |
|-------|------|-------|
| `duration_hours` | `Decimal \| None` | Planned or actual duration (0.5 step) |
| `guest_count` | `int \| None` | Actual guests on board — distinct from `event.capacity` |
| `charterer` | `str \| None` | Charter customer / event host |
| `funker` | `CrewRef \| None` | Responsible person |
| `skipper` | `CrewRef \| None` | Boat operator |
| `crew` | `list[CrewRef]` | Additional crew |

**Existing fields** (unchanged from spec 012): `status`, `version`, `boarding_fee`, `bar_surcharge`, `kiosk_tally`, `crew_tally`, `applied_kiosk_tally`, `applied_crew_tally`, `applied_ship_notes_ids`, `applied_ship_todos_ids`, `ship_status`, `new_notes`, `new_todos`, `cash_amount`, `cash_handed_to`, `expenses`, `submitted_at`, `submitted_by`, `report_id`, `created_at`, `updated_at`.

**`CrewRef` submodel**: unchanged shape (`display_name: str`, `admin_user_id: UUID | None`). Moves from `backend/app/models/tour.py` into `backend/app/models/fahrbericht.py`.

### Fahrbericht submission — no Event.status change

The submission pipeline **does not mutate `event.status`**. Event status continues to reflect the registration lifecycle (DRAFT → OPEN → REGISTRATION_CLOSED → LOTTERY_PENDING → CONFIRMED → COMPLETED/CANCELLED). Fahrbericht has its own DRAFT → SUBMITTED lifecycle independent of it.

This decouples the two concerns:
- An Event in DRAFT (private charter, never published) can have a submitted Fahrbericht without needing a dummy transit through the lottery machine.
- An Event already in COMPLETED can have a late-added Fahrbericht without trying to "re-complete" it.

Admins still manually transition Events to COMPLETED/CANCELLED via the existing UI.

### Report pointer (moved)

- Old: `pk = TOUR#{tour_id}`, `sk = REPORT` in the tours table.
- New: `pk = EVENT#{event_id}`, `sk = REPORT` in the events table.

Report META rows (`pk = REPORT#{report_id}`, `sk = META`) and VERSION rows stay in `funke-{env}-reports` unchanged.

### Consumption & ship-state ledger (parameter rename only)

The ledger shape is identical — only the variable name changes from `tour_id` to `event_id`:

```
CONSUMPTION#{event_id}#v{version}
STATE#{event_id}#v{version}
```

Since all current ledger rows are about to be wiped with the tours table, there's no data migration — just a rename of keys going forward.

### Tour (deleted)

- `funke-{env}-tours` table removed from CDK.
- `backend/app/models/tour.py` — deleted.
- `backend/app/services/tour_service.py` — deleted.
- `backend/app/api/admin/tours.py` — deleted (this kills both the `/tours` CRUD routes and the `/events/{id}/tour` convenience routes).
- Frontend: `TourListPage.vue`, `TourDetailPage.vue`, `TourCreatePage.vue`, `useTourActions.js` — deleted (if the composable was ever created — verify before deleting).

### BarItem & ShipState (unchanged)

Models and tables untouched. The only change is the callers pass `event_id` instead of `tour_id` into `apply_consumption` / `apply_ship_status` — see the ledger rename above.

## API

### Fahrbericht — URL prefix change

| Method | Old path | New path |
|--------|----------|----------|
| `GET` | `/api/admin/tours/{tour_id}/fahrbericht` | `/api/admin/events/{event_id}/fahrbericht` |
| `POST` | same | same |
| `PUT` | same | same |
| `DELETE` | same | same |
| `POST /submit` | same | same |
| `POST /reopen` | same | same |
| `POST /reapply-side-effects` | same | same |

All method shapes, payloads, and response bodies unchanged apart from the path parameter.

### Reports — convenience lookup

- Old: `GET /api/admin/tours/{tour_id}/report`
- New: `GET /api/admin/events/{event_id}/report`

The rest of the Reports API (`/reports`, `/reports/{id}`, `/reports/{id}/versions/{v}`, `/reports/{id}/pdf`, `/reports/{id}/resend`) is unchanged but the **`GET /api/admin/reports` list route is removed** — no cross-event list, finance gets everything by email.

### Tours — routes deleted

All `/api/admin/tours/**` paths and the `/api/admin/events/{event_id}/tour` (GET + POST) routes go away.

## Migration

### Existing data

Confirmed with user: no real tours, Fahrberichte, or reports have been recorded yet. We **wipe** rather than migrate.

Steps (manual, one-time, at deploy):

1. `cdk deploy` — the new infra drops `funke-{env}-tours` via the CDK change.
2. Any leftover rows in the legacy bar-items / ship-state tables with `CONSUMPTION#{tour_id}#...` keys are orphaned but harmless. Optional cleanup (not required for correctness): a one-off scan+delete via the AWS console or a short script. Skipped in this spec.
3. Reports table: any META/VERSION rows pointing at deleted Tours are also orphaned. Harmless but can be cleaned up later.

### Backwards compatibility

- No existing public URLs break (public registration flow is untouched).
- Admin deep-links to `/admin/tours/**` return 404 after deploy. Acceptable — staff use the in-app nav, not bookmarks.
- `/admin/ship` kept as a frontend redirect to `/admin/schaluppe` so any recent bookmarks still land somewhere sensible.

## Testing

### Backend

- Existing test suite passes: `cd backend && python -m pytest tests/ --ignore=tests/unit/test_email_service.py` — the pre-existing unrelated email-template failure stays out of scope.
- Import smoke check: `python -c "from app.main import app"` succeeds with no `tour_service` imports.
- End-to-end happy path (moto) mirroring the prior spec 012 smoke test, but keyed by Event:
  1. Seed the bar catalog.
  2. Create an Event directly via `event_service.create_event()` — status stays DRAFT.
  3. `POST /api/admin/events/{id}/fahrbericht` → creates a DRAFT Fahrbericht.
  4. `PUT .../fahrbericht` with crew + tallies + cash.
  5. `POST .../fahrbericht/submit` → verify:
     - `bar_ok`, `ship_ok`, `report_ok` all true.
     - Event.status still DRAFT (decoupled from submission).
     - `GET /api/admin/events/{id}/report` returns META with `current_version = 1`.
     - `GET .../reports/{report_id}/pdf` returns valid `%PDF` bytes.
  6. Reopen + re-submit → Event.status still DRAFT, Report META.current_version advances to 2.

### Frontend

- `npm run build` — no dead imports, no missing routes.
- Manual smoke at mobile viewport (375px):
  - Bottom nav shows exactly four icons (plus Debug in dev mode). Labels: "Events", "Schaluppe", "Bar", "Einstellungen".
  - Tapping Schaluppe → tiles render; editing a tile persists via PATCH.
  - Tapping Bar → catalog list renders; "Bestand anpassen" ActionSheet works.
  - Events → pick event → "Fahrbericht starten" button visible when no Fahrbericht; tapping creates and navigates to the editor.
  - Fahrbericht submit produces a SubmittedView with "Bearbeiten", "PDF öffnen", "Bericht erneut senden" actions.
  - Einstellungen → shows "Mein Profil" at top; no Touren/Bar/Schiff/Fahrberichte entries.
  - Deep link to `/admin/ship` redirects to `/admin/schaluppe`.

## Offene Fragen

1. **ReportDetailPage**: keep it reachable via deep link for now, or delete along with the list? Recommendation: keep the page file, just remove the list route. The Event detail page can link to `/admin/reports/{id}` when a SUBMITTED Fahrbericht is displayed.
2. **CrewRefInput directory**: move from `frontend/src/components/tour/` to `.../crew/` — cosmetic only. Recommendation: defer, it's noise.
3. **`/admin/ship` redirect**: keep for one deploy then drop? Recommendation: keep, zero cost.
4. **Dev "Debug" tab**: stay pinned inline after the four main tabs, or collapse behind a hamburger when dev mode is on? Recommendation: stay inline — dev mode is already gated by the hidden tap-the-version gesture.

## Deliverable

This spec + its companion `014-tasks.md`. The spec supersedes the Tour portions of specs 010 and the navigation decisions in spec 011; specs 010–013 remain in `specs/` for historical reference.
