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
    InviteUpdate,
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


class TestRegistrationsListCheckedIn(InviteBootBase):
    """The admin roster must be filterable by who has actually arrived.

    Arrivals live in the check-in log, not on the registration, so the list
    endpoint joins them in as a sibling `checked_in` map rather than polluting
    the shared public `RegistrationResponse`.
    """

    async def _list(self, event):
        import app.services.checkin_service as checkin_service_module
        from app.api.admin.festival import list_festival_registrations
        from app.services.checkin_service import CheckinService

        checkin = CheckinService()
        checkin._table = self.tables["registrations_table"]
        checkin_service_module._checkin_service = checkin

        # `_get_org_id` parses the token claim, so org_id is a STRING there.
        user = type("U", (), {"org_id": str(event.org_id), "email": "admin@example.com"})()
        try:
            return await list_festival_registrations(event_id=event.id, user=user)
        finally:
            checkin_service_module._checkin_service = None

    async def _scan(self, event, registration, person_index, name):
        import app.services.checkin_service as checkin_service_module
        from app.services.checkin_service import CheckinService

        checkin = CheckinService()
        checkin._table = self.tables["registrations_table"]
        checkin_service_module._checkin_service = checkin
        await checkin.record_scan(event.id, registration.id, person_index, name)
        checkin_service_module._checkin_service = None

    async def test_nobody_scanned_yet_gives_an_empty_map(self):
        event = self._store_event()
        invite = await self._store_invite(event)
        self._store_registration(event, invite.id)

        result = await self._list(event)

        assert result.total == 1
        assert result.checked_in == {}

    async def test_scanned_people_appear_under_their_registration(self):
        event = self._store_event()
        invite = await self._store_invite(event)
        reg = self._store_registration(
            event, invite.id, group_size=3, group_members=["Bea", "Cem"],
        )
        other = self._store_registration(event, invite.id, email="zwei@example.com")

        # The contact and the SECOND companion arrive; Bea (index 1) does not.
        await self._scan(event, reg, 0, "Lena Schmidt")
        await self._scan(event, reg, 2, "Cem")

        result = await self._list(event)

        assert result.checked_in == {str(reg.id): [0, 2]}
        assert str(other.id) not in result.checked_in

    async def test_indices_are_sorted_regardless_of_scan_order(self):
        """The frontend renders a per-person tick from these — order must be
        stable so a re-render never reshuffles."""
        event = self._store_event()
        invite = await self._store_invite(event)
        reg = self._store_registration(
            event, invite.id, group_size=3, group_members=["Bea", "Cem"],
        )

        await self._scan(event, reg, 2, "Cem")
        await self._scan(event, reg, 0, "Lena Schmidt")
        await self._scan(event, reg, 1, "Bea")

        result = await self._list(event)

        assert result.checked_in[str(reg.id)] == [0, 1, 2]

    async def test_double_scan_counts_the_person_once(self):
        """Offline sync can write the same person twice — the map is deduped by
        `get_checked_in_map`, so a group can never show 4/3 arrived."""
        event = self._store_event()
        invite = await self._store_invite(event)
        reg = self._store_registration(event, invite.id, group_size=1)

        await self._scan(event, reg, 0, "Lena Schmidt")
        await self._scan(event, reg, 0, "Lena Schmidt")

        result = await self._list(event)

        assert result.checked_in[str(reg.id)] == [0]


