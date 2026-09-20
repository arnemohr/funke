"""Invite domain model and schemas (spec 019 — festival sidetrack).

A festival event has no public registration link; every registration
happens through an ``Invite`` — a personal or capped community link with
its own use-count, group-size allowance, and optional expiry. Registration
ONLY happens via an invite link (Ä3, Ä7, Ä11).
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

if TYPE_CHECKING:
    from .event import EventStatus


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
    # „Später Fisch" — this one invite still works after registration closed.
    # It opens exactly two EVENT-level gates (the deadline, and the „status
    # must be OPEN" rule) and nothing else: revoked, exhausted, `expires_at`
    # and the group-size limit all still bind. Deliberately per-invite, so
    # letting one person in never reopens the door for everyone holding an old
    # contingent link.
    late_entry: bool = False
    # The allowance this list had BEFORE it was reopened for a counted number
    # of seats. Reopening clamps `max_uses` to `use_count + n`, which would
    # otherwise destroy the original number — „Aline · open" would go from 200
    # to 89 with no record that it ever was 200. Snapshotted on the first
    # reopen, restored and cleared on close, so the clamp is a temporary state
    # rather than a one-way edit. `None` = never reopened.
    original_max_uses: int | None = None

    @property
    def binds_to_email(self) -> bool:
        """Whether redemption must use this invite's own address.

        Only a link issued for a SINGLE use is tied to one person. A reopened
        Kontingent is also `late_entry` and also carries an address — that of
        the list owner — but several different guests are supposed to use it,
        so binding it would nail the form to the owner's address and lock
        everyone else out. `max_uses == 1` is what actually distinguishes
        „this link is for you" from „this link is for your people".
        """
        return self.late_entry and self.email is not None and self.max_uses == 1

    def is_expired(self, registration_deadline: datetime) -> bool:
        """Check whether this invite can no longer be redeemed.

        True when explicitly revoked, when its own ``expires_at`` has
        passed, or when the event's registration deadline has passed
        (implicit expiry — an invite never outlives its event).

        A `late_entry` invite is the exception to the last rule: outliving the
        deadline is its entire purpose, so only its OWN `expires_at` bounds it.
        Give those invites an `expires_at` — otherwise nothing but the event
        status stops them.
        """
        now = datetime.now(timezone.utc)
        if self.revoked_at is not None:
            return True
        if self.expires_at is not None and now >= self.expires_at:
            return True
        if self.late_entry:
            return False
        if now >= registration_deadline:
            return True
        return False

    def registration_block_reason(
        self,
        event_status: "EventStatus",
        registration_deadline: datetime,
    ) -> str | None:
        """Why this invite cannot be redeemed right now — `None` when it can.

        THE single decision point, shared by the three places that used to ask
        the question separately and could therefore disagree: the invite boot
        (which turns the reason into German), `create_festival_registration`
        (which turns it into an error), and the public guestlist page's
        `can_register` flag (which just checks for `None`). The guestlist was
        in fact already lying — it never looked at the event status, so a
        contingent owner was told they could still register after the event
        moved to CONFIRMED.

        Reasons: ``revoked``, ``exhausted``, ``expired``, ``deadline_passed``,
        ``not_open``.
        """
        from .event import EventStatus as _EventStatus

        now = datetime.now(timezone.utc)
        if self.revoked_at is not None:
            return "revoked"
        if self.use_count >= self.max_uses:
            return "exhausted"
        if self.expires_at is not None and now >= self.expires_at:
            return "expired"
        if not self.late_entry and now >= registration_deadline:
            return "deadline_passed"
        # A late invite stays usable while the event is LIVE — but not once it
        # is over or called off, so nobody has to remember to switch it off.
        allowed = (
            {_EventStatus.OPEN, _EventStatus.REGISTRATION_CLOSED, _EventStatus.CONFIRMED}
            if self.late_entry
            else {_EventStatus.OPEN}
        )
        if event_status not in allowed:
            return "not_open"
        return None


class InviteCreate(BaseModel):
    """Schema for a single invite within a batch-create request."""

    label: str = Field(..., min_length=1, max_length=200)
    email: EmailStr | None = None
    tier: str = Field(..., max_length=50)
    max_uses: int = Field(default=1, ge=1)
    max_group_size: int = Field(default=1, ge=1, le=20)
    expires_at: datetime | None = None
    # „Später Fisch" — see `Invite.late_entry`.
    late_entry: bool = False


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
    # Patchable so a late invite can be switched off again without revoking it.
    late_entry: bool | None = None
