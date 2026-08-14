"""Companion e-mail & personal ticket page (spec 020).

The load-bearing invariant throughout is **index alignment**:
`group_member_emails[i]` is the address of `group_members[i]`, and that person's
`person_index` is `i + 1`. If those ever drift, a personalised QR code gets
mailed to the wrong human — so misalignment is tested as a hard error
everywhere it could be introduced, not just at the happy path.

Layout:
- TestCompanionEmailModel        — T001 alignment/normalisation rules
- TestCompanionEmailStorage      — T002 round-trip + legacy rows
- TestCompanionRecipients        — T003 who gets a mail, and who must not
- TestPersonPageToken            — T004 capability token
- TestCompanionTicketMail        — T005 F5/F6 templates + queued MIME
- TestCompanionSendSites         — T006 create / self-edit diff / cancel
- TestPersonTicketEndpoint       — T007 read-only page + its 404 wall
- TestRundmailFanout             — T008 bulk-mail fan-out
- TestCompanionPrivacyBoundaries — the Gästelisten page and gate CSV must
                                   never carry an address
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models import (
    Event,
    EventStatus,
    EventType,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    FestivalSlot,
    InviteBatchCreate,
    InviteCreate,
    Registration,
    RegistrationAdminPatch,
    RegistrationStatus,
)
from app.services.email_service import EmailContext, EmailService, EmailTemplates
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import InviteService
from app.services.registration_service import (
    CompanionRecipient,
    RegistrationService,
    _companions_needing_fresh_code,
    _registration_to_item,
    build_gate_rows,
    companion_recipients,
)
from app.services.ticket_signing import (
    SignedTicket,
    person_page_token,
    verify_person_page_token,
    verify_ticket,
)

NOW = datetime.now(UTC)


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
        FestivalSlot(key="so", label="Sonntag", date=date(2026, 8, 16)),
    ]


def _registration(**overrides) -> Registration:
    defaults = {
        "event_id": uuid4(),
        "name": "Anna Schmidt",
        "email": "anna@example.de",
        "phone": "0176 1234567",
        "group_size": 1,
        "registration_token": "regtoken-" + uuid4().hex,
        "status": RegistrationStatus.PARTICIPATING,
        "attendance_slots": ["fr"],
    }
    defaults.update(overrides)
    return Registration(**defaults)


# ---------------------------------------------------------------- T001 models


class TestCompanionEmailModel:
    """Alignment and normalisation of `group_member_emails`."""

    def test_aligned_pair_accepted(self):
        reg = _registration(
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", None],
            group_size=3,
        )
        assert reg.group_member_emails == ["lisa@example.de", None]

    def test_short_list_is_padded_to_member_length(self):
        """Only the first companion has an address — the common case."""
        reg = _registration(
            group_members=["Lisa Meier", "Tim Bach", "Jo Klein"],
            group_member_emails=["lisa@example.de"],
            group_size=4,
        )
        assert reg.group_member_emails == ["lisa@example.de", None, None]

    def test_model_load_truncates_an_over_long_address_list(self):
        """Must stay LOADABLE — `list_registrations` parses rows in a
        comprehension, so one unreadable row would take the admin list, the gate
        CSV and the headcount board down with it. Surviving indices are kept."""
        reg = _registration(
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
            group_size=2,
        )
        assert reg.group_member_emails == ["lisa@example.de"]

    def test_addresses_without_members_rejected(self):
        with pytest.raises(ValidationError, match="requires group_members"):
            _registration(group_member_emails=["lisa@example.de"], group_size=2)

    def test_all_none_collapses_to_none(self):
        reg = _registration(
            group_members=["Lisa Meier"], group_member_emails=[None], group_size=2,
        )
        assert reg.group_member_emails is None

    def test_model_load_drops_an_orphaned_address_instead_of_raising(self):
        """A stored row whose member was removed must stay LOADABLE.

        This validator runs on every read from DynamoDB. Raising here would
        turn one badly-written row into a registration nobody can ever load
        again — the guest locked out of their manage page and the gate unable
        to find them. Strictness lives in the input schemas instead.
        """
        reg = _registration(
            group_members=["Lisa Meier", None],
            group_member_emails=["lisa@example.de", "tim@example.de"],
            group_size=2,
        )
        assert reg.group_member_emails == ["lisa@example.de", None]

    def test_orphan_only_row_collapses_to_none_on_load(self):
        reg = _registration(
            group_members=[None],
            group_member_emails=["tim@example.de"],
            group_size=1,
        )
        assert reg.group_member_emails is None

    def test_create_schema_normalises_case_and_blanks(self):
        data = FestivalRegistrationCreate(
            name="Anna Schmidt",
            email="Anna@Example.DE",
            attendance_slots=["fr"],
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["  LISA@Example.de ", "   "],
            phone="0176 1234567",
        )
        # Blank becomes None rather than failing EmailStr; the rest lowercases
        # to match the contact address, so dedupe comparisons are reliable.
        assert data.group_member_emails == ["lisa@example.de", None]

    def test_create_schema_rejects_misaligned_length(self):
        with pytest.raises(ValidationError):
            FestivalRegistrationCreate(
                name="Anna Schmidt",
                email="anna@example.de",
                attendance_slots=["fr"],
                group_size=2,
                group_members=["Lisa Meier"],
                group_member_emails=["lisa@example.de", "tim@example.de"],
                phone="0176 1234567",
            )

    def test_create_schema_rejects_malformed_address(self):
        with pytest.raises(ValidationError):
            FestivalRegistrationCreate(
                name="Anna Schmidt",
                email="anna@example.de",
                attendance_slots=["fr"],
                group_size=2,
                group_members=["Lisa Meier"],
                group_member_emails=["not-an-email"],
                phone="0176 1234567",
            )

    def test_patch_schema_keeps_all_none_list(self):
        """On a PATCH, [None, None] is 'clear every address'.

        Collapsing it to None would make it indistinguishable from 'field not
        provided' and silently swallow the request.
        """
        patch_obj = FestivalAttendancePatch(
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=[None, None],
        )
        assert patch_obj.group_member_emails == [None, None]

    def test_patch_schemas_accept_the_field(self):
        """Both patch schemas are extra='forbid' — they'd 422 without it."""
        assert FestivalAttendancePatch(
            group_member_emails=["lisa@example.de"],
        ).group_member_emails == ["lisa@example.de"]
        assert RegistrationAdminPatch(
            group_member_emails=["lisa@example.de"],
        ).group_member_emails == ["lisa@example.de"]