class TestSpaeteFische(InviteBootBase):
    """„Späte Fische" — a single invite that survives registration close.

    The whole point is that it is PER INVITE: this event has 786 unused seats
    spread over 22 contingent links that are already circulating in group
    chats, so anything event-wide would reopen all of them at once. A late
    invite opens exactly two event-level gates for exactly one link.
    """

    async def _boot(self, invite):
        from app.api.public.invites import get_invite_info

        return await get_invite_info(invite_token=invite.token)

    def _closed_event(self, **overrides):
        """Registration closed the hard way: past deadline AND CONFIRMED."""
        defaults = dict(
            status=EventStatus.CONFIRMED,
            registration_deadline=NOW - timedelta(days=1),
        )
        defaults.update(overrides)
        return self._store_event(**defaults)

    def _create(self, email="spaet@example.com", group_size=1):
        from app.models import FestivalRegistrationCreate

        return FestivalRegistrationCreate(
            name="Spät Dran",
            email=email,
            attendance_slots=["fr"],
            group_size=group_size,
            phone="+49 170 1234567",
        )

    async def test_normal_invite_is_refused_when_closed(self):
        event = self._closed_event()
        invite = await self._store_invite(event)

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)
        assert excinfo.value.status_code == 410

    async def test_late_invite_still_serves_the_form(self):
        event = self._closed_event()
        invite = await self._store_invite(
            event, max_uses=1, max_group_size=1, email="spaet@example.com",
        )
        invite = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        info = await self._boot(invite)

        assert info.event_name == event.name
        assert info.bound_email == "spaet@example.com"

    async def test_late_invite_can_actually_register(self):
        event = self._closed_event()
        invite = await self._store_invite(
            event, max_uses=1, max_group_size=1, email="spaet@example.com",
        )
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        reg_service = registration_service_module.get_registration_service()
        registration, error = await reg_service.create_festival_registration(
            invite.token, self._create(),
        )

        assert error is None, f"late invite was refused: {error!r}"
        assert registration.invite_id == invite.id

    async def test_forwarded_link_cannot_register_someone_else(self):
        """The anti-forwarding lock: a friend can only register under the
        address the link was issued to — so the entry code lands in the
        original mailbox and the link is worthless to pass on."""
        event = self._closed_event()
        invite = await self._store_invite(
            event, max_uses=1, max_group_size=1, email="spaet@example.com",
        )
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        reg_service = registration_service_module.get_registration_service()
        registration, error = await reg_service.create_festival_registration(
            invite.token, self._create(email="freundin@example.com"),
        )

        assert registration is None
        assert "does not match" in error.lower()

    async def test_binding_ignores_case_and_whitespace(self):
        event = self._closed_event()
        invite = await self._store_invite(
            event, max_uses=1, max_group_size=1, email="spaet@example.com",
        )
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        reg_service = registration_service_module.get_registration_service()
        _, error = await reg_service.create_festival_registration(
            invite.token, self._create(email="  SPAET@Example.COM "),
        )

        assert error is None, f"same address rejected over formatting: {error!r}"

    async def test_normal_invites_are_not_address_bound(self):
        """The 24 links already in the wild must behave exactly as before."""
        event = self._store_event(status=EventStatus.OPEN)
        invite = await self._store_invite(event, email="owner@example.com", max_group_size=2)

        reg_service = registration_service_module.get_registration_service()
        _, error = await reg_service.create_festival_registration(
            invite.token, self._create(email="jemand.anders@example.com"),
        )

        assert error is None, f"a normal contingent became address-bound: {error!r}"

    async def test_one_seat_only_no_matter_the_status(self):
        """`max_uses` still binds — that is the cap that makes this safe."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1, max_group_size=1, email=None)
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        reg_service = registration_service_module.get_registration_service()
        _, first_error = await reg_service.create_festival_registration(
            invite.token, self._create(email="erste@example.com"),
        )
        assert first_error is None

        _, second_error = await reg_service.create_festival_registration(
            invite.token, self._create(email="zweite@example.com"),
        )
        assert second_error is not None
        assert "exhaust" in second_error.lower()

    async def test_revoking_kills_a_late_invite_immediately(self):
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1, email="spaet@example.com")
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )
        await self.invite_service.revoke_invite(event.id, invite.id)

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)
        assert excinfo.value.status_code in (404, 410)

    async def test_own_expiry_still_closes_a_late_invite(self):
        """Its own `expires_at` is the only clock left, so it must work."""
        event = self._closed_event()
        invite = await self._store_invite(
            event, max_uses=1, email="spaet@example.com", expires_at=NOW - timedelta(hours=1),
        )
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)
        assert excinfo.value.status_code == 410

    @pytest.mark.parametrize("dead_status", [EventStatus.COMPLETED, EventStatus.CANCELLED])
    async def test_a_finished_festival_closes_even_late_invites(self, dead_status):
        """Nobody should have to remember to switch these off afterwards."""
        event = self._closed_event(status=dead_status)
        invite = await self._store_invite(event, max_uses=1, email="spaet@example.com")
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        with pytest.raises(HTTPException) as excinfo:
            await self._boot(invite)
        assert excinfo.value.status_code == 410

    async def test_guestlist_no_longer_lies_about_can_register(self):
        """The bug this refactor fixed: `can_register` never looked at the
        event status, so contingent owners were told they could still register
        after the event moved to CONFIRMED."""
        from app.api.public.invites import get_invite_guestlist

        event = self._store_event(
            status=EventStatus.CONFIRMED,
            registration_deadline=NOW + timedelta(days=2),
        )
        invite = await self._store_invite(event, max_uses=150)

        result = await get_invite_guestlist(invite_token=invite.token)

        assert result.can_register is False

    async def test_guestlist_says_yes_for_a_late_invite(self):
        from app.api.public.invites import get_invite_guestlist

        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1, email="spaet@example.com")
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        result = await get_invite_guestlist(invite_token=invite.token)

        assert result.can_register is True

    async def test_unbound_late_invite_takes_any_address(self):
        """The one-click button issues a link with NO address: the organiser
        does not know who will use it, and a placeholder address would sit
        there waiting to bounce off our own domain. `max_uses = 1` is then the
        only lock — forwarding cannot add people, it can only change WHICH
        single person gets in."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1, max_group_size=1, email=None)
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        info = await self._boot(invite)
        assert info.bound_email is None, "an address-less invite must not lock the form"

        reg_service = registration_service_module.get_registration_service()
        registration, error = await reg_service.create_festival_registration(
            invite.token, self._create(email="wer.auch.immer@example.com"),
        )

        assert error is None, f"unbound late invite refused: {error!r}"
        assert registration.email == "wer.auch.immer@example.com"

    async def test_reopening_a_contingent_grants_only_the_seats_you_name(self):
        """The override: a closed list is reopened for a COUNTED number of
        seats, never for its whole remainder. Aline's „open" list has 114
        unused seats; reopening it for 3 must mean 3, not 114."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=200, max_group_size=1)
        # 86 people already used it, mirroring production.
        for _ in range(86):
            await self.invite_service.consume_use(event.id, invite.id)

        reopened = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=86 + 3),
        )

        assert reopened.late_entry is True
        assert reopened.max_uses == 89, "reopening must clamp, not restore"
        assert reopened.max_uses - reopened.use_count == 3

        # The link works again — for exactly those three.
        info = await self._boot(reopened)
        assert info.event_name == event.name

    async def test_closing_a_reopened_list_shuts_it_immediately(self):
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=10)
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=3),
        )
        assert (await self._boot(invite)).event_name == event.name

        closed = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=False),
        )

        assert closed.late_entry is False
        with pytest.raises(HTTPException) as excinfo:
            await self._boot(closed)
        assert excinfo.value.status_code == 410

    async def test_reopening_preserves_the_original_allowance(self):
        """The clamp must not destroy the number. „Aline · open" is a 200-seat
        list; reopening it for 3 shrinks the live cap to 89 but has to remember
        that it was 200, or the contingent size is silently gone forever."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=200)
        for _ in range(86):
            await self.invite_service.consume_use(event.id, invite.id)

        reopened = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=89),
        )

        assert reopened.max_uses == 89
        assert reopened.original_max_uses == 200

    async def test_closing_restores_the_original_allowance(self):
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=200)
        for _ in range(86):
            await self.invite_service.consume_use(event.id, invite.id)
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=89),
        )

        closed = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=False),
        )

        assert closed.late_entry is False
        assert closed.max_uses == 200, "the Kontingent must come back intact"
        assert closed.original_max_uses is None
        assert closed.use_count == 86, "restoring must not touch what was used"

    async def test_reopening_twice_keeps_the_true_original(self):
        """A second reopen must not snapshot the already-clamped value — that
        would quietly rewrite 200 into 89 and lose the number after all."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=200)
        for _ in range(86):
            await self.invite_service.consume_use(event.id, invite.id)

        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=89),
        )
        twice = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=91),
        )

        assert twice.max_uses == 91
        assert twice.original_max_uses == 200

    async def test_a_normal_invite_never_gets_a_snapshot(self):
        """Only a clamping reopen snapshots — ordinary edits must leave the
        field alone, or every invite would grow phantom history."""
        event = self._store_event(status=EventStatus.OPEN)
        invite = await self._store_invite(event, max_uses=10)

        updated = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(label="Neuer Name"),
        )

        assert updated.original_max_uses is None


    async def test_reopening_a_spent_personal_link_is_undone_on_close(self):
        """Growth needs the same snapshot as clamping: a used personal invite
        reopened for one more person must go back to being single-use."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1)
        await self.invite_service.consume_use(event.id, invite.id)

        grown = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=2),
        )
        assert grown.max_uses == 2
        assert grown.original_max_uses == 1

        closed = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=False),
        )
        assert closed.max_uses == 1
        assert closed.original_max_uses is None

    async def test_reopened_list_does_not_lock_the_email_field(self):
        """Regression: a reopened Kontingent is `late_entry` AND carries the
        owner's address, so the naive „late_entry and email" rule nailed the
        form to the list owner and made the link unusable for everybody else —
        the second guest would even collide with the duplicate-email check."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=150, email="owner@example.com")
        for _ in range(86):
            await self.invite_service.consume_use(event.id, invite.id)
        reopened = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True, max_uses=89),
        )
        assert reopened.email == "owner@example.com"

        info = await self._boot(reopened)
        assert info.bound_email is None, "a multi-use list must not bind the form"

        # And two DIFFERENT guests can actually use it.
        reg_service = registration_service_module.get_registration_service()
        for address in ("erste@example.com", "zweite@example.com"):
            _, error = await reg_service.create_festival_registration(
                reopened.token, self._create(email=address),
            )
            assert error is None, f"{address} was refused on a reopened list: {error!r}"

    async def test_single_use_late_link_still_binds(self):
        """The binding must survive for the case it was built for."""
        event = self._closed_event()
        invite = await self._store_invite(event, max_uses=1, email="spaet@example.com")
        bound = await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(late_entry=True),
        )

        assert (await self._boot(bound)).bound_email == "spaet@example.com"
