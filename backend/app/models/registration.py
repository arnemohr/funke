"""Registration domain model and schemas.

Represents event registrations with status tracking,
waitlist positioning, and attendance confirmation workflow.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegistrationStatus(str, Enum):
    """Registration status.

    Lifecycle:
    - REGISTERED: Initial signup, awaiting deadline/lottery
    - CONFIRMED: Won lottery or auto-confirmed, awaiting attendance response
    - WAITLISTED: Lost lottery, eligible for backfill
    - PARTICIPATING: Confirmed attendance (responded YES)
    - CANCELLED: Self-cancelled, lost lottery (no waitlist), or declined
    - CHECKED_IN: Checked in at the event
    """

    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    PARTICIPATING = "PARTICIPATING"
    CANCELLED = "CANCELLED"
    CHECKED_IN = "CHECKED_IN"


class RegistrationCreate(BaseModel):
    """Schema for creating a registration."""

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    group_size: int = Field(default=1, ge=1, le=10)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.lower().strip()


class RegistrationUpdate(BaseModel):
    """Schema for updating a registration (admin use)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    group_size: int | None = Field(None, ge=1, le=10)


class Registration(BaseModel):
    """Full registration model with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    name: str
    email: str
    phone: str | None = None
    notes: str | None = None
    group_size: int = 1
    group_members: list[str] | None = None  # Names of all group members (for passenger list)
    status: RegistrationStatus = RegistrationStatus.REGISTERED
    waitlist_position: int | None = None
    registration_token: str  # For cancellation/confirmation links
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    responded_at: datetime | None = None  # When they responded YES/NO
    promoted_from_waitlist: bool = False
    promoted: bool = False  # Admin flag: guaranteed lottery placement
    ttl: int | None = None  # DynamoDB TTL timestamp

    def can_cancel(self) -> bool:
        """Check if registration can be cancelled."""
        return self.status in [
            RegistrationStatus.REGISTERED,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.WAITLISTED,
            RegistrationStatus.PARTICIPATING,
        ]

    def cancel(self) -> "Registration":
        """Cancel the registration.

        Raises:
            ValueError: If registration cannot be cancelled.
        """
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel registration with status {self.status}")
        return self.model_copy(update={"status": RegistrationStatus.CANCELLED})

    def check_in(self) -> "Registration":
        """Mark registration as checked in.

        Raises:
            ValueError: If registration is not confirmed or participating.
        """
        if self.status not in [RegistrationStatus.CONFIRMED, RegistrationStatus.PARTICIPATING]:
            raise ValueError(f"Cannot check in registration with status {self.status}")
        return self.model_copy(update={"status": RegistrationStatus.CHECKED_IN})

    def promote_from_waitlist(self) -> "Registration":
        """Promote from waitlist to confirmed.

        Raises:
            ValueError: If registration is not waitlisted.
        """
        if self.status != RegistrationStatus.WAITLISTED:
            raise ValueError("Can only promote waitlisted registrations")
        return self.model_copy(
            update={
                "status": RegistrationStatus.CONFIRMED,
                "waitlist_position": None,
                "promoted_from_waitlist": True,
            },
        )

    def confirm(self) -> "Registration":
        """Confirm registration (from REGISTERED to CONFIRMED).

        Used after deadline when under capacity or after winning lottery.

        Raises:
            ValueError: If registration is not in REGISTERED status.
        """
        if self.status != RegistrationStatus.REGISTERED:
            raise ValueError(f"Can only confirm REGISTERED registrations, not {self.status}")
        return self.model_copy(update={"status": RegistrationStatus.CONFIRMED})

    def set_attendance_response(self, participating: bool) -> "Registration":
        """Set attendance response (YES/NO).

        Args:
            participating: True for YES, False for NO.

        Returns:
            Updated registration.

        Raises:
            ValueError: If registration is not in CONFIRMED status.
        """
        if self.status != RegistrationStatus.CONFIRMED:
            raise ValueError(f"Can only respond to CONFIRMED registrations, not {self.status}")

        new_status = RegistrationStatus.PARTICIPATING if participating else RegistrationStatus.CANCELLED
        return self.model_copy(
            update={
                "status": new_status,
                "responded_at": lambda: datetime.now(timezone.utc)(),
            },
        )


class RegistrationResponse(BaseModel):
    """Registration response for API (public-facing)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    name: str
    email: str
    group_size: int
    status: RegistrationStatus
    waitlist_position: int | None
    registration_token: str
    group_members: list[str] | None = None
    registered_at: datetime
    responded_at: datetime | None
    promoted: bool = False
