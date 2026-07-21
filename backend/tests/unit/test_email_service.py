"""Tests for email service (T3.6)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import (
    Event,
    EventStatus,
    EventType,
    FestivalSlot,
    Invite,
    Message,
    MessageDirection,
    MessageStatus,
    MessageType,
    Registration,
    RegistrationStatus,
)
from app.services.email_service import (
    EmailContext,
    EmailService,
    EmailTemplates,
    _build_accommodation_label,
    _build_cancellation_url,
    _build_confirmation_url,
    _build_invite_url,
    _build_slot_labels,
    _format_date,
    _format_date_range,
    _message_to_item,
)


class TestEmailTemplates:
    """Templates produce valid subject/body/html."""

    @pytest.fixture
    def ctx(self):
        return EmailContext(
            event_name="Sommerfest 2025",
            event_date="Samstag, 15. Juni 2025 um 18:00",
            event_location="Stadtpark",
            attendee_name="Max Müller",
            attendee_email="max@example.com",
            group_size=2,
            registration_status="CONFIRMED",
            waitlist_position=None,
            cancellation_url="https://example.com/cancel/123?token=abc",
            confirmation_yes_url="https://example.com/confirm/123?token=abc&response=yes",
            confirmation_no_url="https://example.com/confirm/123?token=abc&response=no",
            management_url="https://example.com/registration/123?token=abc",
        )

    def test_registration_confirmed(self, ctx):
        subject, text, html = EmailTemplates.registration_confirmed(ctx)
        assert "Sommerfest 2025" in subject
        assert "Max Müller" in text
        assert "Stadtpark" in text
        assert "verwalten" in text.lower()
        assert "<html>" in html

    def test_registration_waitlisted(self, ctx):
        subject, text, html = EmailTemplates.registration_waitlisted(ctx)
        assert "Warteliste" in subject
        assert "#" not in subject  # No position in subject
        assert "Max Müller" in text

    def test_registration_cancelled(self, ctx):
        subject, text, html = EmailTemplates.registration_cancelled(ctx)
        assert "info" in subject.lower()
        assert "Max Müller" in text

    def test_registration_cancelled_with_custom_message(self, ctx):
        ctx_with_msg = ctx.model_copy(update={"custom_message": "Leider kein Platz mehr."})
        subject, text, html = EmailTemplates.registration_cancelled(ctx_with_msg)
        assert "Leider kein Platz mehr." in text
        assert "Leider kein Platz mehr." in html

    def test_promoted_from_waitlist(self, ctx):
        subject, text, html = EmailTemplates.promoted_from_waitlist(ctx)
        assert "platz frei" in subject.lower()

    def test_event_cancelled(self, ctx):
        subject, text, html = EmailTemplates.event_cancelled(ctx)
        assert "abgesagt" in subject.lower()

    def test_confirmation_request(self, ctx):
        subject, text, html = EmailTemplates.confirmation_request(ctx, 3)
        assert "bald" in subject.lower()
        assert ctx.management_url in text

    def test_confirmation_request_tomorrow(self, ctx):
        subject, text, html = EmailTemplates.confirmation_request(ctx, 1)
        assert "morgen" in subject.lower()

    def test_lottery_winner(self, ctx):
        subject, text, html = EmailTemplates.lottery_winner(ctx)
        assert "bestätigen" in subject.lower()
        assert "ausgelost" in text.lower()

    def test_lottery_waitlisted(self, ctx):
        subject, text, html = EmailTemplates.lottery_waitlisted(ctx)
        assert "Warteliste" in subject
        # No position in subject or body
        assert "#" not in subject

    def test_lottery_rejected(self, ctx):
        subject, text, html = EmailTemplates.lottery_rejected(ctx)
        assert "Leider" in subject

    def test_attendance_response_yes(self, ctx):
        """T13.8: Attendance response confirmation — YES."""
        subject, text, html = EmailTemplates.attendance_response_confirmation(ctx, participating=True)
        assert "Rückmeldung" in subject
        assert "Teilnahme" in html
        assert "Max Müller" in text

    def test_attendance_response_no(self, ctx):
        """T13.8: Attendance response confirmation — NO."""
        subject, text, html = EmailTemplates.attendance_response_confirmation(ctx, participating=False)
        assert "Rückmeldung" in subject
        assert "Absage" in html
        assert "Max Müller" in text

    def test_registration_confirmed_includes_deadline(self, ctx):
        """T13.9: Registration confirmation email includes deadline."""
        ctx.registration_deadline = "Freitag, 20. März 2026 um 18:00"
        subject, text, html = EmailTemplates.registration_confirmed(ctx)
        assert "Anmeldeschluss" in text
        assert "20. März 2026" in text
        assert "Anmeldeschluss" in html


class TestFormatDate:
    """German date formatting."""

    def test_format_date_german(self):
        dt = datetime(2025, 6, 15, 18, 0, tzinfo=timezone.utc)
        result = _format_date(dt)
        assert "Sonntag" in result
        assert "Juni" in result
        assert "18:00" in result

    def test_format_date_monday(self):
        dt = datetime(2025, 6, 16, 9, 30, tzinfo=timezone.utc)
        result = _format_date(dt)
        assert "Montag" in result

    def test_format_date_range_same_month(self):
        start = datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)
        assert _format_date_range(start, end) == "vom 14. bis 16. August 2026"

    def test_format_date_range_cross_month(self):
        start = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)
        assert _format_date_range(start, end) == "vom 30. August bis 1. September 2026"

    def test_format_date_range_single_day(self):
        start = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)
        assert _format_date_range(start, end) == "am Freitag, 14. August 2026"
        assert _format_date_range(start, None) == "am Freitag, 14. August 2026"


class TestBuildUrls:
    """URL builders use base_url from settings."""

    @patch("app.services.email_service.get_settings")
    def test_cancellation_url(self, mock_settings):
        mock_settings.return_value = MagicMock(base_url="https://funke.app")
        reg_id = uuid4()
        url = _build_cancellation_url(reg_id, "mytoken")
        assert f"/cancel/{reg_id}?token=mytoken" in url
        assert url.startswith("https://funke.app")

    @patch("app.services.email_service.get_settings")
    def test_confirmation_url(self, mock_settings):
        mock_settings.return_value = MagicMock(base_url="https://funke.app")
        reg_id = uuid4()
        url = _build_confirmation_url(reg_id, "mytoken", "yes")
        assert f"/confirm/{reg_id}" in url
        assert "response=yes" in url

    @patch("app.services.email_service.get_settings")
    def test_invite_url(self, mock_settings):
        mock_settings.return_value = MagicMock(base_url="https://funke.app")
        url = _build_invite_url("sometoken")
        assert url == "https://funke.app/invite/sometoken"


class TestMessageToItem:
    """DynamoDB serialization."""

    def test_message_to_item_basic(self):
        event_id = uuid4()
        reg_id = uuid4()
        msg = Message(
            event_id=event_id,
            registration_id=reg_id,
            type=MessageType.REGISTRATION_CONFIRMATION,
            direction=MessageDirection.OUTBOUND,
            subject="Test",
            body="Test body",
            status=MessageStatus.SENT,
            recipient_email="test@example.com",
            sent_at=datetime.now(timezone.utc),
        )
        item = _message_to_item(msg)

        assert item["pk"] == f"EVENT#{event_id}"
        assert item["sk"].startswith("MSG#")
        assert item["recipient_email"] == "test@example.com"
        assert item["direction"] == "outbound"
        assert item["status"] == "sent"

    def test_message_to_item_no_optional_fields(self):
        event_id = uuid4()
        msg = Message(
            event_id=event_id,
            type=MessageType.CUSTOM,
            direction=MessageDirection.OUTBOUND,
            subject="Test",
            body="Body",
            status=MessageStatus.QUEUED,
        )
        item = _message_to_item(msg)

        assert "registration_id" not in item
        assert "sent_at" not in item
        assert "recipient_email" not in item


class TestSendEmail:
    """_send_email now queues messages for the queue worker to deliver."""

    @pytest.fixture
    def email_service(self):
        service = EmailService()
        service._messages_table = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_send_email_queues_message(self, email_service):
        """_send_email stores message as QUEUED in DynamoDB."""
        result = await email_service._send_email(
            event_id=uuid4(),
            registration_id=uuid4(),
            to="test@example.com",
            subject="Test",
            text_body="Hello",
            html_body="<p>Hello</p>",
            message_type=MessageType.REGISTRATION_CONFIRMATION,
        )

        assert result is True
        email_service._messages_table.put_item.assert_called_once()

        stored_item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert stored_item["status"] == "queued"
        assert stored_item["recipient_email"] == "test@example.com"
        assert stored_item["subject"] == "Test"
        assert stored_item["body"] == "Hello"
        assert stored_item["body_html"] == "<p>Hello</p>"

    @pytest.mark.asyncio
    async def test_send_email_queue_failure(self):
        """If DynamoDB write fails, returns False."""
        service = EmailService()
        service._messages_table = MagicMock()
        service._messages_table.put_item.side_effect = Exception("DynamoDB unavailable")

        result = await service._send_email(
            event_id=uuid4(),
            registration_id=uuid4(),
            to="test@example.com",
            subject="Test",
            text_body="Hello",
            html_body="<p>Hello</p>",
            message_type=MessageType.REGISTRATION_CONFIRMATION,
        )

        assert result is False


class TestAccommodationLabel:
    """Ä17/Ä21 request semantics for {Schlafplatz}: _build_accommodation_label(
    tent_count, camper_count, overnight_approved)."""

    def test_none_is_none(self):
        """No overnight wish -> None, so the Schlafplatz line is omitted entirely."""
        assert _build_accommodation_label(None, None, False) is None
        assert _build_accommodation_label(0, 0, True) is None

    def test_tent_not_approved(self):
        assert _build_accommodation_label(1, None, False) == "1 Zelt — angefragt"

    def test_tent_approved(self):
        assert _build_accommodation_label(1, None, True) == "1 Zelt — zugesagt"

    def test_camper_not_approved(self):
        assert _build_accommodation_label(None, 1, False) == "1 Camper — angefragt"

    def test_camper_approved(self):
        assert _build_accommodation_label(None, 1, True) == "1 Camper — zugesagt"

    def test_multiple_tents_pluralize(self):
        assert _build_accommodation_label(3, None, False) == "3 Zelte — angefragt"

    def test_both_types_shown(self):
        assert _build_accommodation_label(2, 1, True) == "2 Zelte, 1 Camper — zugesagt"


class TestSlotLabels:
    """{Zeitfenster}: comma-joined chosen slot labels, festival order."""

    def _slots(self):
        from datetime import date

        return [
            FestivalSlot(key="fr-abend", label="Freitag", date=date(2026, 8, 14), is_night=True),
            FestivalSlot(key="sa-tag", label="Samstag", date=date(2026, 8, 15)),
            FestivalSlot(key="so-tag", label="Sonntag", date=date(2026, 8, 16)),
        ]

    def _event(self, **overrides):
        from datetime import UTC, datetime, timedelta

        defaults = {
            "name": "Schaluppenfest",
            "org_id": uuid4(),
            "event_type": EventType.FESTIVAL,
            "start_at": datetime.now(UTC) + timedelta(days=10),
            "end_at": datetime.now(UTC) + timedelta(days=12),
            "registration_deadline": datetime.now(UTC) + timedelta(days=12),
            "festival_slots": self._slots(),
        }
        defaults.update(overrides)
        return Event(**defaults)

    def test_comma_joined_in_festival_order(self):
        event = self._event()
        result = _build_slot_labels(event, ["so-tag", "fr-abend"])
        assert result == "Freitag, Sonntag"

    def test_empty_when_no_slots(self):
        event = self._event()
        assert _build_slot_labels(event, None) == ""
        assert _build_slot_labels(event, []) == ""

    def test_never_a_range(self):
        event = self._event()
        result = _build_slot_labels(event, ["fr-abend", "sa-tag"])
        assert result == "Freitag, Samstag"
        assert "-" not in result.replace("—", "")


class TestFestivalEmailTemplates:
    """F1-F4 template acceptance (spec 019 §Emails)."""

    @pytest.fixture
    def festival_ctx(self):
        return EmailContext(
            event_name="Schaluppenfest",
            event_date="Freitag, 14. August 2026 um 18:00",
            event_location="Werftgelände",
            registration_deadline="Sonntag, 16. August 2026 um 23:59",
            attendee_name="Anna Meier",
            attendee_email="anna@example.com",
            group_size=2,
            registration_status="PARTICIPATING",
            management_url="https://funke.app/registration/123?token=abc",
            invite_url="https://funke.app/invite/xyz",
            slot_labels="Freitag, Samstag",
            accommodation_label="Zelt — angefragt",
            contact_hint="crew@schaluppe.de",
            mitmach_hint=None,
        )

    # --- F1 ---

    def test_f1_personal_variant(self, festival_ctx):
        subject, text, html = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name="Anna", include_personal_sentence=True,
        )
        assert subject == "Du bist eingeladen: Schaluppenfest"
        assert "Moin Anna" in text
        assert "persönlich für dich" in text
        assert festival_ctx.invite_url in text
        assert festival_ctx.contact_hint in text

    def test_f1_generic_variant(self, festival_ctx):
        subject, text, html = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name=None, include_personal_sentence=False,
        )
        assert "Moin!" in text
        assert "persönlich für dich" not in text
        assert festival_ctx.invite_url in text
        assert festival_ctx.contact_hint in text

    def test_f1_params_are_independent(self, festival_ctx):
        """greeting_name and include_personal_sentence vary independently."""
        _, text, _ = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name="Ben", include_personal_sentence=False,
        )
        assert "Moin Ben" in text
        assert "persönlich für dich" not in text

        _, text, _ = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name=None, include_personal_sentence=True,
        )
        assert "Moin!" in text
        assert "persönlich für dich" in text

    def test_f1_renders_event_facts(self, festival_ctx):
        """F1 is built from event properties — period, name, location, deadline, hint."""
        ctx = festival_ctx.model_copy(update={
            "event_period": "vom 21. bis 23. August 2026",
            "mitmach_hint": "Schichtplan: https://example.com/schichten",
            "event_description": "Drei Tage Werftfest mit Musik.",
        })
        _, text, html = EmailTemplates.festival_invitation(
            ctx, greeting_name="Anna", include_personal_sentence=True,
        )
        for body in (text, html):
            assert "vom 21. bis 23. August 2026" in body
            assert "Schaluppenfest" in body
            assert "Werftgelände" in body
            assert ctx.registration_deadline in body
            assert "Schichtplan: https://example.com/schichten" in body
            assert "Drei Tage Werftfest mit Musik." in body
        assert "14. bis 16. August" not in text

    def test_f1_falls_back_to_event_date_without_period(self, festival_ctx):
        _, text, _ = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name="Anna", include_personal_sentence=True,
        )
        assert festival_ctx.event_date in text

    def test_f1_omits_unset_facts(self, festival_ctx):
        ctx = festival_ctx.model_copy(update={
            "event_location": None,
            "registration_deadline": None,
            "mitmach_hint": None,
            "contact_hint": None,
            "event_description": None,
        })
        _, text, _ = EmailTemplates.festival_invitation(
            ctx, greeting_name="Anna", include_personal_sentence=True,
        )
        assert "Wo:" not in text
        assert "Anmelden bis:" not in text
        assert "Bei Fragen:" not in text
        assert "None" not in text

    def test_f1_personal_companion_sentence(self, festival_ctx):
        """Personal invites with group room spell out the companion allowance."""
        _, text, _ = EmailTemplates.festival_invitation(
            festival_ctx, greeting_name="Anna", include_personal_sentence=True,
        )
        assert "Du kannst eine Begleitung mitbringen." in text

        ctx3 = festival_ctx.model_copy(update={"group_size": 3})
        _, text, _ = EmailTemplates.festival_invitation(
            ctx3, greeting_name="Anna", include_personal_sentence=True,
        )
        assert "Du kannst bis zu 2 Begleitungen mitbringen." in text

    def test_f1_contingent_variant(self, festival_ctx):
        """Contingent invites (max_uses>1) get numbers + guestlist link."""
        _, text, html = EmailTemplates.festival_invitation(
            festival_ctx,
            greeting_name="Micha",
            include_personal_sentence=False,
            max_uses=10,
            guestlist_url="https://funke.app/invite/xyz/liste",
        )
        assert "Moin Micha" in text
        assert "bis zu 10 Anmeldungen" in text
        assert "bis zu 2 Personen" in text
        assert "https://funke.app/invite/xyz/liste" in text
        assert "https://funke.app/invite/xyz/liste" in html
        assert "persönlich für dich" not in text
        assert "Begleitung" not in text

    def test_f1_contingent_single_person_per_registration(self, festival_ctx):
        ctx1 = festival_ctx.model_copy(update={"group_size": 1})
        _, text, _ = EmailTemplates.festival_invitation(
            ctx1,
            greeting_name="Micha",
            include_personal_sentence=False,
            max_uses=5,
        )
        assert "eine Person pro Anmeldung" in text
        assert "Wer sich über deinen Link" not in text

    # --- F2 ---

    def test_f2_without_qr_paragraph(self, festival_ctx):
        subject, text, html = EmailTemplates.festival_registration_confirmed(
            festival_ctx, include_qr_paragraph=False,
        )
        assert subject == "Deine Anmeldung: Schaluppenfest"
        assert "Eintritts-Codes" not in text
        assert festival_ctx.slot_labels in text
        assert festival_ctx.accommodation_label in text
        assert "jederzeit" in text
        assert "Anmeldeschluss" not in text

    def test_f2_with_qr_paragraph(self, festival_ctx):
        _, text, html = EmailTemplates.festival_registration_confirmed(
            festival_ctx, include_qr_paragraph=True,
        )
        assert "Eintritts-Codes" in text
        assert "Eintritts-Codes" in html

    def test_f2_mitmach_hint_own_paragraph(self, festival_ctx):
        ctx = festival_ctx.model_copy(
            update={"mitmach_hint": "Schichtplan: https://example.com/schichten — Aline koordiniert."},
        )
        _, text, _ = EmailTemplates.festival_registration_confirmed(ctx)
        assert ctx.mitmach_hint in text
        assert f"\n\n{ctx.mitmach_hint}" in text

    def test_f2_no_mitmach_hint_no_empty_paragraph(self, festival_ctx):
        _, text, _ = EmailTemplates.festival_registration_confirmed(festival_ctx)
        assert "\n\n\n" not in text

    # --- F3 ---

    def test_f3_subject_and_body(self, festival_ctx):
        subject, text, html = EmailTemplates.festival_updated(festival_ctx)
        assert subject == "Deine Änderung: Schaluppenfest"
        assert festival_ctx.slot_labels in text
        assert festival_ctx.accommodation_label in text
        assert festival_ctx.management_url in text

    @pytest.mark.parametrize(
        ("tent_count", "camper_count", "approved", "expected"),
        [
            (1, None, False, "1 Zelt — angefragt"),
            (1, None, True, "1 Zelt — zugesagt"),
            (None, 1, False, "1 Camper — angefragt"),
            (None, 1, True, "1 Camper — zugesagt"),
            (2, 1, True, "2 Zelte, 1 Camper — zugesagt"),
        ],
    )
    def test_schlafplatz_states_in_f2_and_f3(self, festival_ctx, tent_count, camper_count, approved, expected):
        label = _build_accommodation_label(tent_count, camper_count, approved)
        assert label == expected
        ctx = festival_ctx.model_copy(update={"accommodation_label": label})

        _, f2_text, _ = EmailTemplates.festival_registration_confirmed(ctx)
        assert expected in f2_text

        _, f3_text, _ = EmailTemplates.festival_updated(ctx)
        assert expected in f3_text

    def test_schlafplatz_line_absent_when_no_accommodation(self, festival_ctx):
        """No overnight wish -> the "- Schlafplatz: ..." line is omitted
        entirely (not rendered as "Nein")."""
        label = _build_accommodation_label(None, None, False)
        assert label is None
        ctx = festival_ctx.model_copy(update={"accommodation_label": label})

        _, f2_text, f2_html = EmailTemplates.festival_registration_confirmed(ctx)
        assert "Schlafplatz" not in f2_text
        assert "Schlafplatz" not in f2_html

        _, f3_text, f3_html = EmailTemplates.festival_updated(ctx)
        assert "Schlafplatz" not in f3_text
        assert "Schlafplatz" not in f3_html

    # --- F4 ---

    def test_f4_no_fisch_wording(self, festival_ctx):
        subject, text, html = EmailTemplates.festival_cancelled(festival_ctx)
        assert subject == "Deine Absage: Schaluppenfest"
        assert "Fisch" not in text
        assert "Fisch" not in html
        assert festival_ctx.contact_hint in text


class TestFestivalSendMethods:
    """T107 send methods queue Messages with the new festival message_types."""

    @pytest.fixture
    def email_service(self):
        service = EmailService()
        service._messages_table = MagicMock()
        return service

    def _slots(self):
        from datetime import date

        return [
            FestivalSlot(key="fr-abend", label="Freitag", date=date(2026, 8, 14), is_night=True),
            FestivalSlot(key="sa-tag", label="Samstag", date=date(2026, 8, 15)),
        ]

    def _event(self, **overrides):
        from datetime import UTC, datetime, timedelta

        defaults = {
            "name": "Schaluppenfest",
            "org_id": uuid4(),
            "event_type": EventType.FESTIVAL,
            "start_at": datetime.now(UTC) + timedelta(days=10),
            "end_at": datetime.now(UTC) + timedelta(days=12),
            "registration_deadline": datetime.now(UTC) + timedelta(days=12),
            "festival_slots": self._slots(),
            "contact_hint": "crew@schaluppe.de",
            "participation_hint": "Schichtplan: https://example.com/schichten",
        }
        defaults.update(overrides)
        return Event(**defaults)

    def _registration(self, **overrides):
        defaults = {
            "event_id": uuid4(),
            "name": "Anna Meier",
            "email": "anna@example.com",
            "phone": "0170123456",
            "group_size": 1,
            "registration_token": "regtoken",
            "status": RegistrationStatus.PARTICIPATING,
            "attendance_slots": ["fr-abend", "sa-tag"],
            "tent_count": 1,
        }
        defaults.update(overrides)
        return Registration(**defaults)

    def _invite(self, **overrides):
        defaults = {
            "event_id": uuid4(),
            "org_id": uuid4(),
            "token": "invitetoken",
            "label": "Anna Meier",
            "tier": "werft",
            "email": "anna@example.com",
        }
        defaults.update(overrides)
        return Invite(**defaults)

    @pytest.mark.asyncio
    async def test_send_festival_invitation_queues_message(self, email_service):
        event = self._event()
        invite = self._invite()

        result = await email_service.send_festival_invitation(event, invite)

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["status"] == "queued"
        assert item["type"] == MessageType.FESTIVAL_INVITATION.value

    @pytest.mark.asyncio
    async def test_send_festival_invitation_contingent_content(self, email_service):
        """Contingent invites greet by label and include numbers + guestlist URL."""
        event = self._event()
        invite = self._invite(label="Micha", max_uses=10, max_group_size=2)

        result = await email_service.send_festival_invitation(event, invite)

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert "Moin Micha" in item["body"]
        assert "bis zu 10 Anmeldungen" in item["body"]
        assert "/invite/invitetoken/liste" in item["body"]
        assert "persönlich für dich" not in item["body"]

    @pytest.mark.asyncio
    async def test_send_festival_invitation_without_email_returns_false(self, email_service):
        event = self._event()
        invite = self._invite(email=None)

        result = await email_service.send_festival_invitation(event, invite)

        assert result is False
        email_service._messages_table.put_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_invitation_gets_list_unsubscribe(self, email_service, monkeypatch):
        """Bulk-style mail (FESTIVAL_INVITATION) auto-attaches List-Unsubscribe."""
        import app.services.email_service as es
        from app.services.email_client import EmailSettings

        monkeypatch.setattr(
            es, "get_email_settings",
            lambda: EmailSettings(smtp_sender_email="funke@mobilemachenschaften.de"),
        )
        result = await email_service.send_festival_invitation(self._event(), self._invite())

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["list_unsubscribe"] == "<mailto:funke@mobilemachenschaften.de?subject=Abmelden>"

    @pytest.mark.asyncio
    async def test_transactional_confirmation_has_no_list_unsubscribe(
        self, email_service, monkeypatch,
    ):
        """Transactional mail (FESTIVAL_CONFIRMATION) must NOT carry List-Unsubscribe."""
        import app.services.email_service as es
        from app.services.email_client import EmailSettings

        monkeypatch.setattr(
            es, "get_email_settings",
            lambda: EmailSettings(smtp_sender_email="funke@mobilemachenschaften.de"),
        )
        result = await email_service.send_festival_confirmation(self._event(), self._registration())

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert "list_unsubscribe" not in item

    @pytest.mark.asyncio
    async def test_send_festival_confirmation_queues_message(self, email_service):
        event = self._event()
        registration = self._registration()

        result = await email_service.send_festival_confirmation(event, registration)

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["status"] == "queued"
        assert item["type"] == MessageType.FESTIVAL_CONFIRMATION.value
        # T308: manage-page QRs are live, so F2 now renders WITH the
        # entry-codes paragraph (include_qr_paragraph=True at the call site).
        assert "Eintritts-Codes" in item["body"]
        assert "Eintritts-Codes" in item["body_html"]

    @pytest.mark.asyncio
    async def test_send_festival_update_confirmation_queues_message(self, email_service):
        event = self._event()
        registration = self._registration()

        result = await email_service.send_festival_update_confirmation(event, registration)

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["status"] == "queued"
        assert item["type"] == MessageType.FESTIVAL_UPDATE.value

    @pytest.mark.asyncio
    async def test_send_festival_cancellation_queues_message(self, email_service):
        event = self._event()
        registration = self._registration(status=RegistrationStatus.CANCELLED)

        result = await email_service.send_festival_cancellation(event, registration)

        assert result is True
        item = email_service._messages_table.put_item.call_args[1]["Item"]
        assert item["status"] == "queued"
        assert item["type"] == MessageType.FESTIVAL_CANCELLATION.value


class TestFestivalConfirmationQrEmbedding:
    """T312: F2 embeds one QR ticket image per person, using real gate
    credentials from a mocked events table (mirrors the manage-page's
    ensure_gate_credentials call)."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        from app.services.event_service import EventService

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

    def _event(self, **overrides):
        from datetime import UTC, date, timedelta

        defaults = {
            "name": "Schaluppenfest",
            "org_id": uuid4(),
            "event_type": EventType.FESTIVAL,
            "start_at": datetime.now(UTC) + timedelta(days=10),
            "end_at": datetime.now(UTC) + timedelta(days=12),
            "registration_deadline": datetime.now(UTC) + timedelta(days=12),
            "festival_slots": [FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14))],
        }
        defaults.update(overrides)
        return Event(**defaults)

    async def _store_event(self, event):
        from app.services.event_service import _event_to_item

        self.event_service._table.put_item(Item=_event_to_item(event))

    def _registration(self, **overrides):
        defaults = {
            "event_id": uuid4(),
            "name": "Anna Meier",
            "email": "anna@example.com",
            "phone": "0170123456",
            "group_size": 1,
            "registration_token": "regtoken",
            "status": RegistrationStatus.PARTICIPATING,
            "attendance_slots": ["fr"],
        }
        defaults.update(overrides)
        return Registration(**defaults)

    @pytest.mark.asyncio
    async def test_confirmation_embeds_one_qr_per_person(self):
        event = self._event()
        await self._store_event(event)
        registration = self._registration(
            id=uuid4(), event_id=event.id, group_members=["Bob Fisch"], group_size=2,
        )

        result = await self.email_service.send_festival_confirmation(event, registration)

        assert result is True
        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert "inline_images" in item
        assert {img["content_id"] for img in item["inline_images"]} == {"qr-0", "qr-1"}
        for img in item["inline_images"]:
            assert img["content_type"] == "image/png"
            assert img["content_b64"]  # non-empty base64 payload
        assert "cid:qr-0" in item["body_html"]
        assert "cid:qr-1" in item["body_html"]

    @pytest.mark.asyncio
    async def test_confirmation_without_event_stored_falls_back_gracefully(self):
        """Event lookup fails (never stored) — email still queues, just without QR images."""
        event = self._event()  # not stored
        registration = self._registration(id=uuid4(), event_id=event.id)

        result = await self.email_service.send_festival_confirmation(event, registration)

        assert result is True
        item = self.email_service._messages_table.put_item.call_args[1]["Item"]
        assert "inline_images" not in item
        assert "cid:qr-" not in item["body_html"]
