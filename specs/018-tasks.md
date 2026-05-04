# 018 — Modify Single Registrations: Tasks

Spec: [`018-modify-registrations.md`](./018-modify-registrations.md)

Each task is a single, mergeable unit of work. Order is staged so that every intermediate commit builds and the API replacement (PUT `…/group-members` → PUT `…`) lands atomically with its only caller (the new admin UI).

---

## Phase 1: Backend — Models

### T1.1 — Add the partial-update payload model
**File:** `backend/app/models/registration.py`
**Details:**
- Add a Pydantic v2 `RegistrationAdminPatch` model. All fields optional:
  - `name: str | None` — `min_length=1, max_length=200` after strip; reject all-whitespace.
  - `phone: str | None` — empty string allowed and means "clear".
  - `notes: str | None` — empty string allowed and means "clear"; `max_length=500`.
  - `group_size: int | None` — `ge=1`.
  - `group_members: list[str] | None` — each entry trimmed; each entry `min_length=1, max_length=200` after strip.
- Add a `model_validator(mode="after")` that strips `name`, every `group_members` entry, and `notes`/`phone` if non-None. Reject empties for `name`/`group_members[*]` after strip.
- Do **not** enforce cross-field rules here (`len(group_members) == group_size`, `group_size ≤ current`, etc.) — those live in the service where the current registration is loaded.
- Export `RegistrationAdminPatch` from `backend/app/models/__init__.py` if this module is part of the public re-export surface (check existing pattern for `RegistrationCreate`/`RegistrationResponse`).

---

## Phase 2: Backend — Service layer

### T2.1 — Add `admin_update_registration` to `RegistrationService`
**File:** `backend/app/services/registration_service.py`
**Details:**
- Add `async def admin_update_registration(self, event_id: UUID, registration_id: UUID, patch: RegistrationAdminPatch) -> tuple[Registration | None, str | None]`.
- Returns `(registration, None)` on success, `(None, error_code)` on failure. Error codes (caller maps to HTTP status):
  - `"not_found"` → 404
  - `"frozen_registration"` → 400 (status ∈ {`CANCELLED`, `CHECKED_IN`})
  - `"frozen_event"` → 400 (event status `COMPLETED`)
  - `"invalid_group_size"` → 400 (grow attempted, or floor < 1)
  - `"invalid_group_members"` → 400 (length mismatch with `group_size`, or grow via list)
  - `"conflict"` → 409 (optimistic concurrency)
- Algorithm:
  1. Load the registration via `self.get_registration(event_id, registration_id)`. If missing or `event_id` mismatch → `not_found`.
  2. Reject if `registration.status in {CANCELLED, CHECKED_IN}` → `frozen_registration`.
  3. Load event via `event_service.get_event(...)`; reject if `event.status == COMPLETED` → `frozen_event`.
  4. Compute the **target** `(name, phone, notes, group_size, group_members)`:
     - Start with current values.
     - Overlay any non-None patch fields.
     - `group_size` rules (after overlay):
       - Must be ≥ 1. Must be ≤ `registration.group_size` (cannot grow). Else `invalid_group_size`.
     - `group_members` rules:
       - If `patch.group_members is not None` and `patch.group_size is not None`: `len(patch.group_members) == patch.group_size` else `invalid_group_members`.
       - If only `patch.group_members` provided: it must satisfy `len ≤ current group_size`; set target `group_size = len(patch.group_members)`.
       - If only `patch.group_size` provided and the current `group_members` is set: truncate the list from the right to `group_size` entries.
       - If only `patch.group_size` provided and current `group_members` is `None`: leave `group_members` `None`.
  5. Build a single `UpdateExpression` covering only the fields that actually changed (compare to loaded values). Names map directly: `name`, `phone`, `notes`, `group_size`, `group_members`.
  6. Optimistic concurrency: `ConditionExpression = "#s = :cur_status AND attribute_not_exists(responded_at)"` if `registration.responded_at is None`, else `"#s = :cur_status AND responded_at = :cur_responded"`. (`#s` aliases `status` since `status` is a DDB reserved word.) On `ConditionalCheckFailedException` → return `(None, "conflict")` after re-loading the current registration so the caller can include it in the 409 body.
  7. On success: re-load and return the registration. The caller logs.
