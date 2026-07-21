"""Tests for `RegistrationService.get_headcount` (spec 019 — T201).

Covers the slot x tier headcount aggregation: group-size counting, the
CANCELLED exclusion (Ä5), multi-slot peak counting, tier bucketing,
accommodation totals split into requested/approved (Ä15/Ä17), per-slot
overnight demand, the `unknown_slots` diagnostic bucket for orphaned
slot keys, and the soft-cap `overbooked` display flags (Ä4/Ä8).

Pattern: `RegistrationService()` constructed directly and wired to moto
tables via the shared `mock_dynamodb` fixture; events/registrations are
seeded through `_event_to_item` / `_registration_to_item` so the service
reads real DynamoDB items, not in-memory models.
"""

from datetime import date

import pytest

from app.models import (
    AccommodationType,
    EventType,
    FestivalSlot,
    RegistrationStatus,
)
from app.services.registration_service import (
    RegistrationService,
    _registration_to_item,
    compute_very_full_slots,
)


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr-abend", label="Fr Abend", date=date(2026, 8, 14), is_night=True, capacity=150),
        FestivalSlot(key="sa-tag", label="Sa Tag", date=date(2026, 8, 15), capacity=2),
        FestivalSlot(key="so-tag", label="So Tag", date=date(2026, 8, 16)),
    ]


