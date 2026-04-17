# 010 — Schaluppe Tour & Crew: Tasks

## Phase 1: Data Model

### T1.1 — Create Tour model
**File:** `backend/app/models/tour.py` (new)
**Details:**
- Pydantic v2 models:
  - `TourStatus` enum: `PLANNED`, `IN_PROGRESS`, `COMPLETED`, `ARCHIVED`
  - `CrewRef` submodel: `display_name: str`, `admin_user_id: UUID | None = None`
  - `Tour` — all fields listed in spec (id, event_id, name, date, duration_hours, guest_count, charterer, funker: CrewRef | None, skipper: CrewRef | None, crew: list[CrewRef], status, created_at, updated_at, created_by)
  - `TourCreate` — required: `date`; optional rest
  - `TourPatch` — all fields Optional, used for PATCH endpoint
  - `TourResponse` — identical to Tour for MVP
- Follow the field conventions in `backend/app/models/event.py` (datetime UTC, UUID ids, `model_config = ConfigDict(...)` as needed)
- Use `Decimal` for `duration_hours` (matches how monetary/fractional values are handled elsewhere)

### T1.2 — Define Tour DynamoDB keys + indexes
**File:** `backend/app/services/config.py`
**Details:**
- Extend the existing `DynamoDBSettings` / table accessor helpers with constants:
  - `TOUR_PK_PREFIX = "TOUR#"`, `TOUR_SK = "META"`
  - `TOURS_LIST_PK = "TOURS"`, SK format `"{date_iso}#{tour_id}"`
  - `EVENT_TOUR_PK_PREFIX = "EVENT#"`, `EVENT_TOUR_SK = "TOUR"` (for uniqueness)
- The main table already holds these items; no CDK change needed if it's a single-table design. If the existing table has a GSI that can serve the list query by PK/SK prefix, reuse it; otherwise see T1.3.

### T1.3 — CDK: GSI for tour listing (if not already served)
**File:** `infra/` (CDK stack that defines the DynamoDB table)
**Details:**
- Verify whether an existing GSI supports `pk = "TOURS"` + SK begins-with date prefix queries
- If not: add a GSI that projects the required attributes (or confirm the base table scheme supports these queries). Align with the team's single-table pattern
- Document in the spec/CDK if this is the first new GSI since the initial table — capacity/cost note

---

---

## Phase 1b: AdminUser Crew Roles

### T1b.1 — Add `CrewRole` enum and extend AdminUser
**File:** `backend/app/models/admin.py`
**Details:**
- New enum `CrewRole` with members: `FUNKER`, `SKIPPER`, `BARCREW`, `BOARDING`, `ALLROUNDER`
- Add `crew_roles: set[CrewRole] = Field(default_factory=set)` to `AdminUser`
- Not related to `AdminRole` — purely operational role self-selection

### T1b.2 — Persist `crew_roles` in DynamoDB
**File:** `backend/app/services/admin_service.py` (or wherever AdminUser serialization lives — identify during implementation)
**Details:**
- Serialize `crew_roles` as a DynamoDB string set (`SS`) — or an empty attribute when the set is empty
- Deserialize absent attribute as `set()` (backward compatible)
- Add method `update_crew_roles(admin_id: UUID, roles: set[CrewRole]) -> AdminUser`

### T1b.3 — Suggestion service method
**File:** `backend/app/services/admin_service.py`
**Details:**
- `list_crew_suggestions(role: CrewRole | None, q: str | None, limit: int = 10) -> list[AdminUser]`
- Scans admins in the org; filters by role membership (when set) and case-insensitive substring match on email/name
- Ranks: exact role match first, alphabetical fallback
- Used by the autocomplete endpoint

### T1b.4 — Routes for profile + suggestions
**File:** `backend/app/api/admin/profile.py` (new)
**Details:**
- `APIRouter(prefix="/me", tags=["admin.profile"])`
  - `GET /me` → current AdminUser (includes `crew_roles`)
  - `PATCH /me` → body `{ crew_roles: [...] }`