- Do **not** modify `freed_spots`, do **not** call `_promote_from_waitlist`. Capacity behaviour is intentionally local (see spec § Capacity behaviour).
- Use `datetime.now(timezone.utc)` for any timestamp work; do not use `utcnow()`.

### T2.2 — Remove `admin_update_group_members`
**File:** `backend/app/services/registration_service.py`
**Details:**
- Delete the existing `async def admin_update_group_members(...)` method. Its only caller is the admin UI we're rewriting; per project policy no compatibility shim.
- Keep `update_group_members` (used by the public registrant flow) and `confirm_with_names` (separate state transition) untouched.

---

## Phase 3: Backend — API endpoints

### T3.1 — Add admin GET `/events/{event_id}/registrations/{registration_id}`
**File:** `backend/app/api/admin/events.py`
**Details:**
- Add a route `@router.get("/{event_id}/registrations/{registration_id}", response_model=RegistrationResponse, dependencies=[Depends(require_admin)])`.
- Calls `registration_service.get_registration(event_id, registration_id)`. 404 if missing or org mismatch (use the same access pattern the existing `…/registrations/{registration_id}` DELETE endpoint at line 502 uses for org guarding).
- Build the response with the existing helper that constructs `RegistrationResponse` (mirror the shape returned by `list_registrations`).
- No log entry on read.

### T3.2 — Replace PUT `…/group-members` with PUT `…/registrations/{registration_id}`
**File:** `backend/app/api/admin/events.py`
**Details:**
- Remove the existing `@router.put("/{event_id}/registrations/{registration_id}/group-members", ...)` handler (`admin_update_group_members`, around line 854) and its request body model `_GroupMembersUpdate` (around line 850).
- Add a new `@router.put("/{event_id}/registrations/{registration_id}", response_model=RegistrationResponse, dependencies=[Depends(require_admin)])` handler taking a `RegistrationAdminPatch` body.
- Calls `registration_service.admin_update_registration(event_id, registration_id, patch)`. Map error codes to HTTP:
  - `"not_found"` → `HTTPException(404, "Registration not found")`
  - `"frozen_registration"` → `HTTPException(400, "Registration is frozen (CANCELLED or CHECKED_IN)")`
  - `"frozen_event"` → `HTTPException(400, "Event is completed")`
  - `"invalid_group_size"` → `HTTPException(400, "Group size cannot grow and must be ≥ 1")`
  - `"invalid_group_members"` → `HTTPException(400, "Group members payload is inconsistent with group size")`
  - `"conflict"` → `HTTPException(409, ...)` with a JSON body containing the current `RegistrationResponse` so the frontend can re-hydrate without a second round-trip. Use `JSONResponse(status_code=409, content={"detail": "conflict", "registration": current.model_dump(mode="json")})`.
- After a successful update, build `changed_fields = sorted({k for k, v in patch.model_dump(exclude_unset=True).items()})` and call `log_admin_action("registration.update", user.email, str(registration_id), extras={"event_id": str(event_id), "changed_fields": changed_fields})`. Do not include name/phone/notes values in extras.

### T3.3 — Verify the existing DELETE handler still satisfies the spec
**File:** `backend/app/api/admin/events.py`
**Details:**
- Confirm the existing `DELETE /events/{event_id}/registrations/{registration_id}` (around line 502) accepts `CANCELLED` registrations (the spec keeps purge available for cancelled regs). If it currently rejects `CANCELLED`, relax the gate so cancelled regs can be purged; otherwise leave it alone.
- No code change unless the gate currently blocks CANCELLED — note the result in the PR.

---

## Phase 4: Frontend — API client & router

### T4.1 — Replace `updateGroupMembers` with patch helpers
**File:** `frontend/src/services/api.js`
**Details:**
- Delete `adminApi.registrations.updateGroupMembers` (around line 488).
- Add `getAdminRegistration(eventId, registrationId)` → `GET /api/admin/events/${eventId}/registrations/${registrationId}` (admin-flagged request).
- Add `updateAdminRegistration(eventId, registrationId, patch)` → `PUT /api/admin/events/${eventId}/registrations/${registrationId}` with `JSON.stringify(patch)` body. Pass through 409 responses so the page can read `response.registration` for the rehydrate banner — extend the shared `request` helper only if 409 is currently swallowed; otherwise return `{ status, body }` from this single helper.
- Place the new helpers next to the existing `deleteRegistration` / `setPromoted` admin-registration helpers so they sit together.

