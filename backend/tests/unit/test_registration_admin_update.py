"""Tests for the admin single-registration patch endpoint (spec 018).

Covers RegistrationService.admin_update_registration: rename + delete flows,
group_size guards, frozen-state rejections, optimistic concurrency on
status + responded_at.
"""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.models import (
    AccommodationType,
    EventStatus,
    EventType,
    FestivalSlot,
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


def _festival_slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
    ]


class TestFestivalAdminPatch:
    """T205: RegistrationAdminPatch festival fields — slot membership,
    the Ä15 phone-iff-accommodation rule enforced on the resulting state,
    the Ä17 overnight_approved write path, and the T109 append-only
    group_members rule reused for festival admin edits.
    """

    def _festival_event(self, sample_event, **overrides):
        defaults = {
            "event_type": EventType.FESTIVAL,
            "festival_slots": _festival_slots(),
            "status": EventStatus.OPEN,
        }
        defaults.update(overrides)
        return sample_event(**defaults)

    @pytest.mark.asyncio
    async def test_unknown_slot_key_rejected(self, admin_service, mock_dynamodb, sample_event, sample_registration):
        event = self._festival_event(sample_event)
        reg = sample_registration(
            event_id=event.id, status=RegistrationStatus.REGISTERED, attendance_slots=["fr"],
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        patch = RegistrationAdminPatch(attendance_slots=["fr", "removed-slot"])
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

        assert updated is None
        assert error == "invalid_slots"

    @pytest.mark.asyncio
    async def test_valid_slot_subset_persisted(self, admin_service, mock_dynamodb, sample_event, sample_registration):
        event = self._festival_event(sample_event)
        reg = sample_registration(
            event_id=event.id, status=RegistrationStatus.REGISTERED, attendance_slots=["fr"],
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        patch = RegistrationAdminPatch(attendance_slots=["sa"])
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

        assert error is None
        assert updated.attendance_slots == ["sa"]

    @pytest.mark.asyncio
    async def test_accommodation_without_phone_rejected_then_accepted_with_phone(
        self, admin_service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = self._festival_event(sample_event)
        reg = sample_registration(
            event_id=event.id, status=RegistrationStatus.REGISTERED, attendance_slots=["fr"], phone=None,
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        patch = RegistrationAdminPatch(accommodation=AccommodationType.TENT)
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)
        assert updated is None
        assert error == "phone_required_for_accommodation"

        patch2 = RegistrationAdminPatch(accommodation=AccommodationType.TENT, phone="+49 111")
        updated2, error2 = await admin_service.admin_update_registration(event.id, reg.id, patch2)
        assert error2 is None
        assert updated2.accommodation == AccommodationType.TENT
        assert updated2.phone == "+49 111"

    @pytest.mark.asyncio
    async def test_clearing_accommodation_clears_phone_and_resets_approval(
        self, admin_service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = self._festival_event(sample_event)
        reg = sample_registration(
            event_id=event.id,
            status=RegistrationStatus.REGISTERED,
            attendance_slots=["fr"],
            accommodation=AccommodationType.TENT,
            phone="+49 111",
            overnight_approved=True,
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        patch = RegistrationAdminPatch(accommodation=None)
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

        assert error is None
        assert updated.accommodation is None
        assert updated.phone is None
        assert updated.overnight_approved is False

    @pytest.mark.asyncio
    async def test_overnight_approved_write_path_and_rejection_without_wish(
        self, admin_service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = self._festival_event(sample_event)
        reg_with_wish = sample_registration(
            event_id=event.id,
            status=RegistrationStatus.REGISTERED,
            attendance_slots=["fr"],
            accommodation=AccommodationType.CAMPER,
            phone="+49 222",
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg_with_wish)

        patch = RegistrationAdminPatch(overnight_approved=True)
        updated, error = await admin_service.admin_update_registration(event.id, reg_with_wish.id, patch)
        assert error is None
        assert updated.overnight_approved is True

        reg_no_wish = sample_registration(
            event_id=event.id, status=RegistrationStatus.REGISTERED, attendance_slots=["fr"],
        )
        _store_registration(mock_dynamodb, reg_no_wish)

        patch2 = RegistrationAdminPatch(overnight_approved=True)
        updated2, error2 = await admin_service.admin_update_registration(event.id, reg_no_wish.id, patch2)
        assert updated2 is None
        assert error2 == "overnight_approval_requires_accommodation"

    @pytest.mark.asyncio
    async def test_slot_fields_rejected_on_single_event(
        self, admin_service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = sample_event(status=EventStatus.OPEN)  # default event_type=SINGLE
        reg = sample_registration(event_id=event.id, status=RegistrationStatus.REGISTERED)
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        patch = RegistrationAdminPatch(attendance_slots=["fr"])
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, patch)

        assert updated is None
        assert error == "not_festival_event"

    def test_unknown_fields_still_rejected(self):
        with pytest.raises(Exception):
            RegistrationAdminPatch(attendance_slots=["fr"], not_a_real_field="x")

    @pytest.mark.asyncio
    async def test_group_members_append_only_tombstone_rule_reused(
        self, admin_service, mock_dynamodb, sample_event, sample_registration,
    ):
        """Festival admin patches follow T109's append-only rule, not the
        SINGLE-event shrink-only rule: shrinking the list outright is
        rejected, but a same-length tombstone (None) followed by an append
        is accepted and never reindexes surviving entries.
        """
        event = self._festival_event(sample_event)
        reg = sample_registration(
            event_id=event.id,
            status=RegistrationStatus.REGISTERED,
            attendance_slots=["fr"],
            group_size=3,
            group_members=["Alice", "Bob"],
        )
        _store_event(mock_dynamodb, event)
        _store_registration(mock_dynamodb, reg)

        # Outright shrink is rejected — must use a tombstone instead.
        shrink_patch = RegistrationAdminPatch(group_members=["Alice"])
        updated, error = await admin_service.admin_update_registration(event.id, reg.id, shrink_patch)
        assert updated is None
        assert error == "invalid_group_members"

        # Tombstone Bob, then append Carol — indices never shift.
        patch = RegistrationAdminPatch(group_members=["Alice", None, "Carol"])
        updated2, error2 = await admin_service.admin_update_registration(event.id, reg.id, patch)

        assert error2 is None
        assert updated2.group_members == ["Alice", None, "Carol"]
        assert updated2.group_size == 3
