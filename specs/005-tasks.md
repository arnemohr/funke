# 005 — Registration Management Page & Group Member Names: Tasks

## Phase 1: Data Model

### T1.1 — Add `group_members` field to Registration model
**File:** `backend/app/models/registration.py`
**Details:**
- Add `group_members: list[str] | None = None` to `Registration` class (after `group_size`)
- No changes to `RegistrationCreate` (names are not collected at registration time)
- No changes to `RegistrationStatus` enum

### T1.2 — Update DynamoDB serialization for `group_members`
**File:** `backend/app/services/registration_service.py`
**Details:**
- `_registration_to_item()` (~line 40): Add `"group_members": registration.group_members` to item dict (only if not None)
- `_item_to_registration()` (~line 78): Add `group_members=item.get("group_members", None)`
- Backward compatible: existing items without `group_members` default to `None`

### T1.3 — Add `group_members` to RegistrationResponse
**File:** `backend/app/models/registration.py`
**Details:**
- Add `group_members: list[str] | None = None` to `RegistrationResponse`
- Add to admin `RegistrationResponse` in `backend/app/api/admin/events.py` as well

### T1.4 — Update `can_cancel()` to include PARTICIPATING
**File:** `backend/app/models/registration.py`
**Details:**
- Change `can_cancel()` (line 80): Add `RegistrationStatus.PARTICIPATING` to the allowed statuses list
- This enables cancellation after confirmation — one-way, irreversible

---

## Phase 2: Backend — Group Member & Management Endpoints

### T2.1 — New endpoint: Get registration for management page
**File:** `backend/app/api/public/registrations.py` (or new file `backend/app/api/public/management.py`)
**Details:**
- `GET /api/public/registrations/{registration_id}/manage?token={token}`
- Returns full registration details including `group_members`
- Derives `group_members` as `[registration.name]` if `None` and `group_size == 1`
- For groups with `group_members = None`: returns `[registration.name]` + empty strings for remaining slots
- Used by the management page to render current state

### T2.2 — New endpoint: Confirm participation with group member names
**File:** `backend/app/api/public/registrations.py` (or `management.py`)
**Details:**
- `POST /api/public/registrations/{registration_id}/confirm-with-names?token={token}`
- Request body: `{ "group_members": ["Name 1", "Name 2", ...] }`
- Validates: status is CONFIRMED, token matches, `len(group_members) >= 1`, `len(group_members) <= original group_size`
- If `len(group_members) < original group_size`: update `group_size` to `len(group_members)` (user reduced group at confirmation time)
- Updates: status → PARTICIPATING, sets `responded_at`, stores `group_members`, updates `group_size` if reduced
- Does NOT trigger immediate waitlist promotion for freed spots (batch job handles it)
- Returns updated registration

### T2.3 — New endpoint: Update group members
**File:** `backend/app/api/public/registrations.py` (or `management.py`)
**Details:**
- `PUT /api/public/registrations/{registration_id}/group-members?token={token}`
- Request body: `{ "group_members": ["Name 1", "Name 2", ...] }`
- Validates: status is PARTICIPATING, token matches
- `len(group_members)` must be >= 1 and <= current `group_size`
- If `len(group_members) < current group_size`: update `group_size` (member removal)
- Cannot increase `group_size` beyond current value
- Saves immediately to DynamoDB
- Does NOT trigger immediate waitlist promotion (batch job handles it)
- Returns updated registration

### T2.4 — Update cancel endpoint to allow PARTICIPATING
**File:** `backend/app/api/public/cancellations.py`
**Details:**
- The existing `POST /api/public/registrations/{registration_id}/cancel` endpoint currently rejects PARTICIPATING status because `can_cancel()` excludes it
- After T1.4, `can_cancel()` includes PARTICIPATING, so the endpoint works without code changes
- Verify that cancellation from PARTICIPATING triggers immediate waitlist promotion (existing behavior in `cancel_registration()` lines 448-484 — it already checks for CONFIRMED and PARTICIPATING)

### T2.5 — Add admin endpoint for editing group member names
**File:** `backend/app/api/admin/events.py`
**Details:**
- `PUT /events/{event_id}/registrations/{registration_id}/group-members`
- Request body: `{ "group_members": ["Name 1", "Name 2", ...] }`
- Requires OWNER/ADMIN role
- Validates `len(group_members) <= registration.group_size`
- Updates `group_members` in DynamoDB
- Does not change `group_size` (admin only edits names, not headcount)
- Returns updated `RegistrationResponse`

