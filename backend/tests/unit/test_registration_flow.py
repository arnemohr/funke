"""Tests for the improved registration flow (spec 004).

Covers:
- All registrations start as REGISTERED regardless of capacity
- Promoted flag operations
- Promoted stats counting
"""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.models import EventStatus, RegistrationCreate, RegistrationStatus
from app.services.registration_service import (
    RegistrationService,
    _registration_to_item,
    _item_to_registration,
)
from app.services.event_service import _event_to_item


class TestRegistrationAlwaysRegistered:
    """T13.1: Registration always REGISTERED regardless of capacity."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event):
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        self.service._registrations_table = self.tables["registrations_table"]
        self.service._events_table = self.tables["events_table"]
        self.sample_event = sample_event

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    @pytest.mark.asyncio
    async def test_register_under_capacity(self):
        event = self.sample_event(capacity=50)
        self._store_event(event)

        reg_data = RegistrationCreate(name="Alice", email="alice@test.com", group_size=2)
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert error is None
        assert reg.status == RegistrationStatus.REGISTERED
        assert reg.waitlist_position is None

    @pytest.mark.asyncio
    async def test_register_at_capacity(self):
        event = self.sample_event(capacity=2)
        self._store_event(event)

        # Fill capacity
        reg1_data = RegistrationCreate(name="Alice", email="alice@test.com", group_size=2)
        reg1, _ = await self.service.create_registration(event.registration_link_token, reg1_data)
        assert reg1.status == RegistrationStatus.REGISTERED

        # Register beyond capacity — still REGISTERED
        reg2_data = RegistrationCreate(name="Bob", email="bob@test.com", group_size=1)
        reg2, error = await self.service.create_registration(event.registration_link_token, reg2_data)

        assert error is None
        assert reg2.status == RegistrationStatus.REGISTERED
        assert reg2.waitlist_position is None

    @pytest.mark.asyncio
    async def test_register_over_capacity(self):
        event = self.sample_event(capacity=1)
        self._store_event(event)

        # First registration exceeds capacity by group_size
        reg_data = RegistrationCreate(name="Alice", email="alice@test.com", group_size=5)
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert error is None
        assert reg.status == RegistrationStatus.REGISTERED
        assert reg.waitlist_position is None


class TestPromotedFlag:
    """T13.2: Promoted flag operations."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event, sample_registration):
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        self.service._registrations_table = self.tables["registrations_table"]
        self.service._events_table = self.tables["events_table"]
        self.sample_event = sample_event
        self.sample_registration = sample_registration

    def _store_registration(self, reg):
        self.tables["registrations_table"].put_item(Item=_registration_to_item(reg))

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    @pytest.mark.asyncio
    async def test_set_promoted_true(self):
        event_id = uuid4()
        reg = self.sample_registration(event_id=event_id, status=RegistrationStatus.REGISTERED)
        self._store_registration(reg)

        result = await self.service.set_promoted(event_id, reg.id, True)

        assert result is not None
        assert result.promoted is True

    @pytest.mark.asyncio
    async def test_set_promoted_false(self):
        event_id = uuid4()
        reg = self.sample_registration(event_id=event_id, status=RegistrationStatus.REGISTERED, promoted=True)
        self._store_registration(reg)

        result = await self.service.set_promoted(event_id, reg.id, False)

        assert result is not None
        assert result.promoted is False

    @pytest.mark.asyncio
    async def test_set_promoted_on_cancelled_fails(self):
        event_id = uuid4()
        reg = self.sample_registration(event_id=event_id, status=RegistrationStatus.CANCELLED)
        self._store_registration(reg)

        result = await self.service.set_promoted(event_id, reg.id, True)

        assert result is None  # Should fail silently

    @pytest.mark.asyncio
    async def test_promoted_stats(self):
        event_id = uuid4()
        event = self.sample_event(id=event_id, capacity=50)
        self._store_event(event)

        # 2 promoted, 1 not promoted, 1 cancelled+promoted
        self._store_registration(self.sample_registration(
            event_id=event_id, email="a@test.com", promoted=True, group_size=3,
        ))
        self._store_registration(self.sample_registration(
            event_id=event_id, email="b@test.com", promoted=True, group_size=2,
        ))
        self._store_registration(self.sample_registration(
            event_id=event_id, email="c@test.com", promoted=False, group_size=1,
        ))
        self._store_registration(self.sample_registration(
            event_id=event_id, email="d@test.com", promoted=True, group_size=4,
            status=RegistrationStatus.CANCELLED,
        ))

        stats = await self.service.get_registration_stats(event_id)

        assert stats["promoted_count"] == 2  # Excludes cancelled
        assert stats["promoted_spots"] == 5  # 3 + 2


