# 004 — Improved User Registration & Lottery Flow: Tasks

## Phase 1: Model & Serialization

### T1.1 — Add `promoted` field to Registration model
**File:** `backend/app/models/registration.py`
**Details:**
- Add `promoted: bool = False` to `Registration` class (after `promoted_from_waitlist`)
- No changes to `RegistrationStatus` enum
- No changes to `RegistrationCreate` or `RegistrationUpdate`

### T1.2 — Update DynamoDB serialization for `promoted`
**File:** `backend/app/services/registration_service.py`
**Details:**
- `_registration_to_item()`: Add `"promoted": registration.promoted` to the item dict
- `_item_to_registration()`: Add `promoted=item.get("promoted", False)` — fallback ensures backward compat with existing data

---

## Phase 2: Registration Flow Refactor

### T2.1 — Remove capacity-based waitlisting from `create_registration()`
**File:** `backend/app/services/registration_service.py`
**Details:**
- Remove lines 261-271 (capacity check, WAITLISTED assignment, `_get_max_waitlist_position()` call)
- Replace with: always set `initial_status = RegistrationStatus.REGISTERED`, `waitlist_position = None`
- Keep `_get_active_spots_count()` and `_get_max_waitlist_position()` methods — still needed for post-lottery operations
- Update the docstring to reflect new behavior

### T2.2 — Update registration confirmation email to include deadline
**File:** `backend/app/services/registration_service.py`
**Details:**
- After creating registration, the method currently calls email service (if email sending exists downstream)
- Ensure the `event` object (which has `registration_deadline`) is passed to the email template
- See T3.1 for the template side

### T2.3 — Remove WAITLISTED branch from public registration API
**File:** `backend/app/api/public/registrations.py`
**Details:**
- Remove the WAITLISTED email branch (lines 134-135): `elif registration.status.value == "WAITLISTED": await email_service.send_waitlist_notification(...)` — with the new flow, all registrations are REGISTERED so this is dead code
- Remove the WAITLISTED response message branch (lines 151-155) — always return the REGISTERED message
- Update the endpoint docstring to remove references to WAITLISTED

---

## Phase 3: Email Template Updates

### T3.1 — Add registration deadline to confirmation email
**File:** `backend/app/services/email_service.py`
**Details:**
- In `registration_confirmed()` template method: Add a line after the event details section:
  - German: `"Anmeldeschluss: {formatted_deadline}"` (format like "Freitag, 20. März 2026 um 18:00")
  - Include in both text and HTML body
- The `EmailContext` already has access to the event object with `registration_deadline`

### T3.2 — Remove waitlist position from lottery waitlist email
**File:** `backend/app/services/email_service.py`
**Details:**
- `lottery_waitlisted()` template: Remove `#{position}` from subject line
- Remove position reference from email body
- New subject: `"Verlosung: Warteliste für {event_name}"`
- Body: Remove any mention of position number, keep waitlist explanation

### T3.3 — Remove waitlist position from registration waitlist email
**File:** `backend/app/services/email_service.py`
**Details:**
- With the new flow, `registration_waitlisted()` should never be called at registration time (all start as REGISTERED)
- However, keep the template for post-lottery use but remove position from user-facing text
- Subject change: `"Warteliste: {event_name}"` (no position number)

### T3.4 — New template: attendance response confirmation email
**File:** `backend/app/services/email_service.py`
**Details:**
- New method in `EmailTemplates`: `attendance_response_confirmation(ctx, participating: bool)`
- Subject: `"Rückmeldung bestätigt: {event_name}"`
- Body (YES variant): "Danke, {name}! Deine Teilnahme an {event_name} ist bestätigt. Wir freuen uns auf dich!"
- Body (NO variant): "Deine Absage für {event_name} wurde erfasst. Schade, dass du nicht dabei sein kannst."
- Include event date, location in both variants
- New service method: `send_attendance_response_confirmation(event, registration, participating: bool) -> bool`
- Store message with type `CONFIRMATION_REQUEST` (or add new type `ATTENDANCE_RESPONSE`)

---

## Phase 4: Promoted Flag — Backend

### T4.1 — Add `set_promoted()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def set_promoted(self, event_id: UUID, registration_id: UUID, promoted: bool) -> Registration | None`
- DynamoDB `update_item` with `SET promoted = :promoted`
- Only allow if registration status is REGISTERED (not CANCELLED etc.)
- Return updated registration or None on failure

