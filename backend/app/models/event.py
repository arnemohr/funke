"""Event domain model and schemas.

Represents funke events with their lifecycle status,
capacity settings, and registration configuration.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventStatus(str, Enum):
    """Event lifecycle status."""

    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    LOTTERY_PENDING = "LOTTERY_PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    """Event kind: a classic single-slot event, or a multi-day festival."""

    SINGLE = "SINGLE"
    FESTIVAL = "FESTIVAL"


# Valid status transitions
EVENT_STATUS_TRANSITIONS: dict[EventStatus, list[EventStatus]] = {
    EventStatus.DRAFT: [EventStatus.OPEN, EventStatus.CANCELLED],
    EventStatus.OPEN: [EventStatus.REGISTRATION_CLOSED, EventStatus.CANCELLED],
    EventStatus.REGISTRATION_CLOSED: [
        EventStatus.OPEN,
        EventStatus.LOTTERY_PENDING,
        EventStatus.CONFIRMED,
        EventStatus.CANCELLED,
    ],
    EventStatus.LOTTERY_PENDING: [EventStatus.CONFIRMED, EventStatus.CANCELLED],
    EventStatus.CONFIRMED: [EventStatus.COMPLETED, EventStatus.CANCELLED],
    EventStatus.COMPLETED: [],
    EventStatus.CANCELLED: [],
}


class FestivalSlot(BaseModel):
    """A selectable festival time slot (e.g. "Fr Abend", "Sa Tag").

    A night slot is attributed to the date it starts (gate-day attribution).
    `capacity` is a soft cap only — it is never enforced anywhere.
    """

    key: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    date: date
    is_night: bool = False
    capacity: int | None = Field(None, ge=1)


def _validate_festival_slots(slots: list[FestivalSlot] | None) -> list[FestivalSlot]:
    """Validate a festival event's slot list: non-empty, unique keys, sorted by date."""
    if not slots:
        raise ValueError("Festival events require at least one festival slot")

    keys = [slot.key for slot in slots]
    if len(keys) != len(set(keys)):
        raise ValueError("Festival slot keys must be unique")

    dates = [slot.date for slot in slots]
    if dates != sorted(dates):
        raise ValueError("Festival slots must be sorted chronologically by date")

    return slots


class EventBase(BaseModel):
    """Base event fields shared across create/update/response."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=500)
    start_at: datetime
    capacity: int = Field(default=100, ge=1)
    registration_deadline: datetime
    reminder_schedule_days: list[int] = Field(default_factory=lambda: [7, 3, 1])
    autopromote_waitlist: bool = True
    event_type: EventType = EventType.SINGLE
    end_at: datetime | None = None
    festival_slots: list[FestivalSlot] | None = None
    contact_hint: str | None = Field(None, max_length=500)
    participation_hint: str | None = Field(None, max_length=1000)


class EventCreate(EventBase):
    """Schema for creating a new event."""

    # Relaxed to Optional here only: FESTIVAL events no longer take an
    # explicit "Anmeldeschluss" from the organizer (Ä14/Ä20 — registration
    # simply runs until the festival ends), so the field may be omitted and
    # is defaulted from end_at below. SINGLE events still require it
    # explicitly; EventBase/Event keep it as a required `datetime` since by
    # the time an Event exists the value is always concrete.
    registration_deadline: datetime | None = None

    @field_validator("reminder_schedule_days")
    @classmethod
    def validate_reminder_days(cls, v: list[int]) -> list[int]:
        """Ensure reminder days are positive and sorted descending."""
        if not all(d > 0 for d in v):
            raise ValueError("Reminder days must be positive")
        return sorted(set(v), reverse=True)

    @model_validator(mode="after")
    def validate_festival_fields(self) -> Self:
        """Enforce capacity caps and festival-only requirements (Ä8/Ä14/Ä20).

        The "deadline before start" rule only applies to SINGLE events, which
        must always supply registration_deadline explicitly. For FESTIVAL
        events the deadline always equals the festival's end (Ä14/Ä20 — the
        admin UI no longer exposes an "Anmeldeschluss" input at all); if a
        caller omits it, it's defaulted here to end_at instead of failing the
        required-field check, and rejected only when BOTH are missing
        (event_type is not yet available in a field_validator's info.data,
        hence the check lives here rather than on the registration_deadline
        field_validator).
        """
        if self.event_type == EventType.FESTIVAL:
            if self.registration_deadline is None and self.end_at is None:
                raise ValueError("registration_deadline or end_at is required for festival events")
            if self.end_at is None:
                raise ValueError("end_at is required for festival events")
            if self.registration_deadline is None:
                self.registration_deadline = self.end_at
            _validate_festival_slots(self.festival_slots)
        else:
            if self.registration_deadline is None:
                raise ValueError("registration_deadline is required for SINGLE events")
            if self.registration_deadline >= self.start_at:
                raise ValueError("Registration deadline must be before event start")

        max_capacity = 2000 if self.event_type == EventType.FESTIVAL else 500
        if self.capacity > max_capacity:
            raise ValueError(f"Capacity must not exceed {max_capacity} for {self.event_type.value} events")

        return self


class EventUpdate(BaseModel):
    """Schema for updating an event (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=500)
    start_at: datetime | None = None
    capacity: int | None = Field(None, ge=1)
    registration_deadline: datetime | None = None
    reminder_schedule_days: list[int] | None = None
    autopromote_waitlist: bool | None = None
    event_type: EventType | None = None
    end_at: datetime | None = None
    festival_slots: list[FestivalSlot] | None = None
    contact_hint: str | None = Field(None, max_length=500)
    participation_hint: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_festival_fields(self) -> Self:
        """Mirror EventCreate's capacity/slot rules for partial updates.

        Capacity is only checked against the type cap when both fields are
        present in this update payload — an update touching only capacity
        cannot know the persisted event_type. Slot list shape (non-empty,
        unique keys, sorted dates) is validated whenever festival_slots is
        provided, regardless of whether event_type is part of this payload.

        Like EventCreate, a FESTIVAL update omitting registration_deadline
        gets it defaulted to end_at (Ä14/Ä20) rather than rejected — only
        rejected outright when both are missing from this payload.
        """
        if self.capacity is not None and self.event_type is not None:
            max_capacity = 2000 if self.event_type == EventType.FESTIVAL else 500
            if self.capacity > max_capacity:
                raise ValueError(f"Capacity must not exceed {max_capacity} for {self.event_type.value} events")

        if self.event_type == EventType.FESTIVAL:
            if self.registration_deadline is None and self.end_at is None:
                raise ValueError("registration_deadline or end_at is required for festival events")
            if self.end_at is None:
                raise ValueError("end_at is required for festival events")
            if self.registration_deadline is None:
                self.registration_deadline = self.end_at

        if self.festival_slots is not None:
            _validate_festival_slots(self.festival_slots)

        return self


