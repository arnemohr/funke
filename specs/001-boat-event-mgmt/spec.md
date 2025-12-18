# Feature Specification: Funke Event Management System

**Feature Branch**: `001-funke-event-mgmt`
**Created**: 2025-12-14
**Status**: Draft
**Input**: Funke Event Management System — Product Spec v2.0

## Clarifications

### Session 2025-12-14

- Q: What authentication provider should we use for admin login and API validation? → A: Auth0 for admin login/JWT validation (SPA + API).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Event Creation and Registration (Priority: P1)

As an admin, I need to create capacity-constrained funke events and share registration links with my community, so attendees can easily sign up and I can track registrations in real-time.

As an attendee, I need to register for events via a simple form, receive immediate confirmation of my status (confirmed or waitlisted), and have the ability to cancel my registration without needing an account.

**Why this priority**: This is the core value proposition. Without event creation and registration, no other features have meaning. This enables the fundamental workflow: admin creates event → shares link → attendees register.

**Independent Test**: Can be fully tested by creating an event, sharing the registration link, submitting registrations, and verifying status assignment and email confirmations are sent correctly.

**Acceptance Scenarios**:

1. **Given** an admin is logged in, **When** they create an event with name, date, capacity (100), and registration deadline, **Then** the event is saved as DRAFT and a shareable registration link is generated.

2. **Given** a DRAFT event exists, **When** the admin publishes it, **Then** the event status changes to OPEN and the registration link becomes active.

3. **Given** an OPEN event with capacity of 100 and 50 confirmed registrants, **When** a new attendee registers with group size 2, **Then** they receive CONFIRMED status and an email confirmation is sent immediately.

4. **Given** an OPEN event at full capacity (100 confirmed), **When** a new attendee registers, **Then** they receive WAITLISTED status with their position number and an email is sent.

5. **Given** an attendee has registered, **When** they click the cancellation link in their email, **Then** their registration is cancelled without requiring login, they receive a cancellation confirmation email, and the next eligible waitlisted group is promoted.

6. **Given** duplicate email for same event, **When** registration is submitted, **Then** the system rejects it with a clear error message.

---

### User Story 2 - Lottery Execution for Overbooked Events (Priority: P2)

As an admin, when an event is overbooked after registration closes, I need to run a fair lottery to select attendees, so that allocation is transparent, auditable, and all participants are notified of the outcome.

**Why this priority**: Enables fair allocation when demand exceeds capacity, which is a common scenario for popular funke events. Without this, manual selection would be required.

**Independent Test**: Can be tested by creating an overbooked event, closing registration, running the lottery, and verifying winners/waitlist are correctly assigned and all parties notified.

**Acceptance Scenarios**:

1. **Given** an event with registrations exceeding capacity, **When** registration deadline passes, **Then** the event transitions to REGISTRATION_CLOSED and then to LOTTERY_PENDING status.

2. **Given** an event in LOTTERY_PENDING status, **When** admin triggers the lottery, **Then** groups are randomly shuffled (cryptographically random), capacity is filled greedily while keeping groups intact, and remaining registrations move to waitlist.

3. **Given** lottery has been executed, **When** admin reviews results, **Then** they can see all winners and waitlisted attendees before notifications are sent, and can override individual results if needed.

4. **Given** lottery results are finalized, **When** admin confirms results, **Then** all participants receive email notifications (won or waitlisted with position), and the lottery seed is stored for audit/replay.

5. **Given** a lottery has been executed for an event, **When** admin attempts to run lottery again, **Then** the system prevents duplicate execution.

---

### User Story 3 - Confirmation Tracking and Reminders (Priority: P3)

As an admin, I need the system to request confirmations from attendees before the event and track their responses, so I can identify non-responders and fill their spots from the waitlist.

**Why this priority**: Maximizes capacity utilization by identifying attendees who won't show up before the event, allowing waitlist promotion. Reduces no-shows.

**Independent Test**: Can be tested by configuring confirmation schedule, triggering confirmation requests, responding via email links, and verifying escalation and waitlist promotion work correctly.

**Acceptance Scenarios**:

1. **Given** an event with confirmed attendees and a reminder schedule [7, 3, 1] days before, **When** 7 days remain, **Then** confirmation request emails are sent to all confirmed attendees with one-click YES/NO links.

2. **Given** a confirmation request has been sent, **When** attendee clicks YES link, **Then** their status is marked as confirmed, no further reminders are sent for this event, and response timestamp is recorded.

3. **Given** a confirmation request has been sent, **When** attendee clicks NO link, **Then** their registration is cancelled, waitlist promotion is triggered, and cancellation confirmation is sent.

4. **Given** an attendee has not responded to confirmation request, **When** escalation schedule triggers (5 days, then 3 days), **Then** reminder emails are sent.

5. **Given** attendees have not responded by 1 day before event, **When** admin views dashboard, **Then** non-responders are highlighted and admin is notified for manual follow-up.

---

### User Story 4 - Admin Dashboard and Attendee Management (Priority: P4)

As an admin, I need a dashboard to view all events, manage registrations, send custom messages to attendees, and track communication history, so I can effectively manage my events.

