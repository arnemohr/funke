"""Tests for festival sidetrack (spec 019) check-in prerequisites.

Covers T302 (Event gate_token/ticket_secret fields, GSI lookup, lazy
generation), T305 (the begins_with(sk, "REG#") prerequisite fix that
must land before any SCAN# row is ever written), and T308 (manage-page
per-person QR payload builder).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api.public.registrations import _build_qr_payloads
from app.models import Event, EventStatus, Registration, RegistrationStatus
from app.services.event_service import EventService, _event_to_item, _item_to_event
from app.services.registration_service import RegistrationService, _registration_to_item
from app.services.ticket_signing import verify_ticket

NOW = datetime.now(timezone.utc)


def _festival_event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Betriebsfeier Julius Grube Schiffswerft",
        "start_at": NOW + timedelta(days=30),
        "registration_deadline": NOW + timedelta(days=32),
        "end_at": NOW + timedelta(days=32),
        "status": EventStatus.CONFIRMED,
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestGateCredentials:
    """T302: gate_token / ticket_secret persistence, GSI lookup, lazy generation."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = EventService()
        self.service._table = mock_dynamodb["events_table"]

    def test_round_trip_persists_both_fields(self):
        event = _festival_event(gate_token="gate-tok-123", ticket_secret="ticket-secret-abc")
        item = _event_to_item(event)
        restored = _item_to_event(item)

        assert restored.gate_token == "gate-tok-123"
        assert restored.ticket_secret == "ticket-secret-abc"

    def test_round_trip_without_credentials(self):
        event = _festival_event()
        item = _event_to_item(event)
        assert "gate_token" not in item
        assert "ticket_secret" not in item

        restored = _item_to_event(item)
        assert restored.gate_token is None
        assert restored.ticket_secret is None

    @pytest.mark.asyncio
    async def test_get_event_by_gate_token_finds_event(self):
        event = _festival_event(gate_token="find-me-token")
        self.tables["events_table"].put_item(Item=_event_to_item(event))

        found = await self.service.get_event_by_gate_token("find-me-token")

        assert found is not None
        assert found.id == event.id

    @pytest.mark.asyncio
    async def test_get_event_by_gate_token_unknown_returns_none(self):
        result = await self.service.get_event_by_gate_token("no-such-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_gate_credentials_generates_both_on_first_call(self):
        event = _festival_event()
        self.tables["events_table"].put_item(Item=_event_to_item(event))

        result = await self.service.ensure_gate_credentials(event.org_id, event.id)

        assert result is not None
        assert result.gate_token is not None
        assert result.ticket_secret is not None

        stored = await self.service.get_event(event.org_id, event.id)
        assert stored.gate_token == result.gate_token
        assert stored.ticket_secret == result.ticket_secret

    @pytest.mark.asyncio
    async def test_ensure_gate_credentials_idempotent(self):
        event = _festival_event()
        self.tables["events_table"].put_item(Item=_event_to_item(event))

        first = await self.service.ensure_gate_credentials(event.org_id, event.id)
        second = await self.service.ensure_gate_credentials(event.org_id, event.id)

        assert first.gate_token == second.gate_token
        assert first.ticket_secret == second.ticket_secret

    @pytest.mark.asyncio
    async def test_ensure_gate_credentials_never_overwrites_existing_values(self):
        """Review fix: minting is persisted with if_not_exists, so a call
        that races an earlier mint (here: an item that already carries a
        ticket_secret but no gate_token) fills only the missing attribute
        and returns the surviving values — never a fresh secret that would
        invalidate already-issued QR codes."""
        event = _festival_event(ticket_secret="pre-existing-secret", gate_token=None)
        self.tables["events_table"].put_item(Item=_event_to_item(event))

        result = await self.service.ensure_gate_credentials(event.org_id, event.id)

        assert result is not None
        assert result.ticket_secret == "pre-existing-secret"
        assert result.gate_token is not None

        stored = await self.service.get_event(event.org_id, event.id)
        assert stored.ticket_secret == "pre-existing-secret"
        assert stored.gate_token == result.gate_token

    @pytest.mark.asyncio
    async def test_rotate_gate_token_replaces_token_keeps_secret(self):
        """T303: mirrors what the rotate handler does — unconditionally
        replace gate_token, leave ticket_secret untouched, old token dead."""
        from app.services.event_service import _generate_link_token

        event = _festival_event()
        self.tables["events_table"].put_item(Item=_event_to_item(event))

        seeded = await self.service.ensure_gate_credentials(event.org_id, event.id)
        old_token = seeded.gate_token
        old_secret = seeded.ticket_secret

        rotated = seeded.model_copy(update={"gate_token": _generate_link_token()})
        self.service.table.put_item(Item=_event_to_item(rotated))

        assert rotated.gate_token != old_token
        assert rotated.ticket_secret == old_secret

        assert await self.service.get_event_by_gate_token(old_token) is None
        found = await self.service.get_event_by_gate_token(rotated.gate_token)
        assert found is not None
        assert found.id == event.id
        assert found.ticket_secret == old_secret


class TestRegPrefixFilter:
    """T305: list_registrations / stats must not choke on non-REG# rows in the partition."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        self.service._registrations_table = mock_dynamodb["registrations_table"]

    @pytest.mark.asyncio
    async def test_list_registrations_ignores_scan_rows(self):
        event_id = uuid4()
        registration = Registration(
            id=uuid4(),
            event_id=event_id,
            name="Max Mustermann",
            email="max@example.com",
            group_size=1,
            status=RegistrationStatus.PARTICIPATING,
            registration_token="tok-123",
            registered_at=NOW,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))

        # Simulated future SCAN# row (T306) in the same event partition — must
        # not be picked up by list_registrations, nor choke _item_to_registration.
        self.tables["registrations_table"].put_item(
            Item={
                "pk": f"EVENT#{event_id}",
                "sk": f"SCAN#2026-08-15T00:30:00+02:00#{registration.id}#0",
                "entity_type": "CheckinScan",
            }
        )

        results = await self.service.list_registrations(event_id)

        assert len(results) == 1
        assert results[0].id == registration.id

    @pytest.mark.asyncio
    async def test_get_registration_stats_counts_only_registrations(self):
        event_id = uuid4()
        registration = Registration(
            id=uuid4(),
            event_id=event_id,
            name="Erika Musterfrau",
            email="erika@example.com",
            group_size=1,
            status=RegistrationStatus.PARTICIPATING,
            registration_token="tok-456",
            registered_at=NOW,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))
        self.tables["registrations_table"].put_item(
            Item={
                "pk": f"EVENT#{event_id}",
                "sk": f"SCAN#2026-08-15T00:30:00+02:00#{registration.id}#0",
                "entity_type": "CheckinScan",
            }
        )

        stats = await self.service.get_registration_stats(event_id)

        assert stats["participating_count"] == 1


class TestManageQrPayloads:
    """T308: freshly signed per-person QR payloads for the manage page."""

    SECRET = "test-ticket-secret"

    def _registration(self, **overrides) -> Registration:
        defaults = {
            "id": uuid4(),
            "event_id": uuid4(),
            "name": "Kontakt Kalle",
            "email": "kalle@example.com",
            "group_size": 3,
            "group_members": ["Anna Meier", "Ben Otto"],
            "status": RegistrationStatus.PARTICIPATING,
            "registration_token": "tok-qr-1",
            "registered_at": NOW,
            "attendance_slots": ["fr-abend"],
            "overnight_approved": False,
        }
        defaults.update(overrides)
        return Registration(**defaults)

    def test_yields_one_code_per_person_with_correct_indices(self):
        registration = self._registration()

        payloads = _build_qr_payloads(self.SECRET, registration)

        assert [p.person_index for p in payloads] == [0, 1, 2]
        assert [p.name for p in payloads] == ["Kontakt Kalle", "Anna Meier", "Ben Otto"]

        for payload in payloads:
            decoded = verify_ticket(self.SECRET, payload.code)
            assert decoded is not None
            assert decoded["p"] == payload.person_index
            assert decoded["n"] == payload.name
            assert decoded["r"] == str(registration.id)
            assert decoded["o"] == registration.overnight_approved

    def test_reflects_overnight_approved_flip(self):
        registration = self._registration(overnight_approved=True)

        payloads = _build_qr_payloads(self.SECRET, registration)

        for payload in payloads:
            decoded = verify_ticket(self.SECRET, payload.code)
            assert decoded["o"] is True

    def test_tombstoned_member_yields_no_code_later_members_keep_index(self):
        registration = self._registration(
            group_size=3,
            group_members=[None, "Ben Otto"],
        )

        payloads = _build_qr_payloads(self.SECRET, registration)

        # person 0 (contact) + person 2 (Ben Otto) — person 1 is tombstoned.
        assert [p.person_index for p in payloads] == [0, 2]
        assert [p.name for p in payloads] == ["Kontakt Kalle", "Ben Otto"]

    def test_no_group_members_yields_single_contact_code(self):
        registration = self._registration(group_size=1, group_members=None)

        payloads = _build_qr_payloads(self.SECRET, registration)

        assert len(payloads) == 1
        assert payloads[0].person_index == 0
        assert payloads[0].name == "Kontakt Kalle"
