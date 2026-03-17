# Funke Event Management System — Product Spec

**Version:** 2.0  
**Date:** December 14, 2025  
**Status:** Draft

---

## 1. Overview

### Problem
Managing capacity-constrained funke events (100 persons) requires manual tracking of registrations, lottery execution for overbooked events, and multi-channel communication. Current process is time-consuming and error-prone.

### Solution
A lightweight event management system with automated registration, fair lottery allocation, confirmation tracking, and multi-channel notifications.

### Constraints
- No public advertising, no ticket sales (legal requirement)
- Distribution via word-of-mouth (Telegram/Signal groups)
- ~1 event per weekend, 3-4 week registration window

### Success Criteria
| Metric | Target |
|--------|--------|
| Capacity utilization | ≥95% |
| Admin time per event setup | <5 min |
| Confirmation response rate | ≥80% |

### Event Flow

```
1. SETUP        Admin creates event in system
                         ↓
2. DISTRIBUTE   Admin copies event link → shares in closed Telegram group
                         ↓
3. REGISTER     Users click link → fill registration form
                         ↓
4. AUTOMATE     System handles:
                • Registration confirmations (email)
                • Lottery if overbooked (email)
                • Confirmation requests (email)
                • Reminders (email)
                • Waitlist promotions (email)
                         ↓
5. LAST-MINUTE  Admin handles via Telegram group (external to system):
                • Day-of updates
                • Weather changes
                • Location details
                         ↓
6. EVENT DAY    Admin uses check-in feature on-site
```

Note: Telegram is external — used for link distribution and last-minute coordination only. All automated communication is email-based.

---

## 2. Users

### Admin (Primary)
Event organizer with high technical proficiency. Needs efficient event creation, fair allocation when overbooked, and minimal manual intervention.

### Attendee
General public with mixed technical proficiency. Needs easy registration, clear status updates, and fair lottery participation.

---

## 3. Features

### 3.1 Event Management

**Create Event**

| Field | Required | Validation |
|-------|----------|------------|
| Name | Yes | Max 255 chars |
| Date & Time | Yes | Must be future |
| Capacity | Yes | 1–500, default 100 |
| Registration Deadline | Yes | Before event date |
| Description | No | — |
| Location | No | — |
| Reminder Schedule | No | Days before event, e.g. [7, 3, 1] |

Acceptance Criteria:
- [ ] Admin can create event with required fields
- [ ] Validation errors shown inline
- [ ] Event saved as DRAFT by default
- [ ] Admin can clone existing event with new date

**Event States**

```
DRAFT → OPEN → REGISTRATION_CLOSED → LOTTERY_PENDING → CONFIRMED → COMPLETED
                      ↓                                      ↓
                  CANCELLED ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

| State | Description | Triggers |
|-------|-------------|----------|
| DRAFT | Not visible, editable | Manual publish |
| OPEN | Accepting registrations | Deadline reached OR manual close |
| REGISTRATION_CLOSED | No new registrations | Auto if overbooked → LOTTERY_PENDING |
| LOTTERY_PENDING | Awaiting lottery execution | Admin triggers lottery |
| CONFIRMED | Final attendee list set | Event date passes |
| COMPLETED | Event finished | — |
| CANCELLED | Event cancelled | Admin action (any state) |

Acceptance Criteria:
- [ ] State transitions enforced (no skipping states)
- [ ] Cancel possible from any non-terminal state
- [ ] Cancellation notifies all registrants

---

### 3.2 Registration

**Registration Form**

| Field | Required | Format |
|-------|----------|--------|
| Full Name | Yes | — |
| Email | Yes | Valid email, unique per event |
| Phone | No | E.164 (for admin reference only) |
| Group Size | Yes | 1–10 |
| Notes | No | Max 500 chars |

**Status Assignment Logic**

```
ON REGISTRATION:
  current_total = SUM(group_size) WHERE status IN (CONFIRMED, PENDING)
  
  IF current_total + new_group_size ≤ capacity:
    status = CONFIRMED
  ELSE:
    status = WAITLISTED
    waitlist_position = next available position
