"""Tests for the daily `anonymize_expired_data` worker (spec 022).

Replaces the old hard-delete sweep. What matters here is *which* events it
picks up and that it never deletes anything — the field-level scrub itself is
covered by `test_anonymization.py`.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from boto3.dynamodb.conditions import Key

from app.models import Event, EventStatus, EventType, Registration, RegistrationStatus
from app.services.anonymization_service import AnonymizationService
from app.services.event_service import EventService, _event_to_item
from app.services.registration_service import _registration_to_item
from app.workers.handler import (
    _event_finished_at,
    _invocation_deadline,
    anonymize_expired_data,
    handler,
)

NOW = datetime.now(timezone.utc)


def _event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Sommertörn",
        "event_type": EventType.SINGLE,
        "start_at": NOW - timedelta(days=200),
        "registration_deadline": NOW - timedelta(days=210),
        "status": EventStatus.COMPLETED,
        "capacity": 40,
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestAnonymizeExpiredData:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb

        event_service = EventService()
        event_service._table = mock_dynamodb["events_table"]

        anonymization_service = AnonymizationService()
        anonymization_service._events_table = mock_dynamodb["events_table"]
        anonymization_service._registrations_table = mock_dynamodb["registrations_table"]
        anonymization_service._messages_table = mock_dynamodb["messages_table"]

        # Patched at the worker's import sites — the handler resolves both
        # singletons inside the function body.
        self._patches = [
            patch("app.workers.handler.get_event_service", return_value=event_service),
            patch(
                "app.services.anonymization_service.get_anonymization_service",
                return_value=anonymization_service,
            ),
        ]
        for p in self._patches:
            p.start()
        yield
        for p in self._patches:
            p.stop()

    def _seed(self, event: Event) -> Registration:
        self.tables["events_table"].put_item(Item=_event_to_item(event))
        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name="Max Mustermann",
            email="max@example.com",
            group_size=2,
            status=RegistrationStatus.PARTICIPATING,
            registration_token=f"tok-{uuid4()}",
            registered_at=NOW - timedelta(days=220),
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))
        return registration

    def _reg_rows(self, event_id) -> list[dict]:
        resp = self.tables["registrations_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
        )
        return resp.get("Items", [])

    @pytest.mark.asyncio
    async def test_anonymizes_events_past_the_window_and_deletes_nothing(self):
        event = _event()
        self._seed(event)

        result = await anonymize_expired_data()

        assert result["events_anonymized"] == 1
        rows = self._reg_rows(event.id)
        # The row survives — this is the whole difference from the old sweep.
        assert len(rows) == 1
        assert rows[0]["name"] != "Max Mustermann"
        assert int(rows[0]["group_size"]) == 2

    @pytest.mark.asyncio
    async def test_skips_events_inside_the_window(self):
        event = _event(
            start_at=NOW - timedelta(days=10),
            registration_deadline=NOW - timedelta(days=20),
        )
        self._seed(event)

        result = await anonymize_expired_data()

        assert result["events_anonymized"] == 0
        assert result["events_within_retention"] == 1
        assert self._reg_rows(event.id)[0]["name"] == "Max Mustermann"

    @pytest.mark.asyncio
    async def test_sweeps_cancelled_events_too(self):
        """A cancelled event still holds every address collected before it fell
        through, and nothing else would ever clean it up."""
        event = _event(
            status=EventStatus.CANCELLED,
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=20),
            cancelled_at=NOW - timedelta(days=200),
        )
        self._seed(event)

        result = await anonymize_expired_data()

        assert result["events_anonymized"] == 1
        assert self._reg_rows(event.id)[0]["name"] != "Max Mustermann"

    @pytest.mark.asyncio
    async def test_recently_cancelled_future_event_is_left_alone(self):
        event = _event(
            status=EventStatus.CANCELLED,
            start_at=NOW + timedelta(days=30),
            registration_deadline=NOW + timedelta(days=20),
            cancelled_at=NOW - timedelta(days=3),
        )
        self._seed(event)

        result = await anonymize_expired_data()

        assert result["events_anonymized"] == 0
        assert self._reg_rows(event.id)[0]["name"] == "Max Mustermann"

    @pytest.mark.asyncio
    async def test_already_anonymized_events_are_not_reprocessed(self):
        event = _event(anonymized_at=NOW - timedelta(days=1))
        self._seed(event)

        result = await anonymize_expired_data()

        assert result["events_anonymized"] == 0
        # Untouched precisely because the guard fired before the scrub.
        assert self._reg_rows(event.id)[0]["name"] == "Max Mustermann"

    @pytest.mark.asyncio
    async def test_retention_window_is_configurable(self):
        event = _event(
            start_at=NOW - timedelta(days=10),
            registration_deadline=NOW - timedelta(days=20),
        )
        self._seed(event)

        with patch("app.services.config.get_settings") as mock_settings:
            mock_settings.return_value.anonymization_retention_days = 7
            result = await anonymize_expired_data()

        assert result["retention_days"] == 7
        assert result["events_anonymized"] == 1

    @pytest.mark.asyncio
    async def test_out_of_time_defers_instead_of_half_finishing(self):
        """A backlog too big for one invocation drains over several nights.

        The event is reported as unfinished and keeps `anonymized_at` unset, so
        it is still a candidate tomorrow — the alternative was being killed
        mid-write with no record of how far it got.
        """
        event = _event()
        self._seed(event)

        result = await anonymize_expired_data(deadline=NOW - timedelta(seconds=1))

        assert result["events_anonymized"] == 0
        assert result["events_unfinished"] == [str(event.id)]
        assert self._reg_rows(event.id)[0]["name"] == "Max Mustermann"

    def test_handler_passes_the_lambdas_remaining_time_as_a_deadline(self):
        """The wiring, not the sweep: the task only gets a deadline because the
        handler reads it off the Lambda context."""
        event = _event()
        self._seed(event)

        class _NoTimeLeft:
            def get_remaining_time_in_millis(self):
                return 0

        result = handler({"task": "anonymize_expired_data"}, _NoTimeLeft())

        assert result["events_unfinished"] == [str(event.id)]


class TestInvocationDeadline:
    def test_reserves_time_to_finish_and_report(self):
        class _FiveMinutes:
            def get_remaining_time_in_millis(self):
                return 300_000

        deadline = _invocation_deadline(_FiveMinutes())
        remaining = deadline - datetime.now(timezone.utc)
        # Five minutes minus the reserve, give or take the test's own runtime.
        assert timedelta(seconds=270) < remaining < timedelta(seconds=281)

    def test_no_deadline_outside_lambda(self):
        """Local runs and scripts have no clock to race, so they run to the end."""
        assert _invocation_deadline(None) is None


class TestEventFinishedAt:
    def test_cancelled_uses_cancellation_time_not_the_planned_date(self):
        """Otherwise a festival cancelled a year ahead would sit on its
        addresses until long after the guests stopped expecting it to exist."""
        event = _event(
            status=EventStatus.CANCELLED,
            start_at=NOW + timedelta(days=365),
            registration_deadline=NOW + timedelta(days=300),
            cancelled_at=NOW - timedelta(days=5),
        )
        assert _event_finished_at(event) == event.cancelled_at

    def test_legacy_cancelled_row_without_a_timestamp_falls_back(self):
        event = _event(
            status=EventStatus.CANCELLED,
            start_at=NOW - timedelta(days=5),
            registration_deadline=NOW - timedelta(days=10),
            cancelled_at=None,
        )
        assert _event_finished_at(event) == event.start_at

    def test_festival_measures_from_its_end(self):
        event = _event(
            event_type=EventType.FESTIVAL,
            start_at=NOW - timedelta(days=100),
            end_at=NOW - timedelta(days=97),
            registration_deadline=NOW - timedelta(days=97),
            festival_slots=[
                {"key": "fr", "label": "Freitag", "date": (NOW - timedelta(days=99)).date()},
            ],
        )
        assert _event_finished_at(event) == event.end_at
