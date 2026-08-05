"""Registration domain model and schemas.

Represents event registrations with status tracking,
waitlist positioning, and attendance confirmation workflow.
"""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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


class AccommodationType(str, Enum):
    """Overnight accommodation choice for festival registrations (Ä15).

    NEEDS_SPOT was dropped; `None` on the registration means "übernachtet
    nicht". This is a REQUEST, not an entitlement (Ä17) — see
    `Registration.overnight_approved`.
    """

    TENT = "TENT"
    CAMPER = "CAMPER"


def _has_two_words(value: str) -> bool:
    """Check whether a name contains at least two whitespace-separated words."""
    return len(value.split()) >= 2


def _normalize_overnight_counts(model: BaseModel, group_size: int) -> None:
    """Normalize `tent_count`/`camper_count` in place (Ä21).

    A count of 0 becomes None ("keine"); neither may exceed `group_size`.
    Shared by `FestivalRegistrationCreate`; the patch schemas leave the
    resulting-state check to the service (it needs the stored group size).
    """
    for field in ("tent_count", "camper_count"):
        value = getattr(model, field)
        if value in (None, 0):
            object.__setattr__(model, field, None)
        elif value > group_size:
            raise ValueError(f"{field} must not exceed group_size")


def _clean_member_emails(v: list[str | None] | None) -> list[str | None] | None:
    """Shape-only pre-validation for companion addresses (spec 020).

    Blank/whitespace entries become `None` so an untouched form field reads as
    "no address" rather than failing `EmailStr`; everything else is lowercased
    and stripped to match `normalize_email` on the contact address. Actual
    address syntax is left to `EmailStr`.
    """
    if v is None:
        return None
    cleaned: list[str | None] = []
    for entry in v:
        if entry is None:
            cleaned.append(None)
            continue
        stripped = str(entry).strip().lower()
        cleaned.append(stripped or None)
    return cleaned


def _align_member_emails(
    emails: list[str | None] | None,
    members: list[str | None] | None,
    *,
    collapse_empty: bool,
) -> list[str | None] | None:
    """Index-align companion addresses with `group_members` (spec 020).

    `group_member_emails` is read positionally in lockstep with
    `group_members` — index *i* is the address of `group_members[i]`, and
    `person_index` is `i + 1`. A length mismatch or an address parked on a
    `None` tombstone would therefore mail a personalised QR to the wrong
    human, so both are hard errors rather than best-effort repairs. A short
    list is padded (the common case: only the first companion has an address).

    `collapse_empty` folds an all-`None` list back to `None`. Correct for
    create schemas, where "field absent" and "no addresses given" mean the
    same thing — and deliberately WRONG for patch schemas, where `None` means
    "not provided" and collapsing would silently swallow a request to clear
    every address.
    """
    if emails is None:
        return None
    if collapse_empty and not any(email is not None for email in emails):
        return None
    if members is None:
        if any(email is not None for email in emails):
            raise ValueError("group_member_emails requires group_members")
        return None if collapse_empty else emails
    if len(emails) > len(members):
        raise ValueError("group_member_emails must not be longer than group_members")

    padded: list[str | None] = list(emails) + [None] * (len(members) - len(emails))
    # strict=True: padded is built to match members exactly, so a mismatch
    # here means the padding logic above broke, not bad input.
    for i, (member, email) in enumerate(zip(members, padded, strict=True)):
        if member is None and email is not None:
            raise ValueError(
                f"group_member_emails[{i}] is set but group_members[{i}] was removed",
            )
    return padded