```

**Registration States**

| State | Description |
|-------|-------------|
| CONFIRMED | Has a spot |
| WAITLISTED | In queue, ordered by position |
| PENDING_CONFIRMATION | Awaiting response to confirmation request |
| CANCELLED | Cancelled by user or admin |
| NO_SHOW | Didn't attend (post-event) |

Acceptance Criteria:
- [ ] Duplicate email for same event rejected with clear error
- [ ] Immediate confirmation shown after submission
- [ ] Status (CONFIRMED/WAITLISTED) clearly communicated
- [ ] Waitlist position shown if applicable
- [ ] User can cancel via unique link (no login required)
- [ ] Cancellation triggers waitlist promotion (if enabled)

---

### 3.3 Lottery System

**Trigger Conditions**
- Event status = REGISTRATION_CLOSED
- Total registrations > capacity
- Admin manually triggers

**Algorithm Requirements**
- Cryptographically random selection
- Deterministic replay with same seed (for auditing)
- Group integrity: entire group wins or loses together
- Greedy fill: maximize capacity utilization

**Process**
1. Admin triggers lottery
2. System shuffles all registrations (seeded RNG)
3. Iterate shuffled list, confirm groups that fit remaining capacity
4. Remaining registrations → waitlist (preserving shuffle order)
5. Notifications sent to all participants

Acceptance Criteria:
- [ ] Lottery only executable once per event
- [ ] Results shown to admin before notifications sent
- [ ] Admin can override individual results before finalizing
- [ ] All participants notified of outcome
- [ ] Lottery seed stored for audit/replay

---

### 3.4 Waitlist Management

**Promotion Logic**
```
ON CANCELLATION (if auto-promote enabled):
  freed_capacity = cancelled_group_size
  
  FOR EACH waitlisted registration (ordered by position):
    IF registration.group_size ≤ freed_capacity:
      PROMOTE to CONFIRMED
      freed_capacity -= registration.group_size
      NOTIFY user
      BREAK (promote one group at a time)
```

Acceptance Criteria:
- [ ] Waitlist ordered by position (lottery result or registration time)
- [ ] Auto-promotion configurable per event
- [ ] Promoted user notified immediately
- [ ] Admin can manually promote/demote

---

### 3.5 Confirmation Tracking

**Flow**
1. System sends confirmation request N days before event
2. User responds YES / NO via link or reply
3. Non-responders: escalate through channels, then to admin

**Response Actions**

| Response | Action |
|----------|--------|
| YES | Mark CONFIRMED, no further reminders |
| NO | Mark CANCELLED, trigger waitlist promotion |
| No response | Escalate: retry → different channel → admin alert |

**Escalation Schedule** (configurable)
- Day 7: Email confirmation request
- Day 5: Reminder on preferred channel
- Day 3: Reminder on alternate channel
- Day 1: Admin notified of non-responders

Acceptance Criteria:
- [ ] One-click confirm/cancel (no login required)
- [ ] Response tracked with timestamp
- [ ] Escalation stops after response
- [ ] Admin dashboard shows response rates

---

### 3.6 Communications

**Channels**

All automated communication via email. Telegram is used externally by admin for link sharing and last-minute coordination (not integrated into system).

| Channel | Use Case |
|---------|----------|
| Email | All automated notifications, reminders, confirmations |
| Telegram | Manual only — admin shares links in closed group (external) |

**Email Infrastructure**

Gmail API handles both sending and receiving from a single account.

| Direction | Method | Notes |
|-----------|--------|-------|
| Outbound | Gmail API send | Subject to daily limits |
| Inbound | Gmail API + Pub/Sub | Push notifications for replies |

**Account Recommendation:** Google Workspace (€6/month)
- 2,000 emails/day (vs 500 for personal Gmail)
- Custom domain option (e.g., events@funke.events)
- Professional appearance, better deliverability
- Reduced spam folder risk

**Capacity Planning**
```
Per event (100 capacity, ~150 registrations):
  - Registration confirmations:  150
  - Lottery results:             150
  - Confirmation requests:       100
  - Reminders:                   100
  - Buffer (replies, custom):    100
  ─────────────────────────────────
  Total:                        ~600 emails

