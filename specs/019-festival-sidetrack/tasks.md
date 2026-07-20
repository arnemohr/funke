# 019 — Festival Sidetrack: Implementation Tasks

**Date:** 2026-07-19
**Authoritative spec:** [./spec.md](./spec.md) — when this file and the spec disagree, the spec wins.

Registration must open around **25.7.** — the festival („Betriebsfeier Julius Grube Schiffswerft") runs **Fri 14.–Sun 16.8.** and the core crew (Werft +1, volunteers) needs the most lead time. **Registration and self-edits run until the END of the festival** (Ä14) — the deadline is pure config, set to Sun 16.8. 23:59; **Mon 10.8. is the catering-snapshot date** (catering CSV pulled that day while registration keeps running), not a registration close. Work is phased per the spec's runbook: **P1 — registration can open** (build week 20.–26.7., live ~25.7., waves 1+2 go out end of that week), **P2 — planning tools** (week 27.7.–2.8., the headcount board must be live and trusted **before wave 3** goes out), **P3 — check-in** (week 3.–9.8., scanner **field test hard deadline Mon 10.8.** — same day as the catering snapshot; if the field test fails, paper is the plan of record).

## How to work these tasks

> **Repo conventions** (verified in earlier sessions — re-verify if you touch these areas):
> - DynamoDB single-table per domain: lowercase pk/sk keys (`EVENT#{id}`, `REG#{id}`); key prefixes centralized in `backend/app/services/config.py`
> - Services: class + lazy singleton getter (`_service = None; def get_x_service()`)
> - Pydantic v2: `model_copy(update={...})`, never assign to fields
> - `datetime.now(timezone.utc)` everywhere — EXCEPT the new check-in log sk, which the spec mandates as Europe/Berlin local time (deliberate, documented exception)
> - German UI text (Pico CSS), Vue 3 Composition API script setup
> - Tests: `moto[dynamodb]` + `mock_aws`, pytest-asyncio `asyncio_mode=auto`, `email-validator` package needed for model imports; patch `get_gmail_client` at source (`app.services.email_client.get_gmail_client`)
> - Existing specs use NNN-tasks.md convention; this one lives at `specs/019-festival-sidetrack/tasks.md`
>
> **Test command:** `cd backend && uv run pytest`
>
> **Two-CDK-deploy constraint (spec Risks #2):** CloudFormation allows only **one GSI change per stack update**. This spec needs two new GSIs on the events table: `invite-token-index` (P1, T101) and `gate-token-index` (P3, T301). Each gets its **own** `cdk deploy`, run **early** in its phase, before any backend code that queries it ships. Never batch the two.
>
> **Definition of done (every task):** code merged + tests green (`uv run pytest` exit 0) + all user-facing strings German + no regression to regular (SINGLE) events — the existing create → register → lottery flow must stay untouched.
>
> **Deliberate deviation from the spec:** festival admin reads also allow VIEWER (the spec says OWNER/ADMIN) — intentional, consistent with the existing admin routers; writes stay OWNER/ADMIN.

## Dependency overview

Task IDs per phase with their direct dependencies (`←` = depends on):

- **P1** (target: live ~25.7.)
  - T101 ← — (invite-token GSI; **deploy alone, first**)
  - T102 ← —
  - T103 ← T102
  - T104 ← T101
  - T105 ← T101, T104
  - T106 ← T102, T104
  - T107 ← T102, T106
  - T108 ← T103, T105, T106, T107
  - T109 ← T108
  - T110 ← T102, T103, T108
  - T111 ← T108, T109
  - T112 ← T105, T107, T103
  - T113 ← T112
  - T114 ← T107
  - T115 ← T111, T112
  - T116 ← T115
  - T117 ← T115, T111
  - T118 ← T115
  - T119 ← T115, T118
  - T120 ← T101–T119
- **P2** (headcount board before wave 3, week 27.7.–2.8.)
  - T201 ← T102, T106, T108
  - T202 ← T201, T112
  - T203 ← T109, T112
  - T204 ← T201, T113
  - T205 ← T102, T106
  - T206 ← T202, T203, T204, T115
  - T207 ← T202, T206, T118
  - T208 ← T203, T205, T206
  - T209 ← T119, T112
  - T210 ← T201, T111, T116 (if-time, cut first)
  - T211 ← T208, T115
  - T212 ← T201–T211
- **P3** (field test Mon 10.8.)
  - T301 ← — (gate-token GSI; **2nd separate CDK deploy, first in phase**; requires T101 already deployed)
  - T302 ← T301
  - T303 ← T302
  - T304 ← T302
  - T305 ← T302 (must land before any SCAN# row is written)
  - T306 ← T302, T304, T305
  - T307 ← T301, T303, T306
  - T308 ← T302, T304
  - T309 ← T308
  - T310 ← T307
  - T311 ← T310
  - T313 ← T306, T202, T207
  - T312 ← T303, T309, T310, T311, T313

## P1 — registration can open (target: live ~25.7.)

Deploy-order constraint (spec Risks #2): **T101 must be merged and `cdk deploy` run alone before any other backend change ships** — CloudFormation allows only one GSI change per stack update, and the P3 `gate-token-index` will need its own later deploy. Everything else in P1 can ship in one backend + one frontend deploy after that.

Semantic anchor for all tasks below (spec "Critical semantic decision"): festival registrations are created directly in status `PARTICIPATING` with `responded_at = registered_at`. Never `CONFIRMED` (that status feeds the nag-reminder worker and discard-unacknowledged flow). Do not "fix" this.

### T101 — Add invite-token GSI to the events table (own CDK deploy) ✅ (deployed 19.7., `cdk diff` showed exactly one GSI; index ACTIVE on funke-dev-events)
- **Phase:** P1 · **Size:** S · **Depends on:** —
- **Files:** `infra/cdk/stacks/database_stack.py` (edit), `backend/tests/unit/conftest.py` (edit)
- **What to do:**
  - In `database_stack.py`, add a GSI to `self.events_table`, mirroring `link-token-index` at database_stack.py:72-79 exactly: `index_name="invite-token-index"`, partition key `dynamodb.Attribute(name="invite_token", type=dynamodb.AttributeType.STRING)`, `projection_type=dynamodb.ProjectionType.ALL`, no sort key.
  - In `tests/unit/conftest.py`, add the same `invite-token-index` (pk `invite_token`, ALL projection) to the moto `funke-dev-events` table definition inside the `mock_dynamodb` fixture, alongside the existing `status-index`/`link-token-index`, so service tests written in T105+ can query it.
  - Do NOT add the P3 `gate-token-index` in this change — one GSI per CloudFormation update.
- **Acceptance:**
  - `cdk diff` shows exactly one GSI addition on the events table and nothing else.
  - This change is deployed to the target environment before T105+ backend code lands (note in PR description).
  - Existing test suite (`cd backend && uv run pytest`) still passes with the extended conftest table schema.

### T102 — Event model: EventType, FestivalSlot, festival fields, capacity validator (Ä8) ✅
- **Phase:** P1 · **Size:** M · **Depends on:** —
- **Files:** `backend/app/models/event.py` (edit), `backend/app/models/__init__.py` (edit — re-export new symbols), `backend/tests/unit/test_festival_models.py` (new)
- **What to do:**
  - Add `class EventType(str, Enum): SINGLE = "SINGLE"; FESTIVAL = "FESTIVAL"` next to `EventStatus` (event.py:15-24).
  - Add `class FestivalSlot(BaseModel)` with fields: `key: str` (1-50 chars, e.g. `"fr-abend"`), `label: str` (1-100, e.g. `"Fr Abend"`), `date: date` (gate-day attribution; a night slot is attributed to the date it starts), `is_night: bool = False`, `capacity: int | None = None` (ge=1). Soft cap only — never enforced anywhere.
  - Add to `EventBase` (event.py:44-54), all additive with defaults: `event_type: EventType = EventType.SINGLE`, `end_at: datetime | None = None`, `festival_slots: list[FestivalSlot] | None = None`, `contact_hint: str | None = None` (max_length=500), `participation_hint: str | None = None` (Ä16 — the Mitmach text incl. Schichtplan link; persisted like `contact_hint`, max_length ~1000).
  - **Capacity Ä8**: remove `le=500` from the `capacity` Field constraint and replace with a model validator on `EventCreate` (and mirror on `EventUpdate` where both fields are present): `capacity <= 500` when `event_type == SINGLE`, `capacity <= 2000` when FESTIVAL. Keep `ge=1`.
  - Add `EventCreate` validator for festival slots: when `event_type == FESTIVAL`, `festival_slots` must be non-empty, keys unique, entries sorted chronologically by `date`; raise `ValueError` otherwise. Follow the `info.data.get(...)` cross-field pattern of `validate_deadline` (event.py:68-75). **Apply the same slot validator on `EventUpdate` too** — T118's acceptance assumes the backend rejects bad slot sets on save, not only on create.
  - **`EventUpdate`**: add the new fields there as well — `festival_slots`, `end_at`, `contact_hint`, `participation_hint` (all optional) — so the FestivalPage settings form (T118) can round-trip them.
  - **Required-for-FESTIVAL**: `registration_deadline` and `end_at` are REQUIRED at model level when `event_type == FESTIVAL` (model validator on `EventCreate`/`EventUpdate`) — T104's `is_expired` and T108's deadline check dereference `registration_deadline` and would crash on `None`. Per Ä14 the deadline is *configured* as the festival's end (Sun 16.8. 23:59) — registration runs until and during the festival; the mechanics don't change, only the configured value is late.
  - Add helpers on `Event`: `slot_keys() -> list[str]`, `night_slots() -> list[FestivalSlot]`, `slots_on(d: date) -> list[FestivalSlot]`. Pure reads, empty-list-safe when `festival_slots is None`.
  - Add the new public-relevant fields to `EventPublic` (event.py:140-152): `event_type`, `end_at`, `contact_hint` (slots are served by the invite form-boot endpoint, not EventPublic).
  - Do NOT copy the broken `lambda: datetime.now(timezone.utc)()` constructs at event.py:125/:127/:135 into any new code.
- **Acceptance:**
  - `tests/unit/test_festival_models.py::TestEventFestivalFields`: SINGLE event with capacity 501 → ValidationError; FESTIVAL with capacity 1500 → ok; FESTIVAL with capacity 2001 → ValidationError; FESTIVAL without slots → ValidationError; duplicate slot keys → ValidationError; unsorted dates → ValidationError; `slot_keys()`/`night_slots()`/`slots_on()` return expected values; default `event_type` is SINGLE so all existing events parse unchanged.
  - `EventUpdate` with duplicate/unsorted/empty `festival_slots` on a FESTIVAL event → ValidationError (validator runs on update, not only create).
  - FESTIVAL `EventCreate`/`EventUpdate` with `registration_deadline=None` or `end_at=None` → ValidationError; SINGLE without them still parses (unchanged).
  - `participation_hint` round-trips on `EventCreate` and `EventUpdate`.
  - Existing event tests pass unmodified.

### T103 — Persist festival fields; suppress link token + autopromote at festival create ✅
- **Phase:** P1 · **Size:** S · **Depends on:** T102
- **Files:** `backend/app/services/event_service.py` (edit), `backend/tests/unit/test_festival_models.py` (edit)
- **What to do:**
  - `_event_to_item` (event_service.py:32-73): write `item["event_type"] = event.event_type.value` unconditionally; add optional-field blocks per the existing pattern (:53-71) for `end_at` (`.isoformat()`), `contact_hint`, `participation_hint` (Ä16 — same pattern as `contact_hint`), and `festival_slots` (list of dicts: `{"key", "label", "date": slot.date.isoformat(), "is_night", **({"capacity": n} if capacity else {})}`).
  - `_item_to_event` (:76-97): `event_type=item.get("event_type", "SINGLE")` (backfill default like `autopromote_waitlist` at :89), `end_at=datetime.fromisoformat(...) if item.get("end_at") else None`, `contact_hint=item.get("contact_hint")`, `participation_hint=item.get("participation_hint")`, `festival_slots=[FestivalSlot(**s) for s in item["festival_slots"]] if item.get("festival_slots") else None`.
  - `create_event` (token set at :141): when `event_data.event_type == EventType.FESTIVAL`, set `registration_link_token=None` (skip `_generate_link_token()`) and force `autopromote_waitlist=False` regardless of input. SINGLE path unchanged.
- **Acceptance:**
  - Round-trip test (moto or pure): FESTIVAL `Event` with slots/end_at/contact_hint/participation_hint → `_event_to_item` → `_item_to_event` → equal fields; legacy item without `event_type` parses as SINGLE.
  - Test: `create_event` with FESTIVAL yields `registration_link_token is None` and `autopromote_waitlist is False`; with SINGLE yields a token as before.

### T104 — Invite model + sk-prefix constant ✅
- **Phase:** P1 · **Size:** S · **Depends on:** T101
- **Files:** `backend/app/models/invite.py` (new), `backend/app/models/__init__.py` (edit), `backend/app/services/config.py` (edit)
- **What to do:**
  - `Invite(BaseModel)` per spec: `id: UUID` (default uuid4), `event_id: UUID`, `org_id: UUID`, `token: str`, `label: str` (1-200), `batch_label: str | None` (≤200), `email: EmailStr | None`, `tier: str` (free-form, ≤50; conventions werft/volunteer/org/open), `max_uses: int = 1` (ge=1), `use_count: int = 0` (ge=0), `max_group_size: int = 1` (ge=1, le=20), `expires_at: datetime | None`, `revoked_at: datetime | None`, `created_at: datetime` (factory `datetime.now(timezone.utc)` — no `utcnow()`), `created_by_admin_id: UUID | None`, `sent_at: datetime | None`, `last_registered_at: datetime | None`. Immutable updates via `model_copy(update={...})` only.
  - Request schemas: `InviteCreate {label, email?, tier, max_uses=1, max_group_size=1, expires_at?}`; `InviteBatchCreate {batch_label: str | None, invites: list[InviteCreate]}` (min length 1); `InviteUpdate` (all optional, `extra="forbid"` like `RegistrationAdminPatch`, registration.py:75).
  - Add `is_expired(self, registration_deadline: datetime) -> bool` helper: true when `revoked_at` set, or `expires_at` passed, or `registration_deadline` passed (implicit expiry per spec).
  - config.py: add `EVENT_SK_INVITE_PREFIX = "INVITE#"` to the constants block (config.py:119-136).
- **Acceptance:**
  - Model importable via `app.models` (needs `email-validator` installed, per repo test note); `max_group_size=21` → ValidationError; `is_expired` unit-tested for all three triggers in `tests/unit/test_invite_service.py` (file created in T105 — the helper test may land there).

### T105 — invite_service: CRUD, token lookup, atomic consume/release, batch create ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T101, T104
- **Files:** `backend/app/services/invite_service.py` (new), `backend/tests/unit/test_invite_service.py` (new)
- **What to do:**
  - Class + lazy singleton getter (`_invite_service = None; def get_invite_service()`), table via `get_events_table()` (config.py:55) — invites live in the **events table** as co-located rows (FAHRBERICHT precedent).
  - Module-level `_invite_to_item` / `_item_to_invite`: `pk=f"EVENT#{invite.event_id}"`, `sk=f"INVITE#{invite.id}"` (use `EVENT_SK_INVITE_PREFIX`), `entity_type="Invite"`, plain attribute `invite_token` (GSI key). Follow the required/optional-block serializer pattern of `_event_to_item` (event_service.py:32-73); `use_count` stored as number, written unconditionally.
  - Methods:
    - `create_invites_batch(org_id, event_id, batch: InviteBatchCreate, admin_id) -> list[Invite]`: one `Invite` per entry, `token=secrets.token_urlsafe(16)` (mirror `_generate_link_token`, event_service.py:27-29), `batch_label` applied to all; put each item.
    - `list_invites(event_id) -> list[Invite]`: query `Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("INVITE#")`, with pagination loop (copy registration_service.py:532-535).
    - `get_invite(event_id, invite_id)`, `get_invite_by_token(token)` — GSI query mirroring `get_event_by_link_token` (event_service.py:200-227) with `IndexName="invite-token-index"`, `KeyConditionExpression="invite_token = :token"`, try/except ClientError → None.
    - `update_invite(event_id, invite_id, patch: InviteUpdate) -> Invite | None` (model_copy + put); `revoke_invite(...)` sets `revoked_at=now`; `mark_sent(...)` sets `sent_at=now` only if currently unset (idempotent, Ä7); `touch_last_registered(...)`.
    - `consume_use(event_id, invite_id) -> bool`: `table.update_item` with `UpdateExpression="ADD use_count :one"`, `ConditionExpression="use_count < :max AND attribute_not_exists(revoked_at)"`, values `{":one": 1, ":max": invite.max_uses}`; catch `ClientError` code `ConditionalCheckFailedException` → return False.
    - `release_use(event_id, invite_id) -> bool`: `ADD use_count :neg` with `ConditionExpression="use_count > :zero"`.
  - Grandfathering (spec Ä-Invite): `update_invite` reducing `max_group_size` must NOT touch existing registrations — enforcement of "grow to max(current_size, invite.max_group_size)" lives in T109.
- **Acceptance (tests in `tests/unit/test_invite_service.py`, moto pattern: `InviteService()` with `_table` overridden, class-based `TestX` + autouse setup fixture per conftest conventions):**
  - Batch create of 3 entries → `list_invites` returns 3, all share `batch_label`, unique tokens.
  - `get_invite_by_token` finds an invite via the GSI; unknown token → None.
  - Consume/exhaust: `max_uses=2` → two consumes succeed, third returns False and `use_count` stays 2.
  - Consume after revoke → False.
  - `release_use` decrements; release at 0 → False (no negative counts).
  - `mark_sent` twice → `sent_at` unchanged after first call.
  - Expiry-at-deadline: `is_expired(deadline_in_past)` true even with `expires_at=None` and `revoked_at=None`.

### T106 — Registration model: festival fields, AccommodationType, FestivalRegistrationCreate, serialization ✅
- **Phase:** P1 · **Size:** M · **Depends on:** T102 (creates `test_festival_models.py`, edited here), T104
- **Files:** `backend/app/models/registration.py` (edit), `backend/app/models/__init__.py` (edit), `backend/app/services/registration_service.py` (edit — serializers only), `backend/tests/unit/test_festival_models.py` (edit)
- **What to do:**
  - Add `class AccommodationType(str, Enum): TENT = "TENT"; CAMPER = "CAMPER"` (Ä15 — NEEDS_SPOT dropped; `None` means „übernachtet nicht").
  - Add to `Registration` (registration.py:119-141), all optional additive: `invite_id: UUID | None = None`, `invite_label: str | None = None`, `tier: str | None = None` (denormalized for boards/CSV), `attendance_slots: list[str] | None = None`, `accommodation: AccommodationType | None = None` (a REQUEST, not an entitlement — Ä17), `phone: str | None = None` (Ä15 — verify the base model doesn't already carry a phone field before adding), `overnight_approved: bool = False` (Ä17 — set ONLY by admins via `RegistrationAdminPatch`/the T208 toggle, never via any public endpoint; drives the „angefragt"/„zugesagt" display).
  - **Tombstone typing (index stability, spec §Registration)**: on the festival paths, `group_members` is `list[str | None]` — a `None` entry is a tombstone for a removed member; indices never shift (QR `person_index` depends on them). Widen the base `Registration.group_members` type accordingly (additive — existing SINGLE data has no `None`s).
  - Add `FestivalRegistrationCreate(BaseModel)` — separate from `RegistrationCreate`; the existing `le=5` cap stays untouched: `name` (1-200), `email: EmailStr` with the lowercase normalizer (copy registration.py:44-48), `notes` (≤500), `group_size: int = 1` (ge=1, le=20), `group_members: list[str] | None` (copy `_clean_members`, registration.py:50-63 — no tombstones at create time), `attendance_slots: list[str]` (min_length=1), `accommodation: AccommodationType | None = None`, `phone: str | None = None`.
  - **Validators (Ä15/Ä16)** on `FestivalRegistrationCreate`:
    - **Full-name rule (Ä16)**: `name` and every non-None `group_members` entry must contain ≥ 2 words; German error „Bitte Vor- und Nachnamen angeben".
    - **Phone iff overnight (Ä15)**: `accommodation` set (TENT/CAMPER) ⇒ `phone` required (error if missing/blank); `accommodation is None` ⇒ silently clear `phone` to None.
  - Add `FestivalAttendancePatch(BaseModel, extra="forbid")`: `attendance_slots: list[str] | None`, `accommodation: AccommodationType | None`, `phone: str | None`, `group_size: int | None` (ge=1, le=20), `group_members: list[str | None] | None` (None entries = tombstones, T109). Full-name rule applies to non-None `group_members` entries here too.
  - **`overnight_approved` is deliberately in NEITHER `FestivalRegistrationCreate` NOR `FestivalAttendancePatch`** (Ä17 — guests can never set it; `extra="forbid"` on the patch already rejects it, the create schema simply has no such field). The only write path is the admin patch (T205).
  - Extend `RegistrationResponse` (registration.py:224-240) additively with `attendance_slots`, `accommodation`, `phone`, `overnight_approved`, `invite_label`, `tier`.
  - `_registration_to_item` (registration_service.py:41-85): optional blocks — `attendance_slots` with `is not None` (mirror `group_members` :79), `accommodation` as `.value`, `invite_id` as `str()`, `invite_label`, `tier`, `phone`; write `overnight_approved` unconditionally as bool, parse with `item.get("overnight_approved", False)`. `group_members` may contain `None` entries — DynamoDB stores them as NULL list elements; verify the round-trip preserves them. `_item_to_registration` (:88-121): symmetric `.get()` parsing (`UUID(item["invite_id"]) if item.get("invite_id") else None`).
- **Acceptance:**
  - Round-trip test: festival `Registration` with all new fields → item → model → equal; a `group_members` list with a `None` tombstone round-trips with the gap intact; legacy item without the fields parses with `None`s.
  - `FestivalRegistrationCreate` tests: `group_size=21` rejected, `attendance_slots=[]` rejected, email lowercased, `group_size=6` accepted (unlike `RegistrationCreate`).
  - Full-name rule: `name="Anna"` rejected with „Bitte Vor- und Nachnamen angeben"; `name="Anna Meier"` accepted; a one-word `group_members` entry rejected.
  - Phone iff overnight: `accommodation=TENT` without `phone` → ValidationError; `accommodation=None` with `phone="0123"` → parses with `phone is None`.
  - Ä17 guard: a `FestivalAttendancePatch` payload containing `overnight_approved` → ValidationError (`extra="forbid"`); `FestivalRegistrationCreate` has no such field; a legacy item without the attribute parses as `overnight_approved is False`.
  - Existing registration tests pass unmodified.

### T107 — Emails F1–F4: templates, context fields, send methods, MessageType values ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T102, T106
- **Files:** `backend/app/services/email_service.py` (edit), `backend/app/models/message.py` (edit), `backend/tests/unit/test_email_service.py` (edit)
- **What to do:**
  - `MessageType` (message.py:14-23): add `FESTIVAL_INVITATION = "festival_invitation"`, `FESTIVAL_CONFIRMATION = "festival_confirmation"`, `FESTIVAL_UPDATE = "festival_update"`, `FESTIVAL_CANCELLATION = "festival_cancellation"`.
  - `EmailContext` (email_service.py:29-45), additive optional: `slot_labels: str | None` (pre-rendered `{Zeitfenster}`: comma-joined chosen slot labels in festival order, e.g. `"Freitag, Samstag"` with the default slot config — never a range), `accommodation_label: str | None` (`{Schlafplatz}` with Ä17 request semantics, built from accommodation + `overnight_approved`: None→`"Nein"`; TENT→`"Zelt — angefragt"` / `"Zelt — zugesagt"`; CAMPER→`"Camper — angefragt"` / `"Camper — zugesagt"`. There is deliberately NO automatic approval email — the organizers coordinate by phone, Ä17; the guest sees „zugesagt" on the manage page and in the next F2/F3), `invite_url: str | None` (`{EinladungsLink}`), `contact_hint: str | None` (`{KontaktAdresse}`), `mitmach_hint: str | None` (`{MitmachHinweis}`, Ä16 — the event's `participation_hint`).
  - Add `_build_invite_url(token)` next to `_build_management_url` (email_service.py:71-74): `f"{settings.base_url}/invite/{token}"`.
  - Four `EmailTemplates` static methods returning `(subject, text, html)` with the exact German copy from the spec (F1–F4 blocks), "Moin {name}" style, existing HTML button style:
    - `festival_invitation(ctx, greeting_name: str | None, include_personal_sentence: bool)` — F1, subject `Du bist eingeladen: {event_name}`. Two INDEPENDENT template params (no single `personal` flag): `greeting_name=None` → greeting `Moin!`, else `Moin {greeting_name}`; `include_personal_sentence` controls the „Der Link ist persönlich…" sentence. Whether a label is a person's name is not auto-detectable — convention: personal (`max_uses=1`) invites are labeled with real names, so the caller (T112) derives both params from `max_uses`.
    - `festival_registration_confirmed(ctx, include_qr_paragraph: bool = False)` — F2, subject `Deine Anmeldung: {event_name}`. The „Eintritts-Codes"-paragraph is rendered ONLY when `include_qr_paragraph=True`; P1 always passes False at the call site (T308 flips the call site to True in P3 when manage-page QRs are live — the paragraph itself is built HERE, behind the flag). Per Ä14/Ä16, use the spec's current F2 body: the closing sentence is „Ändern kannst du deine Angaben jederzeit über den Link oben. / Bei Fragen: {KontaktAdresse}" (no „bis zum Anmeldeschluss" wording — registration runs until the festival's end), and a `{MitmachHinweis}` paragraph is rendered as its own paragraph ONLY when `ctx.mitmach_hint` is set.
    - `festival_updated(ctx)` — F3, subject `Deine Änderung: {event_name}`.
    - `festival_cancelled(ctx)` — F4, subject `Deine Absage: {event_name}` (dedicated so the lottery default „…Platz an einen anderen Fisch…" never reaches a festival guest).
  - Four send methods on `EmailService`, following `send_registration_confirmation` (email_service.py:748-787): build context (slot labels resolved via `event.festival_slots` label lookup preserving festival slot order) → template → `_send_email(..., message_type=MessageType.FESTIVAL_*)`. `send_festival_invitation(event, invite)` (requires `invite.email`; returns False otherwise), `send_festival_confirmation(event, registration)`, `send_festival_update_confirmation(event, registration)`, `send_festival_cancellation(event, registration)`.
- **Acceptance (extend `tests/unit/test_email_service.py`, pure template tests + `_messages_table = MagicMock()` pattern):**
  - F1 with `greeting_name="Anna"` + `include_personal_sentence=True` contains „Moin Anna" and „persönlich für dich"; with `greeting_name=None` + `include_personal_sentence=False` contains „Moin!" and not the personal sentence; the two params work independently; both variants contain the invite URL and `{KontaktAdresse}` value.
  - F2 with `include_qr_paragraph=False` does NOT contain „Eintritts-Codes"; with True it does; body lists slot labels comma-joined and the Schlafplatz label; with `mitmach_hint` set the body contains it as its own paragraph, without it no empty paragraph; body contains „jederzeit" and no „Anmeldeschluss"-bound edit wording (Ä14).
  - `{Schlafplatz}` renders all four Ä17 states: accommodation None → „Nein"; TENT + not approved → „Zelt — angefragt"; TENT + approved → „Zelt — zugesagt"; CAMPER analogous — asserted for both the F2 and F3 bodies.
  - F4 does NOT contain „Fisch"; contains contact hint.
  - Send methods queue a Message with `Item["status"] == "queued"` and the new `message_type` values.

### T108 — create_festival_registration: validation chain + atomic invite consume ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T103, T105, T106, T107
- **Files:** `backend/app/services/registration_service.py` (edit), `backend/tests/unit/test_festival_registration.py` (new)
- **What to do:**
  - New method `create_festival_registration(invite_token: str, data: FestivalRegistrationCreate) -> tuple[Registration | None, str | None]`, same tuple contract as `create_registration` (registration_service.py:279-386). Error strings must be router-mappable (T111): use `"not found"`, `"revoked"`, `"expired"`, `"exhausted"`, `"deadline"`, `"not open"`, `"already registered"`, plain messages otherwise.
  - Validation chain, in order (spec §Data model deltas):
    1. `get_invite_service().get_invite_by_token(invite_token)` → None ⇒ `(None, "Invite not found")`. Revoked ⇒ `"Invite revoked"` (router maps to 404 like unknown).
    2. Event via `get_event_service().get_event(invite.org_id, invite.event_id)` (direct lookup, event_service.py:173 — invite carries org_id, avoid the :229 scan).
    3. `event.event_type == FESTIVAL` and `event.status == OPEN`, else `"not open"`; `now < registration_deadline` (hard stop) else `"deadline"` — per Ä14 the deadline is configured as the festival's end, the mechanics are unchanged; `invite.is_expired(event.registration_deadline)` ⇒ `"expired"`.
    4. `data.group_size <= invite.max_group_size` else error naming the allowance.
    5. `set(data.attendance_slots) ⊆ set(event.slot_keys())` and ≥1 slot (schema already enforces min 1).
    6. Overnight (Ä15): `accommodation` is optional and independent of the chosen slots — `None` = no overnight; `is_night` no longer gates anything. Re-check **phone-iff-accommodation** at service level (schema already validates, T106): accommodation set (TENT/CAMPER) ⇒ `phone` required (error if missing); accommodation None ⇒ `phone` cleared to None.
    7. Duplicate email via `_check_duplicate_email(event_id, email)` (registration_service.py:259-277) ⇒ `"already registered"`. (Per event — one person cannot redeem two invites; intended, spec Risks #3.)
    8. **Atomic consume**: `consume_use(...)` → False ⇒ `"exhausted"` (Kontingent aufgebraucht).
    9. Build `Registration`: `status=RegistrationStatus.PARTICIPATING`, `registered_at=now`, `responded_at=registered_at`, `registration_token=secrets.token_urlsafe(32)` (registration_service.py:36-38), denormalized `invite_id/invite_label/tier`, `attendance_slots`, `accommodation`. Conditional put (mirror :363-366). **On put failure: `release_use(...)` before returning the error.**
    10. `mark`: `touch_last_registered(invite)`; send F2 via `send_festival_confirmation` in the try/except-never-fail pattern; email failure never fails the registration.
  - Slot caps are NEVER enforced here (soft only, Ä8/Ä4). No waitlist branch, no `waitlist_position`, ever.
- **Acceptance (tests in `tests/unit/test_festival_registration.py`, moto: `RegistrationService()` + `InviteService()` with tables injected, seed via `_event_to_item`/`_invite_to_item`):**
  - [x] Happy path: registration created with `status == PARTICIPATING`, `responded_at == registered_at`, invite `use_count == 1`, F2 queued (messages table or mocked email service asserted).
  - [x] Slot-subset: unknown slot key ⇒ error, `use_count` stays 0.
  - [x] Overnight (Ä15): `accommodation=TENT` without phone ⇒ error, `use_count` stays 0; `accommodation=CAMPER` + phone with day-only slots ⇒ created (no `is_night` gating); `accommodation=None` ⇒ created with `phone is None`.
  - [x] Group cap: `group_size=3` vs `max_group_size=2` ⇒ error.
  - [x] Deadline passed ⇒ error containing `"deadline"`; event DRAFT ⇒ `"not open"`.
  - [x] Duplicate email ⇒ `"already registered"`, no consume.
  - [x] Consumption race/exhaustion: `max_uses=1`, two sequential creates with different emails ⇒ second fails with `"exhausted"` and `use_count == 1` (conditional-update guarantee).
  - [x] Put failure releases the use: patch `put_item` to raise ⇒ error returned and `use_count` back to 0.

### T109 — update_festival_attendance + festival cancel branch (release use, F4) ✅
- **Phase:** P1 · **Size:** M · **Depends on:** T108
- **Files:** `backend/app/services/registration_service.py` (edit), `backend/app/api/public/cancellations.py` (edit), `backend/tests/unit/test_festival_registration.py` (edit)
- **What to do:**
  - New method `update_festival_attendance(registration_id, token, patch: FestivalAttendancePatch) -> tuple[Registration | None, str | None]`:
    - Lookup via `get_registration_by_token` (registration_service.py:460-485), verify id match; must be a festival registration (event `event_type == FESTIVAL`) and not CANCELLED.
    - Lifecycle gate (spec matrix): event status ∈ {OPEN, REGISTRATION_CLOSED, CONFIRMED} AND `now < registration_deadline`, else error `"deadline"` (manage page then shows contact_hint).
    - Re-run the T108 validations on the patched values: slot subset, ≥1 slot, phone-iff-accommodation against the resulting state (Ä15 — accommodation is always optional, `is_night` gates nothing; accommodation set ⇒ phone required, accommodation None ⇒ phone cleared).
    - **Ä17 reset**: when the patch clears the accommodation wish (accommodation → None), also reset `overnight_approved` to False — a withdrawn request must not keep a stale approval. Guests can never SET the flag (not in the schema, T106); this reset is the only way self-service touches it.
    - **Grandfathering** (spec §Invite): allowed max group size = `max(registration.group_size, invite.max_group_size)` (fetch invite via `registration.invite_id`; if invite missing, fall back to current `group_size`). Reducing `max_group_size` on the invite never invalidates an existing registration.
    - **`group_members` edits are APPEND-ONLY with tombstones** (spec §Registration index stability — QR `person_index` depends on list positions): removing a member REPLACES their entry with `None` (type `list[str | None]`, T106) — never delete/shift entries; new members APPEND at the end; order and indices of existing entries never change; a plain list replacement that reindexes is forbidden. `group_size` counts contact + non-None members, so the "length must fit `group_size - 1`" rule counts ONLY non-None entries. Apply via `model_copy(update={...})`, put, send F3 (`send_festival_update_confirmation`) never-fail.
  - Festival cancel branch in `cancel_registration` (registration_service.py:546+):
    - After the status flip, if the event is FESTIVAL: call `get_invite_service().release_use(event_id, registration.invite_id)` when `invite_id` is set, and **skip** the `_promote_from_waitlist` call at :609 (explicit guard; autopromote=False already makes it inert — defense in depth).
    - **F4 is sent HERE, by the service**: the festival cancel branch itself sends `send_festival_cancellation(event, registration)` in the try/except-never-fail pattern — so every caller (public cancel, admin cancel T203) gets F4 for free and there is exactly one send site.
    - Cancel is allowed anytime until event COMPLETED — ensure no deadline check blocks the festival path.
  - In `public/cancellations.py` (email block :74-94): guard the existing `send_cancellation_confirmation` call with `event.event_type != FESTIVAL` (its lottery copy must never reach festival guests) — do NOT send F4 from this router; the service cancel branch above already sent it.
- **Acceptance (extend `tests/unit/test_festival_registration.py`):**
  - [x] Slot edit before deadline succeeds and F3 is queued; edit after deadline ⇒ error containing `"deadline"`, registration unchanged.
  - [x] Grandfathering: invite `max_group_size` reduced 3→1 while registration has `group_size=3` ⇒ patch keeping `group_size=3` succeeds, growing to 4 fails.
  - [x] Ä17 reset: registration with `accommodation=TENT, overnight_approved=True` patched to `accommodation=None` ⇒ `overnight_approved` back to False (and phone cleared); patching only slots leaves an existing approval untouched.
  - [x] Tombstones: removing member 1 of `["Anna Meier", "Ben Otto"]` ⇒ `group_members == [None, "Ben Otto"]` — „Ben Otto" keeps index 1; re-adding a member appends (`[None, "Ben Otto", "Cem Demir"]`), never fills the gap by shifting; `group_size` reflects contact + non-None members.
  - [x] Cancel releases the use AND queues F4 from the service (assert the F4 message row without going through the router): after cancel, invite `use_count` decremented; a new registration on the same invite succeeds again.
  - [x] Cancel after deadline succeeds; cancelled registration keeps `attendance_slots` (history) but status CANCELLED.
  - [x] Festival cancel triggers no waitlist promotion (assert no WAITLISTED registration got promoted / `_promote_from_waitlist` not called).

### T110 — Defense-in-depth guards: lottery, waitlist, worker, legacy public create ✅
- **Phase:** P1 · **Size:** M · **Depends on:** T102, T103, T108 (creates `test_festival_registration.py`, edited here)
- **Files:** `backend/app/services/lottery_service.py` (edit), `backend/app/api/admin/lottery.py` (edit), `backend/app/services/registration_service.py` (edit), `backend/app/workers/handler.py` (edit), `backend/tests/unit/test_lottery.py` (edit), `backend/tests/unit/test_festival_registration.py` (edit)
- **What to do:**
  - `lottery_service.run_lottery` (lottery_service.py:132-228): after the event fetch at :139-141, alongside the existing status guard at :143-144, raise `ValueError("Für Festivals gibt es keine Lotterie — Anmeldungen über Einladungslinks sind sofort bestätigt.")` when `event.event_type == EventType.FESTIVAL`. Same guard in `finalize_lottery` next to its status guard at :261-262.
  - `admin/lottery.py`: the run endpoint currently maps `ValueError` → 400 (lottery.py:48-51). Add an explicit FESTIVAL pre-check in the handler returning **409** (`HTTPException(status_code=status.HTTP_409_CONFLICT, detail=...)`) per spec, so the service ValueError stays a fallback.
  - `_promote_from_waitlist` (registration_service.py:619-710): next to the `event.autopromote_waitlist` check at :640, early-return when `event.event_type == FESTIVAL` (inert already via autopromote=False from T103 — belt and braces).
  - Worker `send_confirmation_reminders` (workers/handler.py:23+): it iterates `get_events_by_status(EventStatus.CONFIRMED)` (:44) — skip events with `event_type == FESTIVAL` (already inert since festival registrations are PARTICIPATING, never CONFIRMED; guard documents the invariant).
  - Legacy public create: `create_registration` (registration_service.py:279-386) — reject with `"not open"` when the resolved event is FESTIVAL (dead by construction: festivals have no `registration_link_token`, but guard anyway).
- **Acceptance:**
  - [x] `test_lottery.py`: `run_lottery` on a FESTIVAL event raises ValueError (use the existing mocked-event pattern, `self.mock_event_service.get_event.return_value = festival_event`). (Also added the analogous `finalize_lottery` guard test, not explicitly required but exercised for consistency.)
  - [x] `test_festival_registration.py`: FESTIVAL event given an artificial `registration_link_token` → `create_registration` returns the `"not open"` error; `_promote_from_waitlist` on a festival event promotes nobody even with `autopromote_waitlist=True` forced on the model.
  - [x] Full suite passes — regular (SINGLE) lottery/waitlist tests unchanged.
  - Not independently unit-tested: the `admin/lottery.py` 409 pre-check (repo has no HTTP-level test style, per T111's own precedent note — verified by code inspection only).

### T111 — Public invite router + manage-page GET extension ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T108, T109
- **Files:** `backend/app/api/public/invites.py` (new), `backend/app/main.py` (edit), `backend/app/api/public/registrations.py` (edit)
- **What to do:**
  - New bare `router = APIRouter()` module (pattern: public/registrations.py:26); register in main.py next to :136-138: `app.include_router(public_invites.router, prefix="/api/public", tags=["public"])`.
  - `GET /invites/{invite_token}` — form-boot. Response model: `{event_name, start_at, end_at, registration_deadline, contact_hint, participation_hint, slots: [{key, label, date, is_night}], max_group_size}`. No `valid: bool` field — it would be dead: every invalid state answers 404/410, so a 200 IS "valid" (document this in the route docstring). NEVER expose `use_count`/`max_uses` (spec: counts are admin-only). Error branching (mirror registrations.py:99-118 style; the three 410 states get three DISTINCT German messages — never shared copy):
    - Unknown token or revoked → **404** `"Dieser Einladungslink ist ungültig."`
    - Exhausted (`use_count >= max_uses`) → **410** `"Dieser Einladungslink ist bereits vollständig eingelöst."` + contact-hint sentence
    - Expired (the invite's own `expires_at` passed) → **410** `"Dieser Einladungslink ist abgelaufen."` + contact-hint sentence
    - Deadline passed → **410** `"Die Anmeldung ist leider geschlossen."` + contact-hint sentence
    - Contact-hint sentence appended when `event.contact_hint` is set: `" Frag die Person, von der du den Link hast, oder schreib an {contact_hint}."`
  - `POST /invites/{invite_token}/registrations` — body `FestivalRegistrationCreate` → `create_festival_registration`. Map error strings: `"not found"`/`"revoked"` → 404, `"already registered"` → 409, `"deadline"`/`"not open"`/`"expired"`/`"exhausted"` → 410, else 400 (extend the registrations.py:99-118 pattern). Success response: `RegistrationResponse` fields plus `manage_url: str` built as `f"{get_settings().base_url}/registration/{reg.id}?token={reg.registration_token}"` (mirror `_build_management_url`, email_service.py:71-74).
  - `PATCH /registrations/{registration_id}/festival-attendance?token=` — body `FestivalAttendancePatch` → `update_festival_attendance`; same error mapping; F3 sent by the service.
  - Manage GET extension (registrations.py:207-288), all additive: extend `EventInfo` (:177-182) with `event_type`, `contact_hint`, `festival_slots: [{key,label,date,is_night}] | None`; extend `ManageRegistrationResponse` (:185-193) with `attendance_slots`, `accommodation`, `phone` (edit-mode prefill, T117), `overnight_approved` (Ä17 — read-only for guests, drives the „angefragt"/„zugesagt" display; no public endpoint accepts it), `editable_until` (= event `registration_deadline` isoformat, None for SINGLE). German status message for PARTICIPATING already exists in the dict at :259-267 — reuse.
- **Acceptance:**
  - Manual curl walk (documented in PR): boot a valid invite → 200 with slots, `participation_hint`, no counts, and no `valid` key; revoked → 404; exhausted vs expired vs deadline-passed → three 410s with three different `detail` texts, each containing the contact hint; POST creates and returns `manage_url`; PATCH edits slots; SINGLE-event manage response is byte-compatible with before (new fields null).
  - Service-level behavior is covered by T108/T109 tests (repo has no HTTP-level tests — do not introduce a new test style here).

### T112 — Admin festival router: event CRUD, invite batch/list/patch/send/mark-sent, events-list filter ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T105, T107, T103
- **Files:** `backend/app/api/admin/festival.py` (new), `backend/app/main.py` (edit), `backend/app/api/admin/events.py` (edit)
- **What to do:**
  - New router registered in main.py next to :122: `app.include_router(admin_festival.router, prefix="/api/admin/festival", tags=["admin-festival"])`. Guards: `dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))]` on writes, `[...OWNER, ADMIN, VIEWER]` on reads (pattern events.py; FESTIVAL role deferred, Ä1). Copy `_get_org_id`/`_get_admin_id` helpers (events.py:82-95).
  - Festival event CRUD (the festival section is the only UI for it):
    - `POST /events` — body `EventCreate`; force `event_type=EventType.FESTIVAL` via `model_copy(update=...)` before `create_event` (T103 then suppresses link token + autopromote).
    - `GET /events` — `list_events(org_id)` filtered to `event_type == FESTIVAL`. **Declaration-order trap** (same as export-csv, events.py:1113): declare the literal `/events` routes BEFORE the parameterized `GET /{event_id}` in this router, or `"events"` gets swallowed as an `event_id` — note it in a comment.
    - `GET /{event_id}` / `PUT /{event_id}` — settings incl. `festival_slots`, `end_at`, `contact_hint`, `participation_hint`, `registration_deadline`, `capacity` (Ä8 + slot + required-deadline/end_at validators apply on update too, T102).
    - `POST /{event_id}/status` — body `{status}`; use `event.can_transition_to`/`transition_to` (event.py:107-129); 409 on invalid transition.
  - Invite endpoints:
    - `POST /{event_id}/invites` — body `InviteBatchCreate` → `create_invites_batch`; response rows include `token` and `url` (`f"{settings.base_url}/invite/{token}"`). `log_admin_action("festival.invites.create", user.email, str(event_id))` (precedent events.py:1081).
    - `GET /{event_id}/invites` — status list: each row `{id, label, batch_label, tier, email, max_uses, use_count, max_group_size, sent_at, revoked_at, expires_at, expired (computed vs deadline), last_registered_at, url}`.
    - `PATCH /{event_id}/invites/{invite_id}` — body `InviteUpdate` or `{"revoked": true}` → `update_invite`/`revoke_invite`. No rotate endpoint (Ä3).
    - `POST /{event_id}/invites/{invite_id}/send-email` — 400 if invite has no email; `send_festival_invitation` with the F1 params derived here: `greeting_name = invite.label if invite.max_uses == 1 else None`, `include_personal_sentence = invite.max_uses == 1` (whether a label is a person's name is not auto-detectable — convention: personal `max_uses=1` invites are labeled with real names), then `mark_sent`.
    - `POST /{event_id}/invites/{invite_id}/mark-sent` — Ä7 lightweight stamp for the copy-row action; idempotent; returns the updated row.
  - Events-list isolation: in the existing admin list handler in `events.py`, filter out `event_type == FESTIVAL` before building `EventListResponse` (:75-79) so festivals never appear in the regular events UI.
- **Acceptance:**
  - Batch create of a 3-line Kontingent returns 3 rows with URLs; `GET .../invites` shows `use_count/max_uses` and `expired` correctly for a past-deadline festival (service behavior covered by T105 tests; route wiring verified by manual curl walk in PR).
  - `GET /api/admin/events` no longer lists a created festival; `GET /api/admin/festival/events` does.
  - send-email queues an F1 Message and stamps `sent_at`; mark-sent twice leaves the first timestamp (T105 test covers idempotence).

### T113 — Gate CSV export (Ä9 floor) ✅
- **Phase:** P1 · **Size:** M · **Depends on:** T112
- **Files:** `backend/app/api/admin/festival.py` (edit), `backend/app/services/registration_service.py` (edit — pure row builder), `backend/tests/unit/test_festival_registration.py` (edit)
- **What to do:**
  - **Route-ordering trap**: declare `GET /{event_id}/registrations/export-csv` BEFORE any future `/{event_id}/registrations/{registration_id}` route in festival.py, with a docstring noting why — precedent and wording at events.py:1113-1114. Query param `view: str = "gate"`; only `gate` in P1 (catering is P2; return 400 for unknown views).
  - Pure helper `build_gate_rows(registrations: list[Registration], event: Event) -> list[dict]` in registration_service.py (module level, testable without HTTP):
    - Exclude CANCELLED (Ä5).
    - Expand one row per **person**: the contact and each `group_members` entry (person rows carry the contact's name in a `Kontaktperson` column).
    - Sort alphabetically by person name (locale-naive `str.casefold` sort is fine for a printed list).
    - Columns: `Name`, `Kontaktperson`, `Kontingent` (`batch_label` or `invite_label`), `Tier`, `Schlafplatz` (Ä15/Ä17 approval semantics, same mapping as `{Schlafplatz}` in T107: `Nein` / `Zelt — angefragt` / `Zelt — zugesagt` / `Camper — angefragt` / `Camper — zugesagt` — the paper list is the scanner fallback and must show the approval status too), `Telefon` (Ä15 — the registration's phone, on every person row of the group; empty when no overnight), one column per `event.festival_slots` label with `"x"` when the registration ticked it (**info only — slots are never checked at the gate**, Ä13), then empty tick-off columns `Angekommen` and `Bändchen`. Skip `None` tombstone entries in `group_members` (removed members get no row).
  - Route: `list_registrations(event_id)` → `build_gate_rows` → `csv.writer(..., delimiter=";")` (German Excel — same dialect as the catering export, T204) into `io.StringIO`, encode `utf-8-sig` (Excel umlauts — no manual BOM prepending), return `StreamingResponse(io.BytesIO(data), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})` — mirror events.py:1094-1098 incl. the umlaut `str.maketrans` filename sanitization at :1084-1093. Audit: `log_admin_action("festival.gate_export", user.email, str(event_id))`.
  - Ä14 runbook note (docstring): registration runs until the festival's end, so this list is **reprinted every festival evening** — the export must always reflect the live state, no caching.
- **Acceptance (tests on `build_gate_rows`):**
  - Registration with `group_size=3` and 2 group members yields 3 rows; rows sorted alphabetically across registrations. (verified, `test_group_expands_to_one_row_per_person_sorted_alphabetically`)
  - CANCELLED registration contributes 0 rows. (verified, `test_cancelled_registration_yields_no_rows`)
  - Slot columns match `festival_slots` order; a ticked slot shows `"x"`, others empty; `Angekommen`/`Bändchen` columns exist and are empty. (verified, `test_slot_columns_match_festival_slots_order_and_ticks`)
  - Schlafplatz shows the Ä17 states (`Nein` / `Zelt — angefragt` / `Zelt — zugesagt` / Camper analogous; never empty, never NEEDS_SPOT); Telefon filled exactly for overnight registrations; a tombstoned (`None`) group member yields no row. (verified, `test_schlafplatz_states_and_telefon_only_when_overnight` + `test_tombstoned_group_member_yields_no_row`)
  - Manual: downloaded CSV opens in Excel/Numbers with correct umlauts and `;`-separated columns. **(not verified — no manual browser/Excel walk performed this session; route mirrors the already-shipped PDF export's `utf-8-sig`/`str.maketrans` handling at events.py:1084-1098.)**

### T114 — Extend infra/mail-vorlagen.md with F1–F4 and the new placeholders ✅
- **Phase:** P1 · **Size:** S · **Depends on:** T107
- **Files:** `infra/mail-vorlagen.md` (edit)
- **What to do:**
  - Append templates F1–F4 with the exact German copy shipped in T107, synced to the spec's current F1–F4 blocks (subjects, bodies, variant notes: F1 `greeting_name`-„Moin!"/personal-sentence rules — two independent params, convention `max_uses=1` ⇒ real-name label; F2 QR-paragraph gated on P3, `{MitmachHinweis}` paragraph rendered only when set, „jederzeit ändern" closing per Ä14).
  - Document the new placeholders: `{Zeitfenster}` (comma-joined slot labels, e.g. „Freitag, Samstag" — never a range), `{Schlafplatz}` (Ä17 request semantics: „Nein" / „Zelt — angefragt" / „Zelt — zugesagt" / „Camper — angefragt" / „Camper — zugesagt"; approval is coordinated by phone, no automatic approval email), `{EinladungsLink}`, `{KontaktAdresse}`, `{MitmachHinweis}` (Ä16 — the configured Mitmach text incl. Schichtplan link).
  - Verify & document that template 12 (admin bulk mail with `{Verwaltungslink}`) also works for festival registrations — this is the manual pre-festival reminder path (spec „Challenged & decided": no new automatic template). The festival-section send surface for it lands in **T211** (MessageComposer reuse) — note that pointer in the doc.
- **Acceptance:**
  - Doc copy is character-identical to the `EmailTemplates` strings (spot-check subjects + one body each).
  - Template-12 note present with the verification result and the T211 pointer.

### T115 — api.js: publicApi invite methods + adminApi.festival namespace ✅
- **Phase:** P1 · **Size:** S · **Depends on:** T111, T112
- **Files:** `frontend/src/services/api.js` (edit)
- **What to do:**
  - `publicApi`: `getInviteInfo(inviteToken)` → `GET /api/public/invites/{token}`; `createFestivalRegistration(inviteToken, payload)` → POST; `updateFestivalAttendance(registrationId, token, payload)` → `PATCH /api/public/registrations/{id}/festival-attendance?token=${token}` (token-as-query pattern like existing public methods).
  - `adminApi.festival` nested object (pattern: `adminApi.bar`): `createEvent, listEvents, getEvent, updateEvent, setStatus, createInvites(eventId, batch), listInvites(eventId), patchInvite(eventId, inviteId, patch), sendInviteEmail(eventId, inviteId), markInviteSent(eventId, inviteId), exportGateCsv(eventId)`.
  - `exportGateCsv`: copy the blob-download pattern from `exportBoardingPdf` (api.js:386-408) — raw fetch with bearer, `response.blob()`, temp `<a download>`, filename from `Content-Disposition`.
- **Acceptance:**
  - All methods hit the T111/T112 paths with correct verbs and snake_case payloads; error objects keep `.status` (existing `request` helper untouched).
  - Gate CSV downloads via the browser against a local backend.

### T116 — FestivalRegistrationPage (public form) + route ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T115
- **Files:** `frontend/src/pages/registration/FestivalRegistrationPage.vue` (new), `frontend/src/router/index.js` (edit)
- **What to do:**
  - Route: `{ path: '/invite/:inviteToken', component: () => import('../pages/registration/FestivalRegistrationPage.vue'), props: true }`.
  - **Fork** `RegistrationPage.vue` (do NOT branch the original — spec isolation rule). Keep its structure: loading `aria-busy` → error `role="alert"` → event details `<dl>` → form → success; script-setup order per repo convention; inline errors, no toasts (public page).
  - Boot via `publicApi.getInviteInfo(route.params.inviteToken)`. 404/410 → show the backend's German `detail` directly (it already includes the contact hint).
  - **Mitmach-Hinweis box (Ä16)**: render `participation_hint` from the form-boot response in a prominent info box above the form (it contains the Schichtplan link — make URLs clickable or render as pre-wrapped text); omit the box when unset.
  - Form fields: Name*, E-Mail*, Begleitungen (name inputs, shown up to `max_group_size - 1`; `group_size` derived from filled entries), **time-slot checkbox grid grouped by day** — group `slots` by `date`, weekday heading via `formatDate`/`Intl` (formatters.js), one checkbox per slot with its `label` (default config renders as „Freitag" / „Samstag" / „Sonntag" multiple choice; finer windows like „Fr Abend" remain possible as pure config, Ä12).
  - **Full-name validation (Ä16)**: Name and every filled Begleitung entry must contain ≥ 2 words; inline German hint „Bitte Vor- und Nachnamen angeben" before submit (backend re-validates, T106).
  - **Overnight radio, ALWAYS visible (Ä15)** — no night-slot gating logic anywhere on this page. Group label „Übernachtest du auf dem Gelände?", options: „Nein" (default) / „Zelt — wir bringen unser eigenes Zelt mit" (`TENT`) / „Camper/Bus — wir schlafen im eigenen Fahrzeug" (`CAMPER`).
  - **Phone input (Ä15)**: appears and is REQUIRED when Zelt or Camper is selected — label „Telefonnummer — für die Stellplatz-Planung"; hidden and cleared from the payload when „Nein".
  - **Request copy (Ä17)**: when Zelt or Camper is selected, show next to the radio: „Schlafplätze sind begrenzt — deine Angabe ist eine Anfrage, keine Zusage. Wir melden uns bei dir." (overnight is a request; approval happens admin-side, never on this form).
  - Submit: snake_case payload (`group_size`, `group_members`, `attendance_slots`, `accommodation`, `phone`), trimmed/lowercased per RegistrationPage; map 409 → „Mit dieser E-Mail-Adresse gibt es schon eine Anmeldung.", 410 → backend detail.
  - Success screen: „Link speichern!" box with the `manage_url` from the POST response + copy button (`navigator.clipboard.writeText(url).catch(() => {})` per RegistrationPage precedent).
- **Acceptance:**
  - Manual walk: valid invite renders the Mitmach-Hinweis box and slots grouped by day (default: Freitag/Samstag/Sonntag); the overnight radio is visible from the start with „Nein" preselected regardless of slot selection; choosing Zelt/Camper reveals a required phone input AND the „Schlafplätze sind begrenzt — … Anfrage, keine Zusage …" copy (hidden on „Nein"), switching back to „Nein" hides and clears both; submitting Zelt without phone blocks with a German inline error; a one-word name blocks with „Bitte Vor- und Nachnamen angeben"; success screen shows a copyable manage URL; revoked/expired/exhausted/deadline links show their distinct German messages incl. contact hint.
  - No modification to `RegistrationPage.vue`; regular `/register/:token` flow unaffected.

### T117 — Manage-page festival branch: slot summary, edit until deadline, cancel ✅
- **Phase:** P1 · **Size:** M · **Depends on:** T115, T111
- **Files:** `frontend/src/pages/registration/RegistrationManagePage.vue` (edit)
- **What to do:**
  - Additive branch keyed on `eventInfo?.event_type === 'FESTIVAL'` inside the existing status-switch template (the PARTICIPATING/CONFIRMED blocks) — grounding: the switch of `v-else-if` blocks with `.status-banner` sections.
  - Show: chosen slot labels (map `attendance_slots` keys → `eventInfo.festival_slots` labels, festival order), the overnight status line from `overnight_approved` (Ä17: „Übernachtung: Zelt — angefragt" / „Übernachtung: Zelt — zugesagt" / Camper analogous / „Übernachtung: Nein") + phone when overnight, group members (skip `None` tombstones in the display). The approval status is display-only — guests have NO control for it (edit mode edits the wish, never the flag; clearing the wish resets it server-side, T109).
  - Edit mode (button „Angaben ändern") visible while `now < editable_until` and status not CANCELLED (per Ä14 the deadline is the festival's end, so this stays editable during the festival): slot checkbox grid + always-visible overnight radio + phone-iff-overnight input + group member inputs (same Ä15/Ä16 rules and full-name validation as T116; extract a small shared component or duplicate locally — do not touch the SINGLE branches). **Member removal sends a `None` tombstone at that index, new members append — never reindex** (T109 append-only rule; the QR `person_index` depends on it). Save via `publicApi.updateFestivalAttendance(...)`, then `await loadRegistration()`; per-action `saving/saveError/saveSuccess` triplet with the 3s auto-clear (existing pattern).
  - Post-deadline: replace the edit button with „Deine Zeiten kannst du nicht mehr selbst ändern — schreib uns an {contact_hint}" (only when `contact_hint` set) — with the Ä14 config this only fires after the festival has ended; the copy stays correct.
  - Cancel: reuse the existing `showCancelDialog` Pico dialog + `handleCancel()` path unchanged — available regardless of deadline for festival registrations (backend allows it; F4 is sent server-side).
- **Acceptance:**
  - Manual walk: festival registration shows slots + the overnight status line („… — angefragt" until an admin approves, „… — zugesagt" after; + Telefon when overnight) with no guest-facing control for the approval; edit before deadline persists and re-renders (F3 queued backend-side); switching overnight to Zelt requires a phone number; removing a member then reloading shows the remaining members unchanged (tombstone, no reindex); after deadline the contact-hint text appears and inputs are gone; cancel works after the deadline and the page re-renders CANCELLED.
  - A SINGLE-event manage page renders pixel-identical to before (new fields null → branch inactive).

### T118 — FestivalPage (settings + slot editor), admin routes, nav tab ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T115
- **Files:** `frontend/src/pages/admin/festival/FestivalPage.vue` (new), `frontend/src/router/index.js` (edit), `frontend/src/App.vue` (edit)
- **What to do:**
  - Routes (all `beforeEnter: authGuard`, lazy imports, `props: true`): `/admin/festival` → FestivalPage; `/admin/festival/:eventId/invites` → InvitesPage (page lands in T119 — add both routes here, InvitesPage import resolves after T119 merges, or add its route in T119 if merged separately; keep one PR if possible).
  - FestivalPage: loads `adminApi.festival.listEvents()`; if none → create form; else settings view. Do NOT reuse `EventForm.vue` (no `event_type` field there; isolation) — build a festival-specific form: Name*, Beschreibung, Ort, Beginn*/Ende* (`datetime-local`: `berlinToUTCISO` comes from formatters.js; `formatDateTimeLocal` is a **local function in `EventForm.vue:131`**, not in formatters.js — copy it into FestivalPage or extract it to formatters.js, since EventForm.vue itself must not be reused), Anmeldeschluss* (per Ä14 configured as the festival's end, e.g. So 16.8. 23:59 — hint text „Anmeldung läuft bis zum Ende des Festivals"), Gesamt-Kapazität (soft, hint „Richtwert — blockiert nie"), Kontakt-Adresse (`contact_hint`), **Mitmach-Hinweis textarea** (`participation_hint`, Ä16 — label „Mitmach-Hinweis (mit Schichtplan-Link)").
  - **Slot editor**: editable row list — Label*, Datum*, „Nacht"-checkbox, Kapazität (optional, soft); `key` auto-slugified from label (lowercase, umlauts transliterated, spaces→`-`, deduped); add/remove/reorder rows; client-side hint when rows are not date-sorted (backend validator rejects on create AND update, T102). Expected default config (B-decision 19.7.): three rows „Freitag" / „Samstag" / „Sonntag" — finer windows stay possible. Warn before removing a slot that may already have registrations („Zeitfenster mit Anmeldungen nicht löschen — erst mit dem Team klären").
  - Status actions: buttons per `EVENT_STATUS_TRANSITIONS`-legal next states (Veröffentlichen → OPEN, Anmeldung schließen → REGISTRATION_CLOSED, …) calling `adminApi.festival.setStatus`; `showToast` on success/error (admin pages use toasts, `useToast.js`).
  - Nav: new tab in App.vue bottom nav (lines 26-84 pattern): `<a class="nav-tab">` with lucide `Tent` icon, label „Festival", `isFestivalActive = route.path.startsWith('/admin/festival')`, `navTo('/admin/festival')`. Note: this is a 5th tab (6th in devMode) — verify `flex: 1` widths on a 375px viewport.
- **Acceptance:**
  - Manual walk: create festival (default slots „Freitag"/„Samstag"/„Sonntag") → appears under /admin/festival, NOT under /admin/events; capacity 1500 accepted; publish → OPEN; `participation_hint` saves and reloads.
  - Slot editor round-trips: saved slots reload with labels/dates/is_night intact; invalid (empty/unsorted) slot sets surface the backend's German validation error via toast — also on UPDATE of an existing festival (T102 update validator).
  - Nav tab highlights on /admin/festival/* and does not break the existing 4-tab layout on mobile.

### T119 — InvitesPage + InviteBatchModal (Kontingent UI, copy-stamps-sent, chips, revoke) ✅
- **Phase:** P1 · **Size:** L · **Depends on:** T115, T118
- **Files:** `frontend/src/pages/admin/festival/InvitesPage.vue` (new), `frontend/src/pages/admin/festival/InviteBatchModal.vue` (new), `frontend/src/router/index.js` (edit — if the route was not already added in T118)
- **What to do:**
  - InvitesPage (route `/admin/festival/:eventId/invites`, `props: true`): loads `adminApi.festival.listInvites(eventId)`; rows grouped by `batch_label` (Kontingent) with a summary row each: issued seats = Σ `max_uses × max_group_size`, „angemeldet" = Σ `use_count`, „maximal noch zu erwarten" = **Σ `(max_uses − use_count) × max_group_size` over non-revoked, non-expired invites** (people-dimensioned; identical formula to T209 — a plain „issued − registered" would subtract registrations from people) — displayed against the event cap.
  - Status chips per row (derive client-side): `widerrufen` (revoked_at), `abgelaufen` (expired), `angemeldet` (use_count ≥ 1; multi-use shows `„2/5 angemeldet"`), `verschickt` (sent_at), else `offen`. Style via the existing `.status-badge` idiom (EventsPage grounding).
  - **Copy row (Ä7)**: button per row → `navigator.clipboard.writeText` of greeting + link (`` `Moin ${label}! Hier ist dein Einladungslink für ${eventName}: ${url}` ``) → on success `adminApi.festival.markInviteSent(...)` + `showToast('Link kopiert!', 'success')` + refresh row; clipboard-failure fallback `prompt('Kopiere diesen Link:', url)` (pattern: `useEventActions.js` copyRegistrationLink). UI hint text: „Link nochmal schicken = Zeile kopieren".
  - Copy all (per Kontingent): one `Name: URL` line per invite → clipboard (no sent_at stamping mandated by spec for copy-all — stamp each row anyway to keep the chase list honest, it is idempotent).
  - Send-email button (rows with email): `sendInviteEmail` → toast; Revoke: confirm dialog (Pico `<dialog>` pattern from RegistrationManagePage) → `patchInvite(..., { revoked: true })`.
  - InviteBatchModal — UI language „Kontingent anlegen": textarea paste (`Name` or `Name <email>` per line, parse with a `/^(.*?)\s*<(.+@.+)>$/` fallback-to-name regex), batch settings (batch_label*, tier select werft/volunteer/org/open, max_uses, max_group_size), parsed **preview table** with per-row remove, then `createInvites`. German labels throughout.
- **Acceptance:**
  - Manual walk: paste 3 lines (one with `<email>`) → preview shows 3 rows with parsed emails → create → 3 rows appear grouped under the Kontingent with summary numbers matching Σ max_uses×max_group_size.
  - Copying a row puts greeting+URL on the clipboard AND flips the chip offen→verschickt without a reload of the whole page.
  - Revoked row shows „widerrufen" and its link then returns 404 on the public form; a `max_uses=5` invite with 2 registrations shows „2/5 angemeldet".

### T120 — P1 E2E smoke walk + regression + deploy notes ✅ (partial — service/model-level only, no local stack; browser/HTTP walk still needed after deploy, see PR notes)
- **Phase:** P1 · **Size:** M · **Depends on:** T101–T119
- **Files:** none new (checklist in the PR description; fixes land in the files above)
- **What to do:**
  - Full backend suite green: `cd /Users/arnemohr/git/arnemohr/funke/backend && uv run pytest` — includes all new moto tests (invite race, slot subset, full-name rule, phone-iff-overnight, cancel-releases-use, festival-never-lottery/waitlist, duplicate email) AND the untouched regular-event suite (spec Verification: „regression: the regular event flow (create → register → lottery) is untouched").
  - E2E smoke against a local stack (spec Verification E2E line, P1 scope): create a festival with the default slots Freitag/Samstag/Sonntag (FestivalPage, incl. Mitmach-Hinweis) → publish OPEN → create a Kontingent of 2 invites (one with email) → open an invite link in a private window → register with full name + Zelt + Telefonnummer (Anfrage-copy visible) → **inspect the queued F2 Message row** (messages table: correct slots list, Schlafplatz „Zelt — angefragt" (Ä17), Verwaltungslink, MitmachHinweis paragraph, NO QR paragraph) → open the manage link (shows „Übernachtung: Zelt — angefragt") → verify a festival-attendance PATCH containing `overnight_approved` is rejected with 422 (guests can never set it) → edit slots (F3 queued) → cancel (F4 queued by the service, no „Fisch" copy, invite `use_count` back down) → re-register via the second invite → download the gate CSV and confirm: alphabetical, one row per person, the cancelled registration absent, Schlafplatz with Ä17 status („Zelt — angefragt" for the test registration) + Telefon column, slot columns + empty Angekommen/Bändchen columns → trigger the lottery run endpoint on the festival → 409 → confirm the festival is absent from /admin/events and the regular events UI is unchanged.
  - Deploy-order note in the release PR: **1)** T101 CDK stack update alone (`invite-token-index`, wait for GSI ACTIVE), **2)** backend Lambda, **3)** frontend. The P3 `gate-token-index` gets its own later CDK deploy (one GSI per CFN update — spec Risks #2).
- **Acceptance:**
  - Every smoke step above checked off in the PR description with the observed result.
  - `uv run pytest` exit 0; no modification to any pre-existing test expectation.
  - Deploy-order note present; waves 1+2 can be sent by the organizers (end-of-week runbook milestone, spec Timeline 20.–26.7.).

## P2 — Planning tools (headcount board before wave 3)

Goal of this phase (spec `specs/019-festival-sidetrack/spec.md`, Phasing): the organizers can read the numbers before wave 3 goes out — headcount board, festival registration list with admin cancel, catering CSV, and a chase list that shows per Kontingent how many seats are out, registered, and still to expect. Optional if-time: Ä4 `very_full` soft warnings on the public form.

All P2 tasks assume **P1 complete** — in particular the P1 model work (`EventType.FESTIVAL`, `FestivalSlot`, `attendance_slots`, `accommodation`, denormalized `invite_id`/`invite_label`/`tier` on `Registration` — T102/T106), the P1 festival registration service (`create_festival_registration`, festival cancel branch releasing the invite `use_count` — T108/T109), the P1 admin router `backend/app/api/admin/festival.py` (invites CRUD/batch/send/mark-sent — T112; gate CSV export — T113), and the P1 frontend section (`/admin/festival` routes, `InvitesPage.vue`, `adminApi.festival.*` nesting in `api.js` — T115–T119).

### T201 — Implement `get_headcount(event)` in registration_service with moto tests ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T102, T106 (FestivalSlot, `attendance_slots`, `accommodation`, denormalized `tier` on Registration), T108 (festival registration service)
- **Files:** `backend/app/services/registration_service.py` (edit), `backend/tests/unit/test_festival_headcount.py` (new)
- **What to do:**
  - Add `async def get_headcount(self, event: Event) -> dict` to `RegistrationService`, modeled on `get_registration_stats` (`registration_service.py:738-808`): **one** `await self.list_registrations(str(event.id))` call, then a single in-Python aggregation loop — no per-slot queries.
  - Aggregation rules:
    - Skip `RegistrationStatus.CANCELLED` entirely (Ä5: cancelled registrations are excluded from headcount).
    - A registration contributes `registration.group_size` people to **every** slot key in `registration.attendance_slots` (the grid is shared by the whole group). Registrations with empty/None `attendance_slots` contribute to no slot but are counted in a `registrations_without_slots` diagnostic counter.
    - **Diagnostic bucket „Unbekannte Zeitfenster"**: `attendance_slots` keys NOT present in `event.festival_slots` (orphaned after a slot-config edit) must not silently vanish — collect them into a top-level `unknown_slots: {key: total}` dict (Σ `group_size` per orphaned key).
    - Tier bucket = `registration.tier or "unknown"`.
    - **Accommodation totals are OVERALL (Ä15), not per night slot, split into requested vs. approved (Ä17)**: top-level `accommodation_totals = {"TENT": {"requested": x, "approved": y}, "CAMPER": {...}}` — `requested` = Σ `group_size` of ALL non-cancelled registrations with that `accommodation` value (approval-independent), `approved` = the subset with `overnight_approved=True` (always ≤ requested — the approved numbers are the real pitch demand). NEEDS_SPOT no longer exists; `None` = no overnight, not counted.
    - **Overnight demand per slot (Ä15)**: each slot additionally gets `overnight` = Σ `group_size` of non-cancelled registrations that ticked this slot AND have `accommodation` set — „overnight demand per day ≈ attendees of that day with accommodation set"; `is_night` no longer gates this.
  - Return shape (build the slot list from `event.festival_slots` so empty slots appear with zeros, in the event's slot order):
    ```python
    {
        "slots": [
            {
                "key": "fr-abend", "label": "Fr Abend", "date": "2026-08-14",
                "is_night": False,
                "total": 123,                      # Σ group_size of non-cancelled regs with this slot
                "by_tier": {"werft": 40, "volunteer": 50, "unknown": 3},
                "cap": 150,                        # FestivalSlot.capacity, may be None
                "overbooked": False,               # cap is not None and total > cap
                "overnight": 45,                   # Ä15: Σ group_size of regs on this slot with accommodation set
            },
            ...
        ],
        "peak_total": 456,          # max over slots of total (0 if no slots)
        "overall_cap": event.capacity,
        "overall_overbooked": peak_total > event.capacity,
        "accommodation_totals": {                            # Ä15/Ä17: overall, incl. group sizes
            "TENT": {"requested": 30, "approved": 12},       #   approved = real pitch demand
            "CAMPER": {"requested": 10, "approved": 4},
        },
        "total_registrations": ..., # non-cancelled festival registrations
        "total_people": ...,        # Σ group_size over non-cancelled regs
        "registrations_without_slots": ...,
        "unknown_slots": {},        # orphaned attendance_slots keys → Σ group_size ("Unbekannte Zeitfenster")
    }
    ```
  - Soft-cap semantics (Ä4/Ä8): `overbooked` is a display flag only — `get_headcount` never raises and nothing in this method blocks anything.
  - Tests in `backend/tests/unit/test_festival_headcount.py`, class `TestFestivalHeadcount`, following the dominant service-test pattern (`conftest.py` fixtures `mock_dynamodb`/`sample_event`/`sample_registration`; construct `RegistrationService()` directly and inject `self.service._registrations_table` / `_events_table`; seed via `_event_to_item` / `_registration_to_item` from the service modules). Build the festival event via `sample_event(event_type=EventType.FESTIVAL, festival_slots=[...], capacity=...)` overrides.
- **Acceptance:**
  - [x] One `list_registrations` pass; no query inside the aggregation loop (verify by reading the diff — same shape as `get_registration_stats`).
  - [x] moto test: **group sizes count, not registrations** — a `group_size=3` registration on „fr-abend" plus a `group_size=1` registration on „fr-abend" yields `total == 4` for that slot.
  - [x] moto test: **CANCELLED excluded** — cancel one of the seeded registrations (status `CANCELLED`); its people disappear from all slot totals, tier buckets, and accommodation totals.
  - [x] moto test: a registration spanning two slots contributes its full `group_size` to both slots (peak counting, not person-splitting).
  - [x] moto test: tier bucketing — regs with `tier="werft"` / `tier=None` land in `by_tier["werft"]` / `by_tier["unknown"]`.
  - [x] moto test: `accommodation_totals` sums group sizes overall by `TENT`/`CAMPER` split into `requested`/`approved` (Ä17) — a `group_size=3` TENT registration adds 3 to `TENT.requested`, and to `TENT.approved` only when `overnight_approved=True`; `approved ≤ requested` always; `accommodation=None` registrations appear in no bucket.
  - [x] moto test: per-slot `overnight` counts only registrations on that slot with `accommodation` set, independent of `is_night`.
  - [x] moto test: a registration carrying an orphaned slot key (not in `event.festival_slots`) lands in `unknown_slots` with its group size — it does not silently vanish and does not crash the aggregation.
  - [x] moto test: `overbooked` flag — slot with `capacity=2` and `total=3` → `overbooked is True`; slot with `capacity=None` → `overbooked is False` regardless of total; `overall_overbooked` true when `peak_total > event.capacity`.
  - [x] Slots with zero registrations still appear in `slots` with `total=0` and empty tier dict.
  - [x] `cd backend && uv run pytest tests/unit/test_festival_headcount.py` green.

### T202 — Add GET headcount endpoint to the admin festival router ✅
- **Phase:** P2 · **Size:** S (≤2h) · **Depends on:** T201; T112 (P1 admin festival router)
- **Files:** `backend/app/api/admin/festival.py` (edit)
- **What to do:**
  - Add `GET /api/admin/festival/{event_id}/headcount` (router carries the `/api/admin` prefix per `main.py:123-133` conventions — match whatever prefixing P1 chose for `festival.py`).
  - Guard: read access, `dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))]` + `user: CurrentUser` param, org scoping via `_get_org_id(user)` — copy the guard/helper pattern from `backend/app/api/admin/events.py:82-95`.
  - Load the event via `event_service.get_event(org_id, event_id)`; 404 if missing; 400 (`"Kein Festival-Event"` in detail) if `event.event_type != EventType.FESTIVAL`.
  - Return `await registration_service.get_headcount(event)` verbatim (the T201 dict is the response contract; document it in the route docstring).
- **Acceptance:**
  - [x] `GET /api/admin/festival/{event_id}/headcount` returns the T201 shape for a FESTIVAL event; 404 for unknown event; 400 for a SINGLE event.
  - [x] VIEWER role can read (it is a read-only board); no write guard on this route.
  - [x] No new aggregation logic in the router — it delegates to `get_headcount` (endpoint logic in this suite is tested at service level per the existing convention; T201's tests are the coverage).

### T203 — Add festival registrations list + admin cancel endpoints ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T109 (festival cancel branch — releases invite `use_count`, sends F4), T112 (admin festival router)
- **Files:** `backend/app/api/admin/festival.py` (edit), `backend/app/models/registration.py` (edit, only if P1 did not already extend `RegistrationResponse`)
- **What to do:**
  - `GET /api/admin/festival/{event_id}/registrations` — read guard (OWNER/ADMIN/VIEWER), optional query params `status_filter: str | None` and `search: str | None` passed through to `registration_service.list_registrations(event_id, status_filter, search)` (`registration_service.py:487-544`). Response `{items: [...], total: int}` mirroring `EventListResponse` (`events.py:75-79`).
  - Ensure `RegistrationResponse` (`registration.py:224-240`) carries the festival fields additively: `attendance_slots: list[str] | None`, `accommodation: str | None`, `tier: str | None`, `invite_label: str | None`. If P1 (T106) already added them, this is a no-op — verify, don't duplicate.
  - `POST /api/admin/festival/{event_id}/registrations/{registration_id}/cancel` — write guard (OWNER/ADMIN). Just calls `registration_service.cancel_registration` — the festival cancel branch (T109) sets CANCELLED, releases the invite `use_count`, and sends F4 itself, never-fail (**F4 is sent by the service, T109 — no email logic in this router**). Error mapping by service error string, mirroring `cancellations.py:50-64`: "not found" → 404, "cannot cancel" → 400. Audit: `log_admin_action("festival.registration_cancel", user.email, str(registration_id))` (import from `...services.logging` as in `events.py:35`).
  - **Route-ordering trap** (`events.py:1113`): the P1 literal route `GET .../registrations/export-csv` (T113) must stay declared **before** the parameterized `/registrations/{registration_id}/...` routes added here. Add a comment at the cancel route pointing at this rule.
- **Acceptance:**
  - [x] List endpoint returns all non-deleted registrations for the festival incl. `attendance_slots`, `accommodation`, `tier`, `invite_label` per item; `status_filter=CANCELLED` filters correctly.
  - [x] Admin cancel flips status to CANCELLED, releases the invite use (re-registering via the same invite works again), queues F4 — extend the P1 festival cancel service test (in `test_festival_registration.py`, T109) with an assertion that the cancel path invoked here is the same code path (no second cancel implementation in the router).
  - [x] Cancelling an already-CANCELLED registration returns 400, not 500.
  - [x] `export-csv` still resolves after this change (route order preserved — check `app.routes` order or hit both paths in a quick manual run).

### T204 — Catering CSV view on the festival export endpoint ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T201 (reuses `get_headcount`); T113 (P1 gate CSV export, Ä9 floor)
- **Files:** `backend/app/api/admin/festival.py` (edit)
- **What to do:**
  - Extend the existing P1 endpoint `GET /api/admin/festival/{event_id}/registrations/export-csv?view=gate|catering` with the `catering` branch (P1 shipped `gate` in T113). 422/400 for unknown `view` values.
  - Catering view = headcounts per slot, one row per `FestivalSlot`, driven by `await registration_service.get_headcount(event)` — no second aggregation. German headers (this file goes to the caterers): `Zeitfenster;Datum;Personen;davon Übernachtung` — the Übernachtung column = the slot's `overnight` value (Ä15: attendees of that slot with accommodation set; filled for every slot, no `is_night` gating). Append final rows `Spitze (max. gleichzeitig);;{peak_total};`, then the overall totals with the Ä17 split: `Zelt angefragt;;{accommodation_totals.TENT.requested};`, `Zelt zugesagt;;{accommodation_totals.TENT.approved};`, `Camper angefragt;;{accommodation_totals.CAMPER.requested};`, `Camper zugesagt;;{accommodation_totals.CAMPER.approved};`.
  - Ä14 note (docstring): this export IS the **catering snapshot pulled Mon 10.8.** — registration keeps running until the festival's end; the CSV always reflects the live state, the "cutoff" is purely the moment the organizers download it.
  - Build with the stdlib `csv` module (`csv.writer(..., delimiter=";")` — German Excel, same dialect as the gate CSV T113) into `io.StringIO`, encode `utf-8-sig` so Excel opens umlauts correctly (**no manual BOM prepending** — the codec provides it), then return via the StreamingResponse pattern of `events.py:1094-1098` with `media_type="text/csv; charset=utf-8"` and `Content-Disposition: attachment; filename="catering-{slug}.csv"` — reuse the umlaut sanitization via `str.maketrans` from `events.py:1084-1093` for the filename slug.
  - Audit: `log_admin_action("festival.export_catering", user.email, str(event_id))` (mirrors `events.py:1081`).
  - CANCELLED exclusion comes for free from `get_headcount` (T201) — note this in the docstring instead of re-filtering.
- **Acceptance:**
  - [x] `?view=catering` returns a CSV with one row per slot in event slot order, people counts matching the headcount endpoint exactly (same source of truth).
  - [x] Every slot row carries its `overnight` count (no `is_night` gating); the final rows show Spitze plus the Zelt/Camper angefragt/zugesagt totals matching `accommodation_totals` (Ä17).
  - [x] Cancelled registrations do not appear in any count (covered transitively by T201 tests; add one service-level assertion comparing CSV row math inline against `get_headcount` output in `backend/tests/unit/test_festival_headcount.py`, following the `test_admin_features.py` convention of testing export logic inline rather than via TestClient).
  - [x] Filename sanitized (event named „Sömmerfest" → no raw umlauts in the filename); response streams with the correct Content-Disposition header.
  - [x] `?view=bogus` → 4xx, and the P1 `?view=gate` output is byte-identical to before this change (regression check).

### T205 — Add festival slot fields to `RegistrationAdminPatch` ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T102, T106 (P1 models: `attendance_slots`, `AccommodationType`, `FestivalSlot` helpers)
- **Files:** `backend/app/models/registration.py` (edit), `backend/app/services/registration_service.py` (edit), existing spec-018 admin-update tests `backend/tests/unit/test_registration_admin_update.py` (edit)
- **What to do:**
  - Extend `RegistrationAdminPatch` (`registration.py:75-116`, `extra="forbid"` — keep it) with optional fields: `attendance_slots: list[str] | None = None`, `accommodation: AccommodationType | None = None`, `phone: str | None = None`, `overnight_approved: bool | None = None` (Ä17 — **this admin patch is the ONLY write path for the flag**; every public schema rejects/lacks it, T106). Model-level validation only for shape (non-empty strings, dedupe preserving order); slot-key membership needs the event and belongs in the service. In the service, reject `overnight_approved=True` when the resulting state has no accommodation wish (approving „no request" is meaningless), and mirror the T109 reset: clearing accommodation via this patch also resets the flag.
  - In the spec-018 admin-update path in `registration_service.py` (the method behind `adminApi.updateAdminRegistration` / the 409-flow), add festival validation before applying the patch: load the event; if `attendance_slots` is being set, require `event.event_type == FESTIVAL`, `set(attendance_slots) ⊆ set(event.slot_keys())`, and ≥ 1 slot; enforce the **phone-iff-accommodation rule (Ä15)** against the **resulting** state (patched-or-existing accommodation + patched-or-existing phone): accommodation set ⇒ phone must be present; accommodation None ⇒ phone cleared. `is_night` gates nothing. Reject slot fields on SINGLE events with a clear error ("attendance_slots only valid for FESTIVAL events"). Apply via `model_copy(update={...})` — never field assignment.
  - If the admin patch touches `group_members` on a festival registration, the **same append-only/tombstone rule as T109 applies**: removals become `None` entries, additions append, indices never shift (QR `person_index` stability).
  - Admin patch deliberately works **after** the registration deadline (the deadline gates self-service only — spec „other changes go through the … organizers").
  - No email on admin patch (F3 is the self-service change confirmation; admin edits are silent, matching spec-018 behavior).
- **Acceptance:**
  - [x] Patch with a slot key not in `event.festival_slots` → ValueError/400; valid subset → persisted and returned.
  - [x] Patch that sets accommodation without a (patched or existing) phone → rejected; adding the phone in the same patch → accepted; clearing accommodation clears the phone AND resets `overnight_approved`.
  - [x] Ä17: admin patch with `overnight_approved=True` on a registration with an accommodation wish → persisted (the only write path works); `overnight_approved=True` without any wish → rejected.
  - [x] Slot fields on a SINGLE event → rejected; existing spec-018 patch behavior for SINGLE events unchanged (run the whole `test_registration_admin_update.py` module).
  - [x] Unknown fields still rejected (`extra="forbid"` intact).
  - [x] New moto tests appended to `backend/tests/unit/test_registration_admin_update.py` in a `TestFestivalAdminPatch` class covering the four bullets above, using the standard service-injection pattern.

### T206 — Extend `adminApi.festival` with P2 methods in api.js ✅
- **Phase:** P2 · **Size:** S (≤2h) · **Depends on:** T202, T203, T204; T115 (P1 `adminApi.festival` nesting)
- **Files:** `frontend/src/services/api.js` (edit)
- **What to do:**
  - Add to the existing nested `adminApi.festival` object (nested-domain pattern like `adminApi.bar.*` / `adminApi.ship.*`):
    - `headcount(eventId)` → `GET /api/admin/festival/${eventId}/headcount`
    - `listRegistrations(eventId, { status, search } = {})` → `GET .../registrations` with query params
    - `cancelRegistration(eventId, registrationId)` → `POST .../registrations/${registrationId}/cancel`
    - `updateRegistration(eventId, registrationId, patch)` → PATCH via the existing spec-018 admin-update route (reuse/alias `updateAdminRegistration` if the route is shared — do not duplicate the 409 handling; the 409 precedent sets `err.status === 409` and `err.data`)
    - `exportCateringCsv(eventId)` → copy the blob-download pattern from `adminApi.exportBoardingPdf` (api.js:386-408): raw `fetch` with bearer token, `response.blob()`, object URL + temp `<a download>` click, filename from `Content-Disposition`. Parametrize by `?view=catering`; if P1 shipped a gate-CSV download helper (T115 `exportGateCsv`), refactor both onto one shared `downloadCsv(eventId, view)` helper instead of a third copy.
- **Acceptance:**
  - [x] All five methods exist under `adminApi.festival`, auth'd (bearer token path), snake_case query/body keys.
  - [x] CSV download saves a file with the server-provided filename; no JSON parsing attempted on the CSV response.
  - [x] No duplicated blob-download logic if a P1 gate-CSV helper exists (single shared helper).
  - [x] `npx eslint src/services/api.js` clean (no frontend test framework exists; lint is the check).

### T207 — Build HeadcountPage.vue (slot×tier matrix, accommodation totals, overbooked markers) ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T202, T206; T118 (P1 festival routes/nav)
- **Files:** `frontend/src/pages/admin/festival/HeadcountPage.vue` (new), `frontend/src/router/index.js` (edit)
- **What to do:**
  - Route: `/admin/festival/:eventId/headcount`, lazy import, `beforeEnter: authGuard`, `props: true`, `meta: { hideTabBar: true }` (subpage convention). Link to it from the P1 festival event view.
  - Script setup order per repo convention (imports → route/composables → state refs → computeds → functions → `onMounted` last). State: `loading/error/headcount`. Load via `adminApi.festival.headcount(props.eventId)`; errors via `showToast(err.message || 'Laden fehlgeschlagen', 'error')` (admin pages use toasts, `useToast.js`).
  - **Matrix**: table with `class="mobile-card-table"` + `data-label` attrs (EventsPage pattern). Rows = slots (in server order), columns = union of tier keys across all slots (stable order: werft, volunteer, org, open, then others alphabetically, `unknown` last, German column header „ohne Tier" for unknown) + „Gesamt" + „Cap". Wrap the table in an `overflow-x: auto` container.
  - **Overbooked markers**: on `slot.overbooked`, render the total cell with the existing danger tokens (`var(--color-danger-bg)`/`var(--color-danger-text)`) and a „überbucht" badge; when `overall_overbooked`, show a page-top banner „Spitze {peak_total} über Gesamt-Cap {overall_cap} — weiche Grenze, nichts ist blockiert." Soft-cap framing is deliberate (Ä4/Ä8): informational styling, no blocking language.
  - **Übernachtung section (Ä15/Ä17)**: below the matrix, one card with the OVERALL `accommodation_totals` showing BOTH numbers per type — „Zelt: {approved} zugesagt / {requested} angefragt · Camper: {approved} zugesagt / {requested} angefragt — inkl. Begleitungen" (the zugesagt numbers are the real pitch demand; approvals happen on FestivalRegistrationsPage, T208) — plus a per-slot „Übernachtung" column in the matrix showing each slot's `overnight` value (overnight demand per day — phone numbers for the Stellplatz-Planung live on the registrations list/gate CSV).
  - Summary header: `total_people` Personen / `total_registrations` Anmeldungen / Spitze `peak_total`; show `registrations_without_slots` as a warning chip when > 0 („{n} Anmeldungen ohne Zeitfenster"); render `unknown_slots` as a warning card „Unbekannte Zeitfenster" listing each orphaned key with its count (they must not silently vanish from the board).
  - Manual refresh button (`aria-busy` while loading) — no polling.
- **Acceptance:**
  - [x] Matrix renders every slot (including zero-count slots) with per-tier counts and totals matching the endpoint payload 1:1. (verified by code-tracing the template bindings against `get_headcount`'s response shape — no dev-server/browser check run)
  - [x] Overbooked slot cells and the overall banner appear exactly when the API flags say so; a capless slot never shows a marker. (same — bindings are direct `v-if`s on `slot.overbooked` / `overall_overbooked`, which the backend already guarantees false for capless slots)
  - [x] Übernachtung card shows both numbers per type („{approved} zugesagt / {requested} angefragt") matching `accommodation_totals` 1:1; the per-slot Übernachtung column matches the endpoint's `overnight` values; a non-empty `unknown_slots` dict renders the „Unbekannte Zeitfenster" warning card. (same — direct bindings, no separate aggregation)
  - [ ] German UI text throughout, informal „du"; page usable at 375 px width (cards via `mobile-card-table`, no horizontal body scroll). **Not browser-verified** — `npm run build` passed and the page reuses the already-proven `mobile-card-table` CSS, but actual 375px rendering was not visually checked.
  - [ ] Route protected by authGuard; direct deep-link while logged out redirects to login. **Not browser-verified** — route uses the identical `beforeEnter: authGuard` pattern as every other protected admin route, but no live logged-out deep-link was actually attempted.

### T208 — Build FestivalRegistrationsPage.vue (slot columns, admin cancel) ✅
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T203, T205, T206
- **Files:** `frontend/src/pages/admin/festival/FestivalRegistrationsPage.vue` (new), `frontend/src/router/index.js` (edit)
- **What to do:**
  - Route: `/admin/festival/:eventId/registrations`, authGuard, `props: true`, `meta: { hideTabBar: true }`.
  - Load registrations via `adminApi.festival.listRegistrations(eventId)` and the event (for `festival_slots` → column headers). Client-side status filter tabs (`.filter-tabs` pattern, EventsPage.vue:41-62) — Alle / Angemeldet / **Übernachtungs-Anfragen** (Ä17: rows with `accommodation` set, sortable by approval status) / Storniert — plus a text search input filtering name/email client-side.
  - **Table**: `mobile-card-table`, wrapped in `overflow-x: auto`. Columns: Name (+ group members as a stacked sub-line), E-Mail, Personen (`group_size`), Tier, Kontingent (`invite_label`), then **one narrow column per festival slot** (header = slot label; cell = ✓ when the slot key is in `attendance_slots`), Schlafplatz (Ä15: TENT→„Zelt", CAMPER→„Camper", null→„Nein"), Telefon (shown when set — the Stellplatz-Planung contact, Ä15), Status badge (`status-badge status-{status}` convention). Skip `None` tombstones when stacking group members under the name.
  - **Admin cancel**: per-row „Stornieren" action (hidden on CANCELLED rows) opening a Pico `<dialog :open="showCancelDialog || undefined">` confirm — copy the dialog structure from `RegistrationManagePage.vue` (header `rel="prev"` close, `.warning-box`, red confirm via `--pico-primary: #dc2626` override). Warning copy: „{name} und {n} Begleitungen werden storniert. Der Einladungs-Platz wird wieder frei. Die Person bekommt eine Absage-Mail." (no internal template label like „F4" in user-facing copy) On confirm: `adminApi.festival.cancelRegistration(...)`, then reload the list; success/error via `showToast`.
  - **Overnight approval toggle (Ä17)**: in the „Übernachtungs-Anfragen" view the Telefon column is always visible (that's what the number was collected for) and each row gets a one-click toggle **„darf übernachten"** writing `overnight_approved` via the spec-018 admin patch (`adminApi.festival.updateRegistration`, T205/T206 — no new endpoint); row shows „angefragt"/„zugesagt" state; `showToast` on success/error. This toggle is the organizers' pitch-assignment workflow after phone coordination.
  - CANCELLED rows stay visible under the „Storniert" tab (muted styling) — they are the audit trail, not deleted.
  - Do **not** build inline slot editing in this task — the `RegistrationAdminPatch` slot fields (T205) are exercised via the existing spec-018 admin edit surface; add at most a per-row link to it if one exists for this registration.
- **Acceptance:**
  - [x] Every registration row shows per-slot ✓ marks matching its `attendance_slots`; slot column order matches the event's slot order. (verified by code-tracing: `slotColumns` is `event.festival_slots` in server order, unmodified; the ✓ cell binds `(reg.attendance_slots || []).includes(slot.key)` directly — no dev-server/browser check run)
  - [ ] Cancel flow: confirm dialog → row flips to CANCELLED after reload → headcount board (T207) no longer counts those people (verify manually against the endpoint). **Not browser-verified** — requires a live app + backend walk-through the task explicitly calls out as manual.
  - [x] Cancelling shows a toast on success and on failure; the dialog never silently swallows an error. (verified by code-tracing: `confirmCancel`'s try/catch calls `showToast` on both paths, plus an inline `cancelError` box in the dialog on failure)
  - [x] Filter tabs and search work client-side without re-fetching; counts per tab shown (filterCounts computed pattern, EventsPage.vue:147-167). (verified by code-tracing: `filteredRegistrations`/`filterCounts` are pure computeds over the already-loaded `registrations` array; no API call in the tab-switch or search handlers)
  - [ ] „Übernachtungs-Anfragen" lists exactly the rows with an accommodation wish, with phone visible; the „darf übernachten" toggle flips a row to „zugesagt" (persisted via the admin patch, visible after reload) and back; the headcount board's `approved` numbers move accordingly (cross-check T207). **Not browser-verified** — the filter (`!!r.accommodation`), the always-rendered Telefon column, and `toggleOvernightApproval`'s call to `adminApi.festival.updateRegistration(..., { overnight_approved })` followed by a silent reload are code-traced correct, but no live toggle + T207 cross-check was run.
  - [x] German UI text; mobile card layout via `data-label` attrs. (verified by code-tracing: all copy is German; every `<td>` carries a `data-label`, including the per-slot and conditional Übernachtung columns)

### T209 — Invite chase-list polish: Kontingent grouping + summary rows ✅ (partial — code complete; item 1 and item 5 need a manual browser click-through against a live mixed fixture, see notes)
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T119 (P1 InvitesPage), T112 (invites list endpoint); no backend change expected
- **Files:** `frontend/src/pages/admin/festival/InvitesPage.vue` (edit)
- **What to do:**
  - Group the invite rows by `batch_label` (invites with `batch_label=null` under „Ohne Kontingent", last). Each group gets a header row with the Kontingent name and a **summary row** computed client-side from the invite list:
    - **ausgegeben** (issued seats) = Σ `max_uses × max_group_size` over the group's non-revoked invites
    - **angemeldet** = Σ `use_count` over the group (Anmeldungen — matches the `2/5 angemeldet` chip semantics, 1 use = 1 registration)
    - **maximal noch zu erwarten** = Σ `(max_uses − use_count) × max_group_size` over non-revoked, non-expired invites (expired = past `expires_at` or past the event's `registration_deadline` — same rule as the P1 „abgelaufen" chip; reuse that helper, don't re-derive)
  - Page-top total bar: the same three numbers summed across all Kontingente, rendered against the overall cap: „ausgegeben {x} · angemeldet {y} · maximal noch zu erwarten {z} — Cap {capacity}". When `y + z > capacity`, style the „noch zu erwarten" figure with the warning tokens (`--color-warning-*`) — informational, never blocking (soft-cap principle; the spec's control lever is issuing fewer links, not blocking).
  - Keep all existing P1 behaviors intact: status chips (offen/verschickt/angemeldet/abgelaufen/widerrufen), `use_count/max_uses` chip, copy-row-stamps-`sent_at` (Ä7), copy-all, revoke, send-email.
  - Note in a code comment: „angemeldet" counts registrations, not people — people totals live on the headcount board (deliberate separation; no hard Kontingent entity per the challenge round).
- **Acceptance:**
  - [ ] Invites render grouped by Kontingent with per-group summary rows whose three numbers match hand-computed values for a mixed fixture (personal 1×2 links, one 10×1 delegation link, one revoked, one expired). (browser-walk — not run; needs a live mixed fixture)
  - [x] Revoked invites are excluded from „ausgegeben" and „noch zu erwarten" but their `use_count` still counts as „angemeldet" (already-registered people don't vanish on revoke). (verified by code review: `issuedSeats`/`maxExpected` both `filter((i) => !i.revoked_at ...)`; `registered` sums `use_count` over the unfiltered group)
  - [x] Expired invites excluded from „noch zu erwarten" only. (verified: `maxExpected` filters `!i.expired`; `issuedSeats`/`registered` do not filter on `expired`)
  - [x] Total bar shows the cap comparison; warning styling kicks in exactly when `angemeldet + noch zu erwarten > capacity`. (verified: `totalsOverCap = cap != null && totals.registered + totals.maxExpected > cap`, bound to `.totals-warning` on the „noch zu erwarten" figure only)
  - [ ] No P1 regression: copy row still stamps `sent_at`, chips unchanged (manual click-through). (browser-walk — not run; `copyRow`/`statusChip` were not touched by this task's edits)

### T210 — (If-time, Ä4) `very_full` soft warnings on the public festival form ✅ (partial — code + backend tests complete; item 3 needs a manual browser submit-through, see notes)
- **Phase:** P2 · **Size:** M (½ day) · **Depends on:** T201 (per-slot counts); T111 (P1 public invite form-boot endpoint), T116 (FestivalRegistrationPage). **Explicitly optional — cut first if the week runs short; nothing in P2/P3 depends on it.**
- **Files:** `backend/app/api/public/invites.py` (edit), `backend/app/services/registration_service.py` (edit, small helper), `frontend/src/pages/registration/FestivalRegistrationPage.vue` (edit), `backend/tests/unit/test_festival_headcount.py` (edit)
- **What to do:**
  - Backend: in the form-boot endpoint `GET /api/public/invites/{invite_token}`, add a per-slot boolean `very_full` to each slot object. Compute from `get_headcount(event)` totals: `very_full = total >= 0.9 * effective_cap` where `effective_cap = slot.capacity or event.capacity`; **never true when neither cap exists**. Expose ONLY the boolean — no counts, caps, or percentages on the public payload (exact numbers are admin-only per the spec's invite-boot rule).
  - Threshold constant `VERY_FULL_THRESHOLD = 0.9` next to the computation, with a comment pointing at Ä4.
  - Frontend: in the slot grid of FestivalRegistrationPage, render a small inline note under a checked-or-hovered `very_full` slot: „Dieses Zeitfenster ist schon ziemlich voll — du kannst dich trotzdem anmelden." Reassuring copy is load-bearing (Ä4: deterring copy corrupts goal 2 — people must keep declaring slots honestly). Info styling (`--color-info-*` tokens), never disabled checkboxes, never a blocking validation.
  - Tests: extend `TestFestivalHeadcount` with the threshold math — cap 10 & total 9 → very_full; cap 10 & total 8 → not; slot without cap falls back to overall cap; no caps at all → always false.
- **Acceptance:**
  - [x] Public form-boot payload gains only a boolean per slot; no count/cap leaks (assert payload keys in the test). (verified by code review: `InviteSlotInfo` declares exactly `key/label/date/is_night/very_full` — no count/cap/percentage field exists to leak; `compute_very_full_slots` returns only `dict[str, bool]`. No new endpoint-level test file was added — T210's file list scopes tests to `test_festival_headcount.py`, which covers the threshold math, not a full HTTP round-trip.)
  - [x] Threshold ≥ 90 % of slot cap with overall-cap fallback, never true without any cap — covered by the four moto cases above. (`TestVeryFullSlots`, 4/4 green)
  - [ ] Form still submits normally for a very_full slot (soft warning, zero blocking behavior). (browser-walk — not run; verified by code review that no `disabled`/validation was added to the checkbox or submit path, only an inline `<small>` note)
  - [x] German copy exactly in the reassuring register („…du kannst dich trotzdem anmelden"); info styling, not warning/danger. (verified: exact string in `FestivalRegistrationPage.vue`, `.very-full-hint` uses `--color-info-text`, not warning/danger tokens)

### T211 — Template-12 send surface in the festival section (MessageComposer reuse) ✅
- **Phase:** P2 · **Size:** S (≤2h) · **Depends on:** T208 (FestivalRegistrationsPage), T115 (api.js)
- **Files:** `frontend/src/pages/admin/festival/FestivalRegistrationsPage.vue` (edit)
- **What to do:**
  - The manual pre-festival bulk mail (template 12 with `{Verwaltungslink}` — spec „Challenged & decided": no new automatic template) needs a send surface inside the festival section, because festival events are hidden from the regular events UI (T112) and EventDetailPage is therefore unreachable for them.
  - Reuse the existing pieces — both verified present in the repo: `frontend/src/components/MessageComposer.vue` (used by `EventDetailPage.vue:401`) and the custom-message endpoint `POST /api/admin/events/{event_id}/messages` (`backend/app/api/admin/events.py:1150`, called via `adminApi.sendCustomMessage(eventId, data)`). Add a „Nachricht senden" button on FestivalRegistrationsPage that opens `<MessageComposer>` scoped to the festival event — no new backend, no new component.
  - Verify the endpoint accepts a FESTIVAL event (it loads via `get_event(org_id, event_id)` without an event-type filter — confirm no FESTIVAL guard was added by T110/T112 and note the result in the PR).
- **Acceptance:**
  - [x] An organizer can send template 12 (or a custom message) to festival registrations entirely from the festival section; `{Verwaltungslink}` resolves to working manage links. (verified by code-tracing, not a live send: `FestivalRegistrationsPage.vue`'s "Nachricht senden" button opens `<MessageComposer :event-id :registrations>` unmodified; `POST /api/admin/events/{event_id}/messages` (`events.py:1150`) loads the event via `event_service.get_event(org_id, event_id)` — the same single-item getter used everywhere, which applies no `event_type` filter, only `list_events` filters out FESTIVAL (`events.py:175`) — so the endpoint accepts a FESTIVAL event id unchanged; `email_service.send_custom_message` builds the manage link from `registration.id`/`registration.registration_token` generically, independent of event type. **No guard fix was needed.**)
  - [x] SINGLE-event MessageComposer usage on EventDetailPage unchanged. (verified: `git diff`/`git status` show zero changes to `frontend/src/components/MessageComposer.vue` or `frontend/src/pages/admin/EventDetailPage.vue` — T211 only edited `FestivalRegistrationsPage.vue`)

### T212 — P2 exit verification: board trusted before wave 3 ✅ (partial — verified at moto/service/code level; no safe local stack exists, so the live-app browser walk itself is still open, see notes per item)
- **Phase:** P2 · **Size:** S (≤2h) · **Depends on:** T201–T211
- **Files:** none new (checklist in the PR description); `backend/tests/unit/test_admin_features.py` (edit — added one test closing an uncovered assertion found while executing this walk, see item 5)
- **What to do:**
  - Execute and check off the P2 exit criterion (runbook, week 27.7.–2.8.): the headcount board and chase-list summaries are live and trusted **before wave 3 goes out**.
- **Acceptance:**
  - [ ] An organizer can open HeadcountPage and see slot×tier numbers with the overall Zelt/Camper totals and per-slot Übernachtung demand (Ä15). **Data-level verified, UI itself not browser-walked**: `test_festival_headcount.py::TestFestivalHeadcount` (T201) proves `get_headcount`'s `slots[].by_tier`, `accommodation_totals.{TENT,CAMPER}.{requested,approved}` and `slots[].overnight` are computed correctly (group-size counting, CANCELLED exclusion, tier bucketing, per-slot overnight demand independent of `is_night`); `HeadcountPage.vue` was code-traced and renders exactly those fields (tier columns from `slot.by_tier`, an "Übernachtung" column from `slot.overnight`, a Zelt/Camper card from `accommodation_totals.*.approved`). No live page load was performed.
  - [ ] The numbers cross-check against the Kontingent summary rows on InvitesPage (T209 formula) by hand for at least one Kontingent. **Formula cross-check done concretely, live-fixture walk not done**: T119's and T209's task text describe the identical formula because they describe the same code — `InvitesPage.vue` has one `groups` computed property, not two competing implementations, so "T209 formula" and "T119 formula" cannot drift from each other by construction. Hand-computed a 4-invite mixed fixture (personal 1×2 link partially used, a 10×1 delegation link fully used, one revoked invite with a prior use, one expired unused invite) against the exact reduce logic in the file: `issuedSeats=16` (revoked excluded), `registered=3` (all `use_count` counted, including the revoked one's), `maxExpected=1` (revoked AND expired excluded) — matches the spec formula description and the already-verified T209 acceptance items (revoked excluded from issued/maxExpected but counted in registered; expired excluded from maxExpected only) exactly. Not run against a live mixed fixture in the actual app.
  - [ ] Cancelling a test registration from FestivalRegistrationsPage drops its people from the board and the catering CSV on the next load. **Verified transitively at service level, UI click-through not done**: `test_festival_registration.py::test_admin_cancel_path_reuses_same_service_method_and_effects` (T203) proves the admin cancel path is the same `cancel_registration` call and sets `status=CANCELLED`; `get_headcount` and `build_catering_rows` (via `get_headcount`) both gate purely on `reg.status == RegistrationStatus.CANCELLED` (`test_cancelled_excluded_from_everything`, `TestCateringCsvRows`) — so any registration cancelled through any path is provably excluded from both. The actual button-click + page-reload was not performed.
  - [ ] Ä17 loop: a test registration with a Zelt request appears under „Übernachtungs-Anfragen"; toggling „darf übernachten" (T208) flips its manage page to „Übernachtung: Zelt — zugesagt" and moves the board's `approved` number; a public patch attempting to set `overnight_approved` is rejected. **Rejection sub-item fully verified by test; the rest code-traced only**: `test_festival_models.py::test_overnight_approved_rejected_extra_forbid` proves `FestivalAttendancePatch(overnight_approved=True)` raises (model has `extra="forbid"` and no such field) — this is the actual guard the public PATCH endpoint runs through, so "rejected" is proven, not just inspected. The "appears under Übernachtungs-Anfragen" filter and the manage-page copy were code-traced (`FestivalRegistrationsPage.vue`'s `!!r.accommodation` filter; `RegistrationManagePage.vue:461` builds exactly `` `Übernachtung: ${typeLabel} — ${overnightApproved.value ? 'zugesagt' : 'angefragt'}` ``) and the board-number movement is proven by `test_accommodation_totals_requested_vs_approved`, but no live toggle click-through was run (same gap T208/T209 already flagged).
  - [ ] A test bulk mail via the T211 surface reaches a festival registration with a working `{Verwaltungslink}`. **Closed an uncovered assertion**: no existing test exercised `send_custom_message(..., include_links=True)` at all (for any event type), so added `test_send_custom_message_include_links_on_festival_event` (`test_admin_features.py`) — a FESTIVAL-typed event + registration, `include_links=True`, asserts the stored message's `body` and `body_html` contain the exact `_build_management_url` output built from that registration's own id/token. Proves the link-building mechanism is event-type-agnostic and produces a working manage URL for a festival registration specifically. Still not a live send through the actual UI button / real inbox.
  - [ ] Result recorded in the PR description; wave 3 is unblocked (runbook milestone) — **not recorded; no PR exists yet for this branch.** Do not treat P2 as unblocked for wave 3 until the browser-walk items above are actually run against a deployed stack — this task closes the moto/service/code-level gap only, per the explicit no-safe-local-stack constraint.

## P3 — Check-in (field test Mon 10.8. — otherwise paper)

Scope: gate-token GSI (2nd separate CDK deploy, early), `ticket_secret` + stateless HMAC ticket signing (`FUNKE1.<b64url(json)>.<b64url(hmac[:16])>`, no `person_tokens`, no backfill — QRs work immediately for all existing registrations), check-in log (`SCAN#` rows, **Europe/Berlin local time in the sk — deliberate, documented exception** to the UTC convention), public checkin endpoints (boot/scan/override/undo/search, one-tap semantics per Ä6/Ä13), manage-page QR cards, ScannerPage with degraded offline mode (Risk 5), F2 QR-paragraph activation. Check-in rows never flip registration status; `RegistrationStatus.CHECKED_IN` stays unused for festivals (spec.md:256, :295).

### T301 — Add gate-token-index GSI to the events table (2nd CDK deploy, do this first) ✅ (deployed 19.7., diff = exactly one GSI; conftest extended)
- **Phase:** P3 · **Size:** S · **Depends on:** — (T101's `invite-token-index` must already be deployed — one GSI change per CFN update, spec Risk 2)
- **Files:** `infra/cdk/stacks/database_stack.py` (edit)
- **What to do:**
  - Mirror the `link-token-index` snippet at database_stack.py:72-79 exactly: `self.events_table.add_global_secondary_index(index_name="gate-token-index", partition_key=dynamodb.Attribute(name="gate_token", type=dynamodb.AttributeType.STRING), projection_type=dynamodb.ProjectionType.ALL)` — single STRING partition key, no sort key.
  - Deploy immediately (`cdk deploy` on the database stack) — DynamoDB allows only one GSI mutation per CloudFormation update, and every P3 backend task queries this index. Do not batch with any other GSI change.
- **Acceptance:**
  - [ ] `cdk diff` shows exactly one change: the new `gate-token-index` on `funke-{env}-events`.
  - [ ] Deployed to dev (and prod before 10.8.); index status ACTIVE (`aws dynamodb describe-table`).
  - [ ] No test file needed here — the moto-side index is added in T302's conftest edit.

### T302 — Event model: `gate_token` + `ticket_secret` fields, serialization, GSI lookup, lazy generation ✅
- **Phase:** P3 · **Size:** M · **Depends on:** T301
- **Files:** `backend/app/models/event.py` (edit), `backend/app/services/event_service.py` (edit), `backend/tests/unit/conftest.py` (edit), `backend/tests/unit/test_festival_checkin.py` (new)
- **What to do:**
  - `Event` (event.py:91-105 block): add `gate_token: str | None = None` and `ticket_secret: str | None = None`. Do NOT add either to `EventPublic` (event.py:140-152) or to the admin `EventResponse` (`api/admin/events.py:49-72`) — `ticket_secret` is server-side only, exposed solely via the gate-token-authenticated boot call (spec.md:266).
  - `_event_to_item` (event_service.py:53-71 optional-block pattern): add `if event.gate_token: item["gate_token"] = event.gate_token` and same for `ticket_secret`. `_item_to_event` (event_service.py:76-97): `item.get("gate_token")`, `item.get("ticket_secret")`.
  - `get_event_by_gate_token(gate_token: str) -> Event | None`: copy `get_event_by_link_token` (event_service.py:200-227) verbatim with `IndexName="gate-token-index"`, `KeyConditionExpression="gate_token = :token"`, try/except `ClientError` → None.
  - `ensure_gate_credentials(org_id: UUID, event_id: UUID) -> Event`: load event; if `gate_token is None` set via `_generate_link_token()` (event_service.py:27-29); if `ticket_secret is None` set via `secrets.token_urlsafe(32)` (registration-token strength, registration_service.py:36-38); persist with `model_copy(update={...})` + put_item; return the (possibly unchanged) event. Never rotate `ticket_secret` here — rotating it would invalidate every issued QR.
  - conftest.py `mock_dynamodb`: add `gate-token-index` (pk `gate_token`, ALL projection) to the `funke-dev-events` table GSI list, next to the existing `link-token-index`.
- **Acceptance:**
  - [x] `test_festival_checkin.py::TestGateCredentials` (service test pattern: `EventService()` with `_table` overridden to moto table, seed via `_event_to_item`): round-trip persists/parses both fields; `get_event_by_gate_token` finds the event and returns None for an unknown token; `ensure_gate_credentials` generates both on first call and is idempotent on the second (same values back).
  - [x] Grep confirms `ticket_secret` appears in no response model except the checkin boot endpoint (T307).
  - [x] Existing suite green (`cd backend && uv run pytest`).

### T303 — Admin gate-token endpoints: lazy GET + rotate, gate link on FestivalPage ✅
- **Phase:** P3 · **Size:** S · **Depends on:** T302
- **Files:** `backend/app/api/admin/festival.py` (edit — exists from P1, T112), `frontend/src/pages/admin/festival/FestivalPage.vue` (edit), `frontend/src/services/api.js` (edit), `backend/tests/unit/test_festival_checkin.py` (edit — `TestGateCredentials` rotate assertions, file created in T302)
- **What to do:**
  - `GET /api/admin/festival/{event_id}/gate-token` — `dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))]` (guard pattern from `api/admin/events.py`); calls `ensure_gate_credentials` (lazy-generate pattern, spec.md:322); returns `{"gate_url": f"{settings.base_url}/checkin/{event.gate_token}"}` (base_url from `get_settings()`, config.py:24). Never include `ticket_secret`.
  - `POST /api/admin/festival/{event_id}/gate-token/rotate` — same guard; unconditionally sets a fresh `_generate_link_token()` gate_token (old gate link dead immediately), leaves `ticket_secret` untouched (issued QRs stay valid); returns the new `gate_url`. Audit: `log_admin_action("festival.gate_token.rotate", user.email, str(event_id))` (precedent events.py:1081).
  - FestivalPage: settings section „Einlass" — show the gate URL with copy button (clipboard pattern from `useEventActions.js`: `navigator.clipboard.writeText(url).then(() => showToast('Scanner-Link kopiert!', 'success'), () => prompt('Kopiere diesen Link:', url))`), plus „Link erneuern" button with confirm dialog warning „Der alte Scanner-Link funktioniert danach nicht mehr." `api.js`: add `adminApi.festival.getGateToken(eventId)` / `rotateGateToken(eventId)` (nested-object convention).
- **Acceptance:**
  - [x] GET on an event without a gate_token generates one and returns a URL of shape `/checkin/<token>`; second GET returns the same URL.
  - [x] Rotate returns a different token; `get_event_by_gate_token(old)` → None, `(new)` → event; `ticket_secret` unchanged (assert in `test_festival_checkin.py::TestGateCredentials`, service-level via the handler's service calls).
  - [x] VIEWER role gets 403 on both routes (guard declared, verified by inspection — no TestClient suite exists).

### T304 — Stateless HMAC ticket signing/verification util ✅
- **Phase:** P3 · **Size:** S · **Depends on:** T302
- **Files:** `backend/app/services/ticket_signing.py` (new), `backend/tests/unit/test_ticket_signing.py` (new)
- **What to do:**
  - Format (spec §Registration): `FUNKE1.<payload_b64>.<mac_b64>` where `payload_b64 = b64url_nopad(json.dumps({"r": str(registration_id), "p": person_index, "n": name, "s": attendance_slots or [], "o": overnight_approved}, separators=(",", ":"), ensure_ascii=False))` and `mac_b64 = b64url_nopad(hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()[:16])`. The `o` flag (Ä17) serves the OFFLINE card only — the online scan renders the current `overnight_approved` from the registration (T306). **MAC is computed over the b64url payload segment bytes** — this exact rule must be replicated in the scanner's JS verifier (T311), so document it in the module docstring. `person_index` 0 = contact, `1..` = `group_members[p-1]`.
  - `sign_ticket(secret: str, registration_id: UUID | str, person_index: int, name: str, attendance_slots: list[str] | None, overnight_approved: bool = False) -> str`.
  - `verify_ticket(secret: str, code: str) -> dict | None` — split on `.`, require prefix `FUNKE1` and 3 segments, recompute MAC, compare with `hmac.compare_digest`, then json-decode; return the payload dict or `None` on any failure (malformed, bad b64, bad signature). Pure functions, no service class.
- **Acceptance (per spec Verification P3, spec.md:368):**
  - [x] `test_ticket_signing.py`: sign→verify round-trip returns the exact payload (incl. umlaut name „Jörg Müller", empty-slots case, and both `o: true`/`o: false` — Ä17).
  - [x] Tampered payload (single character flipped in segment 2) → None.
  - [x] Wrong secret → None.
  - [x] Foreign event: ticket signed with event A's secret does not verify under event B's secret → None.
  - [x] Garbage inputs (`""`, `"FUNKE1"`, `"FUNKE2.x.y"`, non-b64) → None, no exception.

### T305 — Prerequisite: `begins_with(sk, "REG#")` in registration queries ✅
- **Phase:** P3 · **Size:** S · **Depends on:** T302 (creates `test_festival_checkin.py`, edited here); must land before any `SCAN#` row is ever written — do it before T306
- **Files:** `backend/app/services/registration_service.py` (edit), `backend/tests/unit/test_festival_checkin.py` (edit)
- **What to do:**
  - `list_registrations` (registration_service.py:504-506): change `KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")` to `Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#")` (spec.md:295 names :505 explicitly). Keep the pagination loop :532-535 untouched.
  - Apply the same sk condition to the two other bare-partition queries with the identical implicit assumption: `_get_active_spots_count` (:200-236) and `_get_max_waitlist_position` (:238-257).
- **Acceptance:**
  - [x] New test `TestRegPrefixFilter` in `test_festival_checkin.py`: seed one registration via `_registration_to_item` plus one raw item `{"pk": f"EVENT#{eid}", "sk": "SCAN#2026-08-15T00:30:00+02:00#<rid>#0", "entity_type": "CheckinScan"}`; `list_registrations` returns exactly 1 item and does not raise in `_item_to_registration`; `get_registration_stats` (:738-808) counts 1.
  - [x] Full existing suite green (waitlist/promotion tests in `test_registration_flow.py` exercise :200-257 paths).

### T306 — Check-in log + `checkin_service` (scan semantics, Berlin-time sk, distinct counting, undo, name search) ✅
- **Phase:** P3 · **Size:** L · **Depends on:** T302, T304, T305
- **Files:** `backend/app/services/checkin_service.py` (new), `backend/app/services/config.py` (edit), `backend/tests/unit/test_checkin_service.py` (new)
- **What to do:**
  - config.py: add `CHECKIN_SK_PREFIX = "SCAN#"` next to the existing key-prefix constants (:119-136).
  - `CheckinService` (class + `_service = None; def get_checkin_service()` singleton, pattern registration_service.py:1588-1593). Table: registrations table via `get_registrations_table()`, lazy `_table` property so tests can inject moto tables.
  - **Row shape** (spec.md:295): `pk=f"EVENT#{event_id}"`, `sk=f"SCAN#{iso_ts}#{registration_id}#{person_index}"` with `iso_ts = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")` — **Europe/Berlin local time is a deliberate, comment-documented exception** to the repo's UTC rule (gates run past midnight; Sa 00:30 CEST is Fr 22:30 UTC and would mis-attribute to Friday). Attrs: `entity_type="CheckinScan"`, `person_name`, `scanned_at` (UTC isoformat — keep UTC here for the undo window), `override: bool`. `scan_id` = the sk string itself (unique, sortable, addresses one row).
  - Methods:
    - `record_scan(event_id, registration_id, person_index, person_name, override=False) -> str` — put_item, returns scan_id. Never touches the registration item (check-in rows never flip status, spec.md:295).
    - `get_checked_in_map(event_id) -> dict[tuple[str, int], str]` — query `Key("pk").eq(...) & Key("sk").begins_with("SCAN#")` with pagination (loop pattern registration_service.py:532-535); parse `(registration_id, person_index)` from the sk; **distinct** keys (multi-device offline sync can create duplicate rows — first scan_id wins per key).
    - `count_arrivals(event_id, day: str | None)` — day form queries `begins_with(sk, f"SCAN#{day}")` (e.g. `"2026-08-15"`); returns distinct-person count.
    - `undo_scan(event_id, scan_id) -> bool` — get_item; refuse if missing or `now_utc - scanned_at > 60s` (spec.md:312, ~60 s window); else delete_item, True. Targeting by scan_id keeps concurrent lanes on one stateless gate token from undoing each other.
    - `scan_ticket(event: Event, code: str, override: bool = False) -> dict` — the one-tap orchestration (kept in the service so it's testable without TestClient, matching the repo's service-test-only pattern):
      1. `verify_ticket(event.ticket_secret, code)` → None ⇒ `{"result": "invalid", "reason": "invalid_signature"}` (a foreign event's ticket also lands here — different secret).
      2. Load registration by id from the event partition (get_item `pk=f"EVENT#{event.id}"`, `sk=f"REG#{payload['r']}"`, `_item_to_registration`); missing ⇒ `reason: "unknown_registration"`.
      3. `status == CANCELLED` ⇒ `reason: "cancelled"`.
      4. **Index-stability check** (spec.md:289): current name for `p` = `registration.name` if `p == 0` else `registration.group_members[p-1]`; index out of range, tombstoned (`None`) entry, or name ≠ payload `n` ⇒ `reason: "stale_ticket"` (UI shows „Ticket veraltet — bitte Namenssuche"). This works because group-member edits are append-only with `None` tombstones and never reindex (T109).
      5. **Slots are never checked** (Ä13) — `s` is echoed as info only.
      6. Already in `get_checked_in_map` and not `override` ⇒ card + `already_checked_in: true`, **write nothing** (no second wristband; shift lead decides).
      7. Else `record_scan(..., override=override)` in the same call ⇒ card + `scan_id` (+ `already_checked_in: true` when override re-scans a checked-in person).
      Card dict: person name, contact name, group list with per-member `checked_in` flags (from the map), `attendance_slots`, `accommodation`, and the **overnight status (Ä17)** computed from the CURRENT registration (`accommodation` + `overnight_approved` — NOT from the ticket payload; an approval after ticket issuance must show at the gate, the online scan is authoritative): `overnight_status` ∈ `approved` (zugesagt ✓, incl. the type) / `requested` (nur angefragt ⚠ — nicht zugesagt) / `none` (keine Übernachtung).
    - `checkin_person(event, registration_id, person_index) -> dict` — the name-search check-in target (always a specific `(registration_id, person_index)`, never a name, spec.md:313): same steps 2–7 minus signature, always `override=True`.
    - `search_names(event, q) -> list[dict]` — `registration_service.list_registrations(event.id)`, exclude CANCELLED, case-insensitive substring match against `registration.name` (index 0) and every non-`None` `group_members[i]` (index i+1; skip tombstones); returns **ALL** matches (duplicate names expected), each with disambiguation context: `person_index`, `person_name`, contact name, `group_size`, `invite_label` (Kontingent), `tier`, `checked_in` flag.
- **Acceptance — `test_checkin_service.py` (setup pattern: `CheckinService()` with `_table = tables["registrations_table"]`, seed via `_event_to_item` / `_registration_to_item`; per spec Verification P3, spec.md:368):**
  - [x] First scan commits a row and returns `scan_id`; second scan of the same code returns `already_checked_in: true` and the row count for that person is still 1 (double-scan writes nothing).
  - [x] Cancelled registration ⇒ `reason: "cancelled"`; tampered code ⇒ `"invalid_signature"`; unknown registration id ⇒ `"unknown_registration"` — three distinct reasons.
  - [x] Stale ticket: sign a code for `group_members[0]` (p=1), then rename/remove that member on the registration ⇒ `reason: "stale_ticket"`.
  - [x] Midnight attribution: patch now to `datetime(2026, 8, 14, 22, 30, tzinfo=timezone.utc)` (= Sa 00:30 CEST) ⇒ sk starts with `SCAN#2026-08-15` and `count_arrivals(day="2026-08-15")` counts it, `"2026-08-14"` does not.
  - [x] Distinct counting: manually insert two SCAN# rows with different timestamps for the same `(registration_id, person_index)` (simulated offline duplicate sync) ⇒ `count_arrivals` and `get_checked_in_map` count 1.
  - [x] `undo_scan` deletes within the window; with `scanned_at` backdated 120 s it returns False and the row survives.
  - [x] Override records a row with `override=True` even when already checked in.
  - [x] Overnight status (Ä17): registration with `accommodation=CAMPER, overnight_approved=True` ⇒ card `overnight_status == "approved"` with type CAMPER; same registration with the flag False ⇒ `"requested"`; no accommodation ⇒ `"none"`; flipping the flag on the stored registration AFTER signing the ticket changes the card on the next scan (current-state, not payload).
  - [x] Registration status is unchanged by any of the above (never CHECKED_IN).

### T307 — Public checkin router (boot / scan / override / undo / search) ✅
- **Phase:** P3 · **Size:** M · **Depends on:** T301, T303, T306
- **Files:** `backend/app/api/public/checkin.py` (new), `backend/app/main.py` (edit)
- **What to do:**
  - `router = APIRouter()` bare (pattern public/registrations.py:26); register in main.py next to :136-138: `app.include_router(checkin.router, prefix="/api/public", tags=["public-checkin"])`. No auth dependency — **the gate token IS the auth** (spec.md:336), resolved per request via `event_service.get_event_by_gate_token` (404 on miss, like the token-GSI lookups in public routers).
  - Shared helper `_load_gate_event(gate_token)` → 404 „Unbekannter Scanner-Link." if no event; 410 „Der Einlass ist für dieses Event nicht aktiv." unless `event.status ∈ {REGISTRATION_CLOSED, CONFIRMED}` (gating matrix: ≥ REGISTRATION_CLOSED and not COMPLETED, spec.md:273).
  - `GET /checkin/{gate_token}` — boot payload the scanner PWA caches for offline: event name, `start_at`/`end_at`, `festival_slots` (key/label/date/is_night), and `verification_secret = event.ticket_secret` (lazy via `ensure_gate_credentials` if still None). Exposing the secret to gate clients is accepted Risk 6 — add that spec reference as a code comment so nobody "fixes" it.
  - `POST /checkin/{gate_token}/scan` body `{code: str}` → `checkin_service.scan_ticket(event, code)`; always HTTP 200 with the structured result (`result`/`reason`/`card`/`scan_id`/`already_checked_in`) so the one-tap UI branches without exception handling.
  - `POST /checkin/{gate_token}/override` body `{code: str}` **or** `{registration_id: UUID, person_index: int}` (the name-search target — check-in always addresses a specific `(registration_id, person_index)`, spec.md:313) → `scan_ticket(event, code, override=True)` resp. `checkin_person(...)`; logged with `override=True` („Trotzdem einchecken").
  - `POST /checkin/{gate_token}/undo` body `{scan_id: str}` → `{"ok": checkin_service.undo_scan(event.id, scan_id)}` (False = window expired/unknown; UI copy „Rückgängig nicht mehr möglich").
  - `GET /checkin/{gate_token}/search?q=` — min length 2 (else 422), returns `{"matches": checkin_service.search_names(event, q)}`.
- **Acceptance:**
  - [x] All five routes resolve the gate token first; wrong token → 404 on every route; event in OPEN/DRAFT/COMPLETED → 410.
  - [x] Boot response contains `verification_secret` and slot labels; no other endpoint anywhere returns `ticket_secret` (grep).
  - [x] Router is thin — all semantics live in T306's service functions, which the T306 tests already cover; add one service-level test in `test_checkin_service.py` asserting boot lazy-generation via `ensure_gate_credentials` on an event created without credentials.
  - [x] Regression: full suite green — the regular event flow (create → register → lottery) untouched.

### T308 — Manage-page GET: freshly signed per-person QR payloads + F2 entry-codes paragraph ✅
- **Phase:** P3 · **Size:** M · **Depends on:** T302, T304
- **Files:** `backend/app/api/public/registrations.py` (edit), `backend/app/services/email_service.py` (edit), `backend/tests/unit/test_festival_checkin.py` (edit), `backend/tests/unit/test_email_service.py` (edit)
- **What to do:**
  - Extend `ManageRegistrationResponse` (registrations.py:185-193) additively: `qr_payloads: list[QrPayload] | None = None` with `QrPayload {person_index: int, name: str, code: str}`.
  - In the manage handler (:207-288), after the existing festival additions from P1/P2 (T111): if `event.event_type == FESTIVAL` and `registration.status != CANCELLED`, ensure credentials via `event_service.ensure_gate_credentials` (lazy — first manage view after P3 deploy mints the secret), then build codes with `sign_ticket(event.ticket_secret, registration.id, p, name, registration.attendance_slots, registration.overnight_approved)` for person 0 = `registration.name` and person `i+1` = each non-`None` `group_members[i]` (**skip `None` tombstone entries** — a removed member gets no code — and **keep original indices**, never reindex, spec.md:289). The `o` flag (Ä17) is used ONLY for the offline card: because payloads are signed fresh on every GET, a QR rendered after the admin approval carries `o: true`; an older screenshot is stale offline — acceptable, the online scan renders the current flag (T306). Slot/group edits are likewise reflected on the next render; old screenshots stay authentic-but-stale by design.
  - **F2 activation** (spec.md:205): the entry-codes paragraph already exists in the F2 template behind `include_qr_paragraph` (built in T107) — do NOT add a second paragraph. This task flips the flag to `True` at the `send_festival_confirmation` call site (and updates the T107 test expectation if it asserted the call site passes False). All existing guests get their codes automatically via their existing manage link — no re-send needed.
- **Acceptance:**
  - [x] `test_festival_checkin.py`: for a festival registration with `group_size=3`, `group_members=["Anna Meier", "Ben Otto"]`, the manage flow's payload builder yields 3 codes with person_index 0/1/2, each verifying via `verify_ticket` with the event secret and carrying the right `n` and the registration's `o` flag (re-signing after `overnight_approved` flips yields codes with the new `o` — Ä17); a tombstoned member (`None` entry) yields no code but later members keep their original person_index. (Added `TestManageQrPayloads` against the extracted `_build_qr_payloads` helper — no TestClient suite exists for this router, matching repo convention.)
  - [x] Non-festival events and CANCELLED registrations get `qr_payloads = None`/absent. (Guard is `if is_festival: ... if registration.status != CANCELLED: ...` in the handler — verified by inspection, no TestClient suite exists for this router.)
  - [x] `test_email_service.py`: the T107 template tests stay valid (paragraph behind the flag, both variants); the call-site test now asserts `send_festival_confirmation` renders F2 WITH „Eintritts-Codes" (flag True).

### T309 — QR cards on RegistrationManagePage (`qrcode` npm) ✅
- **Phase:** P3 · **Size:** M · **Depends on:** T308
- **Files:** `frontend/package.json` (edit — add `qrcode`), `frontend/src/pages/registration/RegistrationManagePage.vue` (edit)
- **What to do:**
  - `npm install qrcode` (confirmed absent from package.json). Import `QRCode from 'qrcode'`.
  - Inside the existing festival PARTICIPATING branch (the P1 slot-summary block in the status-switch template, T117), render a „Eintritts-Codes" section when `qr_payloads` is present (its absence = P3 backend not live yet — the section simply doesn't render, matching the F2 variant note spec.md:205): one card per payload with the person's name and a `<canvas>` QR via `QRCode.toCanvas(canvasEl, payload.code, { width: 240, margin: 2 })` in `onMounted`/watch after data load (template ref array).
  - German hint above the cards: „Bitte leite die Codes an deine Begleitungen weiter — jede Person zeigt ihren eigenen Code am Einlass vor. Ein Screenshot reicht." Follow the page's existing card idioms (`.registration-details` / `.info-box`-style scoped CSS with `--color-surface-raised`, `--pico-border-radius`); inline `role="alert"` for errors, no toasts (public page).
- **Acceptance:**
  - [ ] Manage page of a festival PARTICIPATING registration with 2 group members shows 3 named QR cards; a decoded QR reads `FUNKE1.<...>.<...>` and matches the API `code` verbatim. (Browser/field verification — deferred to T312.)
  - [ ] After a slot edit + reload, the QR content changes (freshly signed payloads). (Browser/field verification — deferred to T312.)
  - [ ] Non-festival manage pages and CANCELLED state render exactly as before (no section, no console errors). (Browser verification — deferred to T312; by code inspection the QR section is gated on `qrPayloads.length`, which stays `[]` when the backend omits `qr_payloads`.)
  - [x] No frontend test framework exists — verify via `npm run build` clean + the manual E2E in T312. (`npm run build` green, zero errors/warnings.)

### T310 — ScannerPage: camera scan, one-tap wristband flow, undo, override, name search ✅
- **Phase:** P3 · **Size:** L · **Depends on:** T307
- **Files:** `frontend/package.json` (edit — add `qr-scanner`), `frontend/src/router/index.js` (edit), `frontend/src/services/api.js` (edit), `frontend/src/pages/checkin/ScannerPage.vue` (new)
- **What to do:**
  - `npm install qr-scanner` (nimiq, iOS-Safari-proven, spec.md:343; confirmed absent). Route: `{ path: '/checkin/:gateToken', component: () => import('../pages/checkin/ScannerPage.vue'), props: true, meta: { hideTabBar: true } }` — **no `beforeEnter: authGuard`**, the gate token is the auth (spec.md:336).
  - `api.js`: add a `checkinApi` export (unauthenticated, like `publicApi`): `boot(gateToken)`, `scan(gateToken, code)`, `override(gateToken, body)`, `undo(gateToken, scanId)`, `search(gateToken, q)`.
  - Page (script-setup order convention: imports → route/composables → state refs → computeds → functions → `onMounted` last; German, informal du; big touch targets — this runs on phones at a dark gate):
    - Boot: load `GET /checkin/{gateToken}`; error states: 404 → „Ungültiger Scanner-Link.", 410 → „Der Einlass ist für dieses Event nicht aktiv."
    - Camera: `new QrScanner(videoEl, onDecode, { returnDetailedScanResult: true })`; pause the scanner while a result card is open; debounce identical consecutive decodes.
    - **Traffic-light card (Ä13, spec.md:59)** from the scan response:
      - 🟢 `result` green (`scan_id` present, not `already_checked_in`): full-screen green card — name, group with per-member check-in status, planned slots **as info only** (labels from boot slots — slots are never checked), and the **overnight status rendered prominently (Ä17)** from the card's `overnight_status`: `approved` → „Übernachtung zugesagt ✓ (Zelt/Camper)", `requested` → „Übernachtung nur angefragt ⚠ — nicht zugesagt" (warning styling — the gate crew must see this at a glance), `none` → „Keine Übernachtung —"; headline „✓ Eingecheckt — Bändchen ausgeben"; **3-second undo**: „Rückgängig (3)" countdown button → `undo(scanId)`; on `ok: false` show „Rückgängig nicht mehr möglich".
      - 🟡 `already_checked_in: true`: yellow card „Bereits eingecheckt — kein zweites Bändchen." + subline „Bändchen verloren? Schichtleitung entscheidet." + button **„Trotzdem einchecken"** → `override({ code })` (logged with override=true) → green card.
      - 🔴 rejected, distinct German reason per `reason`: `invalid_signature` → „Ungültiger Code", `cancelled` → „Anmeldung storniert", `stale_ticket` → „Ticket veraltet — bitte Namenssuche", `unknown_registration` → „Anmeldung nicht gefunden"; each with a „Namenssuche" shortcut button.
    - **Name search** (no-QR fallback): input min 2 chars → `search(q)`; render **ALL** matches with disambiguation context (person name, „bei {contact}", „Gruppe {group_size}", Kontingent label, check-in status chip); tapping a row calls `override({ registration_id, person_index })` — always targets the specific person, never a name.
    - „Weiter scannen" resumes the camera from every card.
- **Acceptance:**
  - [ ] Opening `/checkin/<token>` with a valid token boots without login; invalid token shows the 404 message.
  - [ ] Scanning a T309 QR from a second phone screen: green card + wristband headline in one tap; undo within 3 s removes the row (re-scan is green again); after the countdown the undo button disappears.
  - [ ] Second scan of the same code: yellow card, no new log row until „Trotzdem einchecken".
  - [ ] Cancelled/stale/tampered codes show their three distinct red messages.
  - [ ] Overnight status (Ä17) is visible on the card at a glance: ✓ zugesagt (with type) / ⚠ nur angefragt / — keine; an approval toggled admin-side after the QR was rendered still shows ✓ on the next online scan (server card wins over payload).
  - [ ] Name search for a duplicate name lists multiple rows with context; tapping one checks in exactly that `(registration_id, person_index)` (visible in the other row's status on next search).
  - [x] `npm run build` clean; full manual pass is T312. (Build green, zero errors/warnings; the remaining acceptance items above are browser/field verification — no second-phone/camera available in this environment — deferred to T312.)

### T311 — Scanner offline mode: boot cache, local HMAC verify, scan retry queue ✅
- **Phase:** P3 · **Size:** M · **Depends on:** T310
- **Files:** `frontend/src/utils/ticketVerify.js` (new), `frontend/src/composables/useCheckinQueue.js` (new), `frontend/src/pages/checkin/ScannerPage.vue` (edit), `frontend/src/sw.js` (edit — comment only)
- **What to do:**
  - **Boot cache**: persist the boot payload (event, slots, `verification_secret`) in `localStorage` keyed `checkin-boot-${gateToken}`; on boot-fetch failure fall back to the cache and show a persistent banner „Offline — eingeschränkte Prüfung. Gruppenstatus, Stornos und Doppel-Scans sind nicht sichtbar. Papierliste bleibt die Referenz." (Risk 5: degraded, not blind — decided, not to relitigate). App shell is already precached by the PWA (`vite.config.js` injectManifest), so the page itself boots offline once visited.
  - **Local verify** (`ticketVerify.js`): WebCrypto mirror of T304 — split `FUNKE1.<payload>.<mac>`, `crypto.subtle.importKey('raw', utf8(secret), { name: 'HMAC', hash: 'SHA-256' }, ...)` → sign the **b64url payload-segment ASCII bytes**, compare first 16 bytes against the b64url-decoded mac, then JSON-parse the payload. Must match T304's documented MAC rule byte-for-byte.
  - **Offline scan flow**: when `checkinApi.scan` fails with a network error, verify locally; invalid → red „Ungültiger Code"; valid → degraded green card showing only payload data (name, declared slots via cached boot labels, and the payload's `o` flag: `o: true` → „Übernachtung zugesagt ✓", `o: false` → „Übernachtung: keine Zusage im Ticket" — offline it cannot distinguish angefragt from keine, and the flag may be stale; the online card is authoritative, Ä17) and enqueue via `useCheckinQueue`.
  - **Retry queue** (`useCheckinQueue.js`): `localStorage` list of `{code, queued_at}` per gateToken; flush on `window 'online'` event + 30 s interval + manual „Jetzt synchronisieren" button; flush posts each code to `/scan`, treats `already_checked_in` responses as success (duplicates from multi-device offline are expected — the server counts distinct persons, T306), removes entries only on HTTP success. Show a queue badge („3 Scans warten auf Sync").
  - `sw.js`: keep `/api/` **NetworkOnly** — add a comment that checkin offline data is handled at app level (localStorage), deliberately not via SW caching, so the existing "never cache API responses" rule stands.
- **Acceptance:**
  - [ ] Airplane mode after one online boot: scanning a valid QR shows the degraded card with the person's name + slot labels; a tampered QR is rejected locally. (Browser/field verification — deferred to T312.)
  - [ ] Two offline scans enqueue (badge „2"); disabling airplane mode syncs them within 30 s; the check-in log has the rows; re-syncing the same codes creates no double count in `count_arrivals` (distinct counting). (Browser/field verification — deferred to T312.)
  - [x] Node-side parity check committed as a comment/fixture: one hardcoded `(secret, code)` pair generated by `ticket_signing.py` verifies true in `ticketVerify.js` (guards against MAC-input drift). (Fixture documented in `ticketVerify.js`'s module docstring; verified via Node's built-in `crypto.subtle` against `verifyTicketLocal` during implementation — payload, tampered, and wrong-secret cases all matched the backend.)

### T313 — Admin arrival-count surface (check-in log read + minimal display) ✅
- **Phase:** P3 · **Size:** S · **Depends on:** T306 (`count_arrivals`/`get_checked_in_map`), T202 (headcount endpoint), T207 (HeadcountPage)
- **Files:** `backend/app/api/admin/festival.py` (edit), `frontend/src/pages/admin/festival/HeadcountPage.vue` (edit)
- **What to do:**
  - Expose arrivals to admins — extend the existing `GET /api/admin/festival/{event_id}/headcount` response (T202) additively with an `arrivals` block computed via `checkin_service`: `{"total": <distinct persons ever checked in>, "per_day": {"2026-08-14": n, ...}}` — distinct `(registration_id, person_index)` counting (T306 semantics; duplicate offline-sync rows never double-count). Alternatively a tiny separate `GET .../arrivals` route if extending the response is awkward — read guard (OWNER/ADMIN/VIEWER) either way.
  - Minimal display: a „Angekommen" row/stat on HeadcountPage (total + per-day chips) rendered only when the `arrivals` block is present and non-zero — no new page. Spec framing: the check-in log delivers ARRIVAL numbers (who actually came), not per-day presence — label it „Angekommen (Erst-Check-ins)" to avoid misreading it as a live headcount.
- **Acceptance:**
  - [x] Endpoint returns arrivals total + per-day distinct-person counts matching `count_arrivals` (seed one duplicate SCAN# row pair → still counts 1; service-level test extends `test_checkin_service.py`). Added `CheckinService.get_arrivals_summary` + `TestArrivalsSummary` (3 new tests: total/per-day matches `count_arrivals`, duplicate-row pair still counts once, empty log → `{"total": 0, "per_day": {}}`); router merges it into the T202 response only when `total > 0`.
  - [x] HeadcountPage shows the arrival numbers for an event with scans and renders unchanged (no empty section) for an event without any. (verified by code-tracing: `hasArrivals` computed gates the whole card on `headcount.arrivals.total` truthiness, matching the backend's "only present when non-zero" contract — no dev-server/browser check run)
  - [x] SINGLE events unaffected; VIEWER can read. (route already 400s non-FESTIVAL events before the arrivals code runs, so a SINGLE event never queries the check-in log; guard dependency unchanged from T202, still allows VIEWER)

### T312 — Field test Mon 10.8. with real gate people (incl. airplane-mode) — go/no-go for QR check-in ✅ (vorbereitet — Feldtest Mo 10.8. durch Menschen)
- **Phase:** P3 · **Size:** M · **Depends on:** T303, T309, T310, T311, T313
- **Files:** `specs/019-festival-sidetrack/spec.md` (edit — record the decision in the Ä9 row / decision journal), `specs/019-festival-sidetrack/feldtest-checkliste.md` (new — German field-test script prepared 19.7.)
- **Prep verified 19.7. (technical preconditions only — the field test itself is a human activity, not yet run):**
  - All P3 backend tests green (56 tests across `test_ticket_signing.py`, `test_checkin_service.py`, `test_festival_checkin.py`, `test_festival_headcount.py`); full suite exits with exactly the 2 known pre-existing baseline failures and zero others.
  - Frontend `npm run build` green; scanner route `/checkin/:gateToken` builds with no `authGuard` (gate token is the auth).
  - Offline HMAC verify path (`ticketVerify.js`) checked against the backend's `ticket_signing.py` via the Node-`crypto.subtle` parity fixture documented in the module docstring — **not an automated test** (no frontend test runner in this repo), a manually-verified fixture only.
  - German field-test script written to `feldtest-checkliste.md`: Geräte/Equipment, all named test cases (Erstscan→Bändchen, Doppelscan, Bändchen-verloren-Override, Namenssuche inkl. Duplikat, veraltetes Ticket, Übernachtungs-Status ✓/⚠/—, Flugmodus-Scan+Sync, Mitternachts-Randfall), pass/fail criteria mirrored from this task, and the paper-fallback decision rule (not passed by Tue 11.8. → paper is Plan of Record, Ä9).
  - **Remains entirely human and unticked below**: the actual Monday run with real gate people, camera/lighting/network behavior in the field, and the go/no-go decision written into spec.md's decision journal. Nothing here was fabricated or pre-answered.
- **What to do:**
  - Prep (before Monday): P3 deployed to prod; rotate the prod gate token (T303) and hand the link to 2–3 real gate people (not devs) on their own phones; print the gate CSV (P1 T113, Ä9 floor) as the on-site backup; create 2–3 real test registrations with groups so manage-page QRs exist.
  - Script (spec.md:368): each tester runs the full loop unaided — open manage page on phone A, scan its QR with phone B via the gate link (one tap → green), undo within 3 s, re-scan (yellow), „Trotzdem einchecken", name search incl. a duplicate name, one stale ticket (edit a group member first), one **overnight check (Ä17)**: a registration with a Zelt request scans with „nur angefragt ⚠"; after the admin toggles „darf übernachten" the next scan card shows „Übernachtung zugesagt ✓ (Zelt)" — then **airplane mode**: scan offline, verify degraded card, go online, confirm sync in the admin arrival count (the T313 „Angekommen" surface on HeadcountPage).
  - **Pass criteria (all must hold, judged with the gate crew):**
    - [ ] A non-dev completes scan→wristband decision in ≤ 10 s per person without asking questions.
    - [ ] Camera decode works outdoors and in dim light on the crew's own phones (incl. at least one iPhone/Safari).
    - [ ] Double-scan reliably shows yellow, never a second green; undo works; override is logged (`override=true` rows visible).
    - [ ] Airplane-mode scan verifies + queues, and syncs to exactly one distinct check-in after reconnect.
    - [ ] Name search resolves a duplicate name to the right person via the context shown.
  - **Fail path (any criterion fails and can't be fixed same-day):** paper is the plan of record (Ä9) — the printed gate CSV runs the gate, the scanner becomes optional assistance only; record the decision and reasoning in spec.md's decision journal either way. **No new scanner features after 10.8.** — the gate day is unrehearsable.
- **Acceptance:**
  - [ ] Test executed on Mon 10.8. with ≥ 2 real gate people; checklist above filled in.
  - [ ] Go/no-go decision (QR primary vs. paper primary) written into spec.md with date and participants.
  - [ ] Regression sweep the same day: regular (non-festival) event flow create → register → lottery still works in prod (spec.md:368).

### P3 review fix pass (19.7.) ✅
Applied three review findings (backend gate: 2 known baseline failures only; frontend build green):
1. **T306/`checkin_service.scan_ticket`**: a validly-signed payload with a non-int `"p"` (craftable by anyone holding the gate link, Risk 6) raised `TypeError` → HTTP 500, breaking the router's always-200 contract. Now rejected as `unknown_registration` (bool excluded explicitly). Regression tests added in `test_checkin_service.py`.
2. **T302/`event_service.ensure_gate_credentials`**: the unconditional read-modify-`put_item` could mint two different `ticket_secret`s on concurrent first calls (loser's QR payloads scan red forever). Now persisted via `update_item` with `SET ... = if_not_exists(...)` + `ReturnValues=ALL_NEW`, so DynamoDB serializes the mint and every caller gets the winning values. Regression test added in `test_festival_checkin.py`.
3. **T307/`_GATE_OPEN_STATUSES`**: widened to include `OPEN` — under Ä14 the event stays OPEN through the gate days (invite redemption requires OPEN until Sun 16.8. 23:59), so a REGISTRATION_CLOSED-only gate would 410 the scanner during the whole festival. Decision recorded in spec.md (gating matrix + „Challenged & decided" journal). Redemption stays OPEN-only.