### T4.2 — Add promoted toggle endpoint
**File:** `backend/app/api/admin/events.py`
**Details:**
- New request model: `TogglePromotedRequest(BaseModel)` with `promoted: bool`
- New endpoint: `PATCH /events/{event_id}/registrations/{registration_id}/promote`
  - Requires OWNER or ADMIN role
  - Validates event status is OPEN or REGISTRATION_CLOSED
  - Calls `registration_service.set_promoted(event_id, registration_id, promoted)`
  - Returns updated `RegistrationResponse`
  - 400 if event status doesn't allow editing promoted flag

### T4.3 — Add promoted to admin RegistrationResponse
**File:** `backend/app/api/admin/events.py`
**Details:**
- Add `promoted: bool` to `RegistrationResponse` (line ~466)
- Add `promoted=registration.promoted` to `_registration_to_response()` (line ~492)

### T4.4 — Add promoted stats to registration stats
**File:** `backend/app/services/registration_service.py`
**Details:**
- In `get_registration_stats()`: Add counters `promoted_count` and `promoted_spots`
- Iterate registrations, count those with `promoted=True` and `status != CANCELLED`
- Add to return dict

### T4.5 — Add promoted stats to EventResponse
**File:** `backend/app/api/admin/events.py`
**Details:**
- Add `promoted_count: int = 0` and `promoted_spots: int = 0` to `EventResponse`
- Update `_event_to_response()` to populate from stats

---

## Phase 5: Lottery Algorithm Refactor

### T5.1 — Update candidate filtering
**File:** `backend/app/services/lottery_service.py`
**Details:**
- In `run_lottery()`: Change candidate filter from `status in (REGISTERED, WAITLISTED)` to `status == REGISTERED` only
- With the new flow, there are no WAITLISTED registrations at lottery time

### T5.2 — Add promoted validation
**File:** `backend/app/services/lottery_service.py`
**Details:**
- After getting candidates, calculate `promoted_spots = sum(r.group_size for r in candidates if r.promoted)`
- If `promoted_spots > event.capacity`: raise `ValueError(f"Bevorzugte Anmeldungen ({promoted_spots} Plätze) übersteigen die Kapazität ({event.capacity}). Bitte Bevorzugungen anpassen.")`

### T5.3 — Implement under-capacity auto-confirm path
**File:** `backend/app/services/lottery_service.py`
**Details:**
- After candidate filtering, calculate `total_spots = sum(r.group_size for r in candidates)`
- If `total_spots <= event.capacity`: all candidates become winners, empty waitlist
- Still create a `LotteryRun` record for audit (seed="auto-confirm", all in winners list)
- Still transition event to LOTTERY_PENDING

### T5.4 — Implement promoted-first lottery algorithm
**File:** `backend/app/services/lottery_service.py`
**Details:**
- Separate candidates into `promoted` and `non_promoted` lists
- `promoted` go directly to winners, deduct `group_size` from `remaining_capacity`
- Sort `non_promoted` by `(registered_at, id)` for determinism, then shuffle with seed
- Greedily allocate `non_promoted` to winners until capacity exhausted
- Remaining → waitlist

### T5.5 — Add `promoted_ids` to LotteryRun model
**File:** `backend/app/models/lottery.py`
**Details:**
- Add `promoted_ids: list[str] = []` to `LotteryRun` model (for audit trail)
- Update `_lottery_run_to_item()` and `_item_to_lottery_run()` in lottery_service.py

### T5.6 — Add `promoted` to lottery registration serialization
**File:** `backend/app/services/lottery_service.py`
**Details:**
- In `_serialize_registration()`: Add `"promoted": registration.promoted`

---

## Phase 6: Response Confirmation Email Integration

### T6.1 — Send confirmation email after attendance response
**File:** `backend/app/services/registration_service.py`
**Details:**
- In `set_attendance_response()`, after successful status update:
  - Fetch event via `event_service.get_event_by_id(registration.event_id)`
  - Call `email_service.send_attendance_response_confirmation(event, updated_registration, participating)`
  - Wrap in try/except — email failure should not block the response
- Import `get_event_service` (already imported in `_promote_from_waitlist`)

---

## Phase 7: Admin Discard Action