At 1 event/week: ~2,400/month — comfortable within Workspace limits
```

**Email Reply Tracking**

All outgoing emails use a single sender address (e.g., `funke@gmail.com`). Replies are automatically routed to the correct event and attendee via Message-ID tracking.

```
ON SEND EMAIL:
  Generate unique Message-ID
  Store: message_id → {event_id, registration_id, message_type}
  Send email with Message-ID header

ON RECEIVE REPLY:
  Extract In-Reply-To / References header
  Lookup original message_id → {event_id, registration_id}
  Create inbound_message record linked to event + registration
  Notify admin of new reply
```

Requirements:
- Gmail API with OAuth 2.0 authentication
- Scopes: gmail.send, gmail.readonly, gmail.modify
- Pub/Sub push notifications for near real-time reply detection
- Google Cloud project with Gmail API enabled

Acceptance Criteria:
- [ ] All outgoing emails include unique Message-ID
- [ ] Message-ID → event/registration mapping stored
- [ ] Incoming replies matched via In-Reply-To header
- [ ] Unmatched replies flagged for manual review
- [ ] Admin sees reply thread per attendee in dashboard
- [ ] Admin notified of new replies (in-app or email digest)
- [ ] Daily send count tracked, admin warned at 80% of limit
- [ ] Bulk sends queued and rate-limited to avoid hitting limits

**Message Types**
- Registration confirmation
- Lottery result (won / waitlisted)
- Waitlist promotion
- Confirmation request
- Event reminder
- Event cancellation
- Custom admin message

**Delivery Requirements**
- Attempt preferred channel first
- Fallback to email on failure
- Log all attempts with status
- Retry failed messages (max 3 attempts, exponential backoff)

Acceptance Criteria:
- [ ] All automated messages sent via email
- [ ] Delivery status visible to admin
- [ ] Admin can resend failed messages
- [ ] Admin can send custom message to individual attendee
- [ ] Admin can send custom messages to segments (all / confirmed / waitlist)

---

### 3.7 Admin Dashboard

**Event List View**
- All events with status, date, registration count
- Quick actions: view, edit, clone, cancel
- Filter by status, date range

**Event Detail View**
- Registration stats: confirmed / waitlist / cancelled
- Capacity visualization
- Action buttons based on current state
- Registration table with search/filter/sort

**Registration Table**
- Columns: Name, Email, Group Size, Status, Registered At, Confirmed At
- Actions: View details, change status, send message, resend notification, cancel
- Export to CSV

**Attendee Detail View**
- Registration info and status history
- Communication thread (sent messages + replies)
- Quick reply to continue conversation

Acceptance Criteria:
- [ ] Real-time registration count updates
- [ ] Bulk actions (select multiple → change status / send message)
- [ ] Audit log of all admin actions with user attribution
- [ ] Unread reply indicator on registrations with new messages
- [ ] Mobile-responsive for event-day check-in

---

### 3.8 Check-In (Event Day)

**Requirements**
- Searchable attendee list
- Mark attendance with one tap
- Works offline (sync when reconnected)
- Show no-shows after event

Acceptance Criteria:
- [ ] Search by name or email
- [ ] Visual distinction: checked-in vs. not yet
- [ ] Offline mode with local storage
- [ ] Post-event: no-show report generated

---

### 3.9 Multi-Admin Support

**Roles**

| Role | Permissions |
|------|-------------|
| Owner | Full access, manage admins, delete organization |
| Admin | Create/edit/cancel events, manage registrations, send messages, check-in |
| Viewer | Read-only access to events and registrations |

**Admin Management**
- Invite admin via email
- Assign role on invite
- Revoke access anytime
- Transfer ownership (Owner only)

Acceptance Criteria:
- [ ] Owner can invite new admins via email
- [ ] Invited admin receives email with setup link
- [ ] Owner can change admin roles
- [ ] Owner can revoke admin access
- [ ] All admin actions logged with user attribution
- [ ] Admins see only their organization's events
- [ ] Owner can transfer ownership to another admin

---

## 4. Non-Functional Requirements

### Performance
- Page load: <2s on 3G
- Registration submission: <1s response
- Support 500 concurrent registrations

### Availability
- 99.5% uptime
- Graceful degradation if messaging services down

### Security
- HTTPS only
- Admin authentication required
- Rate limiting on registration (10/min per IP)
- Input sanitization (XSS, SQL injection prevention)

### Privacy (GDPR)
- Minimal data collection
- Explicit consent for communications
- Data export on request
- Deletion on request
- Auto-delete personal data 90 days after event

### Localization
- German primary
- English secondary (Phase 2)

---

## 5. Technology Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Frontend | Vue 3 (Composition API) | Simple, readable, maintainable |
| Styling | Pico CSS | Classless, minimal, functional |
| Build | Vite | Fast dev server, optimized builds |
| Backend | Python + FastAPI | Async, type hints, auto OpenAPI docs |
| Database | DynamoDB | Serverless, pay-per-request, ACID transactions |
| Hosting | AWS Lambda + API Gateway | ~€1-5/month, scales to zero |
| Static Assets | S3 + CloudFront | Frontend hosting |
| Auth | Auth0 | Admin authentication only |
| Email | Gmail API | Send + receive, OAuth 2.0 |
| IaC | AWS CDK (Python) | Type-safe, same language as backend |

**Architecture Overview**

```
┌─────────────────────────────────────────────────────────────┐
│                        CloudFront                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────┐           ┌───────────────┐
│   S3 Bucket   │           │  API Gateway  │
│   (Vue SPA)   │           └───────┬───────┘
└───────────────┘                   │
                                    ▼
                            ┌───────────────┐
                            │    Lambda     │
                            │   (FastAPI)   │
                            └───────┬───────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌───────────┐   ┌───────────┐   ┌───────────┐
            │ DynamoDB  │   │  Auth0    │   │  Gmail    │
            └───────────┘   └───────────┘   │   API     │
                                            └───────────┘
