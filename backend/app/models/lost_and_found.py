"""Lost & found page domain models (spec 023 — Fundsachen).

One page per event, living as co-located rows under the event's partition
(``LNF#CONFIG`` plus one ``LNF#PHOTO#{photo_id}`` per photo). The page is
reachable only through ``page_token``; the photos themselves never touch the
API Lambda — the browser uploads them straight to a private bucket with a
presigned POST and reads them back through short-lived presigned GETs.

Immutable updates via ``model_copy(update={...})`` only.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# The Telegram normaliser lives in `contact.py` because spec 024 renders the
# same value as an href onto a public page too — one validator, two features.
# Re-exported from here for existing importers (tests and callers reach for it
# in this module).
from .contact import (  # noqa: F401
    TELEGRAM_HANDLE_PATTERN,
    TELEGRAM_URL_PATTERN,
    normalize_telegram_url,
)

# The caption is what a guest quotes back in a mail next to the number, so it
# is a label, not a description — 200 characters is generous for that.
CAPTION_MAX_LENGTH = 200
INTRO_TEXT_MAX_LENGTH = 2000

# Per-page override bounds. A box of jackets is kept for weeks, a box of car
# keys for months; below a week the page would expire before the guests read
# their mail, above a year it stops being a lost & found box.
RETENTION_DAYS_MIN = 7
RETENTION_DAYS_MAX = 365


class LostAndFoundPhotoState(str, Enum):
    """Lifecycle of one photo row.

    ``PENDING`` exists between minting the upload permission and the browser
    confirming the upload; only ``READY`` rows are ever public. A PENDING row
    older than 24 h is an aborted upload and gets swept away.
    """

    PENDING = "PENDING"
    READY = "READY"


class LostAndFoundConfig(BaseModel):
    """The ``LNF#CONFIG`` row — everything about the page except its photos."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    page_token: str
    # At least one of the two is always set — see `LostAndFoundService.
    # upsert_config`, which is where that invariant is enforced (a model-level
    # rule would reject the partial rows the patch path legitimately builds).
    coordinator_email: EmailStr | None = None
    coordinator_telegram_url: str | None = Field(None, max_length=200)
    coordinator_name: str | None = Field(None, max_length=200)
    # Overrides only the second paragraph of the standard copy; the „what to
    # do now" instructions below it are never overridable, so no page can end
    # up without them.
    intro_text: str | None = Field(None, max_length=INTRO_TEXT_MAX_LENGTH)
    published: bool = False
    # None = follow the `lost_and_found_retention_days` setting.
    retention_days: int | None = Field(None, ge=RETENTION_DAYS_MIN, le=RETENTION_DAYS_MAX)
    # High-water mark of handed-out numbers. Only ever grows — see
    # `LostAndFoundService.create_upload_batch`.
    next_number: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LostAndFoundConfigUpdate(BaseModel):
    """Partial-update payload for the page configuration.

    Every field is optional so the same model serves the first save and later
    edits; an unset field is left alone, an explicit ``None`` clears the
    attribute. The contact is the exception — a page nobody can be reached
    through is worthless — but it takes either form: a mail address, a Telegram
    link, or both. Clearing the last remaining one is refused, and a first save
    with neither fails with ``contact_required``.
    """

    model_config = ConfigDict(extra="forbid")

    coordinator_email: EmailStr | None = None
    coordinator_telegram_url: str | None = Field(None, max_length=200)
    coordinator_name: str | None = Field(None, max_length=200)
    intro_text: str | None = Field(None, max_length=INTRO_TEXT_MAX_LENGTH)
    published: bool | None = None
    retention_days: int | None = Field(None, ge=RETENTION_DAYS_MIN, le=RETENTION_DAYS_MAX)

    @field_validator("coordinator_telegram_url")
    @classmethod
    def validate_telegram_url(cls, value: str | None) -> str | None:
        """Normalise here so the stored value is always a safe `https://t.me/…`
        and the 422 lands on the field the organiser typed in."""
        return normalize_telegram_url(value)


class LostAndFoundPhoto(BaseModel):
    """One ``LNF#PHOTO#{photo_id}`` row.

    ``number`` is the identifier a guest writes into a mail („Nummer 14"), so
    it is assigned once and never reassigned — deleting a photo leaves a gap.
    """

    model_config = ConfigDict(from_attributes=True)

    photo_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    number: int = Field(..., ge=1)
    caption: str | None = Field(None, max_length=CAPTION_MAX_LENGTH)
    state: LostAndFoundPhotoState = LostAndFoundPhotoState.PENDING
    s3_key_display: str
    s3_key_thumb: str
    # Pixel dimensions of the display variant, reported by the browser after
    # it downscaled the file — unknown while the row is PENDING.
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)
    # Stamped when the row is created (i.e. when the upload permission is
    # minted), which is what the PENDING sweep measures its 24 h against.
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LostAndFoundPhotoConfirm(BaseModel):
    """One entry of the confirm call: this upload made it through."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    width: int = Field(..., ge=1, le=20000)
    height: int = Field(..., ge=1, le=20000)
    caption: str | None = Field(None, max_length=CAPTION_MAX_LENGTH)


class PresignedPost(BaseModel):
    """A single presigned POST: where to send the multipart body, and the
    policy fields that must precede the file part in it."""

    url: str
    fields: dict[str, str]


class LostAndFoundUpload(BaseModel):
    """Upload permission for one photo — two variants, one row, one number."""

    photo_id: UUID
    number: int = Field(..., ge=1)
    display: PresignedPost
    thumb: PresignedPost
