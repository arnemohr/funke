# 004 — Improved User Registration & Lottery Flow

## Summary

Refactor the registration lifecycle so that **all registrants start in the `REGISTERED` state** regardless of event capacity. Capacity enforcement is deferred entirely to the lottery phase. Additionally, introduce a **promoted flag** that allows administrators to guarantee specific registrations win the lottery.

## Registration Lifecycle

### 1. Event Creation & Publication
- An event is created in `DRAFT` status and published to `OPEN`.
- Once open, users can register until the registration deadline.

### 2. Registration Phase
- All registrations receive the status `REGISTERED` — there is no immediate waitlisting based on capacity.
- The registration confirmation email must include the registration deadline date so users know when to expect the lottery outcome.
- Administrators may flag individual registrations as **promoted** (internal only; no notification is sent to the user). Promoted registrations are guaranteed to win the lottery.
- When a user cancels their registration, they are removed from the participant list and excluded from the lottery.

### 3. Registration Close
- The registration phase is closed (manually by an admin or automatically at the deadline).

### 4. Lottery Execution
- **Under capacity**: If the total number of registered spots (considering group sizes) does not exceed the event capacity, all registrations are confirmed without a lottery.
- **Over capacity**: A lottery is performed with the following constraints:
  - The event's maximum capacity must not be exceeded.
  - Group sizes are respected (a group is admitted or rejected as a whole).
  - Promoted registrations always win.
  - The lottery algorithm must be as fair as possible for non-promoted participants.
- **Validation**: If the sum of promoted group sizes exceeds capacity, the lottery must not proceed. The admin is shown an error with the promoted count vs. capacity mismatch.

### 5. Lottery Outcome
- **Winners** → status transitions to `CONFIRMED`; a lottery-winner notification email is sent.
- **Non-winners** → status transitions to `WAITLISTED`; a waitlist notification email is sent.
- The waitlist maintains an internal order for administrative use. **No waitlist positions are communicated to users** — neither in emails nor on user-facing pages.

### 6. Participation Acknowledgement
- Confirmed users must acknowledge their participation by clicking the confirmation link in the notification email. Upon acknowledgement, their status transitions to `PARTICIPATING`.
- After the user responds (yes or no), a brief confirmation email is sent so the user has an email record of their response.

### 7. Pre-Event Administration
- Before the event, administrators can **discard registrations** of confirmed users who have not acknowledged their participation (i.e., still in `CONFIRMED` status).
  - The discard action must show a preview of all affected registrations (names, group sizes) and require explicit confirmation before execution.
  - Discarded users receive a cancellation notification email.
- When spots become available (due to cancellations or discards), administrators can manually move waitlisted registrations to `CONFIRMED` or `PARTICIPATING`.

---

## Admin UI Requirements

### Promoted Flag
- The promoted flag is displayed as a toggle in the registration table, visible only when the event is `OPEN` or `REGISTRATION_CLOSED`.
- After the lottery, the promoted status is shown as a read-only badge (no longer editable).
- The toggle must include a tooltip or label clarifying its effect: guaranteed lottery placement.

### Promoted Count in Event Summary
- The event summary (detail modal and lottery page) must display the number of promoted registrations and their total group size.
- If promoted spots exceed capacity, an inline warning is shown so the admin can resolve the conflict before running the lottery.

### Registration Table
- The admin registration table must support filtering by name or email.
- A status filter allows isolating registrations by state (e.g., show only promoted, only waitlisted).

### Status Labels
- The `CONFIRMED` status label in the admin UI should read **"Bestätigung ausstehend"** (confirmation pending) to clarify that the user has not yet responded — distinguishing it from the lottery outcome.
