# 020 — Tasks: Companion e-mail & personal ticket page

**Date:** 2026-07-30
**Authoritative spec:** `specs/020-festival-companion-tickets.md` — where this file and the spec disagree, **the spec wins**. Spec 019 remains authoritative for everything not touched here.

## How to work these tasks

> - Backend: `cd backend && uv run pytest`. Deps via `uv sync --all-extras` (never bare `uv sync` — it drops the dev extras). Frontend: `cd frontend && npm run build` (no test runner in this repo).
> - **Test gate: exactly 2 known baseline failures** — `test_email_service.py::TestEmailTemplates::test_registration_cancelled` and `::TestFormatDate::test_format_date_german`. Anything else red is yours.
> - Pydantic v2: `model_copy(update={...})` for immutability, never assign to fields. `datetime.now(UTC)` / `datetime.now(timezone.utc)` — match the idiom already in the file you're editing.
> - Tests: `moto` `mock_aws` via the `mock_dynamodb` fixture, `FestivalTestBase` pattern, services patched **at source module** (`app.services.event_service.get_event_service`, …), routers called **directly** with `pytest.raises(HTTPException)`.
> - Guest-facing copy is **German**. Mail signature is `Dein Orga-Team` — never a Schaluppe reference.
> - **`person_index` is load-bearing.** `group_members` is append-only with `None` tombstones and is never reindexed. Anything that renumbers it breaks every issued QR.
> - Definition of done per task: code + tests green + the gate still exactly 2 failures.

## Dependency overview

```
T001 (model) ──┬── T002 (storage)     ── T003 (recipients) ──┬── T006 (send sites)
               └── T004 (person token) ── T005 (F5/F6 mails) ─┘
                                          T005 ── T007 (endpoint)
                                          T003 ── T008 (Rundmail fan-out)
T001 ─────────────────────────────────────────── T009..T013 (frontend, contract-driven)
T006, T007, T008 ── T014 (tests) ── T015 (docs)
```

Frontend (T009–T013) is contract-driven and may run **in parallel** with the backend — the two wire contracts below are frozen.

---

## Frozen wire contracts

Both sides code against these; do not drift.

**Create payload** (`POST /api/public/invites/{token}/registrations`) — additive field:

```json
{
  "group_members":       ["Lisa Meier", "Tim Bach"],
  "group_member_emails": ["lisa@example.de", null]
}
```

Same length as `group_members`, index-aligned, `null` = no address. Omit the key entirely when no companion has an address.

**Self-edit payload** (`PATCH /api/public/registrations/{id}/festival-attendance?token=`) — same field, `None` tombstones allowed in both arrays at the same indices.

**Manage-page GET** additionally returns `group_member_emails: list[str | null] | null`, aligned with `group_members`.

**Person ticket** — `GET /api/public/tickets/{event_id}/{registration_id}/{person_index}?token={person_token}`

`event_id` is in the path because registrations are keyed `pk=EVENT#{event_id}` / `sk=REG#{id}` — without it this public, unauthenticated endpoint would need a table scan per view. Revised from the original `/registrations/{id}/person/{index}` shape during T007 for exactly that reason.

```json
{
  "person_index": 2,
  "name": "Lisa Meier",
  "event_name": "Betriebsfeier Julius Grube Schiffswerft",
  "event_period": "14.–16. August 2026",
  "slot_labels": ["Freitag", "Samstag"],
  "group_size": 3,
  "contact_name": "Anna Schmidt",
  "contact_hint": "festival@…",
  "participation_hint": "Das ist eine Mitmachfeier …",
  "ticket_code": "FUNKE1.eyJ…",
  "cancelled": false
}
```

Frontend route: `/ticket/:eventId/:registrationId/:personIndex?token=…`.

---

## T001 — `group_member_emails` on the models

- **Phase:** A · **Size:** M · **Depends on:** —
- **Files:** `backend/app/models/registration.py` (edit), `backend/app/models/message.py` (edit)
- **What to do:**
  - `Registration`: add `group_member_emails: list[EmailStr | None] | None = None` right after `group_members`, with a comment tying it to the index-stability contract.
  - Add a `model_validator(mode="after")` on `Registration` enforcing alignment: if `group_member_emails` is None → fine. If `group_members` is None and emails is not → error. If both present: pad emails with `None` up to `len(group_members)`; reject when longer; reject a non-`None` email at an index where `group_members[i] is None` (tombstone).
  - Same field on `FestivalRegistrationCreate` (`list[EmailStr | None] | None`), with a validator normalising lowercase + strip and rejecting a length that doesn't match `group_members`.
  - Same field on `FestivalAttendancePatch` and `RegistrationAdminPatch` — **both are `extra="forbid"` and will 422 without it.**
  - Same field on `RegistrationResponse`.
  - `message.py`: two new `MessageType` values — `FESTIVAL_COMPANION_TICKET = "festival_companion_ticket"`, `FESTIVAL_COMPANION_CANCELLATION = "festival_companion_cancellation"`.
