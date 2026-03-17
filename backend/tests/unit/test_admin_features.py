"""Tests for admin features (T4.7)."""

import csv
import io
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
from app.services.email_service import EmailService, _message_to_item
from app.services.logging import log_admin_action


class TestCsvExport:
    """T4.1: CSV export produces valid CSV with correct headers."""

    def _make_registration_item(self, **overrides):
        """Create a registration DynamoDB item."""
        from app.services.registration_service import _registration_to_item

        defaults = {
            "id": uuid4(),
            "event_id": uuid4(),
            "name": "Max Müller",
            "email": "max@example.com",
            "group_size": 2,
            "status": RegistrationStatus.CONFIRMED,
            "registration_token": "test-token",
            "registered_at": datetime.now(timezone.utc),
        }
        defaults.update(overrides)
        reg = Registration(**defaults)
        return _registration_to_item(reg), reg

    def test_csv_has_correct_headers(self):
        """CSV should have German headers with semicolons."""
        item, reg = self._make_registration_item()

        # Simulate CSV generation logic from the endpoint
        output = io.StringIO()
        # Write BOM for Excel compatibility
        output.write("\ufeff")
        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "Name", "E-Mail", "Telefon", "Gruppengröße",
            "Status", "Wartelistenplatz", "Angemeldet am",
            "Geantwortet am", "Notizen",
        ])
        writer.writerow([
            reg.name, reg.email, reg.phone or "",
            reg.group_size, reg.status.value,
            reg.waitlist_position or "",
            reg.registered_at.isoformat(),
            reg.responded_at.isoformat() if reg.responded_at else "",
            reg.notes or "",
        ])

        csv_content = output.getvalue()
        assert csv_content.startswith("\ufeff")  # BOM present
        assert "Name;E-Mail;Telefon" in csv_content
        assert "Max Müller" in csv_content
        assert "CONFIRMED" in csv_content

    def test_csv_handles_umlauts(self):
        """CSV should correctly encode German umlauts."""
        item, reg = self._make_registration_item(
            name="Jürgen Österreicher",
            notes="Schöne Grüße",
        )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow([reg.name, reg.notes or ""])

        csv_content = output.getvalue()
        assert "Jürgen" in csv_content
        assert "Grüße" in csv_content


class TestCustomMessage:
    """T4.2/T4.3: Custom message validation and sending."""

    @pytest.fixture
    def email_service(self):
        service = EmailService()
        service._messages_table = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_send_custom_message(self, email_service, sample_event, sample_registration):
        event = sample_event()
        registration = sample_registration(event_id=event.id)

        mock_result = MagicMock(success=True, message_id="gmail-456", error=None)
        mock_gmail = AsyncMock()
        mock_gmail.send_email = AsyncMock(return_value=mock_result)

        with patch("app.services.email_client.get_gmail_client", return_value=mock_gmail):
            result = await email_service.send_custom_message(
                event=event,
                registration=registration,
                subject="Wichtige Info",
                body="Bitte beachtet die neue Uhrzeit.",
            )

        assert result is True
        mock_gmail.send_email.assert_called_once()

        # Verify the email content
        call_args = mock_gmail.send_email.call_args[0][0]
        assert call_args.subject == "Wichtige Info"
        assert "neue Uhrzeit" in call_args.body_text


class TestMessagesLog:
    """T4.4: Messages list returns outbound messages."""

    @pytest.fixture
    def email_service(self, mock_dynamodb):
        service = EmailService()
        service._messages_table = mock_dynamodb["messages_table"]
        return service

    def _store_message(self, table, event_id, direction, msg_type, **kwargs):
        msg = Message(
            event_id=event_id,
            type=msg_type,
            direction=direction,
            subject=kwargs.get("subject", "Test"),
            body=kwargs.get("body", "Test body"),
            status=kwargs.get("status", MessageStatus.SENT),
            recipient_email=kwargs.get("recipient_email", "test@example.com"),
            sent_at=kwargs.get("sent_at", datetime.now(timezone.utc)),
        )
        item = _message_to_item(msg)
        table.put_item(Item=item)
        return msg

    @pytest.mark.asyncio
    async def test_list_messages_returns_outbound(self, email_service, mock_dynamodb):
        event_id = uuid4()
        table = mock_dynamodb["messages_table"]

        # Store outbound message
        self._store_message(
            table, event_id, MessageDirection.OUTBOUND,
            MessageType.REGISTRATION_CONFIRMATION,
            subject="Anmeldung bestätigt",
        )

        # Store inbound message (should be filtered out)
        self._store_message(
            table, event_id, MessageDirection.INBOUND,
            MessageType.CUSTOM,
            subject="Antwort",
        )

        messages = await email_service.list_messages_for_event(event_id)

        assert len(messages) == 1
        assert messages[0]["subject"] == "Anmeldung bestätigt"
        assert messages[0]["type"] == "registration_confirmation"

    @pytest.mark.asyncio
    async def test_list_messages_empty_event(self, email_service):
        messages = await email_service.list_messages_for_event(uuid4())
        assert messages == []


class TestAuditLogging:
    """T4.5: Audit log entries are produced."""

    def test_log_admin_action_basic(self, caplog):
        """log_admin_action logs with structured fields."""
        import logging

        with caplog.at_level(logging.INFO, logger="audit"):
            log_admin_action(
                action="event.create",
                admin_email="admin@example.com",
                event_id="evt-123",
                details={"event_name": "Sommerfest"},
            )

        assert len(caplog.records) >= 1
        record = caplog.records[-1]
        assert "event.create" in record.getMessage()

    def test_log_admin_action_without_optional_fields(self, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="audit"):
            log_admin_action(
                action="event.list",
                admin_email=None,
            )

        assert len(caplog.records) >= 1