# --------------------------------------------------------------- T002 storage


class TestCompanionEmailStorage:
    def test_round_trip_with_tombstones(self, mock_dynamodb):
        service = RegistrationService()
        service._registrations_table = mock_dynamodb["registrations_table"]

        reg = _registration(
            id=uuid4(),
            group_members=["Lisa Meier", None, "Jo Klein"],
            group_member_emails=["lisa@example.de", None, "jo@example.de"],
            group_size=3,
        )
        item = _registration_to_item(reg)
        service._registrations_table.put_item(Item=item)

        from app.services.registration_service import _item_to_registration

        loaded = _item_to_registration(
            service._registrations_table.get_item(
                Key={"pk": item["pk"], "sk": item["sk"]},
            )["Item"],
        )
        assert loaded.group_members == ["Lisa Meier", None, "Jo Klein"]
        assert loaded.group_member_emails == ["lisa@example.de", None, "jo@example.de"]

    def test_legacy_item_without_attribute_reads_as_none(self):
        """Pre-020 rows have no attribute at all — no migration, no backfill."""
        from app.services.registration_service import _item_to_registration

        reg = _registration(id=uuid4(), group_members=["Lisa Meier"], group_size=2)
        item = _registration_to_item(reg)
        assert "group_member_emails" not in item

        loaded = _item_to_registration(item)
        assert loaded.group_member_emails is None


# ------------------------------------------------------------ T003 recipients


class TestCompanionRecipients:
    def test_mixed_addressed_and_unaddressed(self):
        reg = _registration(
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", None],
            group_size=3,
        )
        assert companion_recipients(reg) == [
            CompanionRecipient(person_index=1, name="Lisa Meier", email="lisa@example.de"),
        ]

    def test_contact_own_address_skipped(self):
        """The contact already gets F2 with every QR — no duplicate mail."""
        reg = _registration(
            email="anna@example.de",
            group_members=["Anna Schmidt Zweitgerät"],
            group_member_emails=["ANNA@example.de"],
            group_size=2,
        )
        assert companion_recipients(reg) == []

    def test_duplicate_addresses_collapse_to_first_index(self):
        reg = _registration(
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "lisa@example.de"],
            group_size=3,
        )
        result = companion_recipients(reg)
        assert len(result) == 1
        assert result[0].person_index == 1

    def test_tombstone_skipped_and_later_indices_keep_their_numbers(self):
        """Index stability: removing member 1 must not renumber member 2."""
        reg = _registration(
            group_members=[None, "Jo Klein"],
            group_member_emails=[None, "jo@example.de"],
            group_size=2,
        )
        result = companion_recipients(reg)
        assert len(result) == 1
        assert result[0].person_index == 2
        assert result[0].name == "Jo Klein"

    def test_cancelled_registration_yields_nothing(self):
        reg = _registration(
            status=RegistrationStatus.CANCELLED,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )
        assert companion_recipients(reg) == []

    def test_no_addresses_yields_nothing(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2)
        assert companion_recipients(reg) == []


