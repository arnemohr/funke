"""Tests for festival sidetrack (spec 019) model additions.

Covers T102 (Event model: EventType, FestivalSlot, festival fields, capacity
validator) and is extended by later tasks (T103 persistence, T106 registration
model) for their own festival-related model behavior.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import (
    AccommodationType,
    Event,
    EventCreate,
    EventStatus,
    EventType,
    EventUpdate,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    FestivalSlot,
    Registration,
    RegistrationStatus,
)
from app.services.event_service import EventService, _event_to_item, _item_to_event
from app.services.registration_service import _item_to_registration, _registration_to_item

NOW = datetime.now(UTC)


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr-abend", label="Fr Abend", date=date(2026, 8, 14), is_night=True),
        FestivalSlot(key="sa-tag", label="Sa Tag", date=date(2026, 8, 15)),
        FestivalSlot(key="sa-abend", label="Sa Abend", date=date(2026, 8, 15), is_night=True),
    ]


def _base_kwargs(**overrides) -> dict:
    defaults = {
        "name": "Sommerfestival",
        "start_at": NOW + timedelta(days=30),
        "registration_deadline": NOW + timedelta(days=20),
    }
    defaults.update(overrides)
    return defaults


class TestEventFestivalFields:
    """T102 acceptance: EventType/FestivalSlot/capacity validator on the Event model."""

    def test_default_event_type_is_single(self):
        event = EventCreate(**_base_kwargs())
        assert event.event_type == EventType.SINGLE

    def test_single_capacity_over_500_rejected(self):
        with pytest.raises(ValidationError):
            EventCreate(**_base_kwargs(capacity=501))

    def test_single_capacity_500_accepted(self):
        event = EventCreate(**_base_kwargs(capacity=500))
        assert event.capacity == 500

    def test_festival_capacity_1500_accepted(self):
        event = EventCreate(
            **_base_kwargs(
                capacity=1500,
                event_type=EventType.FESTIVAL,
                end_at=NOW + timedelta(days=32),
                festival_slots=_slots(),
            ),
        )
        assert event.capacity == 1500

    def test_festival_capacity_2001_rejected(self):
        with pytest.raises(ValidationError):
            EventCreate(
                **_base_kwargs(
                    capacity=2001,
                    event_type=EventType.FESTIVAL,
                    end_at=NOW + timedelta(days=32),
                    festival_slots=_slots(),
                ),
            )

    def test_festival_without_slots_rejected(self):
        with pytest.raises(ValidationError):
            EventCreate(
                **_base_kwargs(
                    event_type=EventType.FESTIVAL,
                    end_at=NOW + timedelta(days=32),
                ),
            )

    def test_festival_duplicate_slot_keys_rejected(self):
        slots = _slots()
        slots[1] = slots[1].model_copy(update={"key": slots[0].key})
        with pytest.raises(ValidationError):
            EventCreate(
                **_base_kwargs(
                    event_type=EventType.FESTIVAL,
                    end_at=NOW + timedelta(days=32),
                    festival_slots=slots,
                ),
            )

    def test_festival_unsorted_slot_dates_rejected(self):
        slots = list(reversed(_slots()))
        with pytest.raises(ValidationError):
            EventCreate(
                **_base_kwargs(
                    event_type=EventType.FESTIVAL,
                    end_at=NOW + timedelta(days=32),
                    festival_slots=slots,
                ),
            )

    def test_festival_requires_end_at(self):
        with pytest.raises(ValidationError):
            EventCreate(
                **_base_kwargs(
                    event_type=EventType.FESTIVAL,
                    festival_slots=_slots(),
                ),
            )

    def test_festival_missing_registration_deadline_defaults_to_end_at(self):
        # Ä14/Ä20: the "Anmeldeschluss" input was removed from the admin UI —
        # a festival create omitting registration_deadline no longer fails,
        # it defaults to end_at.
        end_at = NOW + timedelta(days=32)
        kwargs = _base_kwargs(
            event_type=EventType.FESTIVAL,
            end_at=end_at,
            festival_slots=_slots(),
        )
        del kwargs["registration_deadline"]
        event = EventCreate(**kwargs)
        assert event.registration_deadline == end_at

    def test_festival_missing_both_deadline_and_end_at_rejected(self):
        kwargs = _base_kwargs(
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
        )
        del kwargs["registration_deadline"]
        with pytest.raises(ValidationError):
            EventCreate(**kwargs)

    def test_single_without_end_at_or_slots_still_parses(self):
        event = EventCreate(**_base_kwargs())
        assert event.end_at is None
        assert event.festival_slots is None

    def test_participation_hint_roundtrips_on_create(self):
        event = EventCreate(**_base_kwargs(participation_hint="Schichtplan: https://example.com/schicht"))
        assert event.participation_hint == "Schichtplan: https://example.com/schicht"

    def test_participation_hint_roundtrips_on_update(self):
        update = EventUpdate(participation_hint="Schichtplan: https://example.com/schicht")
        assert update.participation_hint == "Schichtplan: https://example.com/schicht"

    def _festival_event(self) -> Event:
        return Event(
            id=uuid4(),
            org_id=uuid4(),
            name="Sommerfestival",
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=32),
            end_at=NOW + timedelta(days=32),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
        )

    def test_slot_keys(self):
        event = self._festival_event()
        assert event.slot_keys() == ["fr-abend", "sa-tag", "sa-abend"]

    def test_night_slots(self):
        event = self._festival_event()
        night = event.night_slots()
        assert {s.key for s in night} == {"fr-abend", "sa-abend"}

    def test_slots_on(self):
        event = self._festival_event()
        assert {s.key for s in event.slots_on(date(2026, 8, 15))} == {"sa-tag", "sa-abend"}
        assert event.slots_on(date(2026, 8, 16)) == []

    def test_slot_helpers_empty_safe_without_slots(self):
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            name="Single Event",
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=20),
            status=EventStatus.OPEN,
        )
        assert event.slot_keys() == []
        assert event.night_slots() == []
        assert event.slots_on(date(2026, 8, 15)) == []


class TestEventUpdateFestivalFields:
    """EventUpdate mirrors EventCreate's capacity/slot validators (T102)."""

    def test_empty_festival_slots_rejected(self):
        with pytest.raises(ValidationError):
            EventUpdate(event_type=EventType.FESTIVAL, festival_slots=[])

    def test_duplicate_festival_slots_rejected(self):
        slots = _slots()
        slots[1] = slots[1].model_copy(update={"key": slots[0].key})
        with pytest.raises(ValidationError):
            EventUpdate(event_type=EventType.FESTIVAL, festival_slots=slots)

    def test_unsorted_festival_slots_rejected(self):
        with pytest.raises(ValidationError):
            EventUpdate(event_type=EventType.FESTIVAL, festival_slots=list(reversed(_slots())))

    def test_valid_festival_slots_accepted(self):
        update = EventUpdate(
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            registration_deadline=NOW + timedelta(days=32),
            end_at=NOW + timedelta(days=32),
        )
        assert update.festival_slots is not None
        assert len(update.festival_slots) == 3

    def test_capacity_checked_only_when_both_fields_present(self):
        # capacity alone (no event_type) can't be checked against a cap here.
        update = EventUpdate(capacity=1500)
        assert update.capacity == 1500

    def test_capacity_over_single_cap_rejected_when_event_type_present(self):
        with pytest.raises(ValidationError):
            EventUpdate(event_type=EventType.SINGLE, capacity=501)

    def test_capacity_within_festival_cap_accepted(self):
        update = EventUpdate(
            event_type=EventType.FESTIVAL,
            capacity=1500,
            festival_slots=_slots(),
            registration_deadline=NOW + timedelta(days=32),
            end_at=NOW + timedelta(days=32),
        )
        assert update.capacity == 1500

    def test_festival_requires_end_at(self):
        with pytest.raises(ValidationError):
            EventUpdate(
                event_type=EventType.FESTIVAL,
                festival_slots=_slots(),
                registration_deadline=NOW + timedelta(days=32),
            )

    def test_festival_missing_registration_deadline_defaults_to_end_at(self):
        # Ä14/Ä20: a festival update omitting registration_deadline no
        # longer fails, it defaults to end_at.
        end_at = NOW + timedelta(days=32)
        update = EventUpdate(
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            end_at=end_at,
        )
        assert update.registration_deadline == end_at

    def test_festival_missing_both_deadline_and_end_at_rejected(self):
        with pytest.raises(ValidationError):
            EventUpdate(
                event_type=EventType.FESTIVAL,
                festival_slots=_slots(),
            )

    def test_festival_with_both_deadline_and_end_at_accepted(self):
        update = EventUpdate(
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            registration_deadline=NOW + timedelta(days=32),
            end_at=NOW + timedelta(days=32),
        )
        assert update.event_type == EventType.FESTIVAL