### T7.1 — Add preview endpoint for unacknowledged registrations
**File:** `backend/app/api/admin/events.py`
**Details:**
- New endpoint: `GET /events/{event_id}/registrations/unacknowledged`
  - Requires OWNER/ADMIN/VIEWER role
  - Returns `RegistrationListResponse` filtered to status == CONFIRMED
  - These are registrations that won the lottery but haven't responded yes/no

### T7.2 — Add discard endpoint
**File:** `backend/app/api/admin/events.py`
**Details:**
- New endpoint: `POST /events/{event_id}/registrations/discard-unacknowledged`
  - Requires OWNER/ADMIN role
  - Calls `registration_service.discard_unacknowledged(event_id)`
  - Returns `{ discarded_count: int, discarded_spots: int }`
  - Log admin action

### T7.3 — Add `discard_unacknowledged()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def discard_unacknowledged(self, event_id: UUID) -> tuple[int, int]`
- Query registrations with status == CONFIRMED
- For each: update status to CANCELLED, send cancellation email
- After all discards: trigger `_promote_from_waitlist()` with total freed spots
- Return (discarded_count, discarded_spots)

---

## Phase 8: Admin Manual Waitlist Promotion

### T8.1 — Add manual promotion endpoint
**File:** `backend/app/api/admin/events.py`
**Details:**
- New request model: `PromoteFromWaitlistRequest(BaseModel)` with `target_status: Literal["CONFIRMED", "PARTICIPATING"] = "CONFIRMED"`
- New endpoint: `POST /events/{event_id}/registrations/{registration_id}/promote-from-waitlist`
  - Requires OWNER/ADMIN role
  - Validates registration is WAITLISTED
  - Accepts optional `target_status` (default: CONFIRMED)
    - `CONFIRMED`: Standard promotion — user receives promotion email with yes/no confirmation buttons
    - `PARTICIPATING`: Direct promotion — skips the acknowledgement step (e.g., user confirmed verbally). User receives a simpler notification email without yes/no buttons
  - Calls `registration_service.promote_single_from_waitlist(event_id, registration_id, target_status)`
  - Returns updated `RegistrationResponse`

### T8.2 — Add `promote_single_from_waitlist()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def promote_single_from_waitlist(self, event_id: UUID, registration_id: UUID, target_status: RegistrationStatus = RegistrationStatus.CONFIRMED) -> Registration | None`
- Get registration, verify WAITLISTED status
- If `target_status` is CONFIRMED: update to CONFIRMED, send promotion email with yes/no buttons
- If `target_status` is PARTICIPATING: update to PARTICIPATING, set `responded_at`, send simpler notification email (no yes/no buttons)
- In both cases: clear waitlist_position, set promoted_from_waitlist=True
- Call `_recompute_waitlist_positions(event_id)`
- Return updated registration

---

## Phase 9: Frontend — Registration Table Enhancements

### T9.1 — Add search filter to RegistrationTable
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- Add text input above table: `placeholder="Name oder E-Mail suchen..."`
- Use `v-model` bound to local `searchTerm` ref
- Emit `@search` event with debounced term (300ms) to parent
- OR filter locally if all data is loaded (simpler approach, registrations are already in memory)

### T9.2 — Add status filter dropdown
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- Add `<select>` next to search input
- Options: Alle, Angemeldet, Bestätigung ausstehend, Nimmt teil, Warteliste, Abgesagt, Eingecheckt, Bevorzugt
- "Bevorzugt" is a special filter that filters by `promoted === true`
- Apply client-side filtering on the already-loaded registrations array

### T9.3 — Add promoted toggle column
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- New column header: "Bevorzugt" (between Status and Angemeldet am)
- When `eventStatus` is OPEN or REGISTRATION_CLOSED:
  - Show toggle switch (`<input type="checkbox">` styled)
  - On change: emit `@toggle-promoted` with `{ registrationId, promoted }`
  - Add tooltip: `title="Garantierte Teilnahme bei der Verlosung"`
- When `eventStatus` is LOTTERY_PENDING, CONFIRMED, COMPLETED:
  - Show read-only star/badge icon if promoted
- When `eventStatus` is DRAFT or CANCELLED: hide column

### T9.4 — Update CONFIRMED status label
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- In `formatStatus()`: Change `'CONFIRMED': 'Wartet auf Bestätigung'` to `'CONFIRMED': 'Bestätigung ausstehend'`

