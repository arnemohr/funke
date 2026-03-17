"""Event domain model and schemas.

Represents funke events with their lifecycle status,
capacity settings, and registration configuration.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventStatus(str, Enum):
    """Event lifecycle status."""

    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    LOTTERY_PENDING = "LOTTERY_PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Valid status transitions
EVENT_STATUS_TRANSITIONS: dict[EventStatus, list[EventStatus]] = {
    EventStatus.DRAFT: [EventStatus.OPEN, EventStatus.CANCELLED],
    EventStatus.OPEN: [EventStatus.REGISTRATION_CLOSED, EventStatus.CANCELLED],
    EventStatus.REGISTRATION_CLOSED: [
        EventStatus.LOTTERY_PENDING,
        EventStatus.CONFIRMED,
        EventStatus.CANCELLED,
    ],
    EventStatus.LOTTERY_PENDING: [EventStatus.CONFIRMED, EventStatus.CANCELLED],
    EventStatus.CONFIRMED: [EventStatus.COMPLETED, EventStatus.CANCELLED],
    EventStatus.COMPLETED: [],
    EventStatus.CANCELLED: [],
}


class EventBase(BaseModel):
    """Base event fields shared across create/update/response."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=500)
    start_at: datetime
    capacity: int = Field(default=100, ge=1, le=500)
    registration_deadline: datetime
    reminder_schedule_days: list[int] = Field(default_factory=lambda: [7, 3, 1])
    autopromote_waitlist: bool = True


class EventCreate(EventBase):
    """Schema for creating a new event."""

    @field_validator("reminder_schedule_days")
    @classmethod
    def validate_reminder_days(cls, v: list[int]) -> list[int]:
        """Ensure reminder days are positive and sorted descending."""
        if not all(d > 0 for d in v):
            raise ValueError("Reminder days must be positive")
        return sorted(set(v), reverse=True)

    @field_validator("registration_deadline")
    @classmethod
    def validate_deadline(cls, v: datetime, info) -> datetime:
        """Ensure registration deadline is before event start."""
        start_at = info.data.get("start_at")
        if start_at and v >= start_at:
            raise ValueError("Registration deadline must be before event start")
        return v


class EventUpdate(BaseModel):
    """Schema for updating an event (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=500)
    start_at: datetime | None = None
    capacity: int | None = Field(None, ge=1, le=500)
    registration_deadline: datetime | None = None
    reminder_schedule_days: list[int] | None = None
    autopromote_waitlist: bool | None = None


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
            updates["published_at"] = lambda: datetime.now(timezone.utc)()
        elif new_status == EventStatus.CANCELLED:
            updates["cancelled_at"] = lambda: datetime.now(timezone.utc)()

        return self.model_copy(update=updates)

    def is_registration_open(self) -> bool:
        """Check if registration is currently open."""
        if self.status != EventStatus.OPEN:
            return False
        if lambda: datetime.now(timezone.utc)() >= self.registration_deadline:
            return False
        return True


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
