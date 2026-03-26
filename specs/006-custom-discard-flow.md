# Plan: Custom discard flow for "Unbestätigte verwerfen"

## Context
When clicking "Unbestätigte verwerfen", the admin currently gets a simple `confirm()` dialog that discards ALL unconfirmed registrations. The new flow should let the admin select which registrations to discard, write a custom cancellation reason, and confirm before proceeding — all in a single modal.

## User Flow
1. Click "Unbestätigte verwerfen" → modal opens
2. Modal shows:
   - "Alle auswählen/abwählen" toggle at top
   - Checkbox list of CONFIRMED registrations (name, email, group_size), all selected by default
   - Info line: "Es rücken automatisch Personen von der Warteliste nach."
   - Textarea pre-filled with the default email text so the admin sees exactly what will be sent
   - Footer: "Abbrechen" (secondary) + **"N Anmeldungen verwerfen"** (red/destructive, disabled when 0 selected, shows spinner while submitting)
   - The submit button label updates live with the count of selected registrations
3. Click "Abbrechen" → closes modal, nothing happens
4. Click red button → button shows loading state, for each selected registration: status → CANCELLED, personalized email sent with the message
5. On success → alert summary: "N Anmeldungen verworfen (X Plätze). Y Nachrücker benachrichtigt." — then modal closes and data refreshes

## Changes

### 1. Frontend: New discard modal in EventsPage.vue
Add a `<dialog>` after the existing delete-event modal:
- Header: "Unbestätigte Anmeldungen verwerfen"
- "Alle auswählen / abwählen" link/checkbox
- List of CONFIRMED registrations as checkboxes: `{name} ({email}) — {group_size} Pers.`
- Info line below the list: "Es rücken automatisch Personen von der Warteliste nach."
- `<textarea>` pre-filled with the default email text (the warm message from step 5, without greeting/signature — just the middle part the admin can customize). This way the admin sees exactly what will be sent and can edit it. Label: "Nachricht an die Teilnehmer"
- Footer: "Abbrechen" + destructive submit button with live count (disabled + spinner while submitting)
- Error display area

New state refs:
- `showDiscardModal: ref(false)`
- `discardMessage: ref('')` — pre-filled with default text on modal open
- `selectedDiscardIds: ref(new Set())` — registration IDs

Default text for textarea (set in `openDiscardModal`):
```
Leider müssen wir dir mitteilen, dass deine Anmeldung für dieses Event nicht berücksichtigt werden konnte.

Wir würden uns sehr freuen, dich bei einem unserer nächsten Events begrüßen zu dürfen!
```

Computed:
- `discardCandidates` — filter `registrations` to CONFIRMED status
- `selectedDiscardCount` — size of selectedDiscardIds

Functions:
- `openDiscardModal(event)` — set `showDiscardModal = true`, pre-select all CONFIRMED registration IDs
- `toggleAllDiscard()` — select all / deselect all
- `toggleDiscardId(id)` — toggle single ID in set
- `handleDiscardConfirm()` — call API, show summary alert with discarded/promoted counts, refresh, close modal

Update `handleDiscardUnacknowledged(event)` → call `openDiscardModal(event)` instead of `confirm()`

### 2. Frontend: Update API method (api.js)
Change `discardUnacknowledged(eventId)` to `discardUnacknowledged(eventId, registrationIds, reason)`:
```js
async discardUnacknowledged(eventId, registrationIds, reason) {
  return request(`/api/admin/events/${eventId}/registrations/discard-unacknowledged`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ registration_ids: registrationIds, reason }),
  }, true)
},
```

### 3. Backend: Accept request body in endpoint (events.py)
- Add `DiscardRequest` model:
  ```python
  class DiscardRequest(BaseModel):
      registration_ids: list[UUID] | None = None
      reason: str | None = None

      @field_validator("reason")
      @classmethod
      def reason_max_length(cls, v):
          if v and len(v) > 2000:
              raise ValueError("reason must be 2000 characters or less")
          return v
  ```
- Update endpoint signature to accept `body: DiscardRequest = DiscardRequest()`
- Pass `body.registration_ids` and `body.reason` to `registration_service.discard_unacknowledged()`

### 4. Backend: Update service (registration_service.py)
- Add params: `registration_ids: list[UUID] | None = None`, `reason: str | None = None`
- **Status guard (critical):** Always query CONFIRMED registrations first, then intersect with `registration_ids`. Never fetch by ID and assume status.
- **Race condition guard:** Before cancelling each registration, re-verify `status == CONFIRMED`. If status changed (e.g., promoted to PARTICIPATING between modal open and submit), skip that registration and log a warning.
- Track skipped registrations and include `skipped_ids` in the response so the admin sees if something unexpected happened.
- Pass `reason` to `email_service.send_cancellation_confirmation(event, cancelled_reg, reason)`
- **Email failure:** If email sending fails for a registration, still cancel it but log the failure. The cancellation should not be rolled back — better to cancel without email than to leave the registration in a broken state. The admin can re-send manually.

### 5. Backend: Rewrite cancellation email to be warm & personal (email_service.py)
- Add `custom_message: str | None = None` to `EmailContext`
- Add `reason: str | None = None` param to `send_cancellation_confirmation()`, pass into EmailContext
- Rewrite `EmailTemplates.registration_cancelled(ctx)` — the email is assembled from fixed greeting/signature + the admin's custom message body:
  ```
  Moin {name},

  {custom_message — the full text from the textarea, as written by the admin}

  Herzliche Grüße,
  Deine Crew von der Schaluppe
  ```
- The admin controls the entire message body via the textarea (pre-filled with a warm default). The template only wraps it with "Moin {name}" and the signature.
- HTML version: same structure, styled warmly (soft heading like "Info zu deiner Anmeldung" instead of "Anmeldung storniert")
- If `custom_message` is empty/None, fall back to the default text

## Files to modify
- `frontend/src/pages/admin/EventsPage.vue` — new modal + updated handler
- `frontend/src/services/api.js` — send registration_ids + reason in body
- `backend/app/api/admin/events.py` — accept DiscardRequest body
- `backend/app/services/registration_service.py` — filter by IDs, pass reason
- `backend/app/services/email_service.py` — EmailContext field + template update

## Safety invariants
- **Only CONFIRMED registrations are ever cancelled by this flow.** WAITLISTED, PARTICIPATING, CHECKED_IN, and REGISTERED are never touched.
- The backend is the single source of truth for status filtering — the frontend selection is an intent, not a guarantee.
- Each registration's status is re-checked at cancellation time to guard against race conditions.
- The response includes `skipped_ids` so the admin knows if any registrations were not discarded due to status changes.

## Verification
- Click "Unbestätigte verwerfen" → modal shows CONFIRMED registrations with checkboxes (name, email, group size)
- All selected by default, toggle works, button count updates live
- Deselect some → only selected ones get discarded
- Textarea pre-filled with default warm message, admin can edit
- Custom message appears in cancellation email body
- "Abbrechen" closes modal without side effects
- Button disabled when 0 selected
- Button shows loading state during submission, prevents double-click
- Info line about waitlist promotion is visible
- Summary alert after success shows discarded count and promoted count
- If a registration's status changed between modal open and submit, it is skipped (not cancelled)
