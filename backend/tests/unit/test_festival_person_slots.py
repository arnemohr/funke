"""Per-person attendance days (spec 021).

The headline property is **backwards compatibility**: with no overrides set,
headcount, gate rows and signed QR payloads must be byte-identical to pre-021
behaviour. That is what lets per-person counting ship without any organiser
seeing a number move, so it is asserted against explicitly-constructed expected
values rather than a snapshot of the new code.

Everything else here is the new surface: overrides, the companion's own-days
edit, and companion self-cancellation.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import (
    Event,
    EventStatus,
    EventType,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    FestivalSlot,
    InviteBatchCreate,
    InviteCreate,
    Registration,
    RegistrationAdminPatch,
    RegistrationStatus,
)
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import InviteService
from app.services.registration_service import (
    RegistrationService,
    _registration_to_item,
    build_gate_rows,
)
from app.services.ticket_signing import person_page_token, verify_ticket

NOW = datetime.now(UTC)


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
        FestivalSlot(key="so", label="Sonntag", date=date(2026, 8, 16)),
    ]


def _registration(**overrides) -> Registration:
    defaults = {
        "event_id": uuid4(),
        "name": "Anna Schmidt",
        "email": "anna@example.de",
        "phone": "0176 1234567",
        "group_size": 1,
        "registration_token": "regtoken-" + uuid4().hex,
        "status": RegistrationStatus.PARTICIPATING,
        "attendance_slots": ["fr", "sa"],
    }
    defaults.update(overrides)
    return Registration(**defaults)


class TestEffectiveMemberSlots:
    """The single reader every consumer goes through."""

    def test_falls_back_to_the_group_grid(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2)
        assert reg.effective_member_slots(0) == ["fr", "sa"]
        assert reg.effective_member_slots(1) == ["fr", "sa"]

    def test_override_wins_for_that_person_only(self):
        reg = _registration(
            group_members=["Lisa Meier", "Tim Bach"],
            group_size=3,
            member_slots={"1": ["fr"]},
        )
        assert reg.effective_member_slots(0) == ["fr", "sa"]
        assert reg.effective_member_slots(1) == ["fr"]
        assert reg.effective_member_slots(2) == ["fr", "sa"]

    def test_contact_can_have_an_override_too(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2, member_slots={"0": ["so"]})
        assert reg.effective_member_slots(0) == ["so"]


class TestMemberSlotsNormalisation:
    def test_override_equal_to_the_group_grid_is_dropped(self):
        """Keeps the map to genuine differences, so it stays answerable."""
        reg = _registration(
            group_members=["Lisa Meier"], group_size=2, member_slots={"1": ["fr", "sa"]},
        )
        assert reg.member_slots is None

    def test_override_on_a_tombstone_is_dropped(self):
        reg = _registration(
            group_members=[None], group_size=1, member_slots={"1": ["fr"]},
        )
        assert reg.member_slots is None

    def test_out_of_range_index_is_dropped(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2, member_slots={"7": ["fr"]})
        assert reg.member_slots is None

    def test_non_integer_key_is_dropped(self):
        reg = _registration(
            group_members=["Lisa Meier"], group_size=2, member_slots={"abc": ["fr"]},
        )
        assert reg.member_slots is None

    def test_empty_override_is_dropped(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2, member_slots={"1": []})
        assert reg.member_slots is None

    def test_duplicate_keys_within_an_override_are_deduped(self):
        reg = _registration(
            group_members=["Lisa Meier"], group_size=2, member_slots={"1": ["fr", "fr"]},
        )
        assert reg.member_slots == {"1": ["fr"]}

    def test_survives_a_storage_round_trip(self, mock_dynamodb):
        service = RegistrationService()
        service._registrations_table = mock_dynamodb["registrations_table"]

        reg = _registration(
            id=uuid4(),
            group_members=["Lisa Meier", "Tim Bach"],
            group_size=3,
            member_slots={"1": ["fr"], "2": ["so"]},
        )
        item = _registration_to_item(reg)
        service._registrations_table.put_item(Item=item)

        from app.services.registration_service import _item_to_registration

        loaded = _item_to_registration(
            service._registrations_table.get_item(
                Key={"pk": item["pk"], "sk": item["sk"]},
            )["Item"],
        )
        assert loaded.member_slots == {"1": ["fr"], "2": ["so"]}

    def test_absent_on_a_legacy_item(self):
        reg = _registration(group_members=["Lisa Meier"], group_size=2)
        assert "member_slots" not in _registration_to_item(reg)


class PersonSlotsBase:
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
            name="Betriebsfeier",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=20),
            end_at=NOW + timedelta(days=22),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            status=EventStatus.OPEN,
            autopromote_waitlist=False,
            registration_link_token=None,
            contact_hint="festival@example.de",
            capacity=1000,
        )
        defaults.update(overrides)
        event = Event(**defaults)
        self.tables["events_table"].put_item(Item=_event_to_item(event))
        return event

    async def _make_invite(self, event: Event, **overrides):
        entry = dict(label="Anna", tier="volunteer", max_uses=5, max_group_size=5)
        entry.update(overrides)
        created = await self.invite_service.create_invites_batch(
            event.org_id, event.id, InviteBatchCreate(invites=[InviteCreate(**entry)]), uuid4(),
        )
        return created[0]

    async def _register(self, invite, **overrides):
        defaults = dict(
            name="Anna Schmidt",
            email="anna@example.de",
            attendance_slots=["fr", "sa"],
            phone="0176 1234567",
        )
        defaults.update(overrides)
        return await self.reg_service.create_festival_registration(
            invite.token, FestivalRegistrationCreate(**defaults),
        )

    async def _group_of_three(self):
        event = self._make_event()
        invite = await self._make_invite(event)
        reg, error = await self._register(
            invite,
            group_size=3,
            group_members=["Lisa Meier", "Tim Bach"],
            group_member_emails=["lisa@example.de", "tim@example.de"],
        )
        assert error is None
        self.mock_email_service.reset_mock()
        return event, reg

    def _token(self, reg, person_index, email):
        return person_page_token(reg.registration_token, person_index, email)


class TestBackwardsCompatibility(PersonSlotsBase):
    """With no overrides, every derived number must be what it was pre-021."""

    @pytest.mark.asyncio
    async def test_headcount_counts_group_size_per_group_slot(self):
        event, _ = await self._group_of_three()

        board = await self.reg_service.get_headcount(event)
        by_key = {row["key"]: row for row in board["slots"]}

        # 3 people on both declared days, 0 on the undeclared one — exactly the
        # pre-021 "add group_size to every ticked slot" arithmetic.
        assert by_key["fr"]["total"] == 3
        assert by_key["sa"]["total"] == 3
        assert by_key["so"]["total"] == 0
        assert by_key["fr"]["by_tier"] == {"volunteer": 3}

    @pytest.mark.asyncio
    async def test_headcount_unchanged_for_a_group_without_member_names(self):
        """A group_size=3 row with group_members=None is a legitimate old row —
        counting live member entries alone would undercount it to 1."""
        event = self._make_event()
        reg = _registration(
            id=uuid4(), event_id=event.id, group_size=3, tier="werft", attendance_slots=["fr"],
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

        board = await self.reg_service.get_headcount(event)
        by_key = {row["key"]: row for row in board["slots"]}
        assert by_key["fr"]["total"] == 3
        assert by_key["fr"]["by_tier"] == {"werft": 3}

    @pytest.mark.asyncio
    async def test_gate_rows_show_the_group_grid_for_everyone(self):
        event, reg = await self._group_of_three()

        rows = build_gate_rows([reg], event)

        assert len(rows) == 3
        for row in rows:
            assert row["Freitag"] == "x"
            assert row["Samstag"] == "x"
            assert row["Sonntag"] == ""


class TestOverridesChangeOnlyTheirOwner(PersonSlotsBase):
    @pytest.mark.asyncio
    async def test_headcount_splits_by_person(self):
        event, reg = await self._group_of_three()

        # Lisa (index 1) only comes on Friday.
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(member_slots={"1": ["fr"]}),
        )
        assert error is None
        assert updated.member_slots == {"1": ["fr"]}

        board = await self.reg_service.get_headcount(event)
        by_key = {row["key"]: row for row in board["slots"]}
        assert by_key["fr"]["total"] == 3  # everyone
        assert by_key["sa"]["total"] == 2  # Lisa dropped Saturday

    @pytest.mark.asyncio
    async def test_gate_rows_show_each_persons_own_days(self):
        event, reg = await self._group_of_three()
        updated, _ = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(member_slots={"1": ["fr"]}),
        )

        rows = {row["Name"]: row for row in build_gate_rows([updated], event)}
        assert rows["Lisa Meier"]["Samstag"] == ""
        assert rows["Lisa Meier"]["Freitag"] == "x"
        assert rows["Tim Bach"]["Samstag"] == "x"
        assert rows["Anna Schmidt"]["Samstag"] == "x"

    @pytest.mark.asyncio
    async def test_unknown_slot_key_rejected(self):
        _, reg = await self._group_of_three()
        updated, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(member_slots={"1": ["nope"]}),
        )
        assert updated is None
        assert error == "Unknown attendance slot selected"

    @pytest.mark.asyncio
    async def test_admin_patch_can_set_overrides_mail_silently(self):
        event, reg = await self._group_of_three()

        updated, error = await self.reg_service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(member_slots={"2": ["so"]}),
        )

        assert error is None
        assert updated.member_slots == {"2": ["so"]}
        self.mock_email_service.send_festival_update_confirmation.assert_not_awaited()


class TestCompanionSetsOwnSlots(PersonSlotsBase):
    @pytest.mark.asyncio
    async def test_companion_sets_their_own_days(self):
        event, reg = await self._group_of_three()

        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["so"],
        )

        assert error is None
        assert updated.effective_member_slots(1) == ["so"]
        # Nobody else moved.
        assert updated.effective_member_slots(0) == ["fr", "sa"]
        assert updated.effective_member_slots(2) == ["fr", "sa"]

    @pytest.mark.asyncio
    async def test_no_mail_is_sent(self):
        event, reg = await self._group_of_three()
        await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["so"],
        )
        self.mock_email_service.send_festival_update_confirmation.assert_not_awaited()
        self.mock_email_service.send_festival_companion_left.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_another_persons_token_cannot_set_my_days(self):
        event, reg = await self._group_of_three()

        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 2, self._token(reg, 1, "lisa@example.de"), ["so"],
        )

        assert updated is None
        assert error == "not found"

    @pytest.mark.asyncio
    async def test_contact_index_is_not_reachable(self):
        """person_index 0 is the contact — they use the manage page."""
        event, reg = await self._group_of_three()
        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 0, self._token(reg, 0, "anna@example.de"), ["so"],
        )
        assert updated is None
        assert error == "not found"

    @pytest.mark.asyncio
    async def test_unknown_slot_rejected(self):
        event, reg = await self._group_of_three()
        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["nope"],
        )
        assert updated is None
        assert error == "Unknown attendance slot selected"

    @pytest.mark.asyncio
    async def test_refused_after_the_deadline(self):
        event = self._make_event(
            registration_deadline=NOW - timedelta(minutes=1),
            start_at=NOW - timedelta(days=2),
            end_at=NOW - timedelta(minutes=1),
        )
        invite = await self._make_invite(event)
        reg = _registration(
            id=uuid4(),
            event_id=event.id,
            group_members=["Lisa Meier"],
            group_member_emails=["lisa@example.de"],
            group_size=2,
            invite_id=invite.id,
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["so"],
        )
        assert updated is None
        assert error == "deadline"

    @pytest.mark.asyncio
    async def test_ticket_payload_carries_the_persons_own_days(self):
        event, reg = await self._group_of_three()
        await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["so"],
        )

        from app.api.public.registrations import get_person_ticket

        with patch(
            "app.api.public.registrations.get_registration_service",
            return_value=self.reg_service,
        ), patch(
            "app.api.public.registrations.get_event_service",
            return_value=self.event_service,
        ):
            result = await get_person_ticket(
                event_id=event.id,
                registration_id=reg.id,
                person_index=1,
                token=self._token(reg, 1, "lisa@example.de"),
            )

        assert result.own_slots == ["so"]
        assert result.slot_labels == ["Sonntag"]
        stored = await self.event_service.get_event_by_id(event.id)
        assert verify_ticket(stored.ticket_secret, result.ticket_code)["s"] == ["so"]


class TestCompanionSelfCancel(PersonSlotsBase):
    @pytest.mark.asyncio
    async def test_removes_only_that_person(self):
        event, reg = await self._group_of_three()

        updated, error = await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        assert error is None
        assert updated.group_members == [None, "Tim Bach"]
        assert updated.group_member_emails == [None, "tim@example.de"]
        assert updated.group_size == 2

    @pytest.mark.asyncio
    async def test_later_companion_keeps_their_index_and_ticket(self):
        """Index stability: Tim's already-issued QR must stay valid."""
        event, reg = await self._group_of_three()
        await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        from app.api.public.registrations import get_person_ticket

        with patch(
            "app.api.public.registrations.get_registration_service",
            return_value=self.reg_service,
        ), patch(
            "app.api.public.registrations.get_event_service",
            return_value=self.event_service,
        ):
            result = await get_person_ticket(
                event_id=event.id,
                registration_id=reg.id,
                person_index=2,
                token=self._token(reg, 2, "tim@example.de"),
            )
        assert result.person_index == 2
        assert result.name == "Tim Bach"

    @pytest.mark.asyncio
    async def test_their_own_page_dies_with_them(self):
        event, reg = await self._group_of_three()
        lisas_token = self._token(reg, 1, "lisa@example.de")
        await self.reg_service.cancel_person(event.id, reg.id, 1, lisas_token)

        from app.api.public.registrations import get_person_ticket

        with patch(
            "app.api.public.registrations.get_registration_service",
            return_value=self.reg_service,
        ), patch(
            "app.api.public.registrations.get_event_service",
            return_value=self.event_service,
        ), pytest.raises(HTTPException) as exc:
            await get_person_ticket(
                event_id=event.id,
                registration_id=reg.id,
                person_index=1,
                token=lisas_token,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_contact_is_notified(self):
        event, reg = await self._group_of_three()

        await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        call = self.mock_email_service.send_festival_companion_left.await_args
        assert call is not None
        assert call.args[2] == "Lisa Meier"

    @pytest.mark.asyncio
    async def test_invite_use_count_is_untouched(self):
        """A use is one REGISTRATION, not one seat (spec 019 §Invite)."""
        event, reg = await self._group_of_three()
        invite_id = reg.invite_id
        before = (await self.invite_service.get_invite(event.id, invite_id)).use_count

        await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        after = (await self.invite_service.get_invite(event.id, invite_id)).use_count
        assert after == before

    @pytest.mark.asyncio
    async def test_headcount_drops_by_exactly_one(self):
        event, reg = await self._group_of_three()
        await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        board = await self.reg_service.get_headcount(event)
        by_key = {row["key"]: row for row in board["slots"]}
        assert by_key["fr"]["total"] == 2
        assert by_key["sa"]["total"] == 2

    @pytest.mark.asyncio
    async def test_their_override_is_dropped(self):
        event, reg = await self._group_of_three()
        await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["so"],
        )
        updated, error = await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )
        assert error is None
        assert (updated.member_slots or {}).get("1") is None

    @pytest.mark.asyncio
    async def test_another_persons_token_cannot_remove_me(self):
        event, reg = await self._group_of_three()
        updated, error = await self.reg_service.cancel_person(
            event.id, reg.id, 2, self._token(reg, 1, "lisa@example.de"),
        )
        assert updated is None
        assert error == "not found"

    @pytest.mark.asyncio
    async def test_cannot_be_used_twice(self):
        event, reg = await self._group_of_three()
        token = self._token(reg, 1, "lisa@example.de")
        await self.reg_service.cancel_person(event.id, reg.id, 1, token)

        updated, error = await self.reg_service.cancel_person(event.id, reg.id, 1, token)
        assert updated is None
        assert error == "not found"

    @pytest.mark.asyncio
    async def test_the_gate_no_longer_issues_their_ticket(self):
        event, reg = await self._group_of_three()
        await self.reg_service.cancel_person(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"),
        )

        from app.services.ticket_signing import build_person_tickets

        # The event needs its ticket_secret; the live paths get it via the
        # endpoint's ensure_gate_credentials call.
        stored_event = await self.event_service.ensure_gate_credentials(event.org_id, event.id)
        stored = await self.reg_service.get_registration(event.id, reg.id)
        indices = {
            t.person_index
            for t in build_person_tickets(
                stored_event.ticket_secret,
                stored.id,
                stored.name,
                stored.group_members,
                stored.attendance_slots,
                stored.overnight_approved,
                stored.member_slots,
            )
        }
        assert indices == {0, 2}