class TestNewlyAddressedCompanions:
    """The self-edit diff (D2) — the guard against mailing on every edit."""

    def _pair(self, before_emails, after_emails, members=("Lisa Meier", "Tim Bach")):
        common = {"group_members": list(members), "group_size": len(members) + 1}
        before = _registration(group_member_emails=before_emails, **common)
        after = _registration(group_member_emails=after_emails, **common)
        return before, after

    def test_newly_added_address_is_returned(self):
        before, after = self._pair([None, None], ["lisa@example.de", None])
        assert [r.person_index for r in _companions_needing_fresh_code(before, after)] == [1]

    def test_corrected_address_is_returned(self):
        before, after = self._pair(["typo@example.de", None], ["lisa@example.de", None])
        assert [r.person_index for r in _companions_needing_fresh_code(before, after)] == [1]

    def test_unchanged_address_is_not_returned(self):
        before, after = self._pair(["lisa@example.de", None], ["lisa@example.de", None])
        assert _companions_needing_fresh_code(before, after) == []

    def test_rename_resends_because_the_old_code_is_dead(self):
        """A rename kills the emailed QR: the gate compares the signed name to
        the current one and rejects a mismatch as `stale_ticket`
        (`checkin_service.py:340`, covered by
        `test_checkin_service.py::TestStaleTicket::test_stale_after_rename`).
        Staying silent here would send that person to the entrance with a code
        that goes red."""
        before = _registration(
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )
        after = _registration(
            group_members=["Lisa Meier-Bach"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )
        assert [r.person_index for r in _companions_needing_fresh_code(before, after)] == [1]

    def test_slot_change_alone_still_does_not_resend(self):
        """Days are informational in the payload and never checked at the gate
        (Ä13), so those codes stay valid — the one case that must stay quiet."""
        before = _registration(
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
            attendance_slots=["fr"],
        )
        after = _registration(
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
            attendance_slots=["fr", "sa"],
        )
        assert _companions_needing_fresh_code(before, after) == []

    def test_rename_without_address_sends_nothing(self):
        """Unreachable by mail — the contact forwards a fresh QR instead."""
        before = _registration(group_members=["Lisa Meier"], group_size=2)
        after = _registration(group_members=["Lisa Meier-Bach"], group_size=2)
        assert _companions_needing_fresh_code(before, after) == []

    def test_previously_absent_list_treats_all_as_new(self):
        before = _registration(group_members=["Lisa Meier"], group_size=2)
        after = _registration(
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )
        assert [r.person_index for r in _companions_needing_fresh_code(before, after)] == [1]


# ------------------------------------------------------------------ T004 token


class TestPersonPageToken:
    MAIL = "lisa@example.de"

    def test_stable_across_calls(self):
        assert person_page_token("regtoken", 2, self.MAIL) == person_page_token(
            "regtoken", 2, self.MAIL,
        )

    def test_differs_per_index(self):
        assert person_page_token("regtoken", 1, self.MAIL) != person_page_token(
            "regtoken", 2, self.MAIL,
        )

    def test_differs_per_registration_token(self):
        assert person_page_token("token-a", 1, self.MAIL) != person_page_token(
            "token-b", 1, self.MAIL,
        )

    def test_differs_per_address(self):
        """The point of binding to the address: replacing the occupant of an
        index invalidates the previous holder's link."""
        assert person_page_token("regtoken", 1, "lisa@example.de") != person_page_token(
            "regtoken", 1, "tim@example.de",
        )

    def test_address_is_normalised(self):
        assert person_page_token("regtoken", 1, " LISA@Example.DE ") == person_page_token(
            "regtoken", 1, "lisa@example.de",
        )

    def test_verify_accepts_matching_token(self):
        assert verify_person_page_token(
            "regtoken", 3, self.MAIL, person_page_token("regtoken", 3, self.MAIL),
        )

    @pytest.mark.parametrize(
        ("reg_token", "index", "email"),
        [
            ("regtoken", 2, MAIL),
            ("other-token", 1, MAIL),
            ("regtoken", 1, "tim@example.de"),
        ],
    )
    def test_verify_rejects_wrong_scope(self, reg_token, index, email):
        issued = person_page_token("regtoken", 1, self.MAIL)
        assert not verify_person_page_token(reg_token, index, email, issued)

    @pytest.mark.parametrize("bad", ["", "garbage", "!!!!"])
    def test_verify_rejects_malformed(self, bad):
        assert not verify_person_page_token("regtoken", 1, self.MAIL, bad)

    @pytest.mark.parametrize("bad", ["ü", "tökén", "\u00fc" * 22])
    def test_verify_rejects_non_ascii_without_raising(self, bad):
        """compare_digest raises TypeError on non-ASCII str. Unguarded that
        became a 500 — and since the registration is looked up BEFORE the token
        is checked, a 500-vs-404 split leaked whether a registration exists."""
        assert not verify_person_page_token("regtoken", 1, self.MAIL, bad)

    def test_verify_rejects_when_no_address_is_stored(self):
        """A companion without an address has no page at all."""
        assert not verify_person_page_token(
            "regtoken", 1, None, person_page_token("regtoken", 1, self.MAIL),
        )

    def test_token_does_not_contain_the_registration_token(self):
        """One-way by construction — a leaked person token grants no writes."""
        assert "regtoken" not in person_page_token("regtoken", 1, self.MAIL)


# ------------------------------------------------------------------ T005 mails


class TestCompanionTicketTemplates:
    def _ctx(self, **overrides) -> EmailContext:
        defaults = {
            "event_name": "Betriebsfeier",
            "event_date": "Freitag, 14. August 2026 um 18:00",
            "event_location": "Werft",
            "attendee_name": "Lisa Meier",
            "attendee_email": "lisa@example.de",
            "group_size": 3,
            "registration_status": "PARTICIPATING",
            "slot_labels": "Freitag, Samstag",
            "contact_hint": "festival@example.de",
            "contact_name": "Anna Schmidt",
            "person_ticket_url": "https://funke.example/ticket/e/r/2?token=abc",
        }
        defaults.update(overrides)
        return EmailContext(**defaults)

    def test_f5_carries_only_this_persons_qr(self):
        ticket = SignedTicket(person_index=2, name="Lisa Meier", code="FUNKE1.x.y")
        _, text, html = EmailTemplates.festival_companion_ticket(self._ctx(), ticket)

        assert "cid:qr-2" in html
        assert "cid:qr-1" not in html
        assert "cid:qr-0" not in html
        assert "Lisa Meier" in text
        assert "Anna Schmidt" in text

    def test_f5_never_contains_a_manage_url(self):
        """D1: the manage token could cancel the whole group."""
        ticket = SignedTicket(person_index=1, name="Lisa Meier", code="FUNKE1.x.y")
        _, text, html = EmailTemplates.festival_companion_ticket(self._ctx(), ticket)

        for body in (text, html):
            assert "/registration/" not in body
        assert "/ticket/" in text

    def test_f5_subject_and_signature(self):
        ticket = SignedTicket(person_index=1, name="Lisa Meier", code="c")
        subject, text, _ = EmailTemplates.festival_companion_ticket(self._ctx(), ticket)

        assert subject == "Dein Eintritts-Code: Betriebsfeier"
        assert "Dein Orga-Team" in text
        assert "Schaluppe" not in text

    def test_f5_omits_mitmach_paragraph_when_unset(self):
        ticket = SignedTicket(person_index=1, name="Lisa Meier", code="c")
        _, text, html = EmailTemplates.festival_companion_ticket(self._ctx(), ticket)
        assert "None" not in text
        assert "None" not in html

    def test_f5_renders_mitmach_paragraph_when_set(self):
        ticket = SignedTicket(person_index=1, name="Lisa Meier", code="c")
        ctx = self._ctx(mitmach_hint="Trag dich im Schichtplan ein!")
        _, text, html = EmailTemplates.festival_companion_ticket(ctx, ticket)
        assert "Schichtplan" in text
        assert "Schichtplan" in html

    def test_f6_states_the_code_is_dead(self):
        subject, text, html = EmailTemplates.festival_companion_cancelled(self._ctx())

        assert subject == "Abgesagt: Betriebsfeier"
        assert "funktioniert nicht mehr" in text
        assert "funktioniert nicht mehr" in html
        assert "Anna Schmidt" in text
        assert "/registration/" not in text


class TestCompanionTicketMailQueueing:
    """F5 through the real EmailService, with real gate credentials."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.event_service = EventService()
        self.event_service._table = mock_dynamodb["events_table"]

        self.email_service = EmailService()
        self.email_service._messages_table = MagicMock()

        self.patcher = patch(
            "app.services.event_service.get_event_service",
            return_value=self.event_service,
        )
        self.patcher.start()
        yield
        self.patcher.stop()

    def _event(self, **overrides) -> Event:
        defaults = {
            "name": "Betriebsfeier",
            "org_id": uuid4(),
            "event_type": EventType.FESTIVAL,
            "start_at": NOW + timedelta(days=10),
            "end_at": NOW + timedelta(days=12),
            "registration_deadline": NOW + timedelta(days=12),
            "festival_slots": _slots(),
        }
        defaults.update(overrides)
        return Event(**defaults)

    @pytest.mark.asyncio
    async def test_queues_exactly_one_qr_for_the_recipient(self):
        event = self._event()
        self.event_service._table.put_item(Item=_event_to_item(event))
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
            group_size=3,
        )
        recipient = CompanionRecipient(2, "Tim Bach", "tim@example.de")

        result = await self.email_service.send_festival_companion_ticket(event, reg, recipient)

        assert result is True
        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["recipient_email"] == "tim@example.de"
        assert [img["content_id"] for img in item["inline_images"]] == ["qr-2"]
        assert "cid:qr-2" in item["body_html"]
        assert "cid:qr-1" not in item["body_html"]
        assert item["type"] == "festival_companion_ticket"

    @pytest.mark.asyncio
    async def test_embedded_code_verifies_for_that_person(self):
        event = self._event()
        self.event_service._table.put_item(Item=_event_to_item(event))
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )

        await self.email_service.send_festival_companion_ticket(
            event, reg, CompanionRecipient(1, "Lisa Meier", "lisa@example.de"),
        )

        stored = await self.event_service.get_event_by_id(event.id)
        # Reconstruct the code the mail embedded and prove the gate accepts it
        # for THIS person index — the whole point of the feature.
        from app.services.ticket_signing import build_person_tickets

        ticket = next(
            t
            for t in build_person_tickets(
                stored.ticket_secret, reg.id, reg.name, reg.group_members,
                reg.attendance_slots, reg.overnight_approved,
            )
            if t.person_index == 1
        )
        payload = verify_ticket(stored.ticket_secret, ticket.code)
        assert payload is not None
        assert payload["p"] == 1
        assert payload["n"] == "Lisa Meier"

    @pytest.mark.asyncio
    async def test_mail_still_goes_out_when_qr_pipeline_fails(self):
        """Event never stored → no ticket_secret. The companion must still get
        a mail with the (self-healing) ticket link rather than nothing."""
        event = self._event()  # deliberately not stored
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )

        result = await self.email_service.send_festival_companion_ticket(
            event, reg, CompanionRecipient(1, "Lisa Meier", "lisa@example.de"),
        )

        assert result is True
        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert "inline_images" not in item
        assert "/ticket/" in item["body"]

    @pytest.mark.asyncio
    async def test_cancellation_notices_use_explicit_recipients(self):
        """After the flip to CANCELLED, companion_recipients() returns [] —
        callers must pass the pre-cancel list, so this path honours it."""
        event = self._event()
        self.event_service._table.put_item(Item=_event_to_item(event))
        cancelled = _registration(
            id=uuid4(),
            event_id=event.id,
            status=RegistrationStatus.CANCELLED,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
            group_size=3,
        )

        sent = await self.email_service.send_festival_companion_cancellations(
            event,
            cancelled,
            recipients=[
                CompanionRecipient(1, "Lisa Meier", "lisa@example.de"),
                CompanionRecipient(2, "Tim Bach", "tim@example.de"),
            ],
        )

        assert sent == 2

    @pytest.mark.asyncio
    async def test_cancellation_without_recipients_sends_nothing_when_cancelled(self):
        event = self._event()
        cancelled = _registration(
            id=uuid4(),
            event_id=event.id,
            status=RegistrationStatus.CANCELLED,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )
        assert await self.email_service.send_festival_companion_cancellations(
            event, cancelled,
        ) == 0


# ------------------------------------------------------------- T006 send sites


class CompanionServiceBase:
    """Real services on moto tables, mocked email service."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb

        self.reg_service = RegistrationService()
        self.reg_service._registrations_table = self.tables["registrations_table"]
        self.reg_service._events_table = self.tables["events_table"]

        self.event_service = EventService()
        self.event_service._table = self.tables["events_table"]

        self.invite_service = InviteService()
        self.invite_service._table = self.tables["events_table"]

        self.mock_email_service = AsyncMock()

        patches = [
            patch(
                "app.services.event_service.get_event_service",
                return_value=self.event_service,
            ),
            patch(
                "app.services.invite_service.get_invite_service",
                return_value=self.invite_service,
            ),
            patch(
                "app.services.email_service.get_email_service",
                return_value=self.mock_email_service,
            ),
        ]
        for p in patches:
            p.start()
        yield
        patch.stopall()

    def _make_event(self, **overrides) -> Event:
        defaults = dict(
            id=uuid4(),
            org_id=uuid4(),
            name="Betriebsfeier",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=20),
            end_at=NOW + timedelta(days=22),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            status=EventStatus.OPEN,
            autopromote_waitlist=False,
            registration_link_token=None,
            contact_hint="festival@example.de",
        )
        defaults.update(overrides)
        event = Event(**defaults)
        self.tables["events_table"].put_item(Item=_event_to_item(event))
        return event

    async def _make_invite(self, event: Event, **entry_overrides):
        entry_defaults = dict(label="Anna", tier="volunteer", max_uses=5, max_group_size=5)
        entry_defaults.update(entry_overrides)
        batch = InviteBatchCreate(invites=[InviteCreate(**entry_defaults)])
        created = await self.invite_service.create_invites_batch(
            event.org_id, event.id, batch, uuid4(),
        )
        return created[0]

    async def _register(self, invite, **overrides):
        defaults = dict(
            name="Anna Schmidt",
            email="anna@example.de",
            attendance_slots=["fr", "sa"],
            phone="0176 1234567",
        )
        defaults.update(overrides)
        return await self.reg_service.create_festival_registration(
            invite.token, FestivalRegistrationCreate(**defaults),
        )

    def _companion_calls(self):
        return self.mock_email_service.send_festival_companion_ticket.await_args_list


