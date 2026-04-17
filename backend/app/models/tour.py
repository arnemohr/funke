"""Tour model — Schaluppe tour wrapper around an Event.

Spec 010. A Tour is the crew-facing record of a trip with the Schaluppe.
It may link to an existing Event (public boat party) or stand alone for a
private charter. The Fahrbericht (spec 012) attaches to the Tour.
"""

from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class TourStatus(str, Enum):
    """Tour lifecycle status."""

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


# Legal transitions from the status diagram in spec 010.
TOUR_STATUS_TRANSITIONS: dict[TourStatus, list[TourStatus]] = {
    TourStatus.PLANNED: [TourStatus.IN_PROGRESS, TourStatus.COMPLETED, TourStatus.ARCHIVED],
    TourStatus.IN_PROGRESS: [TourStatus.COMPLETED, TourStatus.ARCHIVED],
    TourStatus.COMPLETED: [TourStatus.ARCHIVED],
    TourStatus.ARCHIVED: [TourStatus.COMPLETED],  # un-archive
}


class CrewRef(BaseModel):
    """Reference to a crew member slot.

    Always carries a display name for rendering. Optionally carries the id of
    an AdminUser profile when the crew slot was filled via the autocomplete
    picker. A stale `admin_user_id` (profile deleted later) is tolerated —
    the display_name is authoritative.
    """

    display_name: str = Field(..., min_length=1, max_length=120)
    admin_user_id: UUID | None = None


class TourBase(BaseModel):
    """Shared fields across create/update/response."""

    event_id: UUID | None = None
    name: str | None = Field(None, max_length=200)
    date: date_type
    duration_hours: Decimal | None = Field(None, ge=0, le=48)
    guest_count: int | None = Field(None, ge=0, le=500)
    charterer: str | None = Field(None, max_length=200)
    funker: CrewRef | None = None
    skipper: CrewRef | None = None
    crew: list[CrewRef] = Field(default_factory=list)


class TourCreate(TourBase):
    """Create payload. `name` is required when no event link is set."""

    def validate_requires_name(self) -> None:
        if not self.event_id and not self.name:
            raise ValueError("name is required when event_id is not set")


class TourPatch(BaseModel):
    """Partial update — every field optional."""

    event_id: UUID | None = None
    name: str | None = Field(None, max_length=200)
    date: date_type | None = None
    duration_hours: Decimal | None = Field(None, ge=0, le=48)
    guest_count: int | None = Field(None, ge=0, le=500)
    charterer: str | None = Field(None, max_length=200)
    funker: CrewRef | None = None
    skipper: CrewRef | None = None
    crew: list[CrewRef] | None = None
    status: TourStatus | None = None


class Tour(TourBase):
    """Full tour record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    org_id: UUID
    status: TourStatus = TourStatus.PLANNED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None

    def can_transition_to(self, new_status: TourStatus) -> bool:
        return new_status in TOUR_STATUS_TRANSITIONS.get(self.status, [])

    def transition_to(self, new_status: TourStatus) -> Self:
        if not self.can_transition_to(new_status):
            raise ValueError(f"Cannot transition tour from {self.status} to {new_status}")
        return self.model_copy(
            update={"status": new_status, "updated_at": datetime.now(timezone.utc)},
        )


class TourResponse(Tour):
    """API response. Same shape as Tour for MVP."""
