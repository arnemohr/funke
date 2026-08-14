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


class InviteBootBase:
    """Fixture + factories shared by the invite-endpoint test classes."""

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

class TestInviteGuestlist(InviteBootBase):
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


class TestRegistrationClosedByStatus(InviteBootBase):
    """Closing registration must shut the FRONT door without locking the
    people already inside.

    Two independent levers exist on purpose: the `registration_deadline` and
    the event `status`. The status one is what the „Anmeldung schließen" /
    „Bestätigen" buttons move, and until now it did nothing to the public
    invite flow — the boot happily served the form and only
    `create_festival_registration` refused on submit, after the guest had
    typed everything in.
    """

    async def _boot(self, invite):
        from app.api.public.invites import get_invite_info

        return await get_invite_info(invite_token=invite.token)

    async def test_open_event_still_serves_the_form(self):
        event = self._store_event(status=EventStatus.OPEN)
        invite = await self._store_invite(event)

        info = await self._boot(invite)

        assert info.event_name == event.name

    @pytest.mark.parametrize(
        "closed_status",
        [EventStatus.REGISTRATION_CLOSED, EventStatus.CONFIRMED],
    )
    async def test_closed_or_confirmed_refuses_the_form(self, closed_status):
        event = self._store_event(status=closed_status)
        invite = await self._store_invite(event)

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)

        assert excinfo.value.status_code == 410
        assert "geschlossen" in excinfo.value.detail

    async def test_draft_event_refuses_too(self):
        """A festival that was never published must not be reachable either —
        the old code had no status check at all, so a DRAFT invite worked."""
        event = self._store_event(status=EventStatus.DRAFT)
        invite = await self._store_invite(event)

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)

        assert excinfo.value.status_code == 410

    @pytest.mark.parametrize(
        "closed_status",
        [EventStatus.REGISTRATION_CLOSED, EventStatus.CONFIRMED],
    )
    async def test_submitting_anyway_is_still_refused(self, closed_status):
        """The boot gate is UX; this is the one that actually protects."""
        from app.models import FestivalRegistrationCreate

        event = self._store_event(status=closed_status)
        invite = await self._store_invite(event)

        registration, error = await registration_service_module.get_registration_service(
        ).create_festival_registration(
            invite.token,
            FestivalRegistrationCreate(
                name="Spät Dran",
                email="spaet@example.com",
                attendance_slots=["fr"],
                group_size=1,
                phone="+49 170 1234567",
            ),
        )

        assert registration is None
        assert "not open" in error.lower()

    @pytest.mark.parametrize(
        "closed_status",
        [EventStatus.REGISTRATION_CLOSED, EventStatus.CONFIRMED],
    )
    async def test_existing_registration_stays_fully_manageable(self, closed_status):
        """The other half of the requirement: everything an ALREADY registered
        person can do must survive the close — days, companions, overnight,
        and cancelling."""
        from app.models import FestivalAttendancePatch

        event = self._store_event(status=closed_status)
        invite = await self._store_invite(event)
        reg = self._store_registration(event, invite.id, phone="+49 170 1234567")

        reg_service = registration_service_module.get_registration_service()

        updated, error = await reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(attendance_slots=["fr", "sa"], group_size=1),
        )
        assert error is None, f"manage page blocked by status {closed_status}: {error!r}"
        assert updated.attendance_slots == ["fr", "sa"]

        overnight, error = await reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(tent_count=1, phone="+49 170 1234567"),
        )
        assert error is None, f"overnight edit blocked: {error!r}"
        assert overnight.tent_count == 1

        cancelled, error = await reg_service.cancel_registration(
            reg.id, reg.registration_token,
        )
        assert error is None, f"cancelling blocked: {error!r}"
        assert cancelled.status == RegistrationStatus.CANCELLED