class TestCompanionSendOnCreate(CompanionServiceBase):
    @pytest.mark.asyncio
    async def test_one_mail_per_addressed_companion(self):
        event = self._make_event()
        invite = await self._make_invite(event)

        reg, error = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", None],
        )

        assert error is None
        assert reg.group_member_emails == ["lisa@example.de", None]
        self.mock_email_service.send_festival_confirmation.assert_awaited_once()
        calls = self._companion_calls()
        assert len(calls) == 1
        assert calls[0].args[2].email == "lisa@example.de"
        assert calls[0].args[2].person_index == 1

    @pytest.mark.asyncio
    async def test_no_addresses_sends_no_companion_mail(self):
        event = self._make_event()
        invite = await self._make_invite(event)

        await self._register(
            invite, group_size=2, group_members=["Lisa Meier"],
        )

        assert self._companion_calls() == []

    @pytest.mark.asyncio
    async def test_failing_companion_mail_does_not_fail_registration(self):
        """A bad address must never cost the guest their registration."""
        event = self._make_event()
        invite = await self._make_invite(event)
        self.mock_email_service.send_festival_companion_ticket.side_effect = RuntimeError(
            "smtp exploded",
        )

        reg, error = await self._register(
            invite,
            group_size=2,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
        )

        assert error is None
        assert reg is not None
        assert reg.status == RegistrationStatus.PARTICIPATING

    @pytest.mark.asyncio
    async def test_one_bad_address_does_not_block_the_others(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        self.mock_email_service.send_festival_companion_ticket.side_effect = [
            RuntimeError("boom"),
            None,
        ]

        reg, error = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )

        assert error is None
        assert len(self._companion_calls()) == 2

    @pytest.mark.asyncio
    async def test_companion_address_equal_to_contact_is_skipped(self):
        event = self._make_event()
        invite = await self._make_invite(event)

        await self._register(
            invite,
            email="anna@example.de",
            group_size=2,
            group_members=["Anna Schmidt"],
            group_member_emails=["anna@example.de"],
        )

        assert self._companion_calls() == []