class TestFestivalEventPersistence:
    """T103: _event_to_item / _item_to_event round-trip festival fields."""

    def _festival_event(self, **overrides) -> Event:
        defaults = {
            "id": uuid4(),
            "org_id": uuid4(),
            "name": "Sommerfestival",
            "start_at": NOW + timedelta(days=30),
            "registration_deadline": NOW + timedelta(days=32),
            "end_at": NOW + timedelta(days=32),
            "event_type": EventType.FESTIVAL,
            "festival_slots": _slots(),
            "contact_hint": "kontakt@fisch.example",
            "participation_hint": "Schichtplan: https://example.com/schicht",
            "status": EventStatus.OPEN,
        }
        defaults.update(overrides)
        return Event(**defaults)

    def test_festival_event_roundtrips_through_item(self):
        event = self._festival_event()
        item = _event_to_item(event)
        restored = _item_to_event(item)

        assert restored.event_type == EventType.FESTIVAL
        assert restored.end_at == event.end_at
        assert restored.contact_hint == event.contact_hint
        assert restored.participation_hint == event.participation_hint
        assert restored.festival_slots == event.festival_slots

    def test_legacy_item_without_event_type_parses_as_single(self):
        event = self._festival_event(
            event_type=EventType.SINGLE,
            end_at=None,
            festival_slots=None,
            contact_hint=None,
            participation_hint=None,
        )
        item = _event_to_item(event)
        assert "event_type" in item  # written unconditionally, per T103
        del item["event_type"]  # simulate a legacy item predating spec 019

        restored = _item_to_event(item)
        assert restored.event_type == EventType.SINGLE
        assert restored.end_at is None
        assert restored.festival_slots is None