**Why this priority**: Essential for day-to-day operations but builds on top of core registration functionality. Admin needs visibility and control.

**Independent Test**: Can be tested by viewing event list, filtering by status, viewing registration details, sending custom messages, and verifying communication threads are tracked.

**Acceptance Scenarios**:

1. **Given** admin is logged in, **When** they access the dashboard, **Then** they see all events with status, date, registration count, and quick action buttons (view, edit, clone, cancel).

2. **Given** admin views an event detail page, **When** registrations exist, **Then** they see a searchable/sortable table with Name, Email, Group Size, Status, Registration Date, and Confirmation Status.

3. **Given** admin selects attendees, **When** they choose to send a custom message, **Then** the message is sent via email and logged in the communication history.

4. **Given** an attendee has received emails and replied, **When** admin views attendee detail, **Then** they see the full communication thread (sent messages + replies) and can quick-reply.

5. **Given** admin wants to export data, **When** they click export, **Then** a CSV file with all registration data is downloaded.

---

### User Story 5 - Event-Day Check-In (Priority: P5)

As an admin on event day, I need to check in attendees as they arrive using a mobile-friendly interface that works offline, so I can track actual attendance and identify no-shows.

**Why this priority**: Provides closure on the event lifecycle and captures attendance data. Lower priority because events can function without it.

**Independent Test**: Can be tested by loading check-in screen on mobile, checking in attendees, going offline and continuing to check in, then syncing when reconnected.

**Acceptance Scenarios**:

1. **Given** admin opens check-in view for an event on mobile device, **When** searching for an attendee, **Then** results appear as they type (by name or email).

2. **Given** attendee is found in check-in list, **When** admin taps to check them in, **Then** their status updates to checked-in with visual distinction.

3. **Given** device loses network connectivity, **When** admin continues checking in attendees, **Then** check-ins are stored locally and sync when connectivity is restored.

4. **Given** event has concluded, **When** admin views attendance report, **Then** they see checked-in vs. no-show counts and can mark no-shows in the system.

---

### User Story 6 - Multi-Admin Support (Priority: P6)

As an organization owner, I need to invite other admins with appropriate roles (Owner, Admin, Viewer) so multiple people can help manage events while maintaining access control.

**Why this priority**: Enables team collaboration but is not required for single-organizer use case. Can be added after core functionality is stable.

**Independent Test**: Can be tested by inviting a new admin via email, assigning roles, verifying permissions, and revoking access.

**Acceptance Scenarios**:

1. **Given** owner is logged in, **When** they invite a new admin via email with Admin role, **Then** an invitation email is sent with a setup link.

2. **Given** invited admin clicks setup link, **When** they complete account setup, **Then** they can access the dashboard with Admin permissions (create/edit events, manage registrations).

3. **Given** a Viewer role user is logged in, **When** they access the dashboard, **Then** they can only view events and registrations (no edit, send, or cancel actions).

4. **Given** owner wants to change access, **When** they revoke an admin's access, **Then** that admin can no longer access the system.

5. **Given** owner wants to transfer ownership, **When** they select another admin to become owner, **Then** ownership transfers and former owner becomes admin.

---

### Edge Cases

- What happens when a group registration would partially exceed capacity? System confirms if full group fits, otherwise waitlists entire group.
- How does the system handle simultaneous registrations racing for last spots? First complete registration wins; subsequent ones are waitlisted.
- What happens when all waitlisted groups are too large to fit freed capacity? Capacity remains unfilled; admin is notified of situation.
- How does the system handle email delivery failures? Retry with exponential backoff (max 3 attempts), log failures, alert admin.
- What happens when an event is cancelled? All registrants are notified via email; event moves to CANCELLED state.
- How does the system handle registration after deadline? Registration form shows event as closed; no submissions accepted.
- What happens when admin modifies capacity after registrations exist? Existing registrations are preserved; new capacity applies to future registrations.

## Requirements *(mandatory)*

### Functional Requirements

**Event Management**

- **FR-001**: System MUST allow admins to create events with name, date/time, capacity (1-500, default 100), and registration deadline.
- **FR-002**: System MUST enforce event state machine: DRAFT → OPEN → REGISTRATION_CLOSED → LOTTERY_PENDING → CONFIRMED → COMPLETED, with CANCELLED available from any non-terminal state.
- **FR-003**: System MUST generate unique, shareable registration links for each event.
- **FR-004**: System MUST allow admins to clone existing events with a new date.
- **FR-005**: System MUST prevent state transitions that skip intermediate states.

**Registration**

- **FR-006**: System MUST collect attendee name, email, group size (1-10), and optional phone and notes.
- **FR-007**: System MUST validate email format and reject duplicate emails for the same event.
- **FR-008**: System MUST assign CONFIRMED status to registrations that fit within remaining capacity, otherwise WAITLISTED with position number.
- **FR-009**: System MUST send email confirmation immediately upon registration with status (confirmed or waitlisted).
- **FR-010**: System MUST provide unique cancellation links that work without authentication.

**Lottery**

