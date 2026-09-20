"""Tests for editing an event after the Anmeldeschluss.

`update_event` used to refuse every status but DRAFT and OPEN, so a wrong
start time or a moved meeting point could only be fixed by cancelling the whole
event. It now accepts `LATE_EDITABLE_FIELDS` (description, start_at, location)
in the statuses between Anmeldeschluss and Abschluss, and keeps refusing
everything the lottery or an already-issued ticket depends on.

`update_event` had no test coverage at all before this file.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Event, EventStatus, EventType, EventUpdate
from app.services.event_service import LATE_EDITABLE_FIELDS, EventService, _event_to_item

NOW = datetime.now(timezone.utc)

# The statuses a chartered or already-drawn event sits in between the
# Anmeldeschluss and being wrapped up.
AFTER_LOTTERY = [
    EventStatus.REGISTRATION_CLOSED,
    EventStatus.LOTTERY_PENDING,
    EventStatus.CONFIRMED,
]


def _event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Sommertörn",
        "event_type": EventType.SINGLE,
        "start_at": NOW + timedelta(days=10),
        "registration_deadline": NOW + timedelta(days=3),
        "status": EventStatus.CONFIRMED,
        "capacity": 40,
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestLateEdit:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = EventService()
        self.service._table = mock_dynamodb["events_table"]

    def _seed(self, event: Event) -> Event:
        self.tables["events_table"].put_item(Item=_event_to_item(event))
        return event

    async def _update(self, event: Event, **fields):
        return await self.service.update_event(
            event.org_id, event.id, EventUpdate(**fields),
        )

    # --- the three that must still move -------------------------------------

    @pytest.mark.parametrize("status", AFTER_LOTTERY)
    async def test_the_start_time_can_be_corrected(self, status):
        event = self._seed(_event(status=status))
        new_start = event.start_at + timedelta(hours=2)

        updated = await self._update(event, start_at=new_start)

        assert updated is not None
        assert updated.start_at == new_start

    @pytest.mark.parametrize("status", AFTER_LOTTERY)
    async def test_description_and_location_can_be_corrected(self, status):
        event = self._seed(_event(status=status))

        updated = await self._update(
            event, description="Treffpunkt geändert", location="Ruderverein Wilhelmsburg",
        )

        assert updated is not None
        assert updated.description == "Treffpunkt geändert"
        assert updated.location == "Ruderverein Wilhelmsburg"

    async def test_the_status_is_not_touched_by_a_late_edit(self):
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        updated = await self._update(event, description="nur Text")

        assert updated.status == EventStatus.CONFIRMED

    # --- everything the lottery or a ticket depends on stays frozen ----------

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("capacity", 99),
            ("registration_deadline", NOW + timedelta(days=5)),
            ("name", "Anderer Name"),
            ("autopromote_waitlist", False),
        ],
    )
    async def test_frozen_fields_are_refused(self, field, value):
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        with pytest.raises(ValueError) as excinfo:
            await self._update(event, **{field: value})

        assert field in str(excinfo.value)
        assert "Anmeldeschluss" in str(excinfo.value)

    async def test_a_frozen_field_poisons_the_whole_payload(self):
        """All-or-nothing: no partial write that silently drops the capacity."""
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        with pytest.raises(ValueError):
            await self._update(event, description="erlaubt", capacity=99)

        stored = await self.service.get_event(event.org_id, event.id)
        assert stored.description != "erlaubt"
        assert stored.capacity == 40

    # --- the ends of the lifecycle ------------------------------------------

    @pytest.mark.parametrize("status", [EventStatus.DRAFT, EventStatus.OPEN])
    async def test_before_the_deadline_everything_is_still_editable(self, status):
        event = self._seed(_event(status=status))

        updated = await self._update(event, capacity=99, name="Neuer Name")

        assert updated.capacity == 99
        assert updated.name == "Neuer Name"

    @pytest.mark.parametrize("status", [EventStatus.COMPLETED, EventStatus.CANCELLED])
    async def test_a_finished_event_is_frozen_entirely(self, status):
        event = self._seed(_event(status=status))

        assert await self._update(event, description="zu spät") is None

    async def test_an_unknown_event_is_none_not_an_error(self):
        service_event = _event()
        assert await self._update(service_event, description="x") is None

    # --- the contract with the frontend -------------------------------------

    def test_the_whitelist_matches_what_the_edit_page_leaves_enabled(self):
        """EventEditPage.vue hard-codes the same three names in camelCase."""
        assert LATE_EDITABLE_FIELDS == {"description", "start_at", "location"}


class TestFullDocumentPayload(TestLateEdit):
    """The edit form posts every field it renders, not a patch.

    The first cut of the guard rejected a frozen field for merely *appearing*
    in the payload, so changing only the date came back as
    „Gesperrt: autopromote_waitlist, capacity, name, registration_deadline,
    reminder_schedule_days" — every untouched field the form had sent along.
    """

    def _whole_form(self, event: Event, **changes) -> dict:
        """Exactly what EventForm.vue submits: all fields, changed or not."""
        payload = {
            "name": event.name,
            "description": event.description,
            "location": event.location,
            "start_at": event.start_at,
            "capacity": event.capacity,
            "registration_deadline": event.registration_deadline,
            "reminder_schedule_days": event.reminder_schedule_days,
            "autopromote_waitlist": event.autopromote_waitlist,
        }
        payload.update(changes)
        return payload

    async def test_changing_only_the_date_in_a_full_payload_succeeds(self):
        event = self._seed(_event(status=EventStatus.CONFIRMED))
        new_start = event.start_at + timedelta(hours=3)

        updated = await self._update(event, **self._whole_form(event, start_at=new_start))

        assert updated is not None, "an unchanged frozen field must not block the edit"
        assert updated.start_at == new_start
        assert updated.capacity == event.capacity
        assert updated.name == event.name

    async def test_changing_only_the_location_in_a_full_payload_succeeds(self):
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        updated = await self._update(
            event, **self._whole_form(event, location="Ruderverein Wilhelmsburg"),
        )

        assert updated.location == "Ruderverein Wilhelmsburg"

    async def test_a_genuinely_changed_frozen_field_is_still_refused(self):
        """The guard must not have been softened into uselessness."""
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        with pytest.raises(ValueError) as excinfo:
            await self._update(event, **self._whole_form(event, capacity=999))

        message = str(excinfo.value)
        assert "capacity" in message
        # and only that one — not the untouched fields alongside it
        for untouched in ("name", "registration_deadline", "autopromote_waitlist"):
            assert untouched not in message

    async def test_a_full_payload_with_nothing_changed_is_a_no_op(self):
        event = self._seed(_event(status=EventStatus.CONFIRMED))

        updated = await self._update(event, **self._whole_form(event))

        assert updated is not None
        assert updated.start_at == event.start_at

    async def test_a_minute_truncated_deadline_is_not_treated_as_a_change(self):
        """The form's datetime-local input has minute precision.

        `formatDateTimeLocal` renders the stored value to the minute and
        `berlinToUTCISO` converts it back, so seconds and microseconds are lost
        on every round trip. The deadline comes back *differing* from what is
        stored while representing the same thing the organiser saw — and must
        not be read as an attempt to change it.
        """
        event = self._seed(
            _event(
                status=EventStatus.CONFIRMED,
                registration_deadline=NOW.replace(microsecond=123456) + timedelta(days=3),
            ),
        )
        round_tripped = event.registration_deadline.replace(second=0, microsecond=0)
        assert round_tripped != event.registration_deadline

        updated = await self._update(
            event,
            **self._whole_form(
                event,
                start_at=event.start_at + timedelta(hours=1),
                registration_deadline=round_tripped,
            ),
        )

        assert updated is not None, "a minute-truncated deadline must not block the edit"
        assert updated.start_at == event.start_at + timedelta(hours=1)
        assert updated.registration_deadline == event.registration_deadline, (
            "and the stored deadline must not be silently coarsened"
        )
