"""Tests for `EventService.delete_festival_event` (spec 019 delete flow).

Mirrors `delete_event`'s CANCELLED-only status guard, but additionally
purges every co-located row a festival owns: invites (events table,
`INVITE#`), registrations + check-in scans (registrations table, `REG#`/
`SCAN#`), and messages (messages table, `MSG#`). Covers: full purge +
isolation from another event's rows, the status guard (German message),
and unknown-id / wrong-event-type handling.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from boto3.dynamodb.conditions import Key

from app.models import (
    Event,
    EventStatus,
    EventType,
    Invite,
    Message,
    MessageType,
    Registration,
    RegistrationStatus,
)
from app.services.checkin_service import CheckinService
from app.services.email_service import _message_to_item
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import _invite_to_item
from app.services.registration_service import _registration_to_item

NOW = datetime.now(timezone.utc)


def _festival_event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Betriebsfeier Julius Grube Schiffswerft",
        "event_type": EventType.FESTIVAL,
        "start_at": NOW + timedelta(days=30),
        "registration_deadline": NOW + timedelta(days=32),
        "end_at": NOW + timedelta(days=32),
        "status": EventStatus.CANCELLED,
        "capacity": 500,
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestDeleteFestivalEvent:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = EventService()
        self.service._table = mock_dynamodb["events_table"]

        self.checkin_service = CheckinService()
        self.checkin_service._table = mock_dynamodb["registrations_table"]

    def _seed_event(self, event: Event) -> None:
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    def _seed_invite(self, event: Event) -> Invite:
        invite = Invite(
            event_id=event.id,
            org_id=event.org_id,
            token=f"tok-{uuid4()}",
            label="Solo",
            tier="open",
        )
        self.tables["events_table"].put_item(Item=_invite_to_item(invite))
        return invite

    def _seed_registration(self, event: Event) -> Registration:
        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name="Max Mustermann",
            email="max@example.com",
            group_size=1,
            status=RegistrationStatus.PARTICIPATING,
            registration_token=f"tok-{uuid4()}",
            registered_at=NOW,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))
        return registration

    def _seed_message(self, event: Event) -> Message:
        message = Message(
            event_id=event.id,
            type=MessageType.FESTIVAL_INVITATION,
            subject="Einladung",
            body="Moin, du bist eingeladen.",
        )
        self.tables["messages_table"].put_item(Item=_message_to_item(message))
        return message

    async def _seed_scan(self, event: Event, registration: Registration) -> str:
        return await self.checkin_service.record_scan(event.id, registration.id, 0, registration.name)

    def _invite_rows(self, event_id):
        resp = self.tables["events_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("INVITE#"),
        )
        return resp.get("Items", [])

    def _reg_rows(self, event_id):
        resp = self.tables["registrations_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
        )
        return resp.get("Items", [])

    def _scan_rows(self, event_id):
        resp = self.tables["registrations_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("SCAN#"),
        )
        return resp.get("Items", [])

    def _message_rows(self, event_id):
        resp = self.tables["messages_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("MSG#"),
        )
        return resp.get("Items", [])

    def _event_row(self, org_id, event_id):
        resp = self.tables["events_table"].get_item(
            Key={"pk": f"ORG#{org_id}", "sk": f"EVENT#{event_id}"},
        )
        return resp.get("Item")

    @pytest.mark.asyncio
    async def test_delete_purges_everything_and_leaves_other_events_untouched(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_invite(event)
        registration = self._seed_registration(event)
        await self._seed_scan(event, registration)
        self._seed_message(event)

        # A second, unrelated CANCELLED festival with its own co-located
        # rows — must survive completely untouched.
        other_event = _festival_event()
        self._seed_event(other_event)
        self._seed_invite(other_event)
        other_registration = self._seed_registration(other_event)
        await self._seed_scan(other_event, other_registration)
        self._seed_message(other_event)

        deleted = await self.service.delete_festival_event(event.org_id, event.id)
        assert deleted is True

        assert self._event_row(event.org_id, event.id) is None
        assert self._invite_rows(event.id) == []
        assert self._reg_rows(event.id) == []
        assert self._scan_rows(event.id) == []
        assert self._message_rows(event.id) == []

        assert self._event_row(other_event.org_id, other_event.id) is not None
        assert len(self._invite_rows(other_event.id)) == 1
        assert len(self._reg_rows(other_event.id)) == 1
        assert len(self._scan_rows(other_event.id)) == 1
        assert len(self._message_rows(other_event.id)) == 1

    @pytest.mark.asyncio
    async def test_delete_refused_when_status_open_german_message(self):
        event = _festival_event(status=EventStatus.OPEN)
        self._seed_event(event)

        with pytest.raises(ValueError, match="zuerst abgesagt"):
            await self.service.delete_festival_event(event.org_id, event.id)

        # Refused — nothing was removed.
        assert self._event_row(event.org_id, event.id) is not None

    @pytest.mark.asyncio
    async def test_delete_refused_for_every_non_cancelled_status(self):
        for status in (
            EventStatus.DRAFT,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.CONFIRMED,
            EventStatus.COMPLETED,
        ):
            event = _festival_event(status=status)
            self._seed_event(event)

            with pytest.raises(ValueError):
                await self.service.delete_festival_event(event.org_id, event.id)

    @pytest.mark.asyncio
    async def test_delete_unknown_event_returns_false(self):
        assert await self.service.delete_festival_event(uuid4(), uuid4()) is False

    @pytest.mark.asyncio
    async def test_delete_rejects_single_event_type(self):
        """Ä-isolation: a SINGLE event id must never be reachable here,
        even if somehow CANCELLED — this stays event_service.delete_event's
        job."""
        event = _festival_event(event_type=EventType.SINGLE, status=EventStatus.CANCELLED)
        self._seed_event(event)

        assert await self.service.delete_festival_event(event.org_id, event.id) is False
        # Untouched — delete_festival_event must not delete a SINGLE event.
        assert self._event_row(event.org_id, event.id) is not None