class TestManagePageRoundTrip(PersonSlotsBase):
    """Regression: the manage page must LOAD the overrides it sends back.

    `get_registration_manage` once built its `RegistrationResponse` from an
    explicit kwarg list that omitted `member_slots`. The page seeds its editable
    map from that field and posts the whole map on save, so the omission did not
    merely hide the days — the next save sent `{}` and deleted every override a
    companion had set for themselves.
    """

    async def _manage(self, reg):
        from app.api.public.registrations import get_registration_manage

        # `get_invite_service` is imported inside the handler, so the base
        # class's source-level patch already covers it — patching it here would
        # fail with AttributeError.
        with patch(
            "app.api.public.registrations.get_registration_service",
            return_value=self.reg_service,
        ), patch(
            "app.api.public.registrations.get_event_service",
            return_value=self.event_service,
        ):
            return await get_registration_manage(
                registration_id=reg.id, token=reg.registration_token,
            )

    @pytest.mark.asyncio
    async def test_manage_response_carries_member_slots(self):
        event, reg = await self._group_of_three()
        updated, error = await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["sa"],
        )
        assert error is None
        assert updated.member_slots == {"1": ["sa"]}

        result = await self._manage(reg)

        assert result.registration.member_slots == {"1": ["sa"]}, (
            "manage page cannot see the override it will send back -> next save wipes it"
        )

    @pytest.mark.asyncio
    async def test_unrelated_save_preserves_overrides(self):
        """What the frontend actually does: load, then save an unrelated field.

        The page derives its patch from what the GET returned, so if the GET is
        complete this round-trip has to be lossless.
        """
        event, reg = await self._group_of_three()
        await self.reg_service.set_person_slots(
            event.id, reg.id, 1, self._token(reg, 1, "lisa@example.de"), ["sa"],
        )

        loaded = await self._manage(reg)
        # Exactly the map the page would rebuild from the loaded state.
        patch_body = FestivalAttendancePatch(
            phone="+49 170 9999999",
            member_slots=loaded.registration.member_slots,
        )
        saved, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, patch_body,
        )

        assert error is None
        assert saved.member_slots == {"1": ["sa"]}
        assert saved.effective_member_slots(1) == ["sa"]


