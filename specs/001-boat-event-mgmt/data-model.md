# Data Model — Funke Event Management System

## Entities

- Organization  
  - id (uuid), name, primary_locale (default: de-DE), owner_admin_id (fk AdminUser)  
  - Relationships: has many AdminUsers, Events

- AdminUser  
  - id (uuid), organization_id (fk), email (unique per org), role (Owner|Admin|Viewer), password_hash, created_at, last_login_at, invited_at, invited_by_admin_id (fk)  
  - Relationships: belongs to Organization; created events/messages; audit trail of actions

- Event  
  - id (uuid), organization_id (fk), name, description, location, start_at, capacity (1-500, default 100), registration_deadline, status (DRAFT|OPEN|REGISTRATION_CLOSED|LOTTERY_PENDING|CONFIRMED|COMPLETED|CANCELLED), reminder_schedule_days (array[int]), autopromote_waitlist (bool), registration_link_token, created_by_admin_id (fk), cloned_from_event_id (nullable fk), created_at, published_at, cancelled_at  
  - Relationships: has many Registrations, Messages, LotteryRuns; has one active registration link

- Registration  
  - id (uuid), event_id (fk), name, email, phone (nullable), notes (nullable), group_size (1-10), status (CONFIRMED|WAITLISTED|CANCELLED|CHECKED_IN), waitlist_position (int nullable), registration_token (for cancellation), registered_at, confirmation_response_at (nullable), confirmation_status (PENDING|YES|NO), promoted_from_waitlist (bool)  
  - Constraints: email unique per event; capacity enforcement on confirm; group size capped at remaining capacity else waitlist entire group  
  - Relationships: belongs to Event; has many Messages

- LotteryRun  
  - id (uuid), event_id (fk), executed_by_admin_id (fk), seed (string/hex), shuffled_order (json array of registration ids), winners (json array), waitlist (json array with positions), executed_at, finalized_at, finalization_by_admin_id (fk)  
  - Constraints: max one finalized run per event; rerun blocked after finalization

- Message  
  - id (uuid), event_id (fk), registration_id (nullable fk), type (registration_confirmation|waitlist_notification|lottery_result|reminder|custom|confirmation_request|cancellation), direction (outbound|inbound), subject, body, message_id, in_reply_to, status (queued|sent|delivered|failed|bounced|received), retry_count, sent_at, received_at, error_code (nullable)  
  - Relationships: belongs to Event; optionally to Registration; stores communication thread with replies

- CheckInLog  
  - id (uuid), registration_id (fk), checkin_at, checked_in_by_admin_id (fk), source (online|offline-sync), notes (nullable)  
  - Relationships: belongs to Registration; emitted when attendee is marked checked-in

- AuditLog  
  - id (uuid), organization_id (fk), admin_id (fk), action (enum), entity (enum), entity_id, metadata (json), created_at  
  - Captures admin actions per FR-030 for auditable history

## State Machines

- Event Status  
  - Allowed transitions:  
    - DRAFT → OPEN (publish)  
    - OPEN → REGISTRATION_CLOSED (deadline passed or manual)  
    - REGISTRATION_CLOSED → LOTTERY_PENDING (if over capacity)  
    - LOTTERY_PENDING → CONFIRMED (lottery executed + finalized)  
    - CONFIRMED → COMPLETED (after event end)  
    - Any non-terminal (DRAFT/OPEN/REGISTRATION_CLOSED/LOTTERY_PENDING/CONFIRMED) → CANCELLED  
  - Forbidden: skipping intermediate states; multiple lotteries after finalization

- Registration Status  
  - Initial: CONFIRMED if capacity allows; WAITLISTED otherwise with position; CANCELLED via attendee link or admin; CHECKED_IN after check-in  
  - Waitlist promotions update status to CONFIRMED and adjust downstream positions

- Confirmation Status  
  - PENDING → YES or NO via one-click links; NO triggers cancellation + waitlist promotion; YES stops reminder schedule

## Validation Rules

- Event capacity 1-500 (default 100); group_size 1-10; registration rejected after deadline or when event not OPEN.  
- Email format validated; email unique per event.  
- Lottery uses cryptographically secure shuffle with stored seed and order; rerun prevented after finalization.  
- Cancellation/confirmation links validated via registration_token and expire when event is CANCELLED/COMPLETED.  
- Rate limiting on public endpoints 10/min/IP; auto-delete personal data 90 days post-COMPLETED with queued scrub job.

## Relationships Overview

- Organization 1..* AdminUser, 1..* Event.  
- Event 1..* Registration, 1..* Message, 1..* LotteryRun.  
- Registration 0..* Message, 0..* CheckInLog.  
- AdminUser writes AuditLog, triggers LotteryRun, sends Messages.  
- LotteryRun links to Event and stores final winner/waitlist lists for audit and promotion processing.