---

## Phase 3: Backend — Batch Waitlist Promotion

### T3.1 — Add `freed_spots` tracking field to Event model
**File:** `backend/app/models/event.py`
**Details:**
- Add `freed_spots: int = 0` to Event model
- This accumulates spots freed by group size reductions (not full cancellations)
- Reset to 0 after batch promotion runs

### T3.2 — Track freed spots on group size reduction
**File:** `backend/app/services/registration_service.py`
**Details:**
- In the update-group-members service method: when `group_size` decreases, increment `event.freed_spots` by the difference
- Use DynamoDB `ADD freed_spots :delta` atomic operation to avoid race conditions
- Full cancellations continue to call `_promote_from_waitlist()` directly (unchanged)

### T3.3 — Batch promotion Lambda handler
**File:** `backend/app/api/batch/waitlist_promotion.py` (new)
**Details:**
- Lambda handler triggered by EventBridge schedule (daily at 12:00 noon)
- Scans all events with status CONFIRMED and `freed_spots > 0`
- For each: calls `_promote_from_waitlist(event_id, freed_spots)`, then resets `freed_spots` to 0
- Logs results per event
- Idempotent: if no freed spots, no-op

### T3.4 — Add EventBridge schedule to CDK
**File:** Infrastructure CDK (relevant infra file)
**Details:**
- Add a scheduled Lambda invocation: daily at 12:00 UTC (or configured timezone)
- Target: the batch promotion handler from T3.3
- Use the existing Lambda function with a new handler path, or a dedicated batch Lambda

---

## Phase 4: Email Link Migration

### T4.1 — Add `_build_management_url()` helper
**File:** `backend/app/services/email_service.py`
**Details:**
- New function: `_build_management_url(registration_id: UUID, token: str) -> str`
- Returns: `f"{settings.base_url}/registration/{registration_id}?token={token}"`

### T4.2 — Replace confirm/cancel links in all email templates
**File:** `backend/app/services/email_service.py`
**Details:**
- Replace `_build_cancellation_url()` and `_build_confirmation_url()` calls with `_build_management_url()` in these templates:
  - `registration_confirmed()` (~line 70): cancel link → management link
  - `registration_waitlisted()` (~line 138): cancel link → management link
  - `promoted_from_waitlist()` (~line 238): yes/no links → single management link
  - `lottery_winner()` (~line 301): cancel link → management link
  - `lottery_waitlisted()` (~line 352): cancel link → management link
  - `confirmation_request()` (~line 503): yes/no links → single management link
- All links use text: "Anmeldung verwalten"
- Remove the two-button (yes/no) pattern from `promoted_from_waitlist` and `confirmation_request` — replace with a single "Anmeldung verwalten" button/link
- Keep `_build_cancellation_url()` and `_build_confirmation_url()` functions alive for now (old links still need to resolve via redirects)

### T4.3 — Add reminder text for incomplete group names
**File:** `backend/app/services/email_service.py`
**Details:**
- In `confirmation_request()` template: if the registration is PARTICIPATING but `group_members` is incomplete (`None` or `len < group_size`), append: "Bitte trage noch die Namen aller Mitfahrenden ein."
- This requires passing `group_members` info to the email context

---

## Phase 5: Frontend — Registration Management Page

### T5.1 — Create RegistrationManagePage.vue
**File:** `frontend/src/pages/registration/RegistrationManagePage.vue` (new)
**Details:**
- Route: `/registration/:registrationId` with query param `token`
- On mount: call `GET /api/public/registrations/{id}/manage?token={token}`
- Render state-dependent views per spec:

**Layout structure:**
1. Status banner (full-width, color-coded)
2. Primary action area
3. Secondary actions (bottom, de-emphasized)

**REGISTERED state:**
- Gray banner: "Deine Anmeldung ist eingegangen. Nach Anmeldeschluss wird per Los entschieden."
- Registration details (name, email, group size)
- Cancel button (secondary)

**CONFIRMED state:**
- Green banner: "Du hast einen Platz bekommen!"
- Name entry form: fields for each group member, first pre-filled with registrant name
- All fields required
- Remove button on fields 2+ (reduces group size, minimum 1 field)
- Cannot add fields beyond original group_size
- "Teilnahme bestätigen" submit button
- Cancel button (secondary)
- Solo registrations (group_size=1): minimal form, pre-filled name, just confirm button