class TestDynamoDBSerialization:
    """Test promoted field serialization/deserialization."""

    def test_promoted_roundtrip(self, sample_registration):
        reg = sample_registration(promoted=True)
        item = _registration_to_item(reg)
        assert item["promoted"] is True

        restored = _item_to_registration(item)
        assert restored.promoted is True

    def test_promoted_defaults_false(self, sample_registration):
        reg = sample_registration()
        item = _registration_to_item(reg)
        # Remove promoted to simulate old data
        del item["promoted"]

        restored = _item_to_registration(item)
        assert restored.promoted is False


class TestRegistrationGroupMembers:
    """Group member names captured at registration time."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_dynamodb, sample_event):
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        self.service._registrations_table = self.tables["registrations_table"]
        self.service._events_table = self.tables["events_table"]
        self.sample_event = sample_event

    def _store_event(self, event):
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    @pytest.mark.asyncio
    async def test_group_members_full_list_persisted(self):
        event = self.sample_event(capacity=50)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Anna",
            email="anna@test.com",
            group_size=3,
            group_members=["Anna", "Bob", "Carol"],
        )
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert error is None
        assert reg.group_members == ["Anna", "Bob", "Carol"]

        # Roundtrip through DynamoDB
        item = self.tables["registrations_table"].get_item(
            Key={"pk": f"EVENT#{event.id}", "sk": f"REG#{reg.id}"},
        )["Item"]
        assert item["group_members"] == ["Anna", "Bob", "Carol"]

    @pytest.mark.asyncio
    async def test_group_members_partial_saves_short_list(self):
        event = self.sample_event(capacity=50)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Anna",
            email="anna@test.com",
            group_size=3,
            group_members=["Anna", "Bob"],
        )
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert error is None
        assert reg.group_size == 3
        assert reg.group_members == ["Anna", "Bob"]

    @pytest.mark.asyncio
    async def test_group_members_longer_than_size_rejected(self):
        event = self.sample_event(capacity=50)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Anna",
            email="anna@test.com",
            group_size=2,
            group_members=["Anna", "Bob", "Carol"],
        )
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert reg is None
        assert error == "group_members cannot exceed group_size"

    @pytest.mark.asyncio
    async def test_group_members_omitted_stays_none(self):
        event = self.sample_event(capacity=50)
        self._store_event(event)

        reg_data = RegistrationCreate(name="Anna", email="anna@test.com", group_size=2)
        reg, error = await self.service.create_registration(event.registration_link_token, reg_data)

        assert error is None
        assert reg.group_members is None


class TestRegistrationCreateValidator:
    """RegistrationCreate.group_members validator (Pydantic)."""

    def test_strips_whitespace(self):
        reg = RegistrationCreate(
            name="Anna", email="a@test.com", group_size=2, group_members=["  Bob  "],
        )
        assert reg.group_members == ["Bob"]

    def test_rejects_empty_entry(self):
        with pytest.raises(ValueError, match="non-empty"):
            RegistrationCreate(
                name="Anna", email="a@test.com", group_size=2, group_members=["Anna", "  "],
            )

    def test_rejects_overlong_entry(self):
        with pytest.raises(ValueError, match="200 characters"):
            RegistrationCreate(
                name="Anna",
                email="a@test.com",
                group_size=2,
                group_members=["Anna", "x" * 201],
            )

    def test_none_passthrough(self):
        reg = RegistrationCreate(name="Anna", email="a@test.com", group_size=1)
        assert reg.group_members is None