- `APIRouter(prefix="/crew-suggestions")`
  - `GET /crew-suggestions?role=&q=` → `list[{admin_user_id, display_name, email, crew_roles}]`
- Both behind the existing Auth0 admin guard

### T1b.5 — Register routers
**File:** `backend/app/main.py`
**Details:**
- `app.include_router(profile_router, prefix="/api/admin")`
- `app.include_router(crew_suggestions_router, prefix="/api/admin")`

### T1b.6 — Frontend: ProfilePage
**File:** `frontend/src/pages/admin/ProfilePage.vue` (new)
**Details:**
- Route: `/admin/profile`
- Title "Mein Profil" with PageHeader
- Section "Ich kann an Bord:" with one checkbox per CrewRole (German labels: Funker*in, Skipper, Bar-Crew, Boarding, Allrounder)
- Save on blur; small "Gespeichert"/"Fehler" indicator
- Entry point: add a ListItemButton on SettingsPage (`frontend/src/pages/admin/SettingsPage.vue`) at the top of the menu

### T1b.7 — Frontend: CrewRef autocomplete component
**File:** `frontend/src/components/tour/CrewRefInput.vue` (new)
**Details:**
- Props: `modelValue: CrewRef | null`, `roleFilter: CrewRole | null`, `placeholder: string`
- v-model binding emits `{display_name, admin_user_id}` (or null when cleared)
- Debounced (~200ms) GET `/api/admin/crew-suggestions?role=...&q=...`
- Dropdown list below the input; keyboard navigation (ArrowUp/Down + Enter)
- When a suggestion is selected: both fields populated; show a small "verlinkt" chip
- When the user leaves the field with unselected typed text: store `{display_name: typed, admin_user_id: null}` — free-text fallback
- Shared by TourDetailPage's Crew tab and spec 012's Fahrbericht Fahrt tab

---

## Phase 2: Service Layer

### T2.1 — Create TourService
**File:** `backend/app/services/tour_service.py` (new)
**Details:**
- Singleton + lazy init pattern matching `backend/app/services/registration_service.py`:
  ```python
  _service = None
  def get_tour_service() -> TourService: ...
  ```