### T4.2 — Add the detail route
**File:** `frontend/src/router/index.js`
**Details:**
- Add `{ path: '/admin/events/:eventId/registrations/:registrationId', name: 'admin-registration-detail', component: () => import('@/pages/admin/RegistrationDetailPage.vue'), meta: { requiresAuth: true, requiresAdmin: true } }` (use the same `meta` shape as existing admin routes such as `EventDetailPage`).
- Place it next to the existing event-scoped admin routes (lottery, fahrbericht).

---

## Phase 5: Frontend — RegistrationDetailPage

### T5.1 — Scaffold the page component
**File:** `frontend/src/pages/admin/RegistrationDetailPage.vue` (new)
**Details:**
- `<script setup>` Composition API. `import { ref, computed, watch } from 'vue'`, `useRoute`, `useRouter`, `adminApi`, the toast composable used elsewhere (check `EventDetailPage.vue` for pattern).
- On mount, call `adminApi.registrations.getAdminRegistration(eventId, registrationId)`. While loading, render the `aria-busy="true"` shell used by `RegistrationTable.vue`. On 404 render the empty state "Diese Anmeldung existiert nicht mehr." with a link back to `/admin/events/${eventId}`.
- Header block:
  - Muted line "Schaluppentour DD.MM.YYYY, HH:MM" — derive from event name + `start_at`. Source the event from the same admin call you'd use on `EventDetailPage` (reuse `adminApi.getEvent` if cheap; otherwise piggyback on a `?include=event` query param if you add one — prefer a separate parallel fetch to avoid backend changes).
  - `<h1>` with the registrant's `name`.
  - Status badge using the same `.status-badge` class pattern as `RegistrationTable.vue`.
  - "← Zurück zur Anmeldeliste" button: `router.back()` if `window.history.length > 1` and the previous route is admin-scoped, else `router.push(/admin/events/${eventId})`.
- Skeleton in three `<section>` blocks: `Anmeldedaten`, `Gäste auf der Bordliste`, `Aktionen`. No real content yet — filled in later tasks.
- Define `frozenReason` computed: returns the right banner copy for `CANCELLED`, `CHECKED_IN`, or event `COMPLETED`; null otherwise.
- Render the frozen banner above Section A when `frozenReason` is non-null. Banner copy from spec § Copy.

### T5.2 — Section A: Anmeldedaten + save flow
**File:** `frontend/src/pages/admin/RegistrationDetailPage.vue`
**Details:**
- Local form state object `formA` with `{ name, phone, notes }` initialised from server data; `serverA` snapshot used for dirty diff and `Verwerfen` reset.
- Render rows per spec table:
  - `name` — `<input type="text" maxlength="200">`. Two-way bound; updates also live-update the registrant's row in Section B (see T5.3).
  - `email` — read-only with `<a href="mailto:…">`.
  - `phone` — `<input type="tel">`. Empty string clears.
  - `notes` — `<textarea maxlength="500">`.
  - `Angemeldet am` — read-only formatted timestamp (use the same date util `RegistrationTable.vue` uses).
  - `Bestätigt am` — same, hidden when null.
  - Promoted toggle — only render when event status ∈ {`OPEN`, `REGISTRATION_CLOSED`}. Reuse the existing `setPromoted` admin call (no patch endpoint involvement; toggle is independent).
- Buttons row:
  - `Änderungen speichern` (primary). Disabled when `!isDirtyA || saving`.
  - `Verwerfen` (secondary). Visible only when `isDirtyA`. Resets `formA` to `serverA`.
- `saveA()`: build a patch with only the changed fields out of `name`/`phone`/`notes`. Empty-string `phone`/`notes` is sent as `""` (clears). Call `updateAdminRegistration`. On 200, replace `serverA` with the response, toast "Änderungen gespeichert.", clear dirty flag. On 409, replace local state with the 409 body's `registration`, show concurrency banner copy.
- All inputs render as plain text rows (no `<input>`) when `frozenReason` is non-null; save buttons hidden.

### T5.3 — Section B: Gäste auf der Bordliste + delete flow
**File:** `frontend/src/pages/admin/RegistrationDetailPage.vue`
**Details:**
- Compute `slots`: an array length `group_size` of `{ kind: 'registrant' | 'named' | 'placeholder', name, index }`:
  - Slot 0 is always `registrant` and bound to `formA.name`.
  - Slots 1…N: if `group_members` is set and entry exists → `named` with that name; else `placeholder` rendered as muted "Gast 2", "Gast 3", …
