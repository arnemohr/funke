# Tasks: Funke Event Management System

**Input**: Design documents from `/specs/001-funke-event-mgmt/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Only add test tasks when explicitly requested (not requested here).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project structure per implementation plan (backend/app, frontend/src, infra/cdk)
- [X] T002 Initialize Python backend dependencies in backend/requirements.txt (FastAPI, mangum, boto3, pydantic)
- [X] T003 Initialize Vue 3 + Vite + Pico CSS frontend in frontend/package.json with Pinia and Vue Router
- [X] T004 Create environment templates for backend and frontend in .env.example covering Auth0, Gmail API, DynamoDB, API base URLs
- [X] T005 Configure linting/formatting (ruff/black for backend, eslint/prettier for frontend) with project scripts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented
**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Scaffold AWS CDK app in infra/cdk/app.py with separate stacks for API, database, storage, and schedulers
- [X] T007 Define DynamoDB tables and TTL settings in infra/cdk/stacks/database_stack.py (events, registrations, messages, admins, lottery runs)
- [X] T008 Configure API Gateway + Lambda integration for FastAPI (Mangum) in infra/cdk/stacks/api_stack.py with 10/min/IP throttle on public routes
- [X] T009 Implement Auth0 JWT validation middleware in backend/app/services/auth.py for admin routes
- [X] T010 Implement Gmail API client with OAuth2 token refresh in backend/app/services/email_client.py
- [X] T011 Wire FastAPI application entrypoint with routers and CORS in backend/app/main.py
- [X] T012 Create base domain models/schemas for Event, Registration, Message, LotteryRun, Admin in backend/app/models/
- [X] T013 Configure logging/observability helpers (structured logs, request ids) in backend/app/services/logging.py

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Event Creation and Registration (Priority: P1) 🎯 MVP

**Goal**: Admins can create/publish events and attendees can register with capacity-aware confirmation/waitlist plus cancellation.

**Independent Test**: Create event → publish → register attendees until capacity → verify confirmed/waitlisted statuses, emails sent, and cancellation link works without login.

- [X] T014 [US1] Implement event service for create/publish/clone with DynamoDB transactions in backend/app/services/event_service.py
- [X] T015 [US1] Implement registration service for capacity/waitlist assignment and cancellation tokens in backend/app/services/registration_service.py
- [X] T016 [US1] Add admin event endpoints (create/publish/clone) in backend/app/api/admin/events.py
- [X] T017 [US1] Add public registration endpoints (event info, submit registration) in backend/app/api/public/registrations.py
- [X] T018 [US1] Implement email sending for registration confirmation/waitlist/cancellation in backend/app/services/email_service.py
- [X] T019 [P] [US1] Build attendee registration page using link token with Pico form in frontend/src/pages/registration/RegistrationPage.vue
- [X] T020 [P] [US1] Build admin event create/publish UI and form component in frontend/src/pages/admin/EventsPage.vue
- [X] T021 [US1] Add cancellation handling endpoint and confirmation page in backend/app/api/public/cancellations.py and frontend/src/pages/cancel/CancelPage.vue

**Checkpoint**: User Story 1 fully functional and testable independently ✓ COMPLETE

---

## Phase 4: User Story 2 - Lottery Execution for Overbooked Events (Priority: P2)

**Goal**: Admins can run a fair lottery for overbooked events, review results, and finalize notifications.

**Independent Test**: Close registration on an overbooked event → run lottery → review winners/waitlist → finalize → emails sent; rerun blocked after finalization.

- [X] T022 [US2] Implement lottery service with crypto seed shuffle and deterministic replay in backend/app/services/lottery_service.py
- [X] T023 [US2] Add lottery run/review/finalize endpoints in backend/app/api/admin/lottery.py
- [X] T024 [P] [US2] Build admin lottery review/finalize UI in frontend/src/pages/admin/events/[eventId]/lottery.vue
- [X] T025 [US2] Extend email service for lottery outcome notifications in backend/app/services/email_service.py

**Checkpoint**: User Story 2 functional and independently verifiable ✓ COMPLETE

---

## Phase 5: User Story 3 - Confirmation Tracking and Reminders (Priority: P3)

**Goal**: Send scheduled confirmation requests, process YES/NO responses, and promote waitlist on NO responses.

**Independent Test**: Configure reminder schedule → send confirmations → click YES/NO → verify statuses, reminders stop on YES, cancellations trigger promotion, escalation reminders sent.

- [X] T026 [US3] Implement scheduled confirmation worker with EventBridge triggers in backend/app/workers/handler.py and infra/cdk/stacks/scheduler_stack.py (confirmation reminder runs hourly)
- [X] T027 [US3] Add attendance confirmation endpoint (YES/NO via token) in backend/app/api/public/confirmations.py with CONFIRMED → PARTICIPATING/CANCELLED transitions
- [X] T028 [US3] Unified registration status model (REGISTERED → CONFIRMED → PARTICIPATING) with responded_at timestamp in backend/app/models/registration.py (replaces dual-status approach)
- [X] T029 [P] [US3] Integrated reminder schedule management in event create/edit forms and attendance summary in frontend/src/pages/admin/EventsPage.vue
- [X] T030 [US3] Confirmation request and lottery rejection email templates in backend/app/services/email_service.py with one-click YES/NO links

**Checkpoint**: User Story 3 functional and independently verifiable ✓ COMPLETE

---

## Phase 6: User Story 4 - Admin Dashboard and Attendee Management (Priority: P4)

**Goal**: Admin dashboard with event list, registration management, messaging, threads, and export.

**Independent Test**: View dashboard list → filter/search registrations → send custom message → see thread updates → export CSV.

- [ ] T031 [US4] Implement admin events list/quick actions API in backend/app/api/admin/events_list.py
- [ ] T032 [US4] Implement registrations list/search/export endpoints in backend/app/api/admin/registrations.py
- [ ] T033 [US4] Implement messaging endpoints for custom sends and thread retrieval in backend/app/api/admin/messages.py
- [ ] T034 [P] [US4] Build dashboard UI (events list, event detail, communication thread) in frontend/src/pages/admin/dashboard.vue and frontend/src/pages/admin/events/[eventId].vue
- [ ] T035 [US4] Add CSV export generation utility in backend/app/services/export_service.py

**Checkpoint**: User Story 4 functional and independently verifiable

---

## Phase 7: User Story 5 - Event-Day Check-In (Priority: P5)

**Goal**: Mobile-friendly, offline-capable check-in with sync and reporting.

**Independent Test**: Load check-in page → search attendee → check in while online/offline → sync backlog after reconnect → view checked-in vs no-show counts.

- [ ] T036 [US5] Add check-in list and sync endpoints in backend/app/api/admin/checkins.py
- [ ] T037 [US5] Implement offline check-in queue/sync service and service worker in frontend/src/services/checkinSync.ts and frontend/src/service-worker.ts
- [ ] T038 [P] [US5] Build mobile-friendly check-in page with search and status badges in frontend/src/pages/admin/events/[eventId]/checkin.vue
- [ ] T039 [US5] Implement check-in service and no-show reporting in backend/app/services/checkin_service.py

**Checkpoint**: User Story 5 functional and independently verifiable

---

## Phase 8: User Story 6 - Multi-Admin Support (Priority: P6)

**Goal**: Owners invite admins/viewers, manage roles, and transfer ownership.

**Independent Test**: Owner sends invite → invitee accepts and gets role → viewer read-only → role change and ownership transfer reflected in permissions.

- [ ] T040 [US6] Implement invitation service (role assignment, invite tokens) in backend/app/services/invitation_service.py
- [ ] T041 [US6] Add invitation/role management endpoints in backend/app/api/admin/invitations.py
- [ ] T042 [P] [US6] Build admin management UI for invites/roles in frontend/src/pages/admin/settings/admins.vue
- [ ] T043 [US6] Integrate Auth0 Management API for role mapping and ownership transfer in backend/app/services/auth.py

**Checkpoint**: User Story 6 functional and independently verifiable

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T044 [P] Update documentation and quickstart steps in specs/001-funke-event-mgmt/quickstart.md and README.md
- [ ] T045 Security and rate-limit verification (API Gateway throttling, HTTPS enforcement, Auth0 scopes) in infra/cdk/stacks/api_stack.py
- [ ] T046 Data retention and GDPR review (DynamoDB TTL, export/delete flows) in backend/app/services/compliance.py

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1): No dependencies - can start immediately
- Foundational (Phase 2): Depends on Setup completion - BLOCKS all user stories
- User Stories (Phases 3-8): All depend on Foundational completion; proceed in priority order or in parallel after Phase 2
- Polish (Final Phase): Depends on desired user stories being complete

### User Story Dependencies

- User Story 1 (P1): Starts after Phase 2; no other story dependency
- User Story 2 (P2): Depends on US1 data structures; runs after Phase 2 and US1 services
- User Story 3 (P3): Depends on US1 registration data; can run after Phase 2 and US1
- User Story 4 (P4): Depends on US1/US3 data; can run after Phase 2 and US1
- User Story 5 (P5): Depends on US1 data; can run after Phase 2 and US1
- User Story 6 (P6): Depends on foundational Auth0 and admin models; can start after Phase 2 (and optionally after US1 for admin UI shell)

### Parallel Opportunities

- Setup: T003 with T005 can run in parallel
- Foundational: T009-T013 can run in parallel once CDK scaffolding exists (T006-T008)
- Story-level: Within each story, frontend [P] tasks can run in parallel with backend tasks; stories can be parallelized after Phase 2 if team capacity allows

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup  
2. Complete Phase 2: Foundational  
3. Complete Phase 3: User Story 1  
4. STOP and VALIDATE: exercise registration/cancellation flow end-to-end (including emails)

### Incremental Delivery

1. Foundation ready → deliver US1 (MVP)  
2. Add US2 (lottery) → demo → add US3 (confirmations) → US4 (dashboard) → US5 (check-in) → US6 (multi-admin)  
3. Finish with Polish phase and compliance checks

### Parallel Team Strategy

1. Complete Setup + Foundational together  
2. After Phase 2, assign:  
   - Dev A: US1/US2 backend  
   - Dev B: US1/US3 frontend  
   - Dev C: US4 dashboard frontend/backend  
   - Dev D: US5 offline check-in  
3. Integrate and validate each story independently before merging