- Methods:
  - `create_tour(data: TourCreate, created_by: str) -> Tour` — generates id, timestamps, default status=PLANNED; fails with `ValueError("event already has a tour")` when `event_id` collides (check via `GET EVENT#{event_id}#TOUR`)
  - `get_tour(tour_id: UUID) -> Tour | None`
  - `get_tour_for_event(event_id: UUID) -> Tour | None`
  - `list_tours(status: TourStatus | None, from_date: date | None, to_date: date | None, limit: int, cursor: str | None) -> tuple[list[Tour], str | None]`
  - `update_tour(tour_id: UUID, patch: TourPatch) -> Tour | None` — uses `model_copy(update={...})`, enforces status-transition rules (see spec's diagram)
  - `delete_tour(tour_id: UUID) -> None` — conditional: fails with `ValueError("tour has fahrbericht")` if a Fahrbericht exists (stubbed call to `fahrbericht_service` from spec 012; for now just check for `sk = FAHRBERICHT` under the same pk)
  - `transition_to_completed(tour_id: UUID) -> None` — internal helper called by spec 012

### T2.2 — Implement conditional write for event_id uniqueness
**File:** `backend/app/services/tour_service.py`
**Details:**
- On `create_tour` with `event_id` set:
  1. Write the Tour item (`TOUR#{id}` / `META`)
  2. Write the pointer item (`EVENT#{event_id}` / `TOUR` with `tour_id` attribute) using `ConditionExpression="attribute_not_exists(pk)"`
  3. If step 2 fails, roll back the Tour write
- Document the two-step write in comments as the single place that enforces the invariant

---

## Phase 3: API Routes

### T3.1 — Create tour admin router
**File:** `backend/app/api/admin/tours.py` (new)
**Details:**
- `APIRouter(prefix="/tours", tags=["admin.tours"])`
- Endpoints per spec:
  - `GET /` → list with query params
  - `POST /` → create, returns 201 + Tour
  - `GET /{tour_id}` → fetch
  - `PATCH /{tour_id}` → update
  - `DELETE /{tour_id}` → delete; returns 409 when Fahrbericht exists
- All endpoints behind the existing Auth0 admin dependency (match pattern in `backend/app/api/admin/events.py`)
- Error translation: `ValueError` → 409 with `detail`

### T3.2 — Event/tour convenience routes
**File:** `backend/app/api/admin/events.py`
**Details:**
- Add two routes to the existing events router:
  - `GET /events/{event_id}/tour` → 404 or Tour
  - `POST /events/{event_id}/tour` → create pre-filled tour; body optional overrides
- Both delegate to `tour_service`

### T3.3 — Register router in app
**File:** `backend/app/main.py`
**Details:**
- `app.include_router(admin_tours_router, prefix="/api/admin")`

---

## Phase 4: Frontend — Tour Pages

### T4.1 — Add tour admin API client
**File:** `frontend/src/services/api.js`
**Details:**
- Add `adminApi.tours`:
  - `list(params)` → `GET /api/admin/tours`
  - `create(body)` → `POST /api/admin/tours`
  - `get(id)` → `GET /api/admin/tours/{id}`
  - `patch(id, body)` → `PATCH /api/admin/tours/{id}`
  - `delete(id)` → `DELETE /api/admin/tours/{id}`
  - `getForEvent(eventId)` → `GET /api/admin/events/{eventId}/tour`
  - `createForEvent(eventId, body)` → `POST /api/admin/events/{eventId}/tour`

### T4.2 — TourListPage
**File:** `frontend/src/pages/admin/TourListPage.vue` (new)
**Details:**
- Route: `/admin/tours`
- Filter tabs (All / Planned / In Progress / Completed / Archived) — mirror the tab implementation in `EventsPage.vue`
- List items use the `.list-group` card pattern from spec 008 (reuse classes in `design-tokens.css`)
- Each row: date, name, crew summary, status badge
- FAB "Neue Tour" using `IconButton` + the FAB layout added in commit 9be5787
- Empty state message

### T4.3 — TourDetailPage
**File:** `frontend/src/pages/admin/TourDetailPage.vue` (new)
**Details:**
- Route: `/admin/tours/:id`
- Tab layout mirrored from `EventDetailPage.vue` (Details / Crew / Fahrbericht)
- Details tab: inline-editable fields, status badge
- Crew tab: Funker (`CrewRefInput` with `roleFilter=FUNKER`), Skipper (`CrewRefInput` with `roleFilter=SKIPPER`), Crew list (array of `CrewRefInput` rows with `roleFilter=null`). Each additional crew row uses `ListItemButton` per row with trailing `Trash2` icon
- Fahrbericht tab: placeholder button "Bericht öffnen" / "Bericht starten" — wired in spec 012
- Reuse `PageHeader` component for the top bar

### T4.4 — TourCreatePage / inline form
**File:** `frontend/src/pages/admin/TourCreatePage.vue` (new) or dialog component
**Details:**
- Route: `/admin/tours/new` (accepts `?event_id=...` to pre-fill)
- Form fields: name, date (default today), duration_hours, guest_count, charterer
- On submit: POST, redirect to detail page

### T4.5 — useTourActions composable
**File:** `frontend/src/composables/useTourActions.js` (new)
**Details:**
- Matches the pattern in `frontend/src/composables/useEventActions.js`
- Exposes: `createTour`, `patchTour`, `deleteTour`, `archiveTour`, `unarchiveTour`, plus loading/error refs
- Used by TourListPage and TourDetailPage

### T4.6 — Router integration
**File:** `frontend/src/router/index.js`
**Details:**
- Add three routes (`TourListPage`, `TourDetailPage`, `TourCreatePage`) behind the admin auth guard
- Add `meta: { hideTabBar: false }` so the existing bottom tab bar stays visible (matches EventsPage)

### T4.7 — Nav entry for Tours
**File:** `frontend/src/App.vue` (or wherever `frontend/src/components/BottomNav.vue` lives)
**Details:**
- Add a "Touren" entry to the primary nav, icon `Anchor` from `lucide-vue-next`
- Active state uses `.router-link-active` — already styled from spec 008

### T4.8 — EventDetailPage integration
**File:** `frontend/src/pages/admin/EventDetailPage.vue`
**Details:**
- At the top of the "Details" tab, add a "Tour" section:
  - If `adminApi.tours.getForEvent(eventId)` returns a Tour: show crew summary + link "Tour öffnen" → `/admin/tours/{id}`
  - Otherwise: show button "Tour anlegen" that calls `createForEvent` and routes to the new tour
- Reuse the existing `.list-group` card look so it visually fits inline

---

## Phase 5: Status Badges

### T5.1 — Add tour status badge styles
**File:** `frontend/src/assets/design-tokens.css`
**Details:**
- Add classes following the existing `.status-badge` pattern:
  - `.status-planned` (neutral grey)
  - `.status-in-progress` (info blue)
  - `.status-completed` (success green)
  - `.status-archived` (muted)
- Use the same token variables as the registration/event badges

### T5.2 — Add `formatTourStatus()` helper
**File:** `frontend/src/utils/formatters.js`
**Details:**
- Add function mapping:
  - `PLANNED` → `Geplant`
  - `IN_PROGRESS` → `Läuft`
  - `COMPLETED` → `Abgeschlossen`
  - `ARCHIVED` → `Archiviert`

---

## Phase 6: Tests

### T6.1 — Tour service unit tests
**File:** `backend/tests/unit/test_tour_service.py` (new)
**Details:**
- Use `moto[dynamodb]` + `mock_aws` per project convention (see Memory note)
- Cases:
  - create_tour → item persisted, pointer item written when event_id set
  - create_tour with duplicate event_id → ValueError
  - update_tour transitions legal/illegal
  - delete_tour with Fahrbericht stub present → ValueError
  - list_tours filters by status/date range

### T6.2 — Tour API contract tests
**File:** `backend/tests/contract/test_tour_routes.py` (new)
**Details:**
- Use the existing httpx+pytest-asyncio fixtures
- Unauthenticated admin → 401
- CRUD happy paths
- 409 on duplicate event_id

### T6.3 — Frontend component tests (best-effort)
**File:** `frontend/src/pages/admin/__tests__/TourListPage.spec.js` (new — if test harness exists)
**Details:**
- If a frontend test runner is set up: snapshot the filter tabs and empty state
- Otherwise: note as deferred until the project adopts a Vitest/Playwright setup

---

## Phase 7: Documentation

### T7.1 — Update AGENTS.md
**File:** `AGENTS.md`
**Details:**
- Short note in the "Models" / "Services" sections: Tours live in `backend/app/models/tour.py` and `backend/app/services/tour_service.py`, with the same singleton-lazy-init convention as registrations
- Mention the two-write event-link invariant so future developers don't break it

---

## Execution Order

```
T1.1 → T1.2 → T1.3                          (Tour model + keys + index)
  ↓
T1b.1 → T1b.2 → T1b.3 → T1b.4 → T1b.5       (AdminUser crew roles + suggestions — backend)
  ↓
T2.1 → T2.2                                  (Tour service, incl. uniqueness)
  ↓
T3.1 → T3.2 → T3.3                           (API routes)
  ↓
T5.1 → T5.2                                  (Design tokens + formatters)
  ↓
T1b.6 → T1b.7                                (ProfilePage + CrewRefInput — must land before T4.3)
  ↓
T4.1 → T4.2 → T4.3 → T4.4 → T4.5 → T4.6 → T4.7 → T4.8   (Tour frontend)
  ↓
T6.1 → T6.2 → T6.3                           (Tests)
  ↓
T7.1                                         (Docs)
```