class RegistrationCreate(BaseModel):
    """Schema for creating a registration."""

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    group_size: int = Field(default=1, ge=1, le=5)
    group_members: list[str] | None = Field(default=None)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.lower().strip()

    @field_validator("group_members")
    @classmethod
    def _clean_members(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned: list[str] = []
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("group_members entries must be non-empty")
            if len(stripped) > 200:
                raise ValueError("group_members entries must be at most 200 characters")
            cleaned.append(stripped)
        return cleaned or None


class FestivalRegistrationCreate(BaseModel):
    """Schema for creating a festival registration (spec 019).

    Separate from `RegistrationCreate` — the existing `le=5` group cap on the
    latter stays untouched; festival groups may be much larger (invite-gated).
    """

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    notes: str | None = Field(None, max_length=500)
    group_size: int = Field(default=1, ge=1, le=20)
    group_members: list[str] | None = Field(default=None)
    # Spec 020: optional per-companion address, index-aligned with
    # `group_members`. Given one, that companion gets their own F5 with only
    # their own QR instead of the contact forwarding it by hand.
    group_member_emails: list[EmailStr | None] | None = Field(default=None)
    attendance_slots: list[str] = Field(..., min_length=1)
    # Ä20/Ä21: overnight is captured as two independent unit counts — a group
    # may bring tents AND campers. `None`/0 on both means "übernachtet nicht".
    tent_count: int | None = Field(None, ge=0, le=20)
    camper_count: int | None = Field(None, ge=0, le=20)
    phone: str | None = Field(None, max_length=50)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.lower().strip()

    @field_validator("group_members")
    @classmethod
    def _clean_members(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned: list[str] = []
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("group_members entries must be non-empty")
            if len(stripped) > 200:
                raise ValueError("group_members entries must be at most 200 characters")
            cleaned.append(stripped)
        return cleaned or None

    @field_validator("name")
    @classmethod
    def _full_name(cls, v: str) -> str:
        if not _has_two_words(v):
            raise ValueError("Bitte Vor- und Nachnamen angeben")
        return v

    @field_validator("group_members")
    @classmethod
    def _full_name_members(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        for entry in v:
            if not _has_two_words(entry):
                raise ValueError("Bitte Vor- und Nachnamen angeben")
        return v

    @field_validator("attendance_slots")
    @classmethod
    def _clean_slots(cls, v: list[str]) -> list[str]:
        """Shape-only validation: non-empty strings, dedupe preserving order.

        Without the dedupe, a raw API payload like ["freitag", "freitag"]
        would be persisted as-is and double-count in the headcount board
        (get_headcount adds group_size once per occurrence). Mirrors
        `RegistrationAdminPatch._clean_slots`; slot-key membership against
        `event.festival_slots` stays a service-level concern.
        """
        cleaned: list[str] = []
        seen: set[str] = set()
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("attendance_slots entries must be non-empty")
            if stripped not in seen:
                seen.add(stripped)
                cleaned.append(stripped)
        if not cleaned:
            raise ValueError("attendance_slots must not be empty")
        return cleaned

    _clean_emails = field_validator("group_member_emails", mode="before")(
        staticmethod(_clean_member_emails),
    )

    @model_validator(mode="after")
    def _align_emails(self) -> "FestivalRegistrationCreate":
        object.__setattr__(
            self,
            "group_member_emails",
            _align_member_emails(
                self.group_member_emails, self.group_members, collapse_empty=True,
            ),
        )
        return self

    @model_validator(mode="after")
    def _phone_required(self) -> "FestivalRegistrationCreate":
        if not self.phone or not self.phone.strip():
            raise ValueError("phone is required")
        return self

    @model_validator(mode="after")
    def _normalize_overnight_counts(self) -> "FestivalRegistrationCreate":
        """Normalize the tent/camper counts (Ä21).

        0 is stored as None ("keine"), and neither count may exceed the group
        size (a group cannot bring more tents — or more campers — than it has
        people). Bringing both is allowed; the two are independent.
        """
        _normalize_overnight_counts(self, self.group_size)
        return self


class FestivalAttendancePatch(BaseModel):
    """Partial-update payload for public self-service festival attendance edits.

    `overnight_approved` is deliberately NOT a field here (Ä17) — guests can
    never set it; `extra="forbid"` also rejects any attempt to smuggle it in.
    """

    model_config = ConfigDict(extra="forbid")

    attendance_slots: list[str] | None = None
    tent_count: int | None = Field(None, ge=0, le=20)
    camper_count: int | None = Field(None, ge=0, le=20)
    phone: str | None = Field(None, max_length=50)
    group_size: int | None = Field(None, ge=1, le=20)
    # None entries are tombstones for removed members (T109) — indices never shift.
    group_members: list[str | None] | None = None
    # Spec 020: index-aligned with `group_members`. NOT collapsed when every
    # entry is None — on a patch that is a request to clear every address, and
    # folding it to None would make it indistinguishable from "not provided".
    group_member_emails: list[EmailStr | None] | None = None

    @field_validator("group_members")
    @classmethod
    def _clean_members(cls, v: list[str | None] | None) -> list[str | None] | None:
        if v is None:
            return None
        cleaned: list[str | None] = []
        for entry in v:
            if entry is None:
                cleaned.append(None)
                continue
            stripped = entry.strip()
            if not stripped:
                raise ValueError("group_members entries must be non-empty")
            if len(stripped) > 200:
                raise ValueError("group_members entries must be at most 200 characters")
            if not _has_two_words(stripped):
                raise ValueError("Bitte Vor- und Nachnamen angeben")
            cleaned.append(stripped)
        return cleaned

    _clean_emails = field_validator("group_member_emails", mode="before")(
        staticmethod(_clean_member_emails),
    )

    @model_validator(mode="after")
    def _align_emails(self) -> "FestivalAttendancePatch":
        # Only checkable here when the patch carries both arrays; a patch
        # sending addresses alone is aligned against the STORED members in
        # `update_festival_attendance`, which is the only place that knows them.
        if self.group_member_emails is not None and self.group_members is not None:
            object.__setattr__(
                self,
                "group_member_emails",
                _align_member_emails(
                    self.group_member_emails, self.group_members, collapse_empty=False,
                ),
            )
        return self

    @field_validator("attendance_slots")
    @classmethod
    def _clean_slots(cls, v: list[str] | None) -> list[str] | None:
        """Shape-only validation: non-empty strings, dedupe preserving order.

        Mirrors `RegistrationAdminPatch._clean_slots` — without it a raw
        API payload with a duplicated slot key would double-count in the
        headcount board. Slot-key membership is a service-level concern.
        """
        if v is None:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("attendance_slots entries must be non-empty")
            if stripped not in seen:
                seen.add(stripped)
                cleaned.append(stripped)
        if not cleaned:
            raise ValueError("attendance_slots must not be empty")
        return cleaned


class RegistrationUpdate(BaseModel):
    """Schema for updating a registration (admin use)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    group_size: int | None = Field(None, ge=1, le=10)


class RegistrationAdminPatch(BaseModel):
    """Partial-update payload for admin single-registration edits (spec 018).

    Extended for the festival sidetrack (spec 019, T205): `attendance_slots`
    / `accommodation` / `overnight_approved` are additive, optional fields.
    This admin patch is the ONLY write path for `overnight_approved` (Ä17)
    — every public schema (`FestivalRegistrationCreate`,
    `FestivalAttendancePatch`) rejects or lacks it entirely. Slot-key
    membership needs the event and is validated in the service, not here.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    group_size: int | None = Field(None, ge=1)
    # `None` entries are tombstones for removed members on a FESTIVAL
    # registration (T109's append-only rule, reused by T205's service-level
    # handling) — indices never shift. SINGLE-event admin edits never send
    # them (that flow stays shrink-only), so the wider type is harmless there.
    group_members: list[str | None] | None = None
    # Spec 020 — organizers may correct a companion address here. This path is
    # deliberately mail-SILENT (D3): only the guest-facing create/self-edit
    # flows send companion mail.
    group_member_emails: list[EmailStr | None] | None = None
    # Festival sidetrack (spec 019, T205) — additive optional fields.
    attendance_slots: list[str] | None = None
    tent_count: int | None = Field(None, ge=0, le=20)
    camper_count: int | None = Field(None, ge=0, le=20)
    overnight_approved: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        return stripped

    @field_validator("phone", "notes")
    @classmethod
    def _strip_clearable(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.strip()

    @field_validator("group_members")
    @classmethod
    def _strip_members(cls, v: list[str | None] | None) -> list[str | None] | None:
        if v is None:
            return v
        cleaned: list[str | None] = []
        for entry in v:
            if entry is None:
                cleaned.append(None)
                continue
            stripped = entry.strip()
            if not stripped:
                raise ValueError("group_members entries must be non-empty")
            if len(stripped) > 200:
                raise ValueError("group_members entries must be at most 200 characters")
            cleaned.append(stripped)
        return cleaned

    @field_validator("attendance_slots")
    @classmethod
    def _clean_slots(cls, v: list[str] | None) -> list[str] | None:
        """Shape-only validation: non-empty strings, dedupe preserving order.

        Slot-key membership against `event.festival_slots` is a service-
        level concern (needs the event) — see `admin_update_registration`.
        """
        if v is None:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("attendance_slots entries must be non-empty")
            if stripped not in seen:
                seen.add(stripped)
                cleaned.append(stripped)
        if not cleaned:
            raise ValueError("attendance_slots must not be empty")
        return cleaned


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
    # Names of all group members (for passenger list). On festival paths a `None`
    # entry is a tombstone for a removed member — indices never shift, since QR
    # `person_index` depends on them (spec 019 §Registration index stability).
    group_members: list[str | None] | None = None
    # Spec 020: optional per-companion address, index-aligned with
    # `group_members` (index i = address of group_members[i], person_index
    # i+1). `None` = no address; that companion's QR still goes to the contact.
    # Not in the `email-index` GSI, so it never affects the duplicate check.
    group_member_emails: list[EmailStr | None] | None = None
    status: RegistrationStatus = RegistrationStatus.REGISTERED
    waitlist_position: int | None = None
    registration_token: str  # For cancellation/confirmation links
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    responded_at: datetime | None = None  # When they responded YES/NO
    page_viewed_at: datetime | None = None  # When they last opened the manage page
    last_reminder_sent_at: datetime | None = None  # Dedup: skip if already reminded today
    promoted_from_waitlist: bool = False
    promoted: bool = False  # Admin flag: guaranteed lottery placement
    ttl: int | None = None  # DynamoDB TTL timestamp
    # Festival sidetrack (spec 019) — additive optional fields
    invite_id: UUID | None = None
    invite_label: str | None = None
    tier: str | None = None  # Denormalized invite tier, for boards/CSV
    attendance_slots: list[str] | None = None  # Keys of the chosen FestivalSlots
    # Overnight is a REQUEST, not an entitlement (Ä17). Captured as two
    # independent unit counts (Ä21) — a group may bring tents AND campers.
    # `None` = none of that kind; the scarce resource is Stellplätze, so these
    # count vehicles/tents, not people. Legacy rows (pre-Ä21) are mapped from
    # the old single `accommodation`/`accommodation_count` on read.
    tent_count: int | None = None
    camper_count: int | None = None
    # Ä17: set ONLY by admins (RegistrationAdminPatch / the T208 toggle), never
    # via any public endpoint; a single flag confirms the whole overnight wish
    # (tents + campers together); drives the „angefragt"/„zugesagt" display.
    overnight_approved: bool = False

    @model_validator(mode="after")
    def _align_member_emails(self) -> "Registration":
        """Keep the two companion arrays index-aligned (spec 020).

        Last line of defence: every write path already aligns, but this is the
        model that gets persisted, and a drift here would mail a personalised
        QR to the wrong person. Pads a short list; raises on anything worse.
        """
        object.__setattr__(
            self,
            "group_member_emails",
            _align_member_emails(
                self.group_member_emails, self.group_members, collapse_empty=True,
            ),
        )
        return self

    @property
    def has_overnight(self) -> bool:
        """True when the group requested any overnight (tent or camper)."""
        return bool(self.tent_count or self.camper_count)

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
                "responded_at": datetime.now(UTC),
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
    group_members: list[str | None] | None = None
    # Spec 020 — index-aligned with `group_members`; lets the manage page show
    # per-companion "Code geschickt" vs "leite ihren QR weiter".
    group_member_emails: list[str | None] | None = None
    registered_at: datetime
    responded_at: datetime | None
    promoted: bool = False
    # Festival sidetrack (spec 019) — additive optional fields
    attendance_slots: list[str] | None = None
    tent_count: int | None = None
    camper_count: int | None = None
    phone: str | None = None
    overnight_approved: bool = False
    invite_label: str | None = None
    tier: str | None = None
