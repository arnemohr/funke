"""Tests for the public invite guestlist endpoint (Gästelisten view).

The router function is a thin shim over the three services, so it is
covered here directly (pattern: test_checkin_service.py) — services wired
to moto tables via the module singletons.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.services.event_service as event_service_module
import app.services.invite_service as invite_service_module
import app.services.registration_service as registration_service_module
from app.api.public.invites import get_invite_guestlist
from app.models import (
    Event,
    EventStatus,
    EventType,
    FestivalSlot,
    InviteBatchCreate,
    InviteCreate,
    Registration,
    RegistrationStatus,
)
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import InviteService, _invite_to_item
from app.services.registration_service import RegistrationService, _registration_to_item

NOW = datetime.now(UTC)


def _slots() -> list[FestivalSlot]:
    from datetime import date

    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
    ]


class TestInviteGuestlist:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb

        event_service = EventService()
        event_service._table = self.tables["events_table"]
        event_service_module._event_service = event_service

        self.invite_service = InviteService()
        self.invite_service._table = self.tables["events_table"]
        invite_service_module._invite_service = self.invite_service

        reg_service = RegistrationService()
        reg_service._registrations_table = self.tables["registrations_table"]
        reg_service._events_table = self.tables["events_table"]
        registration_service_module._registration_service = reg_service

        yield

        event_service_module._event_service = None
        invite_service_module._invite_service = None
        registration_service_module._registration_service = None

    def _store_event(self, **overrides) -> Event:
        defaults = dict(
            id=uuid4(),
            org_id=uuid4(),
            name="Sommerfestival",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=20),
            end_at=NOW + timedelta(days=22),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            status=EventStatus.OPEN,
            autopromote_waitlist=False,
            registration_link_token=None,
        )
        defaults.update(overrides)
        event = Event(**defaults)
        self.tables["events_table"].put_item(Item=_event_to_item(event))
        return event

    async def _store_invite(self, event: Event, **entry_overrides):
        entry_defaults = dict(label="Micha", tier="werft", max_uses=10, max_group_size=2)
        entry_defaults.update(entry_overrides)
        batch = InviteBatchCreate(invites=[InviteCreate(**entry_defaults)])
        created = await self.invite_service.create_invites_batch(
            event.org_id, event.id, batch, uuid4(),
        )
        return created[0]

    def _store_registration(self, event: Event, invite_id, **overrides) -> Registration:
        defaults = dict(
            event_id=event.id,
            name="Lena Schmidt",
            email="lena@example.com",
            group_size=1,
            registration_token=f"tok-{uuid4()}",
            status=RegistrationStatus.PARTICIPATING,
            invite_id=invite_id,
            attendance_slots=["fr"],
            registered_at=NOW,
        )
        defaults.update(overrides)
        registration = Registration(**defaults)
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))
        return registration

    async def test_happy_path_lists_only_this_invites_registrations(self):
        event = self._store_event()
        invite = await self._store_invite(event)
        other_invite = await self._store_invite(event, label="Andere")

        self._store_registration(event, invite.id, name="Lena Schmidt", registered_at=NOW)
        self._store_registration(
            event, invite.id, name="Jan Hansen", group_size=2,
            attendance_slots=["fr", "sa"], registered_at=NOW - timedelta(hours=1),
        )
        self._store_registration(event, other_invite.id, name="Fremde Person")
        self._store_registration(
            event, invite.id, name="Storniert", status=RegistrationStatus.CANCELLED,
        )

        result = await get_invite_guestlist(invite.token)

        assert result.invite_label == "Micha"
        assert result.event_name == "Sommerfestival"
        assert result.max_uses == 10
        assert result.max_group_size == 2
        assert result.can_register is True
        assert [r.name for r in result.registrations] == ["Jan Hansen", "Lena Schmidt"]
        assert result.registrations[0].group_size == 2
        assert result.registrations[0].attendance_slots == ["fr", "sa"]
        assert {s.key: s.label for s in result.slots} == {"fr": "Freitag", "sa": "Samstag"}

    async def test_unknown_token_404(self):
        self._store_event()
        with pytest.raises(HTTPException) as exc:
            await get_invite_guestlist("does-not-exist")
        assert exc.value.status_code == 404

    async def test_revoked_invite_404(self):
        event = self._store_event()
        invite = await self._store_invite(event)
        revoked = invite.model_copy(update={"revoked_at": NOW})
        self.tables["events_table"].put_item(Item=_invite_to_item(revoked))

        with pytest.raises(HTTPException) as exc:
            await get_invite_guestlist(invite.token)
        assert exc.value.status_code == 404

    async def test_exhausted_invite_still_readable(self):
        """A full contingent renders with can_register=False — no 410."""
        event = self._store_event()
        invite = await self._store_invite(event, max_uses=1)
        used = invite.model_copy(update={"use_count": 1})
        self.tables["events_table"].put_item(Item=_invite_to_item(used))

        result = await get_invite_guestlist(invite.token)

        assert result.use_count == 1
        assert result.can_register is False

    async def test_deadline_passed_still_readable(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=10),
            registration_deadline=NOW - timedelta(days=1),
            end_at=NOW - timedelta(days=1),
        )
        invite = await self._store_invite(event)

        result = await get_invite_guestlist(invite.token)

        assert result.can_register is False
