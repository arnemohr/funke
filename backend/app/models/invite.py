"""Invite domain model and schemas (spec 019 — festival sidetrack).

A festival event has no public registration link; every registration
happens through an ``Invite`` — a personal or capped community link with
its own use-count, group-size allowance, and optional expiry. Registration
ONLY happens via an invite link (Ä3, Ä7, Ä11).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Invite(BaseModel):
    """Full invite model with all fields.

    Immutable updates via ``model_copy(update={...})`` only.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    org_id: UUID
    token: str
    label: str = Field(..., min_length=1, max_length=200)
    batch_label: str | None = Field(None, max_length=200)
    email: EmailStr | None = None
    tier: str = Field(..., max_length=50)  # free-form; conventions: werft/volunteer/org/open
    max_uses: int = Field(default=1, ge=1)
    use_count: int = Field(default=0, ge=0)
    max_group_size: int = Field(default=1, ge=1, le=20)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by_admin_id: UUID | None = None
    sent_at: datetime | None = None
    last_registered_at: datetime | None = None

    def is_expired(self, registration_deadline: datetime) -> bool:
        """Check whether this invite can no longer be redeemed.

        True when explicitly revoked, when its own ``expires_at`` has
        passed, or when the event's registration deadline has passed
        (implicit expiry — an invite never outlives its event).
        """
        now = datetime.now(timezone.utc)
        if self.revoked_at is not None:
            return True
        if self.expires_at is not None and now >= self.expires_at:
            return True
        if now >= registration_deadline:
            return True
        return False


class InviteCreate(BaseModel):
    """Schema for a single invite within a batch-create request."""

    label: str = Field(..., min_length=1, max_length=200)
    email: EmailStr | None = None
    tier: str = Field(..., max_length=50)
    max_uses: int = Field(default=1, ge=1)
    max_group_size: int = Field(default=1, ge=1, le=20)
    expires_at: datetime | None = None


class InviteBatchCreate(BaseModel):
    """Schema for batch-creating invites (a Kontingent)."""

    batch_label: str | None = Field(None, max_length=200)
    invites: list[InviteCreate] = Field(..., min_length=1)
    # When true, the F1 invitation is sent immediately to every invite in the
    # batch that has an email (and `sent_at` stamped). Defaults False so API
    # clients never fire mail unexpectedly; the create modal sends true.
    send_emails: bool = False


class InviteUpdate(BaseModel):
    """Partial-update payload for admin invite edits."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    tier: str | None = Field(None, max_length=50)
    max_uses: int | None = Field(None, ge=1)
    max_group_size: int | None = Field(None, ge=1, le=20)
    expires_at: datetime | None = None