### T9.5 — Remove waitlist position from ConfirmPage
**File:** `frontend/src/pages/confirm/ConfirmPage.vue`
**Details:**
- In the WAITLISTED section (lines 44-58): Remove `#{{ registration.waitlist_position }}` from the status icon
- Remove the "Wartelistenplatz" line from registration details
- Replace the position icon with a generic waitlist icon (e.g., `⏳`)
- Update `formatStatus()` in this file: Change `'CONFIRMED': 'Wartet auf Bestätigung'` to `'CONFIRMED': 'Bestätigung ausstehend'` (same as T9.4, this file has a duplicate function)

### T9.6 — Remove WAITLISTED branch from RegistrationPage success state
**File:** `frontend/src/pages/registration/RegistrationPage.vue`
**Details:**
- In the success state: Remove the conditional heading/body for WAITLISTED status
- Always show the REGISTERED path: "Du stehst auf der Liste!" with lottery explanation
- Remove waitlist position display from the registration details box
- After refactoring, registrations are never WAITLISTED at submission time — this branch is dead code

---

## Phase 10: Frontend — Lottery Page Updates

### T10.1 — Add promoted count to lottery summary metrics
**File:** `frontend/src/pages/admin/events/[eventId]/lottery.vue`
**Details:**
- Add a 4th metric box to `summary-metrics`:
  - Label: "Bevorzugt"
  - Value: `{promoted_count} ({promoted_spots} Plätze)`
- Requires `promoted_count` and `promoted_spots` from the event response (see T4.5)

### T10.2 — Add capacity warning for promoted overflow
**File:** `frontend/src/pages/admin/events/[eventId]/lottery.vue`
**Details:**
- Below summary metrics, conditionally show warning banner:
  - Condition: `event.promoted_spots > event.capacity`
  - Style: yellow/orange background with warning icon
  - Text: "Achtung: Bevorzugte Anmeldungen ({promoted_spots} Plätze) übersteigen die Kapazität ({capacity}). Bitte Bevorzugungen anpassen, bevor die Verlosung gestartet wird."
  - Disable "Verlosung starten" button while warning is active

### T10.3 — Show promoted badge in winners table
**File:** `frontend/src/pages/admin/events/[eventId]/lottery.vue`
**Details:**
- In winners table, add a star icon or badge next to promoted winners' names
- Small indicator like `⭐` or a Pico-styled badge "Bevorzugt"

---

## Phase 11: Frontend — Admin Actions UI

### T11.1 — Add API methods
**File:** `frontend/src/services/api.js`
**Details:**
- `adminApi.togglePromoted(eventId, registrationId, promoted)` → `PATCH /events/{eventId}/registrations/{registrationId}/promote`
- `adminApi.getUnacknowledged(eventId)` → `GET /events/{eventId}/registrations/unacknowledged`
- `adminApi.discardUnacknowledged(eventId)` → `POST /events/{eventId}/registrations/discard-unacknowledged`
- `adminApi.promoteFromWaitlist(eventId, registrationId, targetStatus = 'CONFIRMED')` → `POST /events/{eventId}/registrations/{registrationId}/promote-from-waitlist`

### T11.2 — Wire promoted toggle in EventsPage/EventDetailModal
**File:** `frontend/src/pages/admin/EventsPage.vue`
**Details:**
- Pass `@toggle-promoted` handler to `RegistrationTable`
- Handler calls `adminApi.togglePromoted()` and refreshes registration data
- Show loading state on the specific toggle during API call

### T11.3 — Add discard unacknowledged action
**File:** `frontend/src/pages/admin/EventsPage.vue`
**Details:**
- Add button "Unbestätigte verwerfen" in event actions (visible when event is CONFIRMED)
- On click: fetch preview via `adminApi.getUnacknowledged(eventId)`
- Show confirmation modal with:
  - List of affected registrations (name, email, group_size)
  - Total count and spots
  - Warning text: "Diese Aktion kann nicht rückgängig gemacht werden. Alle aufgelisteten Anmeldungen werden storniert und benachrichtigt."
  - Confirm button: "Verwerfen & Benachrichtigen"
- On confirm: call `adminApi.discardUnacknowledged(eventId)`, refresh data