```

**DynamoDB Single-Table Design**

```
PK                      SK                          Attributes
─────────────────────────────────────────────────────────────────
ORG#<org_id>            META                        name, created_at
ORG#<org_id>            EVENT#<event_id>            name, date, capacity, status...
ORG#<org_id>            EVENT#<event_id>#REG#<id>   name, email, group_size, status...
ORG#<org_id>            EVENT#<event_id>#MSG#<id>   type, sent_at, message_id...
ORG#<org_id>            ADMIN#<user_id>             email, role, created_at

GSI1 (inverted):
  GSI1PK = SK, GSI1SK = PK
  → Query all registrations by email across events

GSI2 (by status):
  GSI2PK = status, GSI2SK = created_at
  → Query pending confirmations, waitlisted, etc.
```

**Cost Estimate**

| Service | Monthly Cost |
|---------|--------------|
| Lambda | <€1 (free tier covers most) |
| API Gateway | <€1 |
| DynamoDB | €0 (free tier: 25GB, 25 WCU/RCU) |
| S3 + CloudFront | <€1 |
| Auth0 | €0 (free tier: 7,500 MAU) |
| Gmail API | €0 (free) |
| Google Workspace | €6 (recommended) |
| **Total** | **~€6-8/month** |

---

## 6. Out of Scope (v1)

- Payment processing
- Native mobile app
- Multi-tenant (single organization only)
- Public event discovery
- Social features
- Recurring event automation

---

## 7. Open Decisions

| ID | Question | Options | Decision | Date |
|----|----------|---------|----------|------|
| D1 | Domain name | funke.events / [org].de/events | — | — |
| D2 | Data retention period | 90 days / 1 year / indefinite | — | — |
| D3 | Language support | German only / +English | — | — |
| D4 | Gmail account | Personal Gmail / Google Workspace | Workspace recommended | — |

---

## 8. Phases

### Phase 1: MVP (4 weeks)
- Event CRUD
- Registration with status assignment
- Gmail API integration (send + receive)
- Message-ID tracking for reply routing
- Basic admin dashboard with conversation threads
- Manual lottery trigger
- Multi-admin with roles (Owner/Admin/Viewer)

### Phase 2: Automation (2 weeks)
- Confirmation tracking flow
- Automated reminders
- Waitlist auto-promotion

### Phase 3: Polish (2 weeks)
- Check-in functionality
- CSV export
- Audit logging

---

## Appendix A: State Diagrams

### Event Lifecycle
```
┌───────┐
│ DRAFT │
└───┬───┘
    │ publish
    ▼
