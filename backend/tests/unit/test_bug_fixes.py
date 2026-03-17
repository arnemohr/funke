"""Tests verifying bug fixes (T2.1–T2.6)."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from moto import mock_aws

from app.models import (
    Event,
    EventStatus,
    Registration,
    RegistrationCreate,
    RegistrationStatus,
)
from app.services.registration_service import (
    RegistrationService,
    _registration_to_item,
)


class TestRegistrationToItem:
    """T2.1: _registration_to_item produces lowercase pk/sk."""

    def test_pk_sk_are_lowercase(self, sample_registration):
        registration = sample_registration()
        item = _registration_to_item(registration)

        assert "pk" in item
        assert "sk" in item
        assert "PK" not in item
        assert "SK" not in item
        assert item["pk"].startswith("EVENT#")
        assert item["sk"].startswith("REG#")

    def test_item_contains_all_required_fields(self, sample_registration):
        registration = sample_registration(
            phone="+49123",
            notes="test notes",
            waitlist_position=3,
        )
        item = _registration_to_item(registration)

        assert item["name"] == registration.name
        assert item["email"] == registration.email
        assert item["group_size"] == registration.group_size
        assert item["status"] == registration.status.value
        assert item["phone"] == "+49123"
        assert item["notes"] == "test notes"
        assert item["waitlist_position"] == 3
        assert item["entity_type"] == "Registration"


class TestCreateRegistrationStatus:
    """T2.2: create_registration assigns CONFIRMED/WAITLISTED based on capacity."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        """Set up environment and service for each test."""
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        # Inject the mocked tables directly
        self.service._registrations_table = mock_dynamodb["registrations_table"]
        self.service._events_table = mock_dynamodb["events_table"]

    def _store_event(self, event: Event):
        """Store an event in the mocked table."""
        from app.services.event_service import _event_to_item

        item = _event_to_item(event)
        self.tables["events_table"].put_item(Item=item)

    @pytest.mark.asyncio
    async def test_registration_registered_when_under_capacity(self, sample_event):
        event = sample_event(capacity=10, status=EventStatus.OPEN)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Alice",
            email="alice@example.com",
            group_size=2,
        )

        registration, error = await self.service.create_registration(
            event.registration_link_token, reg_data,
        )

        assert error is None
        assert registration is not None
        assert registration.status == RegistrationStatus.REGISTERED
        assert registration.waitlist_position is None

    @pytest.mark.asyncio
    async def test_registration_waitlisted_when_at_capacity(self, sample_event):
        event = sample_event(capacity=2, status=EventStatus.OPEN)
        self._store_event(event)

        # Fill capacity first
        reg1 = RegistrationCreate(
            name="Alice",
            email="alice@example.com",
            group_size=2,
        )
        r1, _ = await self.service.create_registration(
            event.registration_link_token, reg1,
        )
        assert r1.status == RegistrationStatus.REGISTERED

        # Next registration should be waitlisted
        reg2 = RegistrationCreate(
            name="Bob",
            email="bob@example.com",
            group_size=1,
        )
        r2, error = await self.service.create_registration(
            event.registration_link_token, reg2,
        )

        assert error is None
        assert r2 is not None
        assert r2.status == RegistrationStatus.WAITLISTED
        assert r2.waitlist_position == 1

    @pytest.mark.asyncio
    async def test_registration_rejected_for_draft_event(self, sample_event):
        event = sample_event(status=EventStatus.DRAFT)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Alice",
            email="alice@example.com",
            group_size=1,
        )
        registration, error = await self.service.create_registration(
            event.registration_link_token, reg_data,
        )

        assert registration is None
        assert error == "Registration is not open for this event"

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self, sample_event):
        event = sample_event(capacity=10, status=EventStatus.OPEN)
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Alice",
            email="alice@example.com",
            group_size=1,
        )
        r1, _ = await self.service.create_registration(
            event.registration_link_token, reg_data,
        )
        assert r1 is not None

        # Same email should be rejected
        r2, error = await self.service.create_registration(
            event.registration_link_token, reg_data,
        )
        assert r2 is None
        assert "already registered" in error.lower()


class TestRegistrationDeadline:
    """T2.4: DRAFT events blocked from registration."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = RegistrationService()
        self.service._registrations_table = mock_dynamodb["registrations_table"]
        self.service._events_table = mock_dynamodb["events_table"]

    def _store_event(self, event: Event):
        from app.services.event_service import _event_to_item

        item = _event_to_item(event)
        self.tables["events_table"].put_item(Item=item)

    @pytest.mark.asyncio
    async def test_past_deadline_rejected(self, sample_event):
        event = sample_event(
            status=EventStatus.OPEN,
            registration_deadline=datetime.now(timezone.utc) - timedelta(days=1),
        )
        self._store_event(event)

        reg_data = RegistrationCreate(
            name="Alice",
            email="alice@example.com",
            group_size=1,
        )
        registration, error = await self.service.create_registration(
            event.registration_link_token, reg_data,
        )

        assert registration is None
        assert "deadline" in error.lower()