### T11.4 — Add manual promotion button for waitlisted entries
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- For WAITLISTED registrations, show a small "Nachrücken" button with a dropdown/choice:
  - "Nachrücken (Bestätigung nötig)" → promotes to CONFIRMED (user must acknowledge via email)
  - "Nachrücken (direkt teilnehmend)" → promotes to PARTICIPATING (skips acknowledgement)
- Only visible when event is CONFIRMED (post-lottery, admin managing waitlist)
- On click: emit `@promote-waitlisted` with `{ registrationId, targetStatus }`
- Parent handles API call and data refresh

---

## Phase 12: CSV Export & Stats Updates

### T12.1 — Add promoted column to CSV export
**File:** `backend/app/api/admin/events.py`
**Details:**
- In `export_registrations_csv()`: Add "Bevorzugt" column header
- Add `"Ja" if reg.promoted else "Nein"` to each row

---

## Phase 13: Tests

### T13.1 — Test: Registration always REGISTERED
**File:** `backend/tests/unit/test_registration_flow.py` (new)
**Details:**
- Register when under capacity → status = REGISTERED
- Register when at capacity → status = REGISTERED (not WAITLISTED)
- Register when over capacity → status = REGISTERED (not WAITLISTED)

### T13.2 — Test: Promoted flag operations
**File:** `backend/tests/unit/test_registration_flow.py`
**Details:**
- Set promoted = True → persists in DynamoDB
- Set promoted = False → persists
- set_promoted on CANCELLED registration → fails/ignored
- Promoted stats count correctly

### T13.3 — Test: Lottery under capacity
**File:** `backend/tests/unit/test_lottery.py` (new)
**Details:**
- 5 registrations (10 spots each) for event with capacity 100 → all become winners
- Lottery run stored with all in winners list, empty waitlist

### T13.4 — Test: Lottery with promoted registrations
**File:** `backend/tests/unit/test_lottery.py`
**Details:**
- 3 promoted + 10 non-promoted, capacity for 5 → all 3 promoted win + 2 non-promoted win
- Promoted always in winners regardless of shuffle order
- Remaining 8 non-promoted in waitlist

### T13.5 — Test: Lottery promoted exceeds capacity
**File:** `backend/tests/unit/test_lottery.py`
**Details:**
- Promoted group_size sum > capacity → ValueError raised
- Lottery run NOT stored

### T13.6 — Test: Discard unacknowledged
**File:** `backend/tests/unit/test_admin_features.py`
**Details:**
- 3 CONFIRMED registrations → discard → all CANCELLED
- Waitlist promotion triggered for freed spots
- Cancellation emails sent

### T13.7 — Test: Manual waitlist promotion
**File:** `backend/tests/unit/test_admin_features.py`
**Details:**
- WAITLISTED registration → promote → CONFIRMED
- Waitlist positions recomputed
- Promotion email sent

### T13.8 — Test: Attendance response confirmation email
**File:** `backend/tests/unit/test_email_service.py`
**Details:**
- YES response → confirmation email with "Teilnahme bestätigt" content
- NO response → confirmation email with "Absage bestätigt" content

### T13.9 — Test: Registration email includes deadline
**File:** `backend/tests/unit/test_email_service.py`
**Details:**
- Registration confirmation email body contains formatted deadline date

---

## Execution Order

```
T1.1 → T1.2                                  (Model foundation)
  ↓
T2.1, T2.2, T2.3                             (Registration simplification — can run in parallel with T3.x)
T3.1, T3.2, T3.3, T3.4                       (Email templates — independent of each other)
  ↓
T4.1 → T4.2 → T4.3 → T4.4 → T4.5           (Promoted backend — service first, then endpoint, then stats)
  ↓
T5.1 → T5.2 → T5.3 → T5.4 → T5.5 → T5.6   (Lottery refactor — sequential)
  ↓
T6.1                                          (Response email integration — depends on T3.4)
T7.1 → T7.2 → T7.3                          (Discard — sequential)
T8.1 → T8.2                                  (Manual promote — sequential)
  ↓
T9.1, T9.2, T9.3, T9.4, T9.5, T9.6         (Frontend cleanup & table — can be parallel)
T10.1 → T10.2 → T10.3                       (Lottery UI — sequential)
T11.1 → T11.2, T11.3, T11.4                 (Admin actions UI — T11.1 first, rest parallel)
  ↓
T12.1                                         (CSV export — after promoted field exists)
  ↓
T13.1 → T13.9                                (Tests — after all implementation)
```
