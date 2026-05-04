"""Tests for the admin single-registration patch endpoint (spec 018).

Covers RegistrationService.admin_update_registration: rename + delete flows,
group_size guards, frozen-state rejections, optimistic concurrency on
status + responded_at.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models import (
    EventStatus,
    RegistrationAdminPatch,
    RegistrationStatus,
)
from app.services.event_service import (
    _event_to_item,
    get_event_service,
)
from app.services.registration_service import (
    RegistrationService,
    _item_to_registration,
    _registration_to_item,
)


@pytest.fixture
def admin_service(mock_dynamodb):
    """Service wired to the moto tables, with the event_service singleton aligned too.

    The service method resolves its event lookup through the global
    ``event_service`` singleton; without aligning its ``_table`` we'd hit a
    stale (or unset) table reference between tests.
    """
    service = RegistrationService()
    service._registrations_table = mock_dynamodb["registrations_table"]
    service._events_table = mock_dynamodb["events_table"]

    event_service = get_event_service()
    event_service._table = mock_dynamodb["events_table"]

    return service


def _store_event(tables, event):
    tables["events_table"].put_item(Item=_event_to_item(event))


def _store_registration(tables, reg):
    tables["registrations_table"].put_item(Item=_registration_to_item(reg))


def _read_registration(tables, event_id, registration_id):
    item = tables["registrations_table"].get_item(
        Key={"pk": f"EVENT#{event_id}", "sk": f"REG#{registration_id}"},
    ).get("Item")
    return _item_to_registration(item) if item else None


@pytest.mark.asyncio
async def test_rename_single_guest(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.CONFIRMED)
    reg = sample_registration(
        event_id=event.id,
        group_size=3,
        group_members=["Alice", "Bob", "Carol"],
        status=RegistrationStatus.PARTICIPATING,
        responded_at=datetime.now(timezone.utc),
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(group_members=["Alice", "Bob", "Carolina"], group_size=3)
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert error is None
    assert updated.group_size == 3
    assert updated.group_members == ["Alice", "Bob", "Carolina"]


@pytest.mark.asyncio
async def test_delete_one_named_guest(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.CONFIRMED)
    reg = sample_registration(
        event_id=event.id,
        group_size=3,
        group_members=["Alice", "Bob", "Carol"],
        status=RegistrationStatus.PARTICIPATING,
        responded_at=datetime.now(timezone.utc),
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    # Drop "Bob": new list of length 2, send group_size + group_members atomically.
    patch = RegistrationAdminPatch(group_size=2, group_members=["Alice", "Carol"])
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert error is None
    assert updated.group_size == 2
    assert updated.group_members == ["Alice", "Carol"]


@pytest.mark.asyncio
async def test_delete_placeholder_pre_confirmation(admin_service, mock_dynamodb, sample_event, sample_registration):
    """Pre-confirmation: group_members is None. Admin shrinks via group_size only."""
    event = sample_event(status=EventStatus.OPEN)
    reg = sample_registration(
        event_id=event.id,
        group_size=4,
        group_members=None,
        status=RegistrationStatus.REGISTERED,
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(group_size=3)
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert error is None
    assert updated.group_size == 3
    assert updated.group_members is None


@pytest.mark.asyncio
async def test_reject_grow_via_group_size(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.OPEN)
    reg = sample_registration(event_id=event.id, group_size=2, status=RegistrationStatus.REGISTERED)
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(group_size=3)
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert updated is None
    assert error == "invalid_group_size"


@pytest.mark.asyncio
async def test_reject_grow_via_group_members(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.CONFIRMED)
    reg = sample_registration(
        event_id=event.id,
        group_size=2,
        group_members=["Alice", "Bob"],
        status=RegistrationStatus.PARTICIPATING,
        responded_at=datetime.now(timezone.utc),
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(group_members=["Alice", "Bob", "Carol"])
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert updated is None
    assert error == "invalid_group_members"


@pytest.mark.asyncio
async def test_reject_cancelled_registration(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.OPEN)
    reg = sample_registration(event_id=event.id, status=RegistrationStatus.CANCELLED)
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(name="New Name")
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert updated is None
    assert error == "frozen_registration"


@pytest.mark.asyncio
async def test_reject_completed_event(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.COMPLETED)
    reg = sample_registration(event_id=event.id, status=RegistrationStatus.PARTICIPATING)
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(name="New Name")
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert updated is None
    assert error == "frozen_event"


@pytest.mark.asyncio
async def test_clear_phone(admin_service, mock_dynamodb, sample_event, sample_registration):
    event = sample_event(status=EventStatus.OPEN)
    reg = sample_registration(
        event_id=event.id,
        phone="+49 123 456",
        status=RegistrationStatus.REGISTERED,
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(phone="")
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert error is None
    assert updated.phone is None


@pytest.mark.asyncio
async def test_concurrency_conflict_on_responded_at(admin_service, mock_dynamodb, sample_event, sample_registration):
    """Simulate the registrant confirming via the public link mid-edit.

    The admin loaded the registration before responded_at was set; saving with a
    stale baseline must hit ConditionExpression failure → ``conflict``.
    """
    event = sample_event(status=EventStatus.CONFIRMED)
    reg = sample_registration(
        event_id=event.id,
        group_size=2,
        status=RegistrationStatus.CONFIRMED,
        responded_at=None,
    )
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    # Admin loaded; service's view of `responded_at` is None. Now another writer
    # sets responded_at — flipping the row out from under the admin's baseline.
    mock_dynamodb["registrations_table"].update_item(
        Key={"pk": f"EVENT#{reg.event_id}", "sk": f"REG#{reg.id}"},
        UpdateExpression="SET responded_at = :ts",
        ExpressionAttributeValues={":ts": datetime.now(timezone.utc).isoformat()},
    )

    # Patch the service to bypass its own re-read so we exercise the
    # ConditionExpression. We do that by calling admin_update_registration twice:
    # the first call seeds the in-memory view and the side-channel mutation
    # already happened. We need to ensure get_registration returns the OLD state.
    # The service re-loads inside, so we bypass that by spying.
    original_get = admin_service.get_registration

    async def stale_get(*args, **kwargs):
        result = await original_get(*args, **kwargs)
        if result is None:
            return None
        # Pretend responded_at is still None (admin's stale view).
        return result.model_copy(update={"responded_at": None})

    admin_service.get_registration = stale_get
    try:
        patch = RegistrationAdminPatch(name="Changed")
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)
    finally:
        admin_service.get_registration = original_get

    assert updated is None
    assert error == "conflict"


@pytest.mark.asyncio
async def test_no_changes_returns_current(admin_service, mock_dynamodb, sample_event, sample_registration):
    """An empty patch (no changes vs server) must not issue a write — return current."""
    event = sample_event(status=EventStatus.OPEN)
    reg = sample_registration(event_id=event.id, name="Same", status=RegistrationStatus.REGISTERED)
    _store_event(mock_dynamodb, event)
    _store_registration(mock_dynamodb, reg)

    patch = RegistrationAdminPatch(name="Same")  # equals current
    updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

    assert error is None
    assert updated.id == reg.id
    assert updated.name == "Same"