- **Acceptance:**
  - `test_festival_companion_email.py::TestCompanionEmailModel` — aligned pair accepted; short list padded; longer list rejected; address on a tombstone rejected; emails-without-names rejected; addresses normalised to lowercase.
  - Existing `test_festival_models.py` still green (the field is optional everywhere).

## T002 — Persist and read the field

- **Phase:** A · **Size:** S · **Depends on:** T001
- **Files:** `backend/app/services/registration_service.py` (edit)
- **What to do:**
  - `_registration_to_item`: write `group_member_emails` only when not `None`, mirroring the existing `group_members` block.
  - `_item_to_registration`: read it via `item.get("group_member_emails")`. Legacy rows have no attribute → `None`.
- **Acceptance:** round-trip test with `None` tombstones in both arrays; a hand-written legacy item (no attribute) reads back as `None` and serialises unchanged.

## T003 — `companion_recipients` helper

- **Phase:** A · **Size:** S · **Depends on:** T002
- **Files:** `backend/app/services/registration_service.py` (edit)
- **What to do:**
  - Pure, HTTP-free helper next to `build_gate_rows`, plus a frozen `CompanionRecipient` dataclass `(person_index, name, email)`.
  - Skip: CANCELLED registrations (return `[]`); tombstoned members; members with no address; an address equal to `registration.email` (case-insensitive — the contact already gets F2 with every QR); within-group duplicates, **first index wins**.
  - `person_index = i + 1` — same offset as `build_person_tickets`.
- **Acceptance:** `TestCompanionRecipients` — mixed addressed/unaddressed group; contact's own address skipped; duplicate addresses collapse to the first index; tombstone skipped and later indices keep their original numbers; CANCELLED → `[]`.

## T004 — Per-person capability token

