"""Tests for the refactored lottery algorithm (spec 004).

Covers:
- Under-capacity auto-confirm
- Promoted registrations always win
- Promoted exceeding capacity raises error
"""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.models import EventStatus, RegistrationStatus
from app.services.lottery_service import LotteryService
from app.services.registration_service import (
    RegistrationService,
    _registration_to_item,
)
from app.services.event_service import _event_to_item


class TestLotteryUnderCapacity:
    """T13.3: All registrations confirmed when under capacity."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event, sample_registration):
        self.tables = mock_dynamodb
        self.sample_event = sample_event
        self.sample_registration = sample_registration

        # Set up services with mocked tables
        reg_service = RegistrationService()
        reg_service._registrations_table = self.tables["registrations_table"]
        reg_service._events_table = self.tables["events_table"]

        with patch("app.services.registration_service.get_registration_service", return_value=reg_service), \
             patch("app.services.event_service.get_event_service") as mock_evt_svc, \
             patch("app.services.email_service.get_email_service") as mock_email_svc:
            self.lottery_service = LotteryService()
            self.lottery_service._table = self.tables["lottery_runs_table"]
            self.lottery_service.registration_service = reg_service

            # Mock event service
            self.mock_event_service = AsyncMock()
            self.lottery_service.event_service = self.mock_event_service

            # Mock email service
            self.mock_email_service = AsyncMock()
            self.lottery_service.email_service = self.mock_email_service

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    def _store_registration(self, reg):
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

    @pytest.mark.asyncio
    async def test_under_capacity_all_winners(self):
        event = self.sample_event(
            capacity=100,
            status=EventStatus.REGISTRATION_CLOSED,
        )
        self._store_event(event)
        self.mock_event_service.get_event.return_value = event

        # 3 registrations totaling 6 spots (well under 100)
        for i, gs in enumerate([1, 2, 3]):
            self._store_registration(self.sample_registration(
                event_id=event.id,
                email=f"user{i}@test.com",
                group_size=gs,
                status=RegistrationStatus.REGISTERED,
            ))

        result = await self.lottery_service.run_lottery(event.org_id, event.id, uuid4())

        assert len(result.winners) == 3
        assert len(result.waitlist) == 0
        assert result.seed == "auto-confirm"


class TestLotteryWithPromoted:
    """T13.4: Promoted registrations always win."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event, sample_registration):
        self.tables = mock_dynamodb
        self.sample_event = sample_event
        self.sample_registration = sample_registration

        reg_service = RegistrationService()
        reg_service._registrations_table = self.tables["registrations_table"]
        reg_service._events_table = self.tables["events_table"]

        with patch("app.services.registration_service.get_registration_service", return_value=reg_service), \
             patch("app.services.event_service.get_event_service") as mock_evt_svc, \
             patch("app.services.email_service.get_email_service") as mock_email_svc:
            self.lottery_service = LotteryService()
            self.lottery_service._table = self.tables["lottery_runs_table"]
            self.lottery_service.registration_service = reg_service
            self.mock_event_service = AsyncMock()
            self.lottery_service.event_service = self.mock_event_service
            self.mock_email_service = AsyncMock()
            self.lottery_service.email_service = self.mock_email_service

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    def _store_registration(self, reg):
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

    @pytest.mark.asyncio
    async def test_promoted_always_win(self):
        event = self.sample_event(
            capacity=5,
            status=EventStatus.REGISTRATION_CLOSED,
        )
        self._store_event(event)
        self.mock_event_service.get_event.return_value = event

        promoted_ids = []
        # 3 promoted registrations (1 spot each)
        for i in range(3):
            reg = self.sample_registration(
                event_id=event.id,
                email=f"promoted{i}@test.com",
                group_size=1,
                status=RegistrationStatus.REGISTERED,
                promoted=True,
            )
            self._store_registration(reg)
            promoted_ids.append(str(reg.id))

        # 5 non-promoted registrations (1 spot each)
        for i in range(5):
            self._store_registration(self.sample_registration(
                event_id=event.id,
                email=f"regular{i}@test.com",
                group_size=1,
                status=RegistrationStatus.REGISTERED,
                promoted=False,
            ))

        result = await self.lottery_service.run_lottery(event.org_id, event.id, uuid4())

        # All 3 promoted should be in winners
        winner_ids = {w["id"] for w in result.winners}
        for pid in promoted_ids:
            assert pid in winner_ids

        # Total winners = 5 (capacity), waitlist = 3
        assert len(result.winners) == 5
        assert len(result.waitlist) == 3


class TestLotteryPromotedExceedsCapacity:
    """T13.5: Lottery refuses to run when promoted spots exceed capacity."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event, sample_registration):
        self.tables = mock_dynamodb
        self.sample_event = sample_event
        self.sample_registration = sample_registration

        reg_service = RegistrationService()
        reg_service._registrations_table = self.tables["registrations_table"]
        reg_service._events_table = self.tables["events_table"]

        with patch("app.services.registration_service.get_registration_service", return_value=reg_service), \
             patch("app.services.event_service.get_event_service") as mock_evt_svc, \
             patch("app.services.email_service.get_email_service") as mock_email_svc:
            self.lottery_service = LotteryService()
            self.lottery_service._table = self.tables["lottery_runs_table"]
            self.lottery_service.registration_service = reg_service
            self.mock_event_service = AsyncMock()
            self.lottery_service.event_service = self.mock_event_service
            self.mock_email_service = AsyncMock()
            self.lottery_service.email_service = self.mock_email_service

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    def _store_registration(self, reg):
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

    @pytest.mark.asyncio
    async def test_promoted_exceeds_capacity_raises_error(self):
        event = self.sample_event(
            capacity=3,
            status=EventStatus.REGISTRATION_CLOSED,
        )
        self._store_event(event)
        self.mock_event_service.get_event.return_value = event

        # 2 promoted registrations totaling 4 spots (exceeds capacity of 3)
        self._store_registration(self.sample_registration(
            event_id=event.id, email="p1@test.com", group_size=2,
            status=RegistrationStatus.REGISTERED, promoted=True,
        ))
        self._store_registration(self.sample_registration(
            event_id=event.id, email="p2@test.com", group_size=2,
            status=RegistrationStatus.REGISTERED, promoted=True,
        ))

        with pytest.raises(ValueError, match="Bevorzugte Anmeldungen"):
            await self.lottery_service.run_lottery(event.org_id, event.id, uuid4())
