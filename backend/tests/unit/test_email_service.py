"""Tests for email service (T3.6)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import (
    Event,
    EventStatus,
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
    _build_cancellation_url,
    _build_confirmation_url,
    _format_date,
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
        assert "storniert" in subject.lower()
        assert "Max Müller" in text

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