- **Phase:** A · **Size:** S · **Depends on:** T001
- **Files:** `backend/app/services/ticket_signing.py` (edit)
- **What to do:**
  - `person_page_token(registration_token, person_index) -> str` = `_b64url_encode(HMAC-SHA256(registration_token, f"P{person_index}").digest()[:16])`.
  - `verify_person_page_token(registration_token, person_index, token) -> bool` using `hmac.compare_digest`.
  - Module docstring note: derived from the **registration token, deliberately not `event.ticket_secret`** — the ticket secret reaches every gate client via the scanner boot call (019 Risk #6), so a token derived from it would be forgeable by any gate-link holder.
- **Acceptance:** `test_ticket_signing.py` additions — stable across calls; differs per index; differs per registration token; wrong index / wrong token / tampered token / garbage all `False`.

## T005 — F5 + F6 templates and send methods

- **Phase:** A · **Size:** L · **Depends on:** T004
- **Files:** `backend/app/services/email_service.py` (edit)
- **What to do:**
  - `EmailContext`: add `contact_name: str | None = None`, `person_ticket_url: str | None = None`.
  - `_build_person_ticket_url(registration_id, person_index, token)` next to `_build_management_url` → `{base_url}/ticket/{registration_id}/{person_index}?token={token}`.
  - `EmailTemplates.festival_companion_ticket(ctx, ticket)` — **F5**, copy verbatim from the spec. Exactly **one** `cid:qr-{person_index}` image. **No manage URL anywhere in either body.** Omit the Mitmach paragraph when `ctx.mitmach_hint` is unset, mirroring F2.
  - `EmailTemplates.festival_companion_cancelled(ctx)` — **F6**, copy verbatim from the spec.
  - `EmailService.send_festival_companion_ticket(event, registration, recipient)` — mirror the `ensure_gate_credentials` → `build_person_tickets` → `generate_qr_png` sequence in `send_festival_confirmation`, **filtered to the recipient's index**; base64 the PNG into `InlineImageData`; QR failure must degrade to a mail without the image, never raise.
  - `EmailService.send_festival_companion_cancellations(event, registration)` — loop `companion_recipients`, per-recipient try/except, return the count sent.
- **Acceptance:** `TestCompanionTicketMail` — exactly one inline image whose `content_id` matches the person index; `cid:qr-2` present in `body_html`; the manage URL absent from both bodies; contact name and ticket URL present; F6 subject/body; `ensure_gate_credentials` failure still queues a mail (no QR).

## T006 — Wire the three send sites

- **Phase:** A · **Size:** M · **Depends on:** T003, T005
- **Files:** `backend/app/services/registration_service.py` (edit)
- **What to do:**
  - **create** — in `create_festival_registration`, after the existing never-fail F2 block: loop `companion_recipients` with a `try/except` **per recipient**. Log `flow="festival", step="companion_ticket_email", outcome=ok|error, person_index=…`; never log a full address.
  - **self-edit** — in `update_festival_attendance`, capture the pre-update `group_member_emails`, then after a successful write send F5 only where the new value is non-`None` **and differs from the old value at that index**. Slot-only edit → nothing. Rename → nothing.
  - **cancel** — in the festival branch of `cancel_registration`, wherever F4 is sent, also call `send_festival_companion_cancellations`. Must fire for both the guest self-cancel and the admin cancel.
  - **admin patch** — `admin_update_registration` diffs the field into `set_parts`/`remove_parts` and sends **nothing** (D3).
- **Acceptance:** `TestCompanionSendSites` — create with 1 of 2 addressed → exactly 1 F5; a raising email service does not fail the registration; address added on self-edit → 1 F5; slot-only self-edit → 0; rename → 0; cancel → 1 F6 per addressed companion; admin patch writing an address → 0 mails.

## T007 — Person-ticket endpoint

- **Phase:** A · **Size:** M · **Depends on:** T005
- **Files:** `backend/app/api/public/registrations.py` (edit)
- **What to do:**
  - `PersonTicketResponse` exactly as in the frozen contract above.
  - `GET /api/public/registrations/{registration_id}/person/{person_index}` with `token` as a required query param. Verify with `verify_person_page_token` against the loaded registration's `registration_token`; 404 on mismatch, unknown registration, out-of-range index, index 0 (that's the contact — they use the manage page), or a tombstoned index. **Do not leak which of those it was.**
  - `person_index` must resolve through `build_person_tickets` so the code is freshly signed and index-consistent with the manage page and F5.
  - CANCELLED → `200` with `cancelled: true` and an empty `ticket_code`, so the page can say „diese Anmeldung ist storniert" instead of a bare 410.
  - Log `flow="festival", step="person_ticket"`.
- **Acceptance:** `TestPersonTicketEndpoint` — valid token returns a code `verify_ticket` accepts under the event's `ticket_secret`; wrong/absent/tampered token → 404; index 0 → 404; out-of-range → 404; tombstoned → 404; after a rename the response carries the **new** name and a verifying code; response contains no e-mail address, no phone, no registration token, no other member's name; CANCELLED → `cancelled: true`.

## T008 — Orga-Rundmail fan-out

- **Phase:** A · **Size:** M · **Depends on:** T003
- **Files:** `backend/app/models/message.py` (edit), `backend/app/api/admin/events.py` (edit), `backend/app/services/email_service.py` (edit)
- **What to do:**
  - `CustomMessageRequest`: add `include_companions: bool = True`.
  - `send_custom_message` (service): add `recipient_override` / companion mode so a companion copy carries the **person ticket URL** where the contact's copy carries `{Verwaltungslink}` — never the manage URL.
  - `send_custom_message` (router): after the contact's mail, when `include_companions`, loop `companion_recipients` and send one mail each. Count every recipient in `sent`/`failed`/`total`.
- **Acceptance:** `TestRundmailFanout` — `include_companions=False` → 1 message row; `True` → 1 + N rows; companion row's body contains the ticket URL and **not** the manage URL; a failing companion send increments `failed` without aborting the loop; totals match the number of recipients.

## T009 — Registration form: companion e-mail rows

- **Phase:** A · **Size:** M · **Depends on:** contract
- **Files:** `frontend/src/pages/registration/FestivalRegistrationPage.vue` (edit)
- **What to do:**
  - `form.extraMembers` from `['', …]` to `[{ name: '', email: '' }, …]`.
  - Per row: the existing name input plus an optional `type="email"` input, placeholder `name@example.de`.
  - Fieldset note: „E-Mail (optional) — dann schicken wir den Eintritts-Code direkt an die Person. Ohne E-Mail bekommst du alle Codes und leitest sie selbst weiter."
  - In `handleSubmit`: filter rows by **filled name**, and build `group_members` + `group_member_emails` from the **same filtered list** so indices align. Send `group_member_emails` only when at least one address is present; empty string → `null`.
  - Inline hint on a malformed address; never block submit on a missing one.