class TestCompanionSendOnSelfEdit(CompanionServiceBase):
    async def _setup_registration(self, **overrides):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite, group_size=3, group_members=["Lisa Meier", "Tim Bach"], **overrides,
        )
        self.mock_email_service.reset_mock()
        return event, reg

    @pytest.mark.asyncio
    async def test_address_added_later_sends_one_mail(self):
        _, reg = await self._setup_registration()

        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_member_emails=["lisa@example.de", None]),
        )

        assert error is None
        assert updated.group_member_emails == ["lisa@example.de", None]
        calls = self._companion_calls()
        assert len(calls) == 1
        assert calls[0].args[2].email == "lisa@example.de"

    @pytest.mark.asyncio
    async def test_slot_only_edit_sends_no_companion_mail(self):
        _, reg = await self._setup_registration(
            group_member_emails=["lisa@example.de", None],
        )

        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(attendance_slots=["so"]),
        )

        assert error is None
        assert updated.attendance_slots == ["so"]
        assert self._companion_calls() == []

    @pytest.mark.asyncio
    async def test_rename_mails_the_renamed_companion_a_fresh_code(self):
        """A rename invalidates the QR already in that person's inbox — the gate
        rejects a name mismatch as `stale_ticket`. Only the renamed companion is
        mailed; Tim, untouched and addressless, is not."""
        _, reg = await self._setup_registration(
            group_member_emails=["lisa@example.de", None],
        )

        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_members=["Lisa Meier-Bach", "Tim Bach"]),
        )

        assert error is None
        assert updated.group_members == ["Lisa Meier-Bach", "Tim Bach"]

        calls = self._companion_calls()
        assert len(calls) == 1
        recipient = calls[0].args[2]
        assert recipient.person_index == 1
        assert recipient.email == "lisa@example.de"
        # The fresh code must carry the NEW name, or it would be stale on arrival.
        assert recipient.name == "Lisa Meier-Bach"

    @pytest.mark.asyncio
    async def test_unchanged_address_resend_is_suppressed(self):
        _, reg = await self._setup_registration(
            group_member_emails=["lisa@example.de", None],
        )

        _, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_member_emails=["lisa@example.de", None]),
        )

        assert error is None
        assert self._companion_calls() == []

    @pytest.mark.asyncio
    async def test_corrected_address_resends(self):
        _, reg = await self._setup_registration(
            group_member_emails=["typo@example.de", None],
        )

        _, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_member_emails=["lisa@example.de", None]),
        )

        assert error is None
        assert len(self._companion_calls()) == 1

    @pytest.mark.asyncio
    async def test_members_only_patch_tombstoning_clears_that_address(self):
        """Regression: a members-only patch used to orphan the address.

        `model_copy` does not re-run validators, so the orphan was persisted —
        and the Registration validator then raised on every subsequent load,
        making the registration permanently unreadable. The service must
        re-align even when the client sends no addresses.
        """
        event, reg = await self._setup_registration(
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )

        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_members=["Lisa Meier", None]),
        )

        assert error is None
        assert updated.group_members == ["Lisa Meier", None]
        assert updated.group_member_emails == ["lisa@example.de", None]

        # The load that used to blow up.
        reloaded = await self.reg_service.get_registration(event.id, reg.id)
        assert reloaded is not None
        assert reloaded.group_member_emails == ["lisa@example.de", None]
        # And the removed companion is no longer a mail recipient.
        assert [r.person_index for r in companion_recipients(reloaded)] == [1]

    @pytest.mark.asyncio
    async def test_address_on_tombstoned_member_rejected_by_schema(self):
        """When the patch carries both arrays, the schema catches it outright."""
        with pytest.raises(ValidationError, match="was removed"):
            FestivalAttendancePatch(
                group_members=["Lisa Meier", None],
                group_member_emails=["lisa@example.de", "tim@example.de"],
            )

    @pytest.mark.asyncio
    async def test_address_on_tombstoned_member_rejected_by_service(self):
        """A patch sending addresses ALONE can only be checked in the service,
        which is the only place that knows the stored member list."""
        _, reg = await self._setup_registration()

        # Tombstone the second companion first.
        tombstoned, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_members=["Lisa Meier", None]),
        )
        assert error is None
        assert tombstoned.group_members == ["Lisa Meier", None]

        # Now try to park an address on the removed member, addresses only.
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(
                group_member_emails=["lisa@example.de", "tim@example.de"],
            ),
        )

        assert updated is None
        assert error is not None
        assert "removed" in error