- Header line: `{usedCount} von {group_size} Plätzen genutzt` where `usedCount = group_members?.length ?? 1` (pre-confirmation: only the registrant counts as used).
- Per-row UI:
  - `registrant` → input bound to `formA.name`, no trash icon.
  - `named` → `<input maxlength="200">` bound to a local `formB.members[i]`. Trash icon at right.
  - `placeholder` → muted span, **non-editable** (no input). Trash icon at right.
- Trash click → row collapses to "Gast entfernen? `[Entfernen]` `[Abbrechen]`" inline; `Entfernen` stages the slot for removal (struck-through preview), `Abbrechen` reverts. Update the "X von Y" counter to reflect the staged size live.
- Helper line at the bottom of the section (muted): "Gastnamen werden von der Person eingetragen, die sich angemeldet hat." (Render only when at least one placeholder slot exists.)
- Validation: on save, every named slot must be non-empty after trim; show "Name darf nicht leer sein." inline under the offending input and abort the save.
- Buttons row:
  - `Änderungen speichern` becomes `1 Gast entfernen und speichern` / `N Gäste entfernen und speichern` when ≥1 slot is staged for deletion. Disabled when `!isDirtyB || saving`.
  - `Verwerfen` resets local `formB` + the staged-deletion set.
- `saveB()`: compute the post-update slot list (named slots minus staged-deleted, in their current order, with renames applied); compute `target_size = remaining_named_count + 1_for_registrant_if_no_members_list_or_(placeholder_count_after_staged_delete)`. Patch payload rules per spec § API surface:
  - If the registration currently has `group_members`: send `{ group_size: targetSize, group_members: namesAfterEditExcludingRegistrantIfThatIsTheConvention }`. Match the **storage convention** the backend already uses — verify by reading how `update_group_members` writes the list. (Likely it stores **all** member names including registrant; if so, send all.)
  - If the registration currently has no `group_members` (placeholders only) and the only change is deletions: send `{ group_size: targetSize }` (no `group_members`).
- Render all rows as static muted text + counter when `frozenReason` is non-null; save buttons + trash icons hidden.

### T5.4 — Section C: Aktionen
**File:** `frontend/src/pages/admin/RegistrationDetailPage.vue`
**Details:**
- `Nachrücken` / `Direkt bestätigen` button: only render when `registration.status === 'WAITLISTED'` and event status is `CONFIRMED`. Wire to the existing `adminApi.registrations.promoteFromWaitlist(eventId, registrationId)` helper (around `api.js:473`). Mirror the confirmation copy/flow already used in `RegistrationTable.vue`.
- `Anmeldung löschen`: destructive button at the bottom. Reuse the same confirmation modal used in `RegistrationTable.vue` (lift it into a small shared composable if it currently lives inline — otherwise duplicate the confirm prompt; do not introduce a new abstraction just for two callers). On confirm, call `deleteRegistration` and `router.push(/admin/events/${eventId})`.
- When `frozenReason` is non-null:
  - `CANCELLED` → only `Anmeldung löschen` is shown (purge-only).
  - `CHECKED_IN` and event `COMPLETED` → no action buttons rendered.

### T5.5 — 409 conflict + reload banner
**File:** `frontend/src/pages/admin/RegistrationDetailPage.vue`
**Details:**
- When any save returns 409, set `conflictBanner = true`, replace local form state with the embedded `registration` from the response body (full reload semantics; both Section A and Section B), reset both dirty flags, do **not** show the success toast, and render a banner above Section A: "Die Anmeldung wurde zwischenzeitlich aktualisiert. Aktuelle Daten geladen — bitte erneut prüfen." Banner has a dismiss `×`.

---

## Phase 6: Frontend — RegistrationTable entry point

### T6.1 — Make the registrant name a router-link
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- In the row template (around `RegistrationTable.vue:52`), wrap `{{ reg.name }}` in `<router-link :to="{ name: 'admin-registration-detail', params: { eventId, registrationId: reg.id } }">`. Inherit color, add subtle underline-on-hover via existing CSS or a small scoped rule.
- Verify `eventId` is available in this component — it already lives on `EventDetailPage`; thread it through as a prop if the table currently doesn't take it.
- Mobile card variant: same wrap; ensure tap target stays the full name.
- Do not change any other column, action, filter, or mobile card behavior.

