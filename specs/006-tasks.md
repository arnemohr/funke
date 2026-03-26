# 006 Tasks: Custom discard flow

## Task 1: Add `custom_message` to EmailContext and update cancellation template
**File:** `backend/app/services/email_service.py`
- Add `custom_message: str | None = None` to `EmailContext`
- Rewrite `EmailTemplates.registration_cancelled(ctx)`:
  - Use `ctx.custom_message` as the email body (between greeting and signature)
  - Fall back to default warm text if `custom_message` is None/empty
  - Text: `Moin {name},\n\n{message}\n\nHerzliche Grüße,\nDeine Crew von der Schaluppe`
  - HTML: same structure, soft heading "Info zu deiner Anmeldung"
- Add `reason: str | None = None` param to `send_cancellation_confirmation()`
- Pass reason into `EmailContext(custom_message=reason)`

## Task 2: Update registration service to accept IDs and reason
**File:** `backend/app/services/registration_service.py`
- Add params to `discard_unacknowledged()`: `registration_ids: list[UUID] | None = None`, `reason: str | None = None`
- **Status guard:** Always query CONFIRMED registrations first, then intersect with `registration_ids`. Never fetch by ID and assume status.
- **Race condition guard:** Before cancelling each registration, re-verify `status == CONFIRMED`. Skip and log if status changed. Track skipped IDs.
- Pass `reason` to `email_service.send_cancellation_confirmation(event, cancelled_reg, reason)`
- If email sending fails, still cancel but log the failure (don't roll back)
- Return `(discarded_count, discarded_spots, skipped_ids)` — add skipped_ids to the tuple

## Task 3: Update backend endpoint to accept request body
**File:** `backend/app/api/admin/events.py`
- Add `DiscardRequest` model with `registration_ids: list[UUID] | None = None` and `reason: str | None = None`
- Add `field_validator` on `reason`: max 2000 characters
- Update `discard_unacknowledged` endpoint to accept `body: DiscardRequest = DiscardRequest()`
- Pass `body.registration_ids` and `body.reason` to the service call
- Update `DiscardResponse` to include `skipped_ids: list[str]` (IDs that were not discarded due to status changes)

## Task 4: Update frontend API method
**File:** `frontend/src/services/api.js`
- Change `discardUnacknowledged(eventId)` to `discardUnacknowledged(eventId, registrationIds, reason)`
- Send `{ registration_ids: registrationIds, reason }` as JSON body in the POST

## Task 5: Build discard modal in EventsPage
**File:** `frontend/src/pages/admin/EventsPage.vue`
- Add state: `showDiscardModal`, `discardMessage`, `selectedDiscardIds`
- Add computed: `discardCandidates` (CONFIRMED registrations), `selectedDiscardCount`
- Add `<dialog>` with:
  - Header: "Unbestätigte Anmeldungen verwerfen"
  - "Alle auswählen / abwählen" toggle
  - Checkbox list of CONFIRMED registrations: `{name} ({email}) — {group_size} Pers.`
  - Info line: "Es rücken automatisch Personen von der Warteliste nach."
  - `<textarea>` label "Nachricht an die Teilnehmer", pre-filled with default warm text
  - Footer: "Abbrechen" + "N Anmeldungen verwerfen" (red, disabled when 0 selected or submitting, spinner while submitting)
  - Error display
- Add functions: `openDiscardModal`, `toggleAllDiscard`, `toggleDiscardId`, `handleDiscardConfirm`
- `handleDiscardConfirm`: show summary alert with discarded count + promoted spots, warn if any were skipped
- Update `handleDiscardUnacknowledged` to open modal instead of `confirm()`
- Style the destructive button (reuse `.delete-btn` / `.cancel-confirm-btn` pattern)

## Task 6: Manual verification
- Open an event with CONFIRMED registrations
- Click "Unbestätigte verwerfen" → modal opens with all checked, textarea pre-filled
- Verify email addresses are visible next to names
- Verify "Warteliste" info line is visible
- Deselect some registrations, edit the message text
- Button shows correct count
- Submit → button shows spinner, selected registrations cancelled, email sent with custom message
- Summary alert shows discarded count and spots
- "Abbrechen" → nothing happens
- Button disabled when 0 selected
- Double-click prevention: button disabled during submission
