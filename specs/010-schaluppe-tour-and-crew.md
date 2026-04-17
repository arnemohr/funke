# 010 — Schaluppe Tour & Crew

## Summary

Introduce **Schaluppe Tours** — a crew-facing wrapper around a trip with the Schaluppe. A Tour captures who was on board working (crew), who chartered it, and when it happened. A Tour may be linked to an existing Event (public boat party with lottery-managed registrations) or stand alone for a private charter that never had a guest-facing registration flow.

Tours are the foundation for the Fahrbericht (spec 012). They hold the crew roster used by every downstream report and act as the parent record that aggregates what happened on the boat.

## Problem

1. The app only models **guest-facing Events** today. There is no concept of "who worked the tour" — no crew roster, no Funker, no Skipper.
2. **Private charters** (a customer books the Schaluppe for their own group) don't fit Events at all — there is no registration, no lottery, no capacity. But the crew still needs to track fuel, drinks consumed, cash, and ship state for these trips.
3. Without a Tour entity, a Fahrbericht would have to either live on Events (breaking private charters) or float without an owning record.

## Scope

This spec is the **foundation of the 010–013 series**. It introduces:

- The `Tour` data model and API.
- Admin UI to list Tours and manage crew.
- Integration points for specs 011–013 (BarItem consumption, Ship state, Fahrbericht, Report).

Out of scope:
- The Fahrbericht form itself (spec 012).
- Bar catalog, ship state, consumption tracking (spec 011).
- PDF/email of closing reports (spec 013).
- A dedicated crew-member directory separate from Admin users (we extend the existing `AdminUser` with role self-selection — see User Profile & Crew Roles).

## Data Model

### Tour

DynamoDB keys: `pk = TOUR#{tour_id}`, `sk = META`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | Tour identifier |
| `event_id` | UUID \| None | Optional link to a public Event. None for private charters |
| `name` | str | Display name. Defaults from linked Event's name when present, otherwise free text |
| `date` | date (ISO) | Trip date — the day the tour happens |
| `duration_hours` | Decimal \| None | Planned or actual duration in hours (step 0.5) |
| `guest_count` | int \| None | Number of guests on board |
| `charterer` | str \| None | Free text — name of the charter customer or event host |
| `funker` | `CrewRef` \| None | Person responsible (Funker*in). Free text or a pointer to an AdminUser |
| `skipper` | `CrewRef` \| None | Skipper |
| `crew` | list[`CrewRef`] | Additional crew members. Defaults to `[]` |
| `status` | enum | `PLANNED`, `IN_PROGRESS`, `COMPLETED`, `ARCHIVED` |
| `created_at` | datetime | UTC |
| `updated_at` | datetime | UTC |
| `created_by` | str | Auth0 sub of the admin who created the Tour |

### CrewRef

Crew slots (`funker`, `skipper`, `crew[*]`) use a lightweight reference so a tour can be filled in quickly as **free text** but can also be **linked to an AdminUser profile** for autocomplete, role hints, and future reporting. Once an AdminUser profile exists for "Max Müller" with role `SKIPPER`, typing "Max" in the Skipper field suggests that profile; picking the suggestion stores the reference; finishing the field as plain text stores a bare name.

```python
class CrewRef(BaseModel):
    display_name: str                    # Always present, always shown in lists and the PDF
    admin_user_id: UUID | None = None    # Populated when the crew member has a linked AdminUser profile
```

Readers only need `display_name` to render. Writers store `admin_user_id` when the user picked from autocomplete. A stale `admin_user_id` (profile deleted later) is tolerated — the `display_name` is always authoritative for display.

### Status transitions

```
PLANNED ──────► IN_PROGRESS ──────► COMPLETED ──────► ARCHIVED
   │                │                    ▲
   │                │                    │
   └────────────────┴────────────────────┘
       (manual transitions)      (auto on Fahrbericht submit — spec 012)
```

- **PLANNED**: freshly created. Editable.
- **IN_PROGRESS**: optional — admin may mark a Tour as running; mostly a UI hint. Editable.
- **COMPLETED**: set automatically when a Fahrbericht is submitted (spec 012). Tour metadata becomes read-only; only crew is still editable (corrections).
- **ARCHIVED**: manual, admin-only. Hides from default list. Reversible.

### Relation to Events

A Tour with `event_id` set inherits defaults (name, date) from the Event on creation. The Tour may diverge from the Event afterwards; changes to the Event do **not** rewrite Tour fields.

A single Event can have at most one Tour. This is enforced on the backend via a conditional write against the `event_id` (there is a uniqueness index described below).

### Indexes