class TestCompanionSendOnCancel(CompanionServiceBase):
    @pytest.mark.asyncio
    async def test_cancel_notifies_every_addressed_companion(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )
        self.mock_email_service.reset_mock()

        cancelled, error = await self.reg_service.cancel_registration(
            reg.id, reg.registration_token,
        )

        assert error is None
        assert cancelled.status == RegistrationStatus.CANCELLED
        self.mock_email_service.send_festival_cancellation.assert_awaited_once()
        call = self.mock_email_service.send_festival_companion_cancellations.await_args
        # Recipients must come from the PRE-cancel registration; reading them
        # off the cancelled one would silently send nothing.
        assert [r.email for r in call.kwargs["recipients"]] == [
            "lisa@example.de",
            "tim@example.de",
        ]

    @pytest.mark.asyncio
    async def test_cancel_without_addresses_passes_empty_list(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite, group_size=2, group_members=["Lisa Meier"],
        )
        self.mock_email_service.reset_mock()

        await self.reg_service.cancel_registration(reg.id, reg.registration_token)

        call = self.mock_email_service.send_festival_companion_cancellations.await_args
        assert call.kwargs["recipients"] == []


class TestAdminPatchIsMailSilent(CompanionServiceBase):
    @pytest.mark.asyncio
    async def test_admin_writing_an_address_sends_nothing(self):
        """D3: organizers correcting data must not fire mail at guests."""
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite, group_size=3, group_members=["Lisa Meier", "Tim Bach"],
        )
        self.mock_email_service.reset_mock()

        updated, error = await self.reg_service.admin_update_registration(
            event.id,
            reg.id,
            RegistrationAdminPatch(group_member_emails=["lisa@example.de", None]),
        )

        assert error is None
        assert updated.group_member_emails == ["lisa@example.de", None]
        assert self._companion_calls() == []

    @pytest.mark.asyncio
    async def test_single_event_patch_rejects_the_field(self):
        event = self._make_event(
            event_type=EventType.SINGLE,
            festival_slots=None,
            end_at=None,
            capacity=100,
        )
        reg = _registration(
            id=uuid4(), event_id=event.id, group_members=["Lisa Meier"], group_size=2,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

        updated, error = await self.reg_service.admin_update_registration(
            event.id,
            reg.id,
            RegistrationAdminPatch(group_member_emails=["lisa@example.de"]),
        )

        assert updated is None
        assert error == "not_festival_event"


class TestLegacyGroupMemberPathsRejectFestival(CompanionServiceBase):
    """Regression: the pre-020 group-member endpoints corrupted festival rows.

    `update_group_members` writes `group_members` without touching the
    index-aligned `group_member_emails`, and its `group_members` INCLUDES the
    contact person while festival's excludes them. On a festival group that
    produced either a wrong-person QR mailing (reorder) or an emails array
    longer than the members array — a row that then failed to load at all,
    500ing the guest's manage page, the gate lookup and the whole admin list.
    """

    async def _festival_reg(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, error = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )
        assert error is None
        return event, reg

    @pytest.mark.asyncio
    async def test_update_group_members_refuses_festival(self):
        event, reg = await self._festival_reg()

        updated, error = await self.reg_service.update_group_members(
            reg.id, reg.registration_token, ["Tim Bach"],
        )

        assert updated is None
        assert error == "Not available for festival registrations"

        # The row is untouched and still loads.
        reloaded = await self.reg_service.get_registration(event.id, reg.id)
        assert reloaded.group_members == ["Lisa Meier", "Tim Bach"]
        assert reloaded.group_member_emails == ["lisa@example.de", "tim@example.de"]

    @pytest.mark.asyncio
    async def test_reorder_via_legacy_path_cannot_swap_addresses(self):
        """The wrong-QR scenario: reordering names while addresses stay put."""
        event, reg = await self._festival_reg()

        updated, error = await self.reg_service.update_group_members(
            reg.id, reg.registration_token, ["Tim Bach", "Lisa Meier"],
        )

        assert updated is None
        assert error is not None
        reloaded = await self.reg_service.get_registration(event.id, reg.id)
        pairs = [(r.name, r.email) for r in companion_recipients(reloaded)]
        assert pairs == [
            ("Lisa Meier", "lisa@example.de"),
            ("Tim Bach", "tim@example.de"),
        ]

    @pytest.mark.asyncio
    async def test_single_event_registration_still_works(self):
        """The guard must not break the flow this endpoint actually serves."""
        event = self._make_event(
            event_type=EventType.SINGLE, festival_slots=None, end_at=None, capacity=100,
        )
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Anna Schmidt", "Lisa Meier"],
            group_size=2,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

        updated, error = await self.reg_service.update_group_members(
            reg.id, reg.registration_token, ["Anna Schmidt"],
        )

        assert error is None
        assert updated.group_members == ["Anna Schmidt"]
        assert updated.group_size == 1


# --------------------------------------------------------------- T007 endpoint


class TestPersonTicketEndpoint(CompanionServiceBase):
    async def _setup(self, **overrides):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", None],
            **overrides,
        )
        return event, reg

    async def _call(self, event, reg, person_index, token=None):
        from app.api.public.registrations import get_person_ticket

        with patch(
            "app.api.public.registrations.get_registration_service",
            return_value=self.reg_service,
        ), patch(
            "app.api.public.registrations.get_event_service",
            return_value=self.event_service,
        ):
            if token is None:
                stored = await self.reg_service.get_registration(event.id, reg.id)
                emails = stored.group_member_emails or []
                i = person_index - 1
                email = emails[i] if 0 <= i < len(emails) else None
                token = person_page_token(reg.registration_token, person_index, email or "")
            return await get_person_ticket(
                event_id=event.id,
                registration_id=reg.id,
                person_index=person_index,
                token=token,
            )

    @pytest.mark.asyncio
    async def test_valid_token_returns_a_verifying_ticket(self):
        event, reg = await self._setup()

        result = await self._call(event, reg, 1)

        assert result.name == "Lisa Meier"
        assert result.contact_name == "Anna Schmidt"
        assert result.slot_labels == ["Freitag", "Samstag"]
        assert result.cancelled is False

        stored = await self.event_service.get_event_by_id(event.id)
        payload = verify_ticket(stored.ticket_secret, result.ticket_code)
        assert payload is not None
        assert payload["p"] == 1
        assert payload["n"] == "Lisa Meier"

    @pytest.mark.asyncio
    async def test_response_leaks_no_contact_data(self):
        event, reg = await self._setup()

        result = await self._call(event, reg, 1)
        dumped = result.model_dump_json()

        assert "@" not in dumped.replace("festival@example.de", "")  # contact_hint is intended
        assert reg.registration_token not in dumped
        assert "Tim Bach" not in dumped  # no other member's name
        assert "0176" not in dumped  # no phone

    @pytest.mark.asyncio
    async def test_wrong_token_is_404(self):
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(
                event, reg, 1, token=person_page_token("other-token", 1, "lisa@example.de"),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_token_for_another_index_is_404(self):
        """A companion's token must not open a sibling's page."""
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(
                event,
                reg,
                2,
                token=person_page_token(reg.registration_token, 1, "lisa@example.de"),
            )
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("bad_token", ["", "garbage"])
    @pytest.mark.asyncio
    async def test_malformed_token_is_404(self, bad_token):
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 1, token=bad_token)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_index_zero_is_404(self):
        """The contact person uses the manage page, not this one."""
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 0)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_out_of_range_index_is_404(self):
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 9)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_tombstoned_member_is_404(self):
        event, reg = await self._setup()
        await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(
                group_members=["Lisa Meier", None], group_member_emails=["lisa@example.de", None],
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 2)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_page_self_heals_after_a_rename(self):
        """D2 rests on this: no resend on rename, because the page re-signs."""
        event, reg = await self._setup()
        await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_members=["Lisa Meier-Bach", "Tim Bach"]),
        )

        result = await self._call(event, reg, 1)

        assert result.name == "Lisa Meier-Bach"
        stored = await self.event_service.get_event_by_id(event.id)
        payload = verify_ticket(stored.ticket_secret, result.ticket_code)
        assert payload["n"] == "Lisa Meier-Bach"

    @pytest.mark.asyncio
    async def test_replacing_the_occupant_kills_the_old_link(self):
        """Regression: the token used to be an INDEX capability.

        `group_members` entries are individually rewritable (append-only only
        forbids shortening), so a contact can type over row 1 — Lisa out, Tim in.
        With an index-only token, Lisa's old link kept working and rendered Tim's
        name plus a gate-valid QR for Tim. Binding the token to the address
        means the replacement invalidates it.
        """
        event, reg = await self._setup()
        lisas_token = person_page_token(reg.registration_token, 1, "lisa@example.de")
        # Sanity: it works before the swap.
        assert (await self._call(event, reg, 1, token=lisas_token)).name == "Lisa Meier"

        await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(
                group_members=["Tim Bach", "Tim Bach"],
                group_member_emails=["tim@example.de", None],
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 1, token=lisas_token)
        assert exc.value.status_code == 404

        # ...and Tim's own token does work.
        assert (await self._call(event, reg, 1)).name == "Tim Bach"

    @pytest.mark.asyncio
    async def test_clearing_an_address_revokes_the_page(self):
        event, reg = await self._setup()
        lisas_token = person_page_token(reg.registration_token, 1, "lisa@example.de")

        await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(group_member_emails=[None, None]),
        )

        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 1, token=lisas_token)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_ascii_token_is_404_not_500(self):
        """A 500 here would have leaked whether the registration exists."""
        event, reg = await self._setup()
        with pytest.raises(HTTPException) as exc:
            await self._call(event, reg, 1, token="ü" * 22)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancelled_registration_renders_a_readable_state(self):
        event, reg = await self._setup()
        await self.reg_service.cancel_registration(reg.id, reg.registration_token)

        result = await self._call(event, reg, 1)

        assert result.cancelled is True
        assert result.ticket_code == ""


