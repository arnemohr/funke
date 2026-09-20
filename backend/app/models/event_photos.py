"""Event photo collection domain models (spec 024 — Eventfotos).

One collection per event, living as co-located rows under the event's partition
(``PHOTOS#CONFIG``, one ``PHOTOS#ITEM#{photo_id}`` per photo, plus hourly
``PHOTOS#QUOTA#{YYYYMMDDHH}`` counters). The collection is reachable only
through ``upload_token``, and it is a **one-way street**: guests upload, guests
see nothing. That is the invariant the whole feature is built around — no
response model in this module or downstream of it may carry an image URL, an
S3 key or a ``photo_id`` into a public payload.

Mirror image of spec 023: there, the public direction is reading; here it is
writing. Same presigned-POST mechanics, opposite threat model — anyone holding
the link may write into our bucket, so the caps and the upload policy in the
service are the load-bearing part, not decoration.

Immutable updates via ``model_copy(update={...})`` only.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .contact import normalize_telegram_url

# Shown on the admin tile next to the thumbnail, so a first name or a nickname
# — not a field anybody should be able to write an essay into.
UPLOADER_NAME_MAX_LENGTH = 80
# The uploader's note is read in the lightbox („das ist Katja mit dem Hund"),
# a sentence or two, never a caption to be quoted back.
NOTE_MAX_LENGTH = 300
INTRO_TEXT_MAX_LENGTH = 2000

# Per-collection override bounds. Below a week the collection would close
# before the guests get around to their camera roll; above a year it stops
# being a transfer point and becomes an archive of other people's faces.
RETENTION_DAYS_MIN = 7
RETENTION_DAYS_MAX = 365


class EventPhotoState(str, Enum):
    """Lifecycle of one photo row.

    ``PENDING`` exists between minting the upload permission and the browser
    confirming the upload; ``READY`` is a photo that arrived. There is
    deliberately no third state: nothing here is ever public, so „hide" has no
    meaning — what should be gone is deleted. A PENDING row older than 24 h is
    an aborted upload and gets swept away with its objects.
    """

    PENDING = "PENDING"
    READY = "READY"


class EventPhotoConfig(BaseModel):
    """The ``PHOTOS#CONFIG`` row — everything about the collection except its
    photos."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    upload_token: str
    # At least one of the two is always set — see `EventPhotoService.
    # upsert_config`, which is where that invariant is enforced (a model-level
    # rule would reject the partial rows the patch path legitimately builds,
    # exactly as in spec 023). The obligation is stronger here than there: on a
    # page where people hand in photos *of other people*, it has to say who to
    # ask to get one removed again.
    contact_email: EmailStr | None = None
    contact_telegram_url: str | None = Field(None, max_length=200)
    contact_name: str | None = Field(None, max_length=200)
    # Overrides only the second paragraph of the standard copy; the consent /
    # retention / contact paragraph below it is never overridable, so no page
    # can end up without it.
    intro_text: str | None = Field(None, max_length=INTRO_TEXT_MAX_LENGTH)
    # The immediate switch: shuts the collection without devaluing a printed
    # link, unlike rotating the token.
    upload_open: bool = True
    # The unattended switch — default event end + 21 days. Together with
    # `upload_open` this is the strongest abuse control there is, because it
    # limits the write permission to the weeks in which it has a purpose.
    closes_at: datetime | None = None
    # None = follow the `event_photo_retention_days` setting.
    retention_days: int | None = Field(None, ge=RETENTION_DAYS_MIN, le=RETENTION_DAYS_MAX)
    # A RESERVATION counter, not a statistic: incremented when an upload
    # permission is minted (`ADD photo_count :n`) and decremented on every row
    # deletion — including the PENDING sweep of aborted uploads. That way
    # in-flight uploads count against MAX_PHOTOS and the mint path never has to
    # count rows. It also means the number can sit above the number of photos
    # that actually arrived, which is why the public page shows it as „ca.".
    photo_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventPhotoConfigUpdate(BaseModel):
    """Partial-update payload for the collection configuration.

    Every field is optional so the same model serves the first save and later
    edits; an unset field is left alone, an explicit ``None`` clears the
    attribute. The contact is the exception — but it takes either form: a mail
    address, a Telegram link, or both. Clearing the last remaining one is
    refused, and a first save with neither fails with ``contact_required``.
    """

    model_config = ConfigDict(extra="forbid")

    contact_email: EmailStr | None = None
    contact_telegram_url: str | None = Field(None, max_length=200)
    contact_name: str | None = Field(None, max_length=200)
    intro_text: str | None = Field(None, max_length=INTRO_TEXT_MAX_LENGTH)
    upload_open: bool | None = None
    closes_at: datetime | None = None
    retention_days: int | None = Field(None, ge=RETENTION_DAYS_MIN, le=RETENTION_DAYS_MAX)

    @field_validator("contact_telegram_url")
    @classmethod
    def validate_telegram_url(cls, value: str | None) -> str | None:
        """Normalise here so the stored value is always a safe `https://t.me/…`
        and the 422 lands on the field the organiser typed in."""
        return normalize_telegram_url(value)