**PARTICIPATING state:**
- Green banner: "Du bist dabei!"
- Editable group member list, each name saves on blur/change (immediate save)
- Remove button on members 2+ (immediate save)
- First member (registrant) has no remove button but name is editable
- Cancel button (secondary, de-emphasized) with two-button confirmation dialog

**WAITLISTED state:**
- Gray banner: "Du stehst auf der Warteliste. Sobald ein Platz frei wird, wirst du benachrichtigt."
- No position shown
- Cancel button (secondary)

**CANCELLED state:**
- Red banner: "Deine Anmeldung wurde storniert."
- Message: "Eine erneute Anmeldung ist über diese Reservierung nicht möglich."
- No actions

**CHECKED_IN state:**
- Green banner: "Du bist eingecheckt. Viel Spaß!"
- Group member list (read-only)
- No actions

**UI states:**
- Loading: "Anmeldung wird geladen..."
- Saving: buttons show "Wird gespeichert..." / "Wird storniert..."
- Error: inline red alert

### T5.2 — Add route and redirects
**File:** `frontend/src/router/index.js`
**Details:**
- Add new route: `/registration/:registrationId` → `RegistrationManagePage.vue`
- Change `/cancel/:registrationId` route to redirect: `redirect: to => ({ path: /registration/${to.params.registrationId}, query: to.query })`
- Change `/confirm/:registrationId` route to redirect: same pattern
- The `?response=yes|no` query param is silently ignored by the new page

### T5.3 — Add public API methods for management page
**File:** `frontend/src/services/api.js`
**Details:**
- `publicApi.getRegistrationManage(registrationId, token)` → `GET /api/public/registrations/{id}/manage?token={token}`
- `publicApi.confirmWithNames(registrationId, token, groupMembers)` → `POST /api/public/registrations/{id}/confirm-with-names?token={token}`
- `publicApi.updateGroupMembers(registrationId, token, groupMembers)` → `PUT /api/public/registrations/{id}/group-members?token={token}`
- Existing `cancelRegistration()` and `getRegistrationInfo()` remain (still used by the management page for cancel action)

---

## Phase 6: Frontend — Admin Enhancements

### T6.1 — Show group members in RegistrationTable
**File:** `frontend/src/components/RegistrationTable.vue`
**Details:**
- For registrations with `group_size > 1`: show expandable row or tooltip with group member names
- If `group_members` is null or incomplete: show "X von Y Namen eingetragen" hint
- For `group_size == 1`: no extra UI needed

### T6.2 — Add admin group member name editing
**File:** `frontend/src/components/RegistrationTable.vue` or `EventDetailModal.vue`
**Details:**
- In the expanded row / detail view: editable name fields for each group member
- Save calls `adminApi.updateGroupMembers(eventId, registrationId, groupMembers)`
- Show save confirmation inline

### T6.3 — Add admin API method for group member editing
**File:** `frontend/src/services/api.js`
**Details:**
- `adminApi.updateGroupMembers(eventId, registrationId, groupMembers)` → `PUT /events/{eventId}/registrations/{registrationId}/group-members`

### T6.4 — Extend CSV export with group member names
**File:** `backend/app/api/admin/events.py`
**Details:**
- In `export_registrations_csv()`: Add "Mitfahrende" column
- Value: comma-separated group member names, or registrant name if `group_members` is None
- If incomplete: show known names + "(?)" for missing entries

---

## Phase 7: Backend Service Methods

### T7.1 — Add `confirm_with_names()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def confirm_with_names(self, registration_id: UUID, token: str, group_members: list[str]) -> tuple[Registration | None, str | None]`
- Validates token, status == CONFIRMED
- Validates `1 <= len(group_members) <= original_group_size`
- All names must be non-empty strings
- Updates DynamoDB: status → PARTICIPATING, sets `responded_at`, stores `group_members`, updates `group_size` if reduced
- Sends attendance response confirmation email
- Returns (updated_registration, None) or (None, error_message)