- **FR-011**: System MUST use cryptographically random selection for lottery.
- **FR-012**: System MUST keep groups intact (entire group wins or loses together).
- **FR-013**: System MUST fill capacity greedily to maximize utilization.
- **FR-014**: System MUST store lottery seed for deterministic replay.
- **FR-015**: System MUST allow admin to review and override results before notifications.

**Waitlist**

- **FR-016**: System MUST maintain waitlist ordered by lottery result or registration time.
- **FR-017**: System MUST promote waitlisted groups automatically when cancellations occur (if auto-promote enabled).
- **FR-018**: System MUST notify promoted attendees immediately via email.

**Communication**

- **FR-019**: System MUST send all automated notifications via email.
- **FR-020**: System MUST include unique Message-ID in all outgoing emails for reply tracking.
- **FR-021**: System MUST match incoming email replies to correct event and attendee using In-Reply-To header.
- **FR-022**: System MUST retry failed email deliveries with exponential backoff (max 3 attempts).
- **FR-023**: System MUST track daily email send volume and warn admin at 80% of limit.
- **FR-024**: System MUST support confirmation request emails with one-click YES/NO links.

**Admin Dashboard**

- **FR-025**: System MUST require admin authentication for all management operations.
- **FR-026**: System MUST display event list with status, date, registration counts, and quick actions.
- **FR-027**: System MUST provide searchable, sortable registration table with export to CSV.
- **FR-028**: System MUST show communication thread per attendee including replies.
- **FR-029**: System MUST allow admin to send custom messages to individual attendees or segments.
- **FR-030**: System MUST log all admin actions with user attribution and timestamp.

**Check-In**

- **FR-031**: System MUST provide mobile-responsive check-in interface.
- **FR-032**: System MUST support offline check-in with local storage and sync.
- **FR-033**: System MUST generate no-show report after event.

**Multi-Admin**

- **FR-034**: System MUST support three roles: Owner (full access), Admin (manage events/registrations), Viewer (read-only).
- **FR-035**: System MUST allow Owner to invite, modify roles, and revoke admin access.
- **FR-036**: System MUST allow Owner to transfer ownership to another admin.

**Privacy & Security**

- **FR-037**: System MUST auto-delete personal data 90 days after event completion.
- **FR-038**: System MUST support data export and deletion requests per GDPR.
- **FR-039**: System MUST apply rate limiting to public endpoints (10/min per IP).
- **FR-040**: System MUST use HTTPS for all communications.
- **FR-041**: Admin authentication MUST use Auth0 hosted login with JWT validation for SPA + API.

### Key Entities

- **Organization**: Represents the event organizing entity. Has name, owner, and associated admins. Contains multiple events.

- **Event**: A capacity-constrained funke event. Has name, date/time, capacity, registration deadline, status, description, location, and reminder schedule. Belongs to one organization, has many registrations and messages.

- **Registration**: An attendee's signup for an event. Has name, email, phone (optional), group size, status, waitlist position, registration timestamp, confirmation timestamp. Belongs to one event, has many messages.

- **Message**: A communication record. Has type (confirmation, lottery result, reminder, custom), sent timestamp, delivery status, unique Message-ID, and content. Belongs to event and optionally registration.

- **Admin**: A user with management access. Has email, role (Owner/Admin/Viewer), and organization membership.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Capacity utilization reaches 95% or higher for events (target from spec).
- **SC-002**: Admin can set up a new event in under 5 minutes (target from spec).
- **SC-003**: 80% or higher of attendees respond to confirmation requests (target from spec).
- **SC-004**: Attendees complete registration in under 2 minutes.
- **SC-005**: All email notifications are delivered within 5 minutes of triggering event.
- **SC-006**: System supports 500 concurrent registrations without degradation.
- **SC-007**: Check-in interface loads and is usable within 2 seconds on 3G connection.
- **SC-008**: Lottery results are deterministically reproducible given the same seed.
- **SC-009**: 100% of admin actions are auditable with user attribution.
- **SC-010**: Personal data is automatically purged within 90 days after event completion.

## Constraints

- No public advertising or ticket sales (legal requirement).
- Distribution via word-of-mouth through closed Telegram/Signal groups.
- Approximately 1 event per weekend with 3-4 week registration window.
- German language primary; English secondary (Phase 2).
- Monthly infrastructure cost target: under 10 EUR.
- Telegram is external to system — used only for link sharing and last-minute coordination.

## Assumptions

- Single organization deployment for v1 (multi-tenant out of scope).
- Attendees do not need user accounts; they interact via unique links in emails.
- Admin authentication is required; attendee authentication is not.
- Email is the only automated communication channel; SMS/push notifications out of scope for v1.
- Google Workspace account will be used for email (2,000 emails/day limit).
- Lottery is triggered manually by admin, not automatically.
- Waitlist auto-promotion is configurable per event (can be disabled).
- Event capacity is fixed once registrations begin (modification affects future registrations only).

## Out of Scope (v1)

- Payment processing
- Native mobile app
- Multi-tenant architecture
- Public event discovery
- Social features
- Recurring event automation
- SMS/push notifications
- Multi-language support beyond German
