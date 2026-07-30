"""Model helpers that a bad `utcnow()` sed had mangled (spec 020 §Anhang B).

Five expressions had been left as `lambda: datetime.now(...)()` — a stray
lambda prefix plus a stray trailing call. A lambda object is always truthy,
so the two used in a boolean context inverted their result, and the three
used as values stored a lambda where a `datetime` belonged.

All five sat in code no production path reaches, which is exactly why the
damage went unnoticed for so long. These tests are therefore the ONLY thing
standing between the fix and a silent regression — they exercise the helpers
directly rather than through a service.

The load-bearing assertions are `isinstance(..., datetime)` /
`tzinfo is not None`: a stored lambda passes a truthiness check but fails
those, and blows up later on `.isoformat()` at serialization time.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.admin import AdminRole, Invitation
from app.models.event import Event, EventStatus, EventType
from app.models.message import Message, MessageStatus, MessageType
from app.models.registration import Registration, RegistrationStatus
from app.services.email_service import _message_to_item


def _event(status: EventStatus, deadline: datetime) -> Event:
    """Minimal SINGLE event with an explicit status and deadline."""
    return Event(
        org_id=uuid4(),
        name="Testfahrt",
        start_at=deadline + timedelta(days=1),
        registration_deadline=deadline,
        status=status,
        event_type=EventType.SINGLE,
    )


def _registration(status: RegistrationStatus) -> Registration:
    return Registration(
        event_id=uuid4(),
        name="Anna Schmidt",
        email="anna@example.de",
        registration_token="tok-" + uuid4().hex,
        status=status,
    )


def _message() -> Message:
    return Message(
        event_id=uuid4(),
        type=MessageType.CUSTOM,
        subject="Infos zur Fahrt",
        body="Moin!",
    )


def _invitation(expires_in: timedelta, accepted: bool = False) -> Invitation:
    return Invitation(
        org_id=uuid4(),
        email="neu@example.de",
        role=AdminRole.ADMIN,
        token="inv-" + uuid4().hex,
        invited_by_admin_id=uuid4(),
        expires_at=datetime.now(UTC) + expires_in,
        accepted_at=datetime.now(UTC) if accepted else None,
    )


class TestEventIsRegistrationOpen:
    """B1 — `Event.is_registration_open()` (event.py:252).

    The mangled `if lambda: ... >= deadline` was always truthy, so the method
    returned False for every event, including a wide-open one.
    """

    def test_open_and_before_deadline_is_open(self):
        event = _event(EventStatus.OPEN, datetime.now(UTC) + timedelta(days=7))
        assert event.is_registration_open() is True

    def test_open_but_past_deadline_is_closed(self):
        event = _event(EventStatus.OPEN, datetime.now(UTC) - timedelta(minutes=1))
        assert event.is_registration_open() is False

    @pytest.mark.parametrize(
        "status",
        [
            EventStatus.DRAFT,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.CONFIRMED,
            EventStatus.COMPLETED,
            EventStatus.CANCELLED,
        ],
    )
    def test_non_open_status_is_always_closed(self, status):
        """Even a future deadline cannot open a non-OPEN event."""
        event = _event(status, datetime.now(UTC) + timedelta(days=7))
        assert event.is_registration_open() is False


class TestRegistrationSetAttendanceResponse:
    """B2 — `Registration.set_attendance_response()` (registration.py:479).

    Stored `responded_at` as a lambda. Note the live single-event flow uses
    the service method of the same name, which writes the timestamp itself
    via a DynamoDB UpdateExpression and never calls this helper.
    """

    def test_yes_sets_participating_and_timezone_aware_timestamp(self):
        updated = _registration(RegistrationStatus.CONFIRMED).set_attendance_response(True)

        assert updated.status == RegistrationStatus.PARTICIPATING
        # The assertion that would have caught the lambda.
        assert isinstance(updated.responded_at, datetime)
        assert updated.responded_at.tzinfo is not None

    def test_no_sets_cancelled_and_timezone_aware_timestamp(self):
        updated = _registration(RegistrationStatus.CONFIRMED).set_attendance_response(False)

        assert updated.status == RegistrationStatus.CANCELLED
        assert isinstance(updated.responded_at, datetime)
        assert updated.responded_at.tzinfo is not None

    @pytest.mark.parametrize(
        "status",
        [
            RegistrationStatus.REGISTERED,
            RegistrationStatus.WAITLISTED,
            RegistrationStatus.PARTICIPATING,
            RegistrationStatus.CANCELLED,
        ],
    )
    def test_non_confirmed_status_raises(self, status):
        with pytest.raises(ValueError, match="Can only respond to CONFIRMED"):
            _registration(status).set_attendance_response(True)


class TestMessageMarkSent:
    """B3 — `Message.mark_sent()` (message.py:102).

    Stored `sent_at` as a lambda. The live worker marks messages with direct
    UpdateExpressions and never calls this helper.
    """

    def test_marks_sent_with_timezone_aware_timestamp(self):
        updated = _message().mark_sent("<abc123@mail.example.de>")

        assert updated.status == MessageStatus.SENT
        assert updated.email_message_id == "<abc123@mail.example.de>"
        assert isinstance(updated.sent_at, datetime)
        assert updated.sent_at.tzinfo is not None

    def test_result_survives_serialization(self):
        """A stored lambda blew up here — `_message_to_item` calls .isoformat()."""
        item = _message_to_item(_message().mark_sent("<abc123@mail.example.de>"))

        assert isinstance(item["sent_at"], str)
        # Round-trips back into a datetime, i.e. it really was one.
        assert datetime.fromisoformat(item["sent_at"]).tzinfo is not None

    def test_mark_failed_increments_retry_count(self):
        """Neighbour of the fixed line, unmangled — pinned so it stays that way."""
        updated = _message().mark_failed("smtp_error")

        assert updated.status == MessageStatus.FAILED
        assert updated.error_code == "smtp_error"
        assert updated.retry_count == 1


class TestInvitationExpiryAndAccept:
    """B4/B5 — `Invitation.is_expired` / `.accept()` (admin.py:103, :116).

    `is_expired` returned a (truthy) lambda, so `accept()` raised
    "Invitation has expired" for every invitation, including a fresh one.

    This is the ADMIN org-invitation model — not the festival `Invite`
    (models/invite.py), whose own `is_expired(registration_deadline)` is
    correct, live, and covered by test_invite_service.py. Do not conflate.
    """

    def test_future_expiry_is_not_expired(self):
        assert _invitation(timedelta(days=7)).is_expired is False

    def test_past_expiry_is_expired(self):
        assert _invitation(timedelta(minutes=-1)).is_expired is True

    def test_accept_sets_timezone_aware_timestamp(self):
        accepted = _invitation(timedelta(days=7)).accept()

        assert accepted.is_accepted is True
        assert isinstance(accepted.accepted_at, datetime)
        assert accepted.accepted_at.tzinfo is not None

    def test_accept_on_expired_invitation_raises(self):
        with pytest.raises(ValueError, match="expired"):
            _invitation(timedelta(minutes=-1)).accept()

    def test_accept_on_already_accepted_invitation_raises(self):
        with pytest.raises(ValueError, match="already accepted"):
            _invitation(timedelta(days=7), accepted=True).accept()