### T7.2 — Add `update_group_members()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def update_group_members(self, registration_id: UUID, token: str, group_members: list[str]) -> tuple[Registration | None, str | None]`
- Validates token, status == PARTICIPATING
- Validates `1 <= len(group_members) <= current_group_size`
- All names must be non-empty strings
- If `len(group_members) < current_group_size`: update both `group_members` and `group_size`, increment `event.freed_spots`
- If same length: update `group_members` only (name edit)
- Does NOT trigger immediate waitlist promotion
- Returns (updated_registration, None) or (None, error_message)

### T7.3 — Add admin `update_group_members()` service method
**File:** `backend/app/services/registration_service.py`
**Details:**
- New method: `async def admin_update_group_members(self, event_id: UUID, registration_id: UUID, group_members: list[str]) -> Registration | None`
- No token validation (admin authenticated via JWT)
- Validates `len(group_members) <= registration.group_size`
- Updates `group_members` only (admin does not change group_size)
- Returns updated registration

---

## Phase 8: Cleanup

### T8.1 — Remove old ConfirmPage.vue and CancelPage.vue
**File:** `frontend/src/pages/confirm/ConfirmPage.vue`, `frontend/src/pages/cancel/CancelPage.vue`
**Details:**
- Delete both files once the management page is confirmed working
- The routes already redirect (T5.2), so the files are dead code
- Keep the old API endpoints alive — they may still be called by old email links that go through the redirect but some clients might call the API directly

### T8.2 — Deprecate old confirm/cancel API endpoints
**File:** `backend/app/api/public/confirmations.py`, `backend/app/api/public/cancellations.py`
**Details:**
- Keep the endpoints functional (backward compat for links in already-sent emails)
- Add deprecation note in docstrings
- The cancel endpoint continues to work as-is (just cancels)
- The confirm endpoint (`?response=yes|no`) continues to work but does NOT collect group member names — users who click old links will be confirmed without names (acceptable for transition period)

---

## Phase 9: Tests

### T9.1 — Test: confirm_with_names service method
**File:** `backend/tests/unit/test_registration_management.py` (new)
- CONFIRMED + valid names → PARTICIPATING, group_members stored
- CONFIRMED + fewer names than group_size → group_size reduced
- CONFIRMED + empty names → rejected
- CONFIRMED + more names than group_size → rejected
- Non-CONFIRMED status → rejected
- Invalid token → rejected

### T9.2 — Test: update_group_members service method
**File:** `backend/tests/unit/test_registration_management.py`
- PARTICIPATING + name edit (same count) → names updated, group_size unchanged
- PARTICIPATING + member removal (fewer names) → group_size reduced, freed_spots incremented
- PARTICIPATING + more names than current group_size → rejected
- Non-PARTICIPATING status → rejected

### T9.3 — Test: cancel from PARTICIPATING
**File:** `backend/tests/unit/test_registration_management.py`
- PARTICIPATING → cancel → CANCELLED, immediate waitlist promotion triggered
- CANCELLED → confirm → rejected (no re-confirmation)

### T9.4 — Test: batch waitlist promotion
**File:** `backend/tests/unit/test_batch_promotion.py` (new)
- Event with freed_spots=3 → batch runs → promotes matching waitlisted group → freed_spots reset to 0
- Event with freed_spots=0 → batch is no-op
- Group of 4 on waitlist, only 2 freed spots → not promoted (group must fit)

### T9.5 — Test: backward compatibility
**File:** `backend/tests/unit/test_registration_management.py`
- Registration without group_members in DynamoDB → deserialized as None → derived as [name]
- Old confirm endpoint still works (response=yes without names)
- Old cancel endpoint still works

---

## Execution Order

```
T1.1 → T1.2 → T1.3 → T1.4                  (Model foundation)
  ↓
T7.1, T7.2, T7.3                             (Service methods — can be parallel)
  ↓
T2.1 → T2.2 → T2.3 → T2.4 → T2.5          (API endpoints — sequential, depend on services)
  ↓
T3.1 → T3.2 → T3.3 → T3.4                  (Batch promotion — sequential)
  ↓
T4.1 → T4.2 → T4.3                          (Email migration — sequential)
  ↓
T5.3 → T5.1 → T5.2                          (Frontend management page — API first, then page, then routes)
T6.1 → T6.2 → T6.3 → T6.4                  (Admin enhancements — sequential)
  ↓
T8.1 → T8.2                                  (Cleanup — after management page is working)
  ↓
T9.1 → T9.5                                  (Tests — after all implementation)
```