class TestSelfCancelClampsOvernight(PersonSlotsBase):
    """Regression: a shrinking group must not persist an oversized pitch count.

    Both patch paths validate `tent_count <= group_size` against the RESULTING
    state, so an unclamped count locks the registration out of every later
    edit — the organizer's approval toggle AND the contact's own manage page.
    """

    @pytest.mark.asyncio
    async def test_counts_follow_the_group_down(self):
        event, reg = await self._group_of_three()
        reg, error = await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(tent_count=3, phone="+49 170 1111111"),
        )
        assert error is None
        assert reg.tent_count == 3 and reg.group_size == 3

        for idx, addr in ((1, "lisa@example.de"), (2, "tim@example.de")):
            _, err = await self.reg_service.cancel_person(
                event.id, reg.id, idx, self._token(reg, idx, addr),
            )
            assert err is None

        after = await self.reg_service.get_registration(event.id, reg.id)
        assert after.group_size == 1
        assert after.tent_count == 1, "tent_count outgrew the group -> edits now rejected"

    @pytest.mark.asyncio
    async def test_registration_stays_editable_afterwards(self):
        event, reg = await self._group_of_three()
        await self.reg_service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(tent_count=3, phone="+49 170 1111111"),
        )
        for idx, addr in ((1, "lisa@example.de"), (2, "tim@example.de")):
            await self.reg_service.cancel_person(
                event.id, reg.id, idx, self._token(reg, idx, addr),
            )

        # The contact's own manage page still works...
        _, error = await self.reg_service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(attendance_slots=["sa"]),
        )
        assert error is None, f"guest locked out of their own registration: {error!r}"

        # ...and so does the organizer's approval toggle.
        from app.models import RegistrationAdminPatch

        _, error = await self.reg_service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )
        assert error is None, f"organizer locked out of the approval toggle: {error!r}"