┌───────┐
│ OPEN  │◄────────────────────┐
└───┬───┘                     │
    │ deadline OR manual      │ reopen (admin)
    ▼                         │
┌─────────────────────┐       │
│ REGISTRATION_CLOSED │───────┘
└───┬─────────────────┘
    │
    ├─── under capacity ───► CONFIRMED
    │
    └─── over capacity ────► LOTTERY_PENDING
                                   │
                                   │ run lottery
                                   ▼
                              CONFIRMED
                                   │
                                   │ event date passes
                                   ▼
                              COMPLETED
```

### Registration Lifecycle
```
┌────────────┐
│ SUBMITTED  │
└─────┬──────┘
      │ capacity check
      ▼
┌─────────────┐     cancel     ┌───────────┐
│  CONFIRMED  │───────────────►│ CANCELLED │
└──────┬──────┘                └───────────┘
       │                              ▲
       │ confirmation request         │ cancel
       ▼                              │
┌──────────────────────┐              │
│ PENDING_CONFIRMATION │──────────────┤
└──────────────────────┘              │
                                      │
┌────────────┐    promote    ┌────────┴──┐
│ WAITLISTED │──────────────►│ CONFIRMED │
└────────────┘               └───────────┘
```

---

## Appendix B: Message Templates (Content Only)

### Registration Confirmed
```
Subject: ✅ Du bist dabei! {event_name}

Hallo {name},

Du hast einen Platz für {event_name}!

📅 {date}
📍 {location}
👥 {group_size} Personen

[Stornieren: {cancel_link}]
```

### Waitlisted
```
Subject: 📋 Warteliste: {event_name}

Hallo {name},

Du bist auf Platz {position} der Warteliste für {event_name}.
Wir melden uns, falls ein Platz frei wird.

[Stornieren: {cancel_link}]
```

### Confirmation Request
```
Subject: ⏰ Bitte bestätigen: {event_name}

Hallo {name},

{event_name} findet in {days} Tagen statt.
Bitte bestätige deine Teilnahme:

[✅ Ich komme: {confirm_link}]
[❌ Ich kann nicht: {cancel_link}]
```

### Lottery Won
```
Subject: 🎉 Du hast gewonnen! {event_name}

Hallo {name},

Gute Nachrichten! Du hast bei der Verlosung einen Platz gewonnen.

📅 {date}
📍 {location}

[Stornieren: {cancel_link}]
```

### Lottery Lost
```
Subject: 📋 Warteliste: {event_name}

Hallo {name},

Leider hat es diesmal nicht geklappt. Du bist auf Platz {position} 
der Warteliste. Falls jemand absagt, rückst du nach.

[Von Warteliste entfernen: {cancel_link}]
```

---

**Document History**
| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-14 | Initial comprehensive spec |
| 2.0 | 2025-12-14 | Lean spec for spec-driven development |