# ---------------------------------------------------------------- T008 Rundmail


class TestRundmailFanout(CompanionServiceBase):
    async def _setup(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )
        return event, reg

    async def _send(self, event, reg, **overrides):
        from app.api.admin.events import send_custom_message
        from app.models import CustomMessageRequest

        payload = dict(
            registration_ids=[reg.id], subject="Infos", body="Moin!", include_links=True,
        )
        payload.update(overrides)

        user = MagicMock()
        user.email = "orga@example.de"
        user.org_id = event.org_id

        with patch(
            "app.api.admin.events.get_registration_service", return_value=self.reg_service,
        ), patch(
            "app.api.admin.events.get_event_service", return_value=self.event_service,
        ), patch(
            "app.api.admin.events.get_email_service", return_value=self.mock_email_service,
        ), patch(
            "app.api.admin.events._get_org_id", return_value=event.org_id,
        ):
            self.mock_email_service.send_custom_message.return_value = True
            return await send_custom_message(
                event_id=event.id,
                message_data=CustomMessageRequest(**payload),
                user=user,
            )

    @pytest.mark.asyncio
    async def test_companions_included_by_default(self):
        event, reg = await self._setup()

        result = await self._send(event, reg)

        assert result.total == 3  # contact + 2 companions
        assert result.sent == 3
        companions = [
            call.kwargs.get("companion")
            for call in self.mock_email_service.send_custom_message.await_args_list
        ]
        assert companions[0] is None  # the contact
        assert [c.email for c in companions[1:]] == ["lisa@example.de", "tim@example.de"]

    @pytest.mark.asyncio
    async def test_opt_out_sends_only_the_contact(self):
        event, reg = await self._setup()

        result = await self._send(event, reg, include_companions=False)

        assert result.total == 1
        assert result.sent == 1

    @pytest.mark.asyncio
    async def test_failing_companion_counts_as_failed_without_aborting(self):
        event, reg = await self._setup()
        self.mock_email_service.send_custom_message.side_effect = [
            True, RuntimeError("boom"), True,
        ]

        result = await self._send(event, reg)

        assert result.total == 3
        assert result.sent == 2
        assert result.failed == 1