class TestFestivalHeadcount:
    """T201 acceptance criteria."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb, sample_event, sample_registration):
        self.tables = mock_dynamodb
        self.sample_event = sample_event
        self.sample_registration = sample_registration

        self.service = RegistrationService()
        self.service._registrations_table = self.tables["registrations_table"]
        self.service._events_table = self.tables["events_table"]

    def _make_event(self, **overrides):
        defaults = {
            "event_type": EventType.FESTIVAL,
            "festival_slots": _slots(),
            "capacity": 500,
        }
        defaults.update(overrides)
        return self.sample_event(**defaults)

    def _store_reg(self, event, **overrides):
        defaults = {"event_id": event.id}
        defaults.update(overrides)
        reg = self.sample_registration(**defaults)
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))
        return reg

    @pytest.mark.asyncio
    async def test_group_sizes_count_not_registrations(self):
        event = self._make_event()
        self._store_reg(event, group_size=3, attendance_slots=["fr-abend"])
        self._store_reg(event, group_size=1, attendance_slots=["fr-abend"])

        result = await self.service.get_headcount(event)

        fr = next(s for s in result["slots"] if s["key"] == "fr-abend")
        assert fr["total"] == 4

    @pytest.mark.asyncio
    async def test_cancelled_excluded_from_everything(self):
        event = self._make_event()
        self._store_reg(
            event,
            group_size=2,
            attendance_slots=["fr-abend"],
            tier="werft",
            tent_count=1,
            overnight_approved=True,
        )
        self._store_reg(
            event,
            group_size=5,
            attendance_slots=["fr-abend"],
            tier="werft",
            tent_count=1,
            overnight_approved=True,
            status=RegistrationStatus.CANCELLED,
        )

        result = await self.service.get_headcount(event)

        fr = next(s for s in result["slots"] if s["key"] == "fr-abend")
        assert fr["total"] == 2
        assert fr["by_tier"] == {"werft": 2}
        # Only the non-cancelled reg counts: 1 tent, approved.
        assert result["accommodation_totals"]["TENT"] == {
            "requested_units": 1,
            "approved_units": 1,
        }
        assert result["total_registrations"] == 1
        assert result["total_people"] == 2

    @pytest.mark.asyncio
    async def test_multi_slot_registration_contributes_full_group_size_to_each(self):
        event = self._make_event()
        self._store_reg(event, group_size=4, attendance_slots=["fr-abend", "sa-tag"])

        result = await self.service.get_headcount(event)

        fr = next(s for s in result["slots"] if s["key"] == "fr-abend")
        sa = next(s for s in result["slots"] if s["key"] == "sa-tag")
        assert fr["total"] == 4
        assert sa["total"] == 4

    @pytest.mark.asyncio
    async def test_tier_bucketing_werft_and_unknown(self):
        event = self._make_event()
        self._store_reg(event, group_size=2, attendance_slots=["fr-abend"], tier="werft")
        self._store_reg(event, group_size=1, attendance_slots=["fr-abend"], tier=None)

        result = await self.service.get_headcount(event)

        fr = next(s for s in result["slots"] if s["key"] == "fr-abend")
        assert fr["by_tier"]["werft"] == 2
        assert fr["by_tier"]["unknown"] == 1

    @pytest.mark.asyncio
    async def test_accommodation_totals_requested_vs_approved(self):
        event = self._make_event()
        self._store_reg(
            event,
            group_size=3,
            attendance_slots=["fr-abend"],
            tent_count=1,
            overnight_approved=False,
        )
        self._store_reg(
            event,
            group_size=2,
            attendance_slots=["fr-abend"],
            camper_count=1,
            overnight_approved=True,
        )
        self._store_reg(event, group_size=10, attendance_slots=["fr-abend"])

        result = await self.service.get_headcount(event)

        # *_units count tents/campers per type; overnight_people counts humans.
        assert result["accommodation_totals"]["TENT"] == {
            "requested_units": 1,
            "approved_units": 0,
        }
        assert result["accommodation_totals"]["CAMPER"] == {
            "requested_units": 1,
            "approved_units": 1,
        }
        assert result["overnight_people"] == {"requested": 5, "approved": 2}

    @pytest.mark.asyncio
    async def test_accommodation_units_sum_counts_vehicles_not_people(self):
        """Ä21: *_units sum vehicles/tents, and a group bringing BOTH types
        contributes to both buckets. Covers the feedback case — contact and a
        companion each bring their own caravan, plus a tent."""
        event = self._make_event()
        # A 2-person group bringing 2 campers AND 1 tent, approved.
        self._store_reg(
            event,
            group_size=2,
            attendance_slots=["fr-abend"],
            camper_count=2,
            tent_count=1,
            overnight_approved=True,
        )
        # A 4-person group sharing a single camper, only requested.
        self._store_reg(
            event,
            group_size=4,
            attendance_slots=["fr-abend"],
            camper_count=1,
            overnight_approved=False,
        )

        result = await self.service.get_headcount(event)

        camper = result["accommodation_totals"]["CAMPER"]
        tent = result["accommodation_totals"]["TENT"]
        assert camper["requested_units"] == 3  # campers: 2 + 1
        assert camper["approved_units"] == 2  # only the first group's 2 campers
        assert tent["requested_units"] == 1  # the first group's tent
        assert tent["approved_units"] == 1
        # People with any overnight wish: both groups (2 + 4); only first approved.
        assert result["overnight_people"] == {"requested": 6, "approved": 2}

    @pytest.mark.asyncio
    async def test_per_slot_overnight_demand_independent_of_is_night(self):
        event = self._make_event()
        # sa-tag is not a night slot but still accrues overnight demand.
        self._store_reg(
            event,
            group_size=3,
            attendance_slots=["sa-tag"],
            tent_count=1,
        )
        self._store_reg(event, group_size=2, attendance_slots=["sa-tag"])

        result = await self.service.get_headcount(event)

        sa = next(s for s in result["slots"] if s["key"] == "sa-tag")
        assert sa["is_night"] is False
        assert sa["overnight"] == 3

    @pytest.mark.asyncio
    async def test_orphaned_slot_key_lands_in_unknown_slots(self):
        event = self._make_event()
        self._store_reg(event, group_size=4, attendance_slots=["removed-slot"])

        result = await self.service.get_headcount(event)

        assert result["unknown_slots"] == {"removed-slot": 4}
        # Doesn't silently vanish, doesn't crash — and isn't attributed to
        # any real slot.
        assert all(s["total"] == 0 for s in result["slots"])

    @pytest.mark.asyncio
    async def test_overbooked_flags_per_slot_and_overall(self):
        event = self._make_event(capacity=5)
        # sa-tag has capacity=2; 3 people overbooks it.
        self._store_reg(event, group_size=3, attendance_slots=["sa-tag"])

        result = await self.service.get_headcount(event)

        sa = next(s for s in result["slots"] if s["key"] == "sa-tag")
        so = next(s for s in result["slots"] if s["key"] == "so-tag")
        assert sa["cap"] == 2
        assert sa["overbooked"] is True
        assert so["cap"] is None
        assert so["overbooked"] is False
        assert result["peak_total"] == 3
        assert result["overall_overbooked"] is False

        # Now push peak_total over the overall event capacity too.
        self._store_reg(event, group_size=10, attendance_slots=["fr-abend"])
        result2 = await self.service.get_headcount(event)
        assert result2["peak_total"] == 10
        assert result2["overall_overbooked"] is True

    @pytest.mark.asyncio
    async def test_registrations_without_slots_counted_separately(self):
        event = self._make_event()
        self._store_reg(event, group_size=2, attendance_slots=None)

        result = await self.service.get_headcount(event)

        assert result["registrations_without_slots"] == 1
        assert all(s["total"] == 0 for s in result["slots"])

    @pytest.mark.asyncio
    async def test_empty_slots_appear_with_zeros(self):
        event = self._make_event()

        result = await self.service.get_headcount(event)

        assert [s["key"] for s in result["slots"]] == ["fr-abend", "sa-tag", "so-tag"]
        for slot in result["slots"]:
            assert slot["total"] == 0
            assert slot["by_tier"] == {}
        assert result["peak_total"] == 0
        assert result["total_registrations"] == 0
        assert result["total_people"] == 0


class TestVeryFullSlots:
    """T210 (if-time, Ä4): `compute_very_full_slots` threshold math.

    Pure and headcount-driven (literal `get_headcount`-shaped dicts) — the
    "no caps at all" case is impossible via a real `Event` (`capacity` is a
    required int), so it is exercised directly against the helper rather
    than through the service/moto fixtures used elsewhere in this file.
    """

    @staticmethod
    def _headcount(slots, overall_cap):
        return {"overall_cap": overall_cap, "slots": slots}

    def test_at_ninety_percent_of_slot_cap_is_very_full(self):
        headcount = self._headcount([{"key": "sa-tag", "cap": 10, "total": 9}], overall_cap=500)
        assert compute_very_full_slots(headcount) == {"sa-tag": True}

    def test_below_ninety_percent_of_slot_cap_is_not_very_full(self):
        headcount = self._headcount([{"key": "sa-tag", "cap": 10, "total": 8}], overall_cap=500)
        assert compute_very_full_slots(headcount) == {"sa-tag": False}

    def test_slot_without_cap_falls_back_to_overall_cap(self):
        headcount = self._headcount([{"key": "so-tag", "cap": None, "total": 90}], overall_cap=100)
        assert compute_very_full_slots(headcount) == {"so-tag": True}

    def test_no_caps_at_all_is_never_very_full(self):
        slots = [{"key": "so-tag", "cap": None, "total": 10_000}]
        headcount = self._headcount(slots, overall_cap=None)
        assert compute_very_full_slots(headcount) == {"so-tag": False}