---

## Phase 7: Verification

### T7.1 — Backend import smoke
**File:** (run in shell)
**Details:**
- `cd backend && python -c "from app.main import app; print(len(app.routes))"` — succeeds; route count should change by exactly +1 vs. pre-018 (replaced `…/group-members` PUT, added GET `…/registrations/{id}`, added PUT `…/registrations/{id}`; net +1).

### T7.2 — Backend unit tests for the patch endpoint
**File:** `backend/tests/unit/test_registration_admin_update.py` (new)
**Details:**
- Use `moto[dynamodb]` `mock_aws` fixture as the rest of the suite does.
- Cover (one test each):
  - Rename a single guest → `group_members` updated, `group_size` unchanged.
  - Delete one guest from a group of 3 named → both `group_members` and `group_size` updated to 2 in one DDB write.
  - Delete a placeholder pre-confirmation → `group_size` decreases, `group_members` stays None.
  - Attempt to grow `group_size` → 400 `invalid_group_size`.
  - Attempt to grow via longer `group_members` → 400 `invalid_group_members`.
  - Update on `CANCELLED` reg → 400 `frozen_registration`.
  - Update on event with status `COMPLETED` → 400 `frozen_event`.
  - Optimistic concurrency: simulate `responded_at` mutation between read and write → 409 with current `RegistrationResponse` in body.
  - Clear phone via `""` → stored as null/empty per existing convention; assert reminder pipeline no-ops (existing logic, no new wiring).
- No tests assert anything about `freed_spots` or waitlist — capacity is intentionally untouched.

### T7.3 — Frontend build
**File:** (run in shell)
**Details:**
- `cd frontend && npm run build` — no dead imports (`updateGroupMembers` removed cleanly), new route resolves, page lazy-imports work.

### T7.4 — Manual UI smoke at mobile viewport (375px)
**File:** (checklist in PR)
**Details:**
- From an event with mixed registrations: tap a registrant's name in the table → detail page loads.
- Section A: edit `name`, `phone`, `notes` — Save enabled, Verwerfen reverts. After save: toast, dirty cleared, registrant row in Section B reflects the new name.
- Section B (post-confirmation reg with 3 named guests, `group_size=3`): rename one guest → button label stays `Änderungen speichern`. Stage one delete → counter previews `2 von 2 Plätzen genutzt`, button reads `1 Gast entfernen und speichern`. Save → row removed, counter remains `2 von 2`, server-side `group_size` is 2.
- Section B (pre-confirmation reg with placeholders): inputs disabled; trash works on placeholders; saving sends `group_size` only.
- Trash on the registrant's slot is absent.
- `WAITLISTED` reg on a `CONFIRMED` event → `Nachrücken` button visible in Section C.
- `CANCELLED` reg → frozen banner; only `Anmeldung löschen` visible.
- `CHECKED_IN` reg → frozen banner; no edits, no delete.
- Event `COMPLETED` → frozen banner; no edits, no delete; no Nachrücken.
- Deep-link the page in a fresh tab → "← Zurück" falls back to event detail (not `router.back()`).
- 404 deep-link → "Diese Anmeldung existiert nicht mehr." with link back to event.
- Concurrency: open the page, in another tab confirm via the public link, save in the admin tab → banner shown, form rehydrated, no toast.

---

## Execution order

```
T1.1                                                   (model)
  ↓
T2.1                                                   (service: add new method)
  ↓
T3.1 → T3.2 → T3.3                                    (API: new GET, replace PUT, audit DELETE)
  ↓
T2.2                                                   (service: delete obsolete admin_update_group_members — safe now that the only API caller is gone)
  ↓
T4.1 → T4.2                                           (frontend client + router)
  ↓
T5.1 → T5.2 → T5.3 → T5.4 → T5.5                      (RegistrationDetailPage)
  ↓
T6.1                                                   (table entry point)
  ↓
T7.1 → T7.2 → T7.3 → T7.4                              (verification)
```

Ordering rationale: the obsolete service method (T2.2) is deleted **after** the API has been re-pointed (T3.2), so the tree never sits in a state where `events.py` imports a missing service method. The table entry point (T6.1) lands last on the frontend so the new page is reachable only when it works.