- `GSI1`: `pk = TOURS`, `sk = {date}#{tour_id}` — used to list all Tours chronologically.
- `GSI2`: `pk = EVENT#{event_id}`, `sk = TOUR` — used for the uniqueness check and for `GET /events/{event_id}/tour`.

Both indexes follow the single-table conventions already used for Registrations (`backend/app/services/registration_service.py`).

## API

All routes under `/api/admin/` require the existing Auth0 admin guard — no public routes.

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/admin/tours` | List Tours. Query params: `status`, `from_date`, `to_date`, `limit`, `cursor` |
| `POST` | `/api/admin/tours` | Create a Tour. Body: all Tour fields except timestamps. If `event_id` is set and already used, returns 409 |
| `GET`  | `/api/admin/tours/{tour_id}` | Fetch single Tour |
| `PATCH`| `/api/admin/tours/{tour_id}` | Partial update. 409 when transitioning from COMPLETED for non-crew fields |
| `DELETE`| `/api/admin/tours/{tour_id}` | Delete a Tour. 409 if a Fahrbericht exists (spec 012 cross-ref) |
| `GET`  | `/api/admin/events/{event_id}/tour` | Convenience lookup: returns the single Tour for an Event or 404 |
| `POST` | `/api/admin/events/{event_id}/tour` | Convenience creator: creates a Tour pre-filled from the Event |

Crew management is just a PATCH on the Tour (fields `funker`, `skipper`, `crew`). No separate crew endpoints for MVP.

### Validation rules

- `date` is required on create.
- `name` is required if `event_id` is not set; otherwise it defaults to the Event's name.
- `crew` entries are trimmed; empty strings are dropped before storage.
- `status` can only move forward by one step from the admin UI (no jumping PLANNED → COMPLETED manually — that happens via Fahrbericht submission only).

## User Profile & Crew Roles

Crew slots accept free text for MVP, but the app should already be able to **suggest** known crew members. To do that without introducing a separate crew directory, we extend the existing `AdminUser` model (`backend/app/models/admin.py`) with a set of self-declared crew roles — a user opens their profile and ticks which jobs they're willing to do on the Schaluppe.

### CrewRole enum

```
FUNKER      — Funker*in / tour responsible
SKIPPER     — boat operator
BARCREW     — bar service
BOARDING    — guest reception / boarding
ALLROUNDER  — wildcard
```

### AdminUser extension

Add one field to `AdminUser`:

| Field | Type | Notes |
|-------|------|-------|
| `crew_roles` | set[`CrewRole`] | Defaults to empty. Persisted alongside the existing admin item |

Serialized as a DynamoDB string set. Backward compatible — absent values deserialize to `set()`.

No changes to `AdminRole` (the existing Owner/Admin/Viewer access-control concept). `CrewRole` is purely about **operational roles on the boat** and has no effect on permissions.

### Profile page

New route: `/admin/profile` (inside the existing SettingsPage or as a standalone page — `ProfilePage.vue`).

- Section "Ich kann an Bord:" with one checkbox per `CrewRole`
- Save writes back via `PATCH /api/admin/me` (new endpoint — returns the AdminUser with the updated `crew_roles`)
- Shown in the app's Settings menu as a top entry

### Autocomplete API

New endpoint (read-only, admin-guarded):

- `GET /api/admin/crew-suggestions?role={role}&q={query}` → list of `{admin_user_id, display_name, email, crew_roles}` for matching AdminUsers. Ranking: exact role match first, fuzzy name match second.

The Tour detail's crew editor uses this to populate a dropdown under each input: typing "Ma" in the Skipper field calls `?role=SKIPPER&q=Ma`; the results appear as an autocomplete list. Selecting an entry stores a `CrewRef` with both `display_name` and `admin_user_id`. Typing a name that doesn't match any suggestion simply stores a `CrewRef` with `admin_user_id = None` (free-text fallback).

This is additive — the field remains fully free-text. Crews who haven't set up their profile are unaffected.

## UI

### Routes

- `/admin/tours` — Tour list
- `/admin/tours/{id}` — Tour detail
- `/admin/tours/new` — Create Tour form (also reachable from an Event)
- `/admin/profile` — the profile page described above

### Tour list page (`/admin/tours`)

- Title: "Touren" (new left-nav entry between "Veranstaltungen" and "Einstellungen").
- Filter tabs mirror the `EventsPage.vue` pattern: "Alle", "Geplant", "Läuft", "Abgeschlossen", "Archiviert".
- Each Tour row uses the existing list-group styling (`frontend/src/components/ListItemButton.vue`-style card): date + name on top, crew summary (e.g. "Anna (Funker) · Max (Skipper) · +2") on a sub-line, status badge on the right.
- FAB bottom-right: "Neue Tour" — opens the create form.
- Empty state: "Noch keine Touren. Leg die erste an, sobald die Schaluppe ablegt."

### Tour detail page (`/admin/tours/{id}`)

Uses the tab-nav pattern established in `frontend/src/pages/admin/EventDetailPage.vue`. Tabs:

1. **Details** — name, date, duration, guest count, charterer, event link (if any), status badge. All fields inline-editable.
2. **Crew** — three fields (each a CrewRef editor, see below):
   - Funker*in (single CrewRef input, autocomplete filtered to `role=FUNKER`)
   - Skipper (single CrewRef input, autocomplete filtered to `role=SKIPPER`)
   - Weitere Crew (list of CrewRef rows — add/remove rows; each row autocompletes unfiltered across all crew roles). Uses `ListItemButton` per row with a trailing trash icon from `lucide-vue-next`.
   - A CrewRef input is a text input with a dropdown of suggestions beneath it. When the user types and no suggestion is chosen, the value is stored as `{display_name: "<typed text>", admin_user_id: null}`. Selecting a suggestion fills in both fields. A small chip indicator shows when the row is linked to a profile.
3. **Fahrbericht** — deep link into spec 012. Shown as a placeholder in this spec: either "Bericht öffnen" (if one exists) or "Bericht starten" (creates a DRAFT Fahrbericht). This tab is implemented in spec 012.

### Integration with EventDetailPage

Inside `frontend/src/pages/admin/EventDetailPage.vue`, add a new section "Tour" above the existing tab content (or a new tab — see Offene Fragen):

- If the Event has a linked Tour: show crew summary + link "Tour öffnen".
- If not: show a single button "Tour anlegen" → creates a Tour pre-filled with the Event's name + start date, then redirects to the Tour detail.

This is the main way crew reaches the Tour record from the existing event workflow.

### Visual conventions (matches project voice)

- German UI text throughout.
- Mobile-first: every form field is full-width below 640px. Crew list rows use 44px minimum touch targets.
- Icons from `lucide-vue-next` (matching the refresh in commit 9be5787): `Calendar`, `Users`, `Anchor`, `ChevronRight`, `Trash2`.
- Status badges use the existing `.status-badge` class from `frontend/src/assets/design-tokens.css`. Add the four Tour statuses there: `status-planned` (neutral), `status-in-progress` (info blue), `status-completed` (success green), `status-archived` (muted grey).
- Reuse `PageHeader` for the detail page's top bar.
- Reuse `ActionSheet` for the "Crew hinzufügen" interaction on mobile (bottom sheet with a single text input + save).

## Integration points for later specs

- **Spec 011**: When `apply_consumption` needs to attribute a consumption write to a Tour, it will receive `tour_id` from the Fahrbericht.
- **Spec 012**: The Fahrbericht lives at `pk = TOUR#{tour_id}`, `sk = FAHRBERICHT` — same partition as the Tour, so the Tour + its report are co-located in DynamoDB.
- **Spec 012 submission**: Transitions the Tour from any pre-state to `COMPLETED` atomically alongside the Fahrbericht state change.
- **Spec 013**: The closing Report references the Tour via `tour_id` for its identification and deep-link back to this admin UI.