class TestRundmailCompanionLink:
    """The companion's copy must carry the ticket link, not the manage link."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.email_service = EmailService()
        self.email_service._messages_table = MagicMock()
        yield

    def _event(self) -> Event:
        return Event(
            name="Betriebsfeier",
            org_id=uuid4(),
            event_type=EventType.FESTIVAL,
            start_at=NOW + timedelta(days=10),
            end_at=NOW + timedelta(days=12),
            registration_deadline=NOW + timedelta(days=12),
            festival_slots=_slots(),
        )

    @pytest.mark.asyncio
    async def test_companion_copy_uses_ticket_link(self):
        event = self._event()
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
        )

        await self.email_service.send_custom_message(
            event, reg, "Infos", "Moin!",
            include_links=True,
            companion=CompanionRecipient(1, "Lisa Meier", "lisa@example.de"),
        )

        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["recipient_email"] == "lisa@example.de"
        assert "/ticket/" in item["body"]
        assert "/registration/" not in item["body"]
        assert "/registration/" not in item["body_html"]

    @pytest.mark.asyncio
    async def test_contact_copy_still_uses_manage_link(self):
        event = self._event()
        reg = _registration(id=uuid4(), event_id=event.id)

        await self.email_service.send_custom_message(
            event, reg, "Infos", "Moin!", include_links=True,
        )

        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert "/registration/" in item["body"]
        assert "/ticket/" not in item["body"]


# ------------------------------------------------------- privacy regressions


class TestCompanionPrivacyBoundaries(CompanionServiceBase):
    @pytest.mark.asyncio
    async def test_guestlist_page_never_exposes_an_address(self):
        """GuestlistPage promises "keine Kontaktdaten" in its own footer."""
        from app.api.public.invites import get_invite_guestlist

        event = self._make_event()
        invite = await self._make_invite(event)
        await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )

        with patch(
            "app.api.public.invites.get_invite_service", return_value=self.invite_service,
        ), patch(
            "app.api.public.invites.get_event_service", return_value=self.event_service,
        ), patch(
            "app.api.public.invites.get_registration_service", return_value=self.reg_service,
        ):
            response = await get_invite_guestlist(invite.token)

        assert "@" not in response.model_dump_json()

    @pytest.mark.asyncio
    async def test_gate_csv_rows_carry_no_address(self):
        """The gate list is paper carried around a festival site."""
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, _ = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )

        rows = build_gate_rows([reg], event)

        assert len(rows) == 3
        for row in rows:
            assert not any("@" in str(value) for value in row.values())