class TestCreateEventFestivalDefaults:
    """T103: create_event suppresses link token + autopromote for festivals."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = EventService()
        self.service._table = mock_dynamodb["events_table"]

    @pytest.mark.asyncio
    async def test_festival_create_has_no_link_token_and_no_autopromote(self):
        event_data = EventCreate(
            name="Sommerfestival",
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=32),
            end_at=NOW + timedelta(days=32),
            event_type=EventType.FESTIVAL,
            festival_slots=_slots(),
            autopromote_waitlist=True,  # input ignored/forced off for festivals
        )

        event = await self.service.create_event(uuid4(), event_data, uuid4())

        assert event.registration_link_token is None
        assert event.autopromote_waitlist is False
        assert event.event_type == EventType.FESTIVAL

    @pytest.mark.asyncio
    async def test_single_create_still_gets_link_token(self):
        event_data = EventCreate(
            name="Klassisches Event",
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=20),
        )

        event = await self.service.create_event(uuid4(), event_data, uuid4())

        assert event.registration_link_token is not None
        assert event.autopromote_waitlist is True
        assert event.event_type == EventType.SINGLE


class TestFestivalRegistrationPersistence:
    """T106: `_registration_to_item` / `_item_to_registration` round-trip festival fields."""

    def _festival_registration(self, **overrides) -> Registration:
        defaults = {
            "id": uuid4(),
            "event_id": uuid4(),
            "name": "Anna Meier",
            "email": "anna@example.com",
            "phone": "0176 12345678",
            "group_size": 3,
            "group_members": ["Bob Fisch", None, "Carla Muschel"],
            "status": RegistrationStatus.PARTICIPATING,
            "registration_token": "tok-123",
            "responded_at": NOW,
            "invite_id": uuid4(),
            "invite_label": "Werft-Team",
            "tier": "werft",
            "attendance_slots": ["fr-abend", "sa-tag"],
            "tent_count": 2,
            "camper_count": 1,
            "overnight_approved": True,
        }
        defaults.update(overrides)
        return Registration(**defaults)

    def test_festival_registration_roundtrips_through_item(self):
        registration = self._festival_registration()
        item = _registration_to_item(registration)
        restored = _item_to_registration(item)

        assert restored.invite_id == registration.invite_id
        assert restored.invite_label == registration.invite_label
        assert restored.tier == registration.tier
        assert restored.attendance_slots == registration.attendance_slots
        assert restored.tent_count == 2
        assert restored.camper_count == 1
        assert restored.overnight_approved is True
        assert restored.phone == registration.phone

    def test_legacy_accommodation_item_maps_to_counts(self):
        """Pre-Ä21 rows (single accommodation + count) map into tent/camper."""
        registration = self._festival_registration(tent_count=None, camper_count=None)
        item = _registration_to_item(registration)
        item["accommodation"] = AccommodationType.CAMPER.value
        item["accommodation_count"] = 2
        restored = _item_to_registration(item)
        assert restored.camper_count == 2
        assert restored.tent_count is None

    def test_group_members_tombstone_roundtrips_with_gap_intact(self):
        members = ["Bob Fisch", None, "Carla Muschel"]
        registration = self._festival_registration(group_members=members)
        item = _registration_to_item(registration)
        restored = _item_to_registration(item)

        assert restored.group_members == ["Bob Fisch", None, "Carla Muschel"]

    def test_legacy_item_without_festival_fields_parses_with_none_defaults(self):
        registration = self._festival_registration(
            invite_id=None,
            invite_label=None,
            tier=None,
            attendance_slots=None,
            tent_count=None,
            camper_count=None,
            overnight_approved=False,
        )
        item = _registration_to_item(registration)
        assert "overnight_approved" in item  # written unconditionally, per T106
        # Simulate a legacy item that predates spec 019 entirely.
        legacy_keys = (
            "invite_id",
            "invite_label",
            "tier",
            "attendance_slots",
            "tent_count",
            "camper_count",
            "overnight_approved",
        )
        for key in legacy_keys:
            item.pop(key, None)

        restored = _item_to_registration(item)
        assert restored.invite_id is None
        assert restored.invite_label is None
        assert restored.tier is None
        assert restored.attendance_slots is None
        assert restored.tent_count is None
        assert restored.camper_count is None
        assert restored.overnight_approved is False


def _create_kwargs(**overrides) -> dict:
    defaults = {
        "name": "Anna Meier",
        "email": "Anna@Example.com",
        "attendance_slots": ["fr-abend"],
        "phone": "0176 1234567",
    }
    defaults.update(overrides)
    return defaults


class TestFestivalRegistrationCreate:
    """T106 acceptance: FestivalRegistrationCreate schema validators."""

    def test_group_size_21_rejected(self):
        with pytest.raises(ValidationError):
            FestivalRegistrationCreate(**_create_kwargs(group_size=21))

    def test_group_size_6_accepted(self):
        # Unlike RegistrationCreate's le=5 cap.
        registration = FestivalRegistrationCreate(**_create_kwargs(group_size=6))
        assert registration.group_size == 6

    def test_empty_attendance_slots_rejected(self):
        with pytest.raises(ValidationError):
            FestivalRegistrationCreate(**_create_kwargs(attendance_slots=[]))

    def test_email_lowercased(self):
        registration = FestivalRegistrationCreate(**_create_kwargs(email="Anna@Example.com"))
        assert registration.email == "anna@example.com"

    def test_single_word_name_rejected(self):
        with pytest.raises(ValidationError, match="Bitte Vor- und Nachnamen angeben"):
            FestivalRegistrationCreate(**_create_kwargs(name="Anna"))

    def test_full_name_accepted(self):
        registration = FestivalRegistrationCreate(**_create_kwargs(name="Anna Meier"))
        assert registration.name == "Anna Meier"

    def test_single_word_group_member_rejected(self):
        with pytest.raises(ValidationError, match="Bitte Vor- und Nachnamen angeben"):
            FestivalRegistrationCreate(**_create_kwargs(group_members=["Bob"]))

    def test_full_name_group_member_accepted(self):
        registration = FestivalRegistrationCreate(**_create_kwargs(group_members=["Bob Fisch"]))
        assert registration.group_members == ["Bob Fisch"]

    def test_overnight_tent_without_phone_rejected(self):
        kwargs = _create_kwargs(tent_count=1)
        del kwargs["phone"]
        with pytest.raises(ValidationError, match="phone is required"):
            FestivalRegistrationCreate(**kwargs)

    def test_missing_phone_rejected_without_overnight(self):
        kwargs = _create_kwargs()
        del kwargs["phone"]
        with pytest.raises(ValidationError, match="phone is required"):
            FestivalRegistrationCreate(**kwargs)

    def test_blank_phone_rejected(self):
        with pytest.raises(ValidationError, match="phone is required"):
            FestivalRegistrationCreate(**_create_kwargs(phone="   "))

    def test_overnight_tent_with_phone_accepted(self):
        registration = FestivalRegistrationCreate(
            **_create_kwargs(tent_count=1, phone="0176 1234567"),
        )
        assert registration.phone == "0176 1234567"

    def test_no_overnight_keeps_phone(self):
        registration = FestivalRegistrationCreate(**_create_kwargs(phone="0123"))
        assert registration.phone == "0123"
        assert registration.tent_count is None
        assert registration.camper_count is None

    def test_no_overnight_approved_field(self):
        assert "overnight_approved" not in FestivalRegistrationCreate.model_fields

    def test_zero_counts_normalize_to_none(self):
        # Ä21: 0 means "keine" → stored as None.
        registration = FestivalRegistrationCreate(
            **_create_kwargs(tent_count=0, camper_count=0),
        )
        assert registration.tent_count is None
        assert registration.camper_count is None

    def test_both_types_accepted(self):
        # Ä21: a group may bring tents AND campers.
        registration = FestivalRegistrationCreate(
            **_create_kwargs(
                tent_count=2,
                camper_count=1,
                group_size=2,
                group_members=["Bob Fisch"],
            ),
        )
        assert registration.tent_count == 2
        assert registration.camper_count == 1

    def test_tent_count_exceeding_group_size_rejected(self):
        with pytest.raises(ValidationError, match="tent_count must not exceed"):
            FestivalRegistrationCreate(**_create_kwargs(tent_count=3, group_size=2))

    def test_camper_count_exceeding_group_size_rejected(self):
        with pytest.raises(ValidationError, match="camper_count must not exceed"):
            FestivalRegistrationCreate(**_create_kwargs(camper_count=3, group_size=2))


class TestFestivalAttendancePatch:
    """T106 acceptance: FestivalAttendancePatch schema, incl. the Ä17 guest guard."""

    def test_overnight_approved_rejected_extra_forbid(self):
        with pytest.raises(ValidationError):
            FestivalAttendancePatch(overnight_approved=True)

    def test_single_word_group_member_rejected(self):
        with pytest.raises(ValidationError, match="Bitte Vor- und Nachnamen angeben"):
            FestivalAttendancePatch(group_members=["Bob"])

    def test_full_name_group_member_accepted(self):
        patch = FestivalAttendancePatch(group_members=["Bob Fisch"])
        assert patch.group_members == ["Bob Fisch"]

    def test_none_tombstone_entry_preserved(self):
        patch = FestivalAttendancePatch(group_members=["Bob Fisch", None])
        assert patch.group_members == ["Bob Fisch", None]

    def test_group_size_21_rejected(self):
        with pytest.raises(ValidationError):
            FestivalAttendancePatch(group_size=21)

    def test_overnight_counts_accepted(self):
        patch = FestivalAttendancePatch(tent_count=2, camper_count=1)
        assert patch.tent_count == 2
        assert patch.camper_count == 1

    def test_negative_count_rejected(self):
        with pytest.raises(ValidationError):
            FestivalAttendancePatch(tent_count=-1)