- **Acceptance:** manual — two companions, one addressed → payload arrays both length 2 with `null` in the right slot; a filled address on a blank-name row is dropped with its row.

## T010 — Manage page: edit addresses + per-companion status

- **Phase:** A · **Size:** M · **Depends on:** contract
- **Files:** `frontend/src/pages/registration/RegistrationManagePage.vue` (edit)
- **What to do:**
  - `memberEntries` gains `email`; `handleSaveFestival` sends both arrays with tombstones preserved at identical indices.
  - Per companion, one status line: „Code an l…@… geschickt" (mask the local part) when an address is stored, else „Kein Code verschickt — leite ihren QR weiter."
  - The QR grid keeps **every** person (the contact can always forward); companions with their own address get a muted badge.
- **Acceptance:** manual — adding an address and saving keeps `group_members` indices stable; removing a member tombstones both arrays at the same index.

## T011 — `PersonTicketPage.vue`

- **Phase:** A · **Size:** M · **Depends on:** contract
- **Files:** `frontend/src/pages/registration/PersonTicketPage.vue` (new), `frontend/src/router/index.js` (edit), `frontend/src/services/api.js` (edit)
- **What to do:**
  - Route `/ticket/:registrationId/:personIndex`, **no auth guard** — the token is the auth, same as `/invite/:inviteToken`.
  - `publicApi.getPersonTicket(registrationId, personIndex, token)`.
  - Render: own name, event name + period, own day labels, own QR (client-side `qrcode`, reuse the canvas-ref pattern from `RegistrationManagePage.vue`), Mitmach-Hinweis, contact address.
  - Copy: „Änderungen (Tage, Absage) laufen über {contact_name}." **No edit control, no cancel control anywhere on the page.**
  - `cancelled: true` → storniert state, no QR. Error → the same friendly-404 treatment the other public pages use.
- **Acceptance:** manual — page renders one QR that `ScannerPage` accepts; no interactive control other than reload.

## T012 — MessageComposer: `include_companions`

- **Phase:** A · **Size:** S · **Depends on:** contract
- **Files:** `frontend/src/components/MessageComposer.vue` (edit), `frontend/src/services/api.js` (edit)
- **What to do:** `+N Begleitungen mit E-Mail` per row; an `include_companions` checkbox **default on**, passed through `sendCustomMessage`; recipient count in the confirm text includes companions.
- **Acceptance:** manual — count matches the backend's `total`.

## T013 — Admin list + help copy

- **Phase:** A · **Size:** S · **Depends on:** contract
- **Files:** `frontend/src/pages/admin/festival/FestivalRegistrationsPage.vue` (edit), `frontend/src/components/help/FestivalHelp.vue` (edit), `frontend/src/components/help/helpContent.js` (edit), `docs/anleitung.md` (edit)
- **What to do:** companion addresses in the row detail (organisers need to see who is reachable); one sentence of help copy explaining the optional field and that codes go out automatically.
- **Acceptance:** manual.

## T014 — Test suite

- **Phase:** A · **Size:** L · **Depends on:** T006, T007, T008
- **Files:** `backend/tests/unit/test_festival_companion_email.py` (new), `backend/tests/unit/test_ticket_signing.py` (edit), `backend/tests/unit/test_invite_guestlist.py` (edit)
- **What to do:** the full matrix from the spec's §Verification, plus:
  - **Privacy regression in `test_invite_guestlist.py`:** the Gästelisten response must contain **no `@`** in any field, with companion addresses present on the underlying registrations.
  - **Gate CSV regression:** `build_gate_rows` output contains no address, with companion addresses set.
- **Acceptance:** full suite green at exactly the 2 known baseline failures.

## T015 — Docs

- **Phase:** A · **Size:** S · **Depends on:** T014
- **Files:** `infra/mail-vorlagen.md` (edit)
- **What to do:** F5 as **§18**, F6 as **§19**, verbatim from the spec; add `{Kontaktperson}` and `{TicketLink}` to the `## Platzhalter` list.
- **Acceptance:** every placeholder used in the two new templates appears in the Platzhalter list.