## Backward compatibility

- New tables/indexes only. No existing data is touched.
- Existing Events continue to work identically; the "Tour" section on `EventDetailPage.vue` is additive.
- No public API surface changes. All new endpoints sit under `/api/admin/`.

## Testing

- Unit tests for `tour_service.py` using `moto[dynamodb]` + `mock_aws`, following the pattern in `backend/tests/` for `registration_service`.
- Contract tests for the admin routes (create/list/update/delete, conflict on duplicate `event_id`).
- Frontend component tests for the Tour list filter tabs and the crew editor.

## Offene Fragen

Capture during implementation:

1. **Crew directory scope**: we extend `AdminUser` with `crew_roles` for MVP. Non-admin crew members (e.g. occasional volunteers without app accounts) still appear as free-text names. Recommendation: ship as specced; add a "non-admin crew" directory only if operational need surfaces.
2. **EventDetailPage integration**: inline section vs new tab. Recommendation: inline section at the top of the "Details" tab, since a full tab for one link is heavy.
3. **Deletion policy**: hard-delete vs soft-delete (archive). MVP: hard-delete allowed only before Fahrbericht creation; after, admin can only archive.
4. **Tour status on create**: always start at `PLANNED`, or allow creating `IN_PROGRESS` directly from the "Tour anlegen" button mid-trip. Recommendation: always `PLANNED` — one extra click is fine.
