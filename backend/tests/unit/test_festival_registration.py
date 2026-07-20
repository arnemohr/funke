"""Tests for festival registration flows (spec 019 — T108/T109/T110).

Covers:
- T108: create_festival_registration — validation chain order, atomic
  invite consume, release_use on put failure.
- T109: update_festival_attendance (grandfathering, Ä17 approval reset,
  group_members tombstones) + the festival cancel branch (release_use,
  F4 sent from the service, no waitlist promotion).
- T110: defense-in-depth guards (legacy public create, _promote_from_waitlist).

Pattern: RegistrationService/EventService/InviteService wired to moto
tables via `mock_dynamodb`; the email service is mocked (its own template
and queuing behavior is covered by test_email_service.py, T107).
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from app.models import (
    AccommodationType,
    Event,
    EventStatus,
    EventType,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    FestivalSlot,
    InviteBatchCreate,
    InviteCreate,
    InviteUpdate,
    Registration,
    RegistrationCreate,
    RegistrationStatus,
)
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import InviteService
from app.services.registration_service import RegistrationService, _registration_to_item, build_gate_rows

NOW = datetime.now(UTC)


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
        FestivalSlot(key="so", label="Sonntag", date=date(2026, 8, 16)),
    ]


class FestivalTestBase:
    """Shared wiring: real services on moto tables, mocked email service."""

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
            name="Sommerfestival",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=20),
            end_at=NOW + timedelta(days=22),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            status=EventStatus.OPEN,
            autopromote_waitlist=False,
            registration_link_token=None,
            contact_hint="kontakt@fisch.example",
        )
        defaults.update(overrides)
        return Event(**defaults)

    def _store_event(self, event: Event) -> None:
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    async def _make_invite(self, event: Event, **entry_overrides):
        entry_defaults = dict(label="Person A", tier="volunteer", max_uses=1, max_group_size=1)
        entry_defaults.update(entry_overrides)
        batch = InviteBatchCreate(invites=[InviteCreate(**entry_defaults)])
        created = await self.invite_service.create_invites_batch(
            event.org_id, event.id, batch, uuid4(),
        )
        return created[0]


class TestCreateFestivalRegistrationHappyPath(FestivalTestBase):
    @pytest.mark.asyncio
    async def test_happy_path(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_uses=2, max_group_size=3)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr", "sa"],
            group_size=1,
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert error is None
        assert reg is not None
        assert reg.status == RegistrationStatus.PARTICIPATING
        assert reg.responded_at == reg.registered_at
        assert reg.invite_id == invite.id
        assert reg.invite_label == invite.label
        assert reg.tier == invite.tier

        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 1

        self.mock_email_service.send_festival_confirmation.assert_awaited_once()


class TestCreateFestivalRegistrationValidationChain(FestivalTestBase):
    @pytest.mark.asyncio
    async def test_slot_subset_unknown_key_rejected_no_consume(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr", "unknown-slot"],
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert error is not None
        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0

    @pytest.mark.asyncio
    async def test_overnight_tent_without_phone_rejected_service_level(self):
        """Defense-in-depth: schema already requires phone unconditionally;
        this test simulates a caller bypassing the schema (model_copy skips
        validators) to prove the service re-checks it too."""
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr"],
            accommodation=AccommodationType.TENT,
            phone="0176 12345678",
        ).model_copy(update={"phone": None})

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert error is not None
        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0

    @pytest.mark.asyncio
    async def test_camper_with_phone_and_day_only_slots_created(self):
        """Ä15: is_night no longer gates the overnight question at all."""
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr", "sa"],  # day-only slots, no is_night slot chosen
            accommodation=AccommodationType.CAMPER,
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert error is None
        assert reg.accommodation == AccommodationType.CAMPER
        assert reg.phone == "0176 12345678"

    @pytest.mark.asyncio
    async def test_accommodation_none_created_with_phone_kept(self):
        """Phone is required regardless of accommodation — no longer nulled
        out when accommodation is absent."""
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr"],
            accommodation=None,
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert error is None
        assert reg.accommodation is None
        assert reg.phone == "0176 12345678"

    @pytest.mark.asyncio
    async def test_duplicated_slot_key_deduped_and_counted_once(self):
        """Review fix: a raw API payload like ["fr", "fr", "sa"] must not
        double-count in the headcount board — both public schemas dedupe
        preserving order (mirroring RegistrationAdminPatch._clean_slots),
        so get_headcount adds group_size exactly once per slot."""
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_group_size=3)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr", "fr", "sa"],
            group_size=3,
            group_members=["Bert Meier", "Carla Meier"],
            phone="0176 12345678",
        )
        assert data.attendance_slots == ["fr", "sa"]

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert error is None
        assert reg.attendance_slots == ["fr", "sa"]

        headcount = await self.reg_service.get_headcount(event)
        totals = {row["key"]: row["total"] for row in headcount["slots"]}
        assert totals == {"fr": 3, "sa": 3, "so": 0}
        assert headcount["peak_total"] == 3

        # The public self-service edit schema dedupes too.
        patch_payload = FestivalAttendancePatch(attendance_slots=["sa", "sa", "so"])
        assert patch_payload.attendance_slots == ["sa", "so"]

    @pytest.mark.asyncio
    async def test_group_cap_exceeded(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_group_size=2)

        data = FestivalRegistrationCreate(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr"],
            group_size=3,
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert error is not None
        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0

    @pytest.mark.asyncio
    async def test_deadline_passed(self):
        event = self._make_event(registration_deadline=NOW - timedelta(days=1))
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert "deadline" in error.lower()

    @pytest.mark.asyncio
    async def test_event_draft_rejected_as_not_open(self):
        event = self._make_event(status=EventStatus.DRAFT)
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )

        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert "not open" in error.lower()

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected_no_consume(self):
        event = self._make_event()
        self._store_event(event)
        invite1 = await self._make_invite(event, label="Person A")
        invite2 = await self._make_invite(event, label="Person B")

        data1 = FestivalRegistrationCreate(
            name="Anna Meier", email="dup@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg1, error1 = await self.reg_service.create_festival_registration(invite1.token, data1)
        assert error1 is None

        data2 = FestivalRegistrationCreate(
            name="Anna Andere", email="DUP@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg2, error2 = await self.reg_service.create_festival_registration(invite2.token, data2)

        assert reg2 is None
        assert "already registered" in error2.lower()
        refreshed_invite2 = await self.invite_service.get_invite(event.id, invite2.id)
        assert refreshed_invite2.use_count == 0

    @pytest.mark.asyncio
    async def test_exhaustion_race_second_create_fails(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_uses=1)

        data1 = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg1, error1 = await self.reg_service.create_festival_registration(invite.token, data1)
        assert error1 is None

        data2 = FestivalRegistrationCreate(
            name="Ben Otto", email="ben@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg2, error2 = await self.reg_service.create_festival_registration(invite.token, data2)

        assert reg2 is None
        assert "exhausted" in error2.lower()
        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 1

    @pytest.mark.asyncio
    async def test_put_failure_releases_the_use(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        self.reg_service._registrations_table.put_item = lambda **kwargs: (_ for _ in ()).throw(
            ClientError({"Error": {"Code": "InternalServerError", "Message": "boom"}}, "PutItem"),
        )

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)

        assert reg is None
        assert error is not None
        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0


class TestUpdateFestivalAttendance(FestivalTestBase):
    async def _register(self, event, invite, **overrides):
        defaults = dict(
            name="Anna Meier",
            email="anna@example.com",
            attendance_slots=["fr"],
            phone="0176 12345678",
        )
        defaults.update(overrides)
        data = FestivalRegistrationCreate(**defaults)
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)
        assert error is None
        return reg

    @pytest.mark.asyncio
    async def test_slot_edit_succeeds_and_queues_f3(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)
        reg = await self._register(event, invite)

        patch_data = FestivalAttendancePatch(attendance_slots=["sa", "so"])
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, patch_data,
        )

        assert error is None
        assert updated.attendance_slots == ["sa", "so"]
        self.mock_email_service.send_festival_update_confirmation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_edit_after_deadline_rejected_registration_unchanged(self):
        event = self._make_event(registration_deadline=NOW + timedelta(hours=1))
        self._store_event(event)
        invite = await self._make_invite(event)
        reg = await self._register(event, invite)

        # Push the deadline into the past to simulate it passing.
        past_event = event.model_copy(update={"registration_deadline": NOW - timedelta(hours=1)})
        self._store_event(past_event)

        patch_data = FestivalAttendancePatch(attendance_slots=["sa"])
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, patch_data,
        )

        assert updated is None
        assert "deadline" in error.lower()

        unchanged = await self.reg_service.get_registration(event.id, reg.id)
        assert unchanged.attendance_slots == ["fr"]

    @pytest.mark.asyncio
    async def test_grandfathering_keep_succeeds_grow_fails(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_group_size=3)
        reg = await self._register(event, invite, group_size=3)

        # Organizer reduces the invite's allowance after the fact.
        await self.invite_service.update_invite(
            event.id, invite.id, InviteUpdate(max_group_size=1),
        )

        keep_patch = FestivalAttendancePatch(group_size=3)
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, keep_patch,
        )
        assert error is None
        assert updated.group_size == 3

        grow_patch = FestivalAttendancePatch(group_size=4)
        updated2, error2 = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, grow_patch,
        )
        assert updated2 is None
        assert error2 is not None

    @pytest.mark.asyncio
    async def test_a17_reset_on_clearing_accommodation(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)
        reg = await self._register(
            event, invite, accommodation=AccommodationType.TENT, phone="0176 12345678",
        )

        # Simulate an admin approval (T205, out of scope here) directly on
        # the stored item — guests can never set this via any public path.
        approved = reg.model_copy(update={"overnight_approved": True})
        self.tables["registrations_table"].put_item(Item=_registration_to_item(approved))

        clear_patch = FestivalAttendancePatch(accommodation=None)
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, clear_patch,
        )

        assert error is None
        assert updated.overnight_approved is False
        assert updated.phone == "0176 12345678"
        assert updated.accommodation is None

    @pytest.mark.asyncio
    async def test_a17_approval_untouched_when_patching_only_slots(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)
        reg = await self._register(
            event, invite, accommodation=AccommodationType.TENT, phone="0176 12345678",
        )

        approved = reg.model_copy(update={"overnight_approved": True})
        self.tables["registrations_table"].put_item(Item=_registration_to_item(approved))

        slots_patch = FestivalAttendancePatch(attendance_slots=["sa"])
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, slots_patch,
        )

        assert error is None
        assert updated.overnight_approved is True
        assert updated.accommodation == AccommodationType.TENT

    @pytest.mark.asyncio
    async def test_group_members_tombstone_then_append(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_group_size=5)
        reg = await self._register(
            event, invite, group_size=3, group_members=["Anna Meier", "Ben Otto"],
        )

        remove_patch = FestivalAttendancePatch(group_members=[None, "Ben Otto"])
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, remove_patch,
        )
        assert error is None
        assert updated.group_members == [None, "Ben Otto"]
        assert updated.group_size == 2  # contact + 1 non-None member

        append_patch = FestivalAttendancePatch(
            group_members=[None, "Ben Otto", "Cem Demir"],
        )
        updated2, error2 = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, append_patch,
        )
        assert error2 is None
        assert updated2.group_members == [None, "Ben Otto", "Cem Demir"]
        assert updated2.group_size == 3  # contact + 2 non-None members


class TestFestivalCancelBranch(FestivalTestBase):
    @pytest.mark.asyncio
    async def test_cancel_releases_use_and_queues_f4_and_reregister_succeeds(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_uses=1)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)
        assert error is None

        cancelled, cancel_error = await self.reg_service.cancel_registration(
            reg.id, reg.registration_token,
        )
        assert cancel_error is None
        assert cancelled.status == RegistrationStatus.CANCELLED

        self.mock_email_service.send_festival_cancellation.assert_awaited_once()
        self.mock_email_service.send_cancellation_confirmation.assert_not_called()

        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0

        # Same invite, different email, should succeed again.
        data2 = FestivalRegistrationCreate(
            name="Ben Otto", email="ben@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg2, error2 = await self.reg_service.create_festival_registration(invite.token, data2)
        assert error2 is None
        assert reg2 is not None

    @pytest.mark.asyncio
    async def test_cancel_after_deadline_succeeds_keeps_attendance_slots(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr", "sa"],
            phone="0176 12345678",
        )
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)
        assert error is None

        # Deadline has since passed — cancel must still be allowed (Ä5/Ä14).
        past_event = event.model_copy(update={"registration_deadline": NOW - timedelta(days=1)})
        self._store_event(past_event)

        cancelled, cancel_error = await self.reg_service.cancel_registration(
            reg.id, reg.registration_token,
        )

        assert cancel_error is None
        assert cancelled.status == RegistrationStatus.CANCELLED
        assert cancelled.attendance_slots == ["fr", "sa"]

    @pytest.mark.asyncio
    async def test_festival_cancel_triggers_no_waitlist_promotion(self):
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)
        assert error is None

        with patch.object(
            self.reg_service, "_promote_from_waitlist", new=AsyncMock(),
        ) as mock_promote:
            cancelled, cancel_error = await self.reg_service.cancel_registration(
                reg.id, reg.registration_token,
            )
            assert cancel_error is None
            mock_promote.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_cancel_path_reuses_same_service_method_and_effects(self):
        """T203: the admin festival router has no second cancel implementation.

        It only knows a `registration_id` (no token), so it looks the
        registration up first and then calls the very same
        `cancel_registration(registration_id, token)` the public cancel
        flow (and the tests above) exercise — same F4 send, same invite
        release, same status flip. This simulates exactly what
        `cancel_festival_registration` in `api/admin/festival.py` does.
        """
        event = self._make_event()
        self._store_event(event)
        invite = await self._make_invite(event, max_uses=1)

        data = FestivalRegistrationCreate(
            name="Anna Meier", email="anna@example.com", attendance_slots=["fr"],
            phone="0176 12345678",
        )
        reg, error = await self.reg_service.create_festival_registration(invite.token, data)
        assert error is None

        # Admin path: fetch by ID (no token known), then delegate to the
        # same service method — no admin-only cancel branch anywhere.
        looked_up = await self.reg_service.get_registration(event.id, reg.id)
        assert looked_up is not None

        cancelled, cancel_error = await self.reg_service.cancel_registration(
            looked_up.id, looked_up.registration_token,
        )

        assert cancel_error is None
        assert cancelled.status == RegistrationStatus.CANCELLED
        self.mock_email_service.send_festival_cancellation.assert_awaited_once()
        self.mock_email_service.send_cancellation_confirmation.assert_not_called()

        refreshed_invite = await self.invite_service.get_invite(event.id, invite.id)
        assert refreshed_invite.use_count == 0

        # Cancelling again (already-CANCELLED) surfaces a "cannot cancel"
        # error string — the admin router maps this to 400, not 500.
        _, second_error = await self.reg_service.cancel_registration(
            looked_up.id, looked_up.registration_token,
        )
        assert second_error is not None
        assert "cannot cancel" in second_error.lower()


class TestDefenseInDepthGuards(FestivalTestBase):
    """T110: legacy public create + _promote_from_waitlist guards."""

    @pytest.mark.asyncio
    async def test_legacy_create_registration_rejects_festival_event(self):
        # Dead by construction (festivals never get a link token) — but
        # guarded explicitly anyway; force one on to exercise the guard.
        event = self._make_event(
            registration_link_token="artificial-festival-link-token",  # noqa: S106
        )
        self._store_event(event)

        reg_data = RegistrationCreate(name="Anna Meier", email="anna@example.com")
        reg, error = await self.reg_service.create_registration(
            "artificial-festival-link-token", reg_data,
        )

        assert reg is None
        assert "not open" in error.lower()

    @pytest.mark.asyncio
    async def test_promote_from_waitlist_promotes_nobody_for_festival_even_if_forced_on(self):
        event = self._make_event(autopromote_waitlist=True)  # forced on, should still be inert
        self._store_event(event)

        promoted = await self.reg_service._promote_from_waitlist(event.id, available_spots=10)

        assert promoted == []


def _make_gate_registration(event_id, **overrides) -> Registration:
    """Build a Registration for build_gate_rows tests (pure model, no DB)."""
    defaults = dict(
        id=uuid4(),
        event_id=event_id,
        name="Zora Zimmer",
        email="zora@example.com",
        registration_token="tok-" + uuid4().hex,
        status=RegistrationStatus.PARTICIPATING,
        invite_label="Welle 2",
        tier="volunteer",
        attendance_slots=["fr"],
    )
    defaults.update(overrides)
    return Registration(**defaults)


class TestBuildGateRows:
    """T113: build_gate_rows — pure gate-CSV row builder (Ä9 floor)."""

    def _event(self) -> Event:
        return Event(
            id=uuid4(),
            org_id=uuid4(),
            name="Sommerfestival",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=20),
            end_at=NOW + timedelta(days=22),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            status=EventStatus.OPEN,
        )

    def test_group_expands_to_one_row_per_person_sorted_alphabetically(self):
        event = self._event()
        reg = _make_gate_registration(
            event.id,
            name="Bruno Beck",
            group_size=3,
            group_members=["Anna Adler", "Carla Croft"],
        )
        rows = build_gate_rows([reg], event)

        assert [row["Name"] for row in rows] == ["Anna Adler", "Bruno Beck", "Carla Croft"]
        assert all(row["Kontaktperson"] == "Bruno Beck" for row in rows)

    def test_cancelled_registration_yields_no_rows(self):
        event = self._event()
        reg = _make_gate_registration(event.id, status=RegistrationStatus.CANCELLED)

        rows = build_gate_rows([reg], event)

        assert rows == []

    def test_slot_columns_match_festival_slots_order_and_ticks(self):
        event = self._event()
        reg = _make_gate_registration(event.id, attendance_slots=["sa"])

        rows = build_gate_rows([reg], event)

        assert list(rows[0].keys())[6:9] == ["Freitag", "Samstag", "Sonntag"]
        assert rows[0]["Freitag"] == ""
        assert rows[0]["Samstag"] == "x"
        assert rows[0]["Sonntag"] == ""
        assert rows[0]["Angekommen"] == ""
        assert rows[0]["Bändchen"] == ""

    def test_schlafplatz_states_and_telefon_only_when_overnight(self):
        event = self._event()

        no_overnight = _make_gate_registration(event.id, accommodation=None, phone=None)
        tent_requested = _make_gate_registration(
            event.id, accommodation=AccommodationType.TENT, overnight_approved=False, phone="0123",
        )
        tent_approved = _make_gate_registration(
            event.id, accommodation=AccommodationType.TENT, overnight_approved=True, phone="0123",
        )
        camper_requested = _make_gate_registration(
            event.id, accommodation=AccommodationType.CAMPER, overnight_approved=False, phone="0456",
        )
        camper_approved = _make_gate_registration(
            event.id, accommodation=AccommodationType.CAMPER, overnight_approved=True, phone="0456",
        )

        rows = {
            reg.id: build_gate_rows([reg], event)[0]
            for reg in [no_overnight, tent_requested, tent_approved, camper_requested, camper_approved]
        }

        assert rows[no_overnight.id]["Schlafplatz"] == "Nein"
        assert rows[no_overnight.id]["Telefon"] == ""
        assert rows[tent_requested.id]["Schlafplatz"] == "Zelt — angefragt"
        assert rows[tent_requested.id]["Telefon"] == "0123"
        assert rows[tent_approved.id]["Schlafplatz"] == "Zelt — zugesagt"
        assert rows[camper_requested.id]["Schlafplatz"] == "Camper — angefragt"
        assert rows[camper_approved.id]["Schlafplatz"] == "Camper — zugesagt"

    def test_tombstoned_group_member_yields_no_row(self):
        event = self._event()
        reg = _make_gate_registration(
            event.id,
            name="Dana Duft",
            group_size=3,
            group_members=["Erik Ecke", None],
        )

        rows = build_gate_rows([reg], event)

        assert [row["Name"] for row in rows] == ["Dana Duft", "Erik Ecke"]