class Event(EventBase):
    """Full event model with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    org_id: UUID
    status: EventStatus = EventStatus.DRAFT
    registration_link_token: str | None = None
    created_by_admin_id: UUID | None = None
    cloned_from_event_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None
    cancelled_at: datetime | None = None
    ttl: int | None = None  # DynamoDB TTL timestamp
    gate_token: str | None = None
    # Server-side only (spec 019 §P3) — never exposed via EventPublic or the
    # admin EventResponse; only surfaced through the gate-token-authenticated
    # checkin boot endpoint (spec.md:266).
    ticket_secret: str | None = None

    def can_transition_to(self, new_status: EventStatus) -> bool:
        """Check if transition to new status is allowed."""
        return new_status in EVENT_STATUS_TRANSITIONS.get(self.status, [])

    def transition_to(self, new_status: EventStatus) -> Self:
        """Transition to a new status.

        Raises:
            ValueError: If transition is not allowed.
        """
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Cannot transition from {self.status} to {new_status}",
            )

        updates = {"status": new_status}

        if new_status == EventStatus.OPEN:
            updates["published_at"] = datetime.now(timezone.utc)
        elif new_status == EventStatus.CANCELLED:
            updates["cancelled_at"] = datetime.now(timezone.utc)

        return self.model_copy(update=updates)

    def is_registration_open(self) -> bool:
        """Check if registration is currently open."""
        if self.status != EventStatus.OPEN:
            return False
        if datetime.now(timezone.utc) >= self.registration_deadline:
            return False
        return True

    def slot_keys(self) -> list[str]:
        """Return the keys of all festival slots (empty list if none)."""
        return [slot.key for slot in (self.festival_slots or [])]

    def night_slots(self) -> list[FestivalSlot]:
        """Return only the festival slots flagged as overnight (empty list if none)."""
        return [slot for slot in (self.festival_slots or []) if slot.is_night]

    def slots_on(self, d: date) -> list[FestivalSlot]:
        """Return the festival slots attributed to the given gate-day (empty list if none)."""
        return [slot for slot in (self.festival_slots or []) if slot.date == d]


class EventPublic(BaseModel):
    """Public event info for registration page (no sensitive data)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    location: str | None
    start_at: datetime
    capacity: int
    registration_deadline: datetime
    status: str
    autopromote_waitlist: bool
    event_type: str = EventType.SINGLE.value
    end_at: datetime | None = None
    contact_hint: str | None = None