class EventPhoto(BaseModel):
    """One ``PHOTOS#ITEM#{photo_id}`` row.

    No number: unlike a lost & found item, nobody ever quotes a photo in a
    mail, so none needs a stable public identifier. Sorting is chronological,
    by ``captured_at_hint`` where it is plausible and ``uploaded_at``
    otherwise.
    """

    model_config = ConfigDict(from_attributes=True)

    photo_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    state: EventPhotoState = EventPhotoState.PENDING
    s3_key_full: str
    s3_key_thumb: str
    # Pixel dimensions of the `full` variant, reported by the browser after it
    # downscaled the file — unknown while the row is PENDING, and rewritten
    # when a pixelated version replaces the original.
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)
    # Shadows the builtin `bytes`, and that is fine for a pydantic field name:
    # the wire format is what matters here and this is the honest name for the
    # size of the stored object. Renaming it to `size_bytes` in the model only
    # to alias it back on the way out would buy nothing.
    bytes: int | None = Field(None, ge=1)
    uploader_name: str | None = Field(None, max_length=UPLOADER_NAME_MAX_LENGTH)
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)
    # `file.lastModified` from the browser. The canvas downscale strips all
    # EXIF (GPS included — desirable), and the capture time with it, so this is
    # the replacement: on a phone it is the capture time, on a forwarded file
    # the save time. Hence a *hint* — the service only sorts by it when it is
    # plausible (not in the future, not long before the event).
    captured_at_hint: datetime | None = None
    # Stamped when the row is created (i.e. when the upload permission is
    # minted), which is what the PENDING sweep measures its 24 h against.
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Organiser-only flags. `confirm` must never be able to set any of them.
    starred: bool = False
    # „Ich habe dieses Foto auf Gesichter angesehen." Deliberately separate from
    # `edited_at`: most photos need no pixelation, and without this flag there is
    # no way to tell „looked at, nothing to do" from „not looked at yet" — which
    # is the only question that matters when working through 600 photos over
    # several sittings. Pixelating a photo implies it, so `mark_edited` sets it.
    faces_checked: bool = False
    # Set when faces were pixelated in place. Irreversible by design — the
    # bucket is unversioned so nothing keeps the un-pixelated original.
    edited_at: datetime | None = None
    # `HMAC-SHA256(PHOTO_IP_PEPPER, ip)`, truncated to 16 hex chars, and only
    # ever present when that pepper is configured. Exists for exactly one
    # question: are these 400 photos from 30 people or from one? It dies with
    # the row.
    uploader_ip_hash: str | None = Field(None, max_length=32)


class EventPhotoConfirm(BaseModel):
    """One entry of the confirm call: this upload made it through.

    This is the **only** field set an anonymous caller may write on a photo
    row. Never ``state`` to anything other than READY, never ``starred``,
    never an S3 key, never ``uploader_ip_hash`` — a confirm endpoint that any
    link holder may call is not a place for privilege escalation, and
    ``extra="forbid"`` makes an added field a 422 rather than a silent write.
    """

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    width: int = Field(..., ge=1, le=20000)
    height: int = Field(..., ge=1, le=20000)
    bytes: int = Field(..., ge=1, le=8 * 1024 * 1024)
    captured_at_hint: datetime | None = None


class EventPhotoUploadRequest(BaseModel):
    """„Give me permission for N photos" — one call per batch, not per file."""

    model_config = ConfigDict(extra="forbid")

    # The upper bound lives in the service, not here, so the refusal can be a
    # machine-readable error string („batch_too_large") the page turns into
    # German copy — a 422 from pydantic would be an opaque wall of JSON on a
    # page used by guests on a phone.
    count: int = Field(..., ge=1)
    # Both are the uploader's own words about their own batch, copied onto
    # every row of it.
    uploader_name: str | None = Field(None, max_length=UPLOADER_NAME_MAX_LENGTH)
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)


class PresignedPost(BaseModel):
    """A single presigned POST: where to send the multipart body, and the
    policy fields that must precede the file part in it.

    Deliberately a duplicate of the identically shaped model in
    `lost_and_found.py` rather than an import from it. Spec 024 §"Verhältnis zu
    Spec 023" keeps the two features apart on purpose; a cross-feature import
    for a four-line value object would be the one thread tying together the
    read path and the write path, and the first change to either would have to
    reason about both.
    """

    url: str
    fields: dict[str, str]


class EventPhotoUpload(BaseModel):
    """Upload permission for one photo — two variants, one row.

    The `full` and `thumb` policies differ in their size ceiling (6 MB vs
    400 kB); both nail down the exact key, `image/jpeg`, and 15 minutes.
    """

    photo_id: UUID
    full: PresignedPost
    thumb: PresignedPost
