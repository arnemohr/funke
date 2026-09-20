"""Admin event photo API endpoints (spec 024 — Eventfotos).

The organiser side of one event's photo collection: configuration (contact,
copy, retention, the open switch, the automatic close), the printed link and
the token behind it, the grid with its presigned view URLs, starring, notes,
the pixelate handshake, the download manifest and deletion.

Mounted under `/api/admin/events`, so every route carries the event in its path
and every handler resolves it through `event_service.get_event(org_id, …)`
first. That single lookup *is* the authorisation story: `get_event` reads
`pk=ORG#{org_id}`, so another organisation's event ID never resolves and its
collection can be neither read nor written. The photo routes then key on
`EVENT#{event_id}`, which makes a `photo_id` borrowed from another event a 404
rather than a 403 nobody would have had to remember to write.

This is the **reading** direction of a feature whose public direction only
writes (spec 024 §Die Einbahnstraße). Every presigned GET in this module is
admin-only by construction — there is no route outside it that mints one — and
that is the property the whole feature rests on. A new endpoint here is
harmless; a new endpoint in `api/public/event_photos.py` is not.

Like spec 023, the Lambda never carries an image byte: the browser uploads to
S3 against presigned POSTs and reports back, and even „Unkenntlich machen"
happens on a canvas in the organiser's browser (see the service module).
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...models import (
    Event,
    EventPhoto,
    EventPhotoConfig,
    EventPhotoConfigUpdate,
    EventPhotoState,
    EventPhotoUpload,
)
from ...models.event_photos import NOTE_MAX_LENGTH
from ...services.auth import CurrentUser, RequireAdmin, RequireViewer
from ...services.config import get_settings
from ...services.event_photo_service import (
    MANIFEST_TTL_SECONDS,
    MAX_PHOTOS,
    MAX_UPLOAD_BATCH,
    MAX_UPLOAD_BYTES_FULL,
    MAX_UPLOAD_BYTES_THUMB,
    URL_TTL_SECONDS,
    collection_expires_at,
    effective_retention_days,
    get_event_photo_service,
    plausible_capture_time,
    public_upload_url,
)
from ...services.event_service import get_event_service
from ...services.logging import get_logger, log_admin_action

logger = get_logger(__name__)

router = APIRouter()

# How long one DELETE pass may spend before it answers `completed: false` and
# asks to be called again. Well inside the HTTP API's 29 s integration cap and
# the Lambda's own 30 s, so a collection with two thousand rows comes back with
# a partial result instead of being killed — the same budget spec 022's
# anonymise endpoint and spec 023's page delete give themselves.
_DELETE_TIME_BUDGET = timedelta(seconds=20)

# Page size of the admin grid. The whole collection is capped at MAX_PHOTOS and
# read in one Query anyway (spec 024 §Datenmodell), so paging here is purely
# about how many presigned GETs one response has to mint and how many <img>
# elements the phone in the organiser's hand has to hold — not about the read.
_DEFAULT_PAGE_LIMIT = 120
_MAX_PAGE_LIMIT = 500

# One bulk delete may name this many photos. Same order of magnitude as a page
# of the grid plus a generous „select all" on a filtered view; a request beyond
# it would not fit the time budget anyway.
_MAX_BULK_DELETE = 500

# Transliteration for the manifest's filename. Content-Disposition's plain form
# is quoted ASCII, so „Sommerfahrt Müggelsee" has to lose its umlauts here
# rather than in the browser's guess. Same table as the boarding-list PDF
# export in `admin/events.py`.
_FILENAME_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"},
)


# The service raises exact, machine-readable strings; this maps each to the
# status the admin UI branches on plus the German line it shows. The public
# router has its own, deliberately smaller, map — the mint-path errors
# (`collection_full`, `rate_limited`) cannot happen on an admin route.
_ERROR_RESPONSES: dict[str, tuple[int, str]] = {
    "page_not_found": (
        status.HTTP_404_NOT_FOUND,
        "Für dieses Event gibt es noch keine Fotosammlung.",
    ),
    "photo_not_found": (
        status.HTTP_404_NOT_FOUND,
        "Dieses Foto gibt es nicht (mehr).",
    ),
    "contact_required": (
        status.HTTP_400_BAD_REQUEST,
        "Bitte gib an, an wen sich Gäste wenden können — eine E-Mail-Adresse oder "
        "einen Telegram-Link. Ohne Kontakt darf diese Seite nicht online gehen.",
    ),
    "bucket_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Fotospeicher ist in dieser Umgebung nicht eingerichtet.",
    ),
    "objects_not_deleted": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Die Bilddateien konnten nicht gelöscht werden — bitte versuch es noch einmal.",
    ),
    "photos_unreadable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Die Fotos konnten gerade nicht geladen werden — bitte lade die Seite neu.",
    ),
    # „Unreadable" is deliberately not „not found": `get_config` raises on a
    # failed read instead of answering None, so a throttled table cannot turn
    # into „für dieses Event gibt es noch keine Fotosammlung" — which would
    # invite an organiser to create a second collection over a live one and
    # mint a token that devalues every printed slip.
    "config_unreadable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Die Fotosammlung konnte gerade nicht gelesen werden — bitte lade die Seite neu.",
    ),
    "upload_too_recent": (
        status.HTTP_409_CONFLICT,
        "Dieses Foto ist gerade erst hochgeladen worden. Der Upload-Link des Gasts ist noch "
        "ein paar Minuten gültig und würde die Bearbeitung wieder überschreiben — bitte "
        "in einer Viertelstunde nochmal.",
    ),
}


def _map_error(error: str) -> HTTPException:
    """Turn a service error string into its HTTP status and German detail."""
    status_code, detail = _ERROR_RESPONSES.get(error, (status.HTTP_400_BAD_REQUEST, error))
    return HTTPException(status_code=status_code, detail=detail)


def _get_org_id(user: CurrentUser) -> UUID:
    """Extract organization ID from user token."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization ID not found in token",
        )
    return UUID(user.org_id)


async def _get_event_or_404(org_id: UUID, event_id: UUID) -> Event:
    """Fetch the event within the caller's organisation, or 404.

    This is the only authorisation this router needs beyond the role guard:
    `get_event` reads `pk=ORG#{org_id}`, so another organisation's event ID
    never resolves and its collection can be neither read nor written.
    """
    event = await get_event_service().get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event nicht gefunden",
        )
    return event


# --- Request/response payloads ---


class EventPhotoLimits(BaseModel):
    """The caps the admin page has to state and the upload page has to obey.

    Sent along rather than hard-coded in the frontend so a change to the
    service's constants moves the copy („max. 30 Fotos pro Stapel") with it,
    instead of leaving a page that promises something the backend refuses.
    """

    max_photos: int
    max_files_per_batch: int
    max_bytes_full: int
    max_bytes_thumb: int
    # Lifetime of the grid's view URLs; the page reloads them shortly before it
    # runs out (same mechanic as the lost & found page, same reason).
    url_ttl_seconds: int
    manifest_ttl_seconds: int
    # What `retention_days: null` resolves to, so the form can name the default
    # instead of showing an empty field.
    default_retention_days: int


class EventPhotoConfigResponse(BaseModel):
    """The collection's configuration as the admin form and header need it.

    Carries the `upload_token` in the clear: it is the link the organiser
    prints, beams as a QR code and hands out, so hiding it from the very role
    that mints it would buy nothing. `public_url` is that link already
    assembled — the same string the QR code encodes, so the frontend never
    builds the URL a second time and the two cannot drift apart.
    """

    event_id: UUID
    upload_token: str
    public_url: str
    contact_name: str | None
    # Either may be null, never both — the collection always names one way to
    # reach a human, and which one is the organiser's choice.
    contact_email: str | None
    contact_telegram_url: str | None
    intro_text: str | None
    # The organiser's switch, as stored.
    upload_open: bool
    # Whether guests can actually upload *right now*: the switch AND the
    # automatic close AND the retention window. The two fields differ on
    # purpose — the form edits the switch, the header states the reality, and
    # collapsing them would hide „offen, aber `closes_at` war gestern".
    window_open: bool
    closes_at: datetime | None
    # The value in force, i.e. the per-collection override or the environment
    # default.
    retention_days: int
    # When the whole collection gets deleted, counted from the later of event
    # end and collection creation.
    expires_at: datetime
    # The reservation counter, which includes in-flight uploads — that is why
    # the public page shows it as „ca.".
    photo_count: int
    created_at: datetime
    updated_at: datetime
    limits: EventPhotoLimits

    @field_validator("closes_at")
    @classmethod
    def pin_the_timezone(cls, value: datetime | None) -> datetime | None:
        """Never hand `closes_at` out without an offset.

        It is the only timestamp in this response that came from a client:
        a `<input type="datetime-local">` posts `2026-09-05T20:00` with no
        zone, pydantic accepts it, and the service reads a naive value as UTC
        throughout (`_as_utc`). Echoing it back naive means the browser reads
        it as *local* time instead — the header states a close two hours off in
        CEST, and saving the form again shifts the stored instant by that
        offset every round trip. Stamping the zone the service already assumes
        makes the wire value unambiguous and the drift impossible.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class EventPhotoResponse(BaseModel):
    """One photo as the admin grid and lightbox show it.

    The three URLs are presigned GETs with a 15-minute lifetime; they are
    `None` when no bucket is configured (local dev) or when signing one failed
    — a single unsignable key must not take the grid down with it.
    """

    photo_id: UUID
    state: EventPhotoState
    thumb_url: str | None
    full_url: str | None
    # The same object as `full_url`, signed with `Content-Disposition:
    # attachment` instead of `inline` — the mechanism spec 024 §Adminansicht
    # names for „Herunterladen". It is a separate signature because the
    # disposition is part of what is signed, and it is worth the extra URL
    # because `attachment` is the only way a cross-origin link saves a file:
    # `<a download>` is ignored on a foreign origin, and fetching the bytes
    # into a Blob instead would make the button depend on the bucket's CORS
    # rule listing this exact frontend origin.
    download_url: str | None
    width: int | None
    height: int | None
    bytes: int | None
    uploader_name: str | None
    note: str | None
    captured_at_hint: datetime | None
    uploaded_at: datetime
    # The timestamp the grid actually sorts and groups by: the capture hint
    # where it is believable, `uploaded_at` otherwise. Computed here rather
    # than in the browser so the plausibility rule (spec 024 §Skalieren im
    # Browser) lives in exactly one place — the frontend must not reimplement
    # „not in the future, not before the event minus a day".
    taken_at: datetime
    starred: bool
    # „Auf Gesichter angesehen." Separate from `edited_at` on purpose: most
    # photos need no pixelation at all, and only this flag distinguishes
    # „geprüft, nichts zu tun" from „noch nicht angesehen".
    faces_checked: bool
    edited_at: datetime | None
    # `HMAC-SHA256(pepper, ip)`, 16 hex chars, null unless PHOTO_IP_PEPPER is
    # configured. Exposed because it exists for exactly one question an
    # organiser asks — „are these 400 photos from 30 people or from one?" — and
    # a field nobody can ever read is stored personal data with no purpose.
    uploader_ip_hash: str | None


class EventPhotoListResponse(BaseModel):
    """One page of the collection, newest-last, plus what the header needs.

    `total` counts the photos matching the filter, not the page, so the grid
    can page without a second call. `pending_count` is the collection's
    in-flight uploads: they are deliberately **not** in `photos` (unlike spec
    023's admin grid, where the organiser uploads and therefore has to see and
    retry their own failures). Here the uploader is a guest on a phone we will
    never hear from again — a PENDING row is a broken tile the organiser can do
    nothing about, and the 24-hour sweep is what cleans it up. The count is
    here so the header can say „3 Uploads laufen noch" and the number stays
    explainable next to `photo_count`.
    """

    photos: list[EventPhotoResponse]
    total: int
    offset: int
    limit: int
    pending_count: int
    url_ttl_seconds: int


class EventPhotoPatch(BaseModel):
    """Organiser edits on one photo: the star and the uploader's note.

    Both default to `None` = „leave alone", so a star toggle cannot wipe the
    note. Passing an empty string clears the note — the only thing an organiser
    realistically wants to do with somebody else's words.
    """

    model_config = ConfigDict(extra="forbid")

    starred: bool | None = None
    faces_checked: bool | None = None
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)


class EventPhotoBulkDeleteRequest(BaseModel):
    """The photos to delete in one go.

    Bulk delete is not a convenience: deleting 300 photos one tile at a time is
    not a tool, and „not a tool" is how a collection of guests' faces ends up
    still sitting there in month four.
    """

    model_config = ConfigDict(extra="forbid")

    photo_ids: list[UUID] = Field(..., min_length=1, max_length=_MAX_BULK_DELETE)


class EventPhotoBulkDeleteResponse(BaseModel):
    """Result of a bulk delete.

    `requested` vs `deleted` is not an error report: an id that was already
    gone is a success, and a second call with the same list is a no-op.
    `completed: false` means rows the pass did match are still there — S3
    refused, or the time budget ran out — and the client has to call again.
    """

    requested: int
    deleted: int
    completed: bool


class EventPhotoEditConfirm(BaseModel):
    """The pixelated version landed: its dimensions and size.

    Bounds identical to the public confirm's, and for the same reason — these
    are numbers a browser reports about a file it produced, so they get a
    sanity ceiling rather than trust. The keys are never in this payload: the
    replacement goes onto the photo's existing keys, which is the whole point
    (the bucket is unversioned, so the original stops existing).
    """

    model_config = ConfigDict(extra="forbid")

    width: int = Field(..., ge=1, le=20000)
    height: int = Field(..., ge=1, le=20000)
    bytes: int = Field(..., ge=1, le=8 * 1024 * 1024)


class EventPhotoDeleteResponse(BaseModel):
    """Result of deleting the whole collection.

    `completed: false` means the pass ran out of time or S3 refused, and it has
    to be repeated — same contract as a spec 022 anonymisation pass. A caller
    that treats it as success leaves objects orphaned under a config row that
    no longer exists, and nothing ever finds them again.
    """

    photos: int
    completed: bool


def _limits() -> EventPhotoLimits:
    """The service's caps, as the frontend needs to hear them."""
    return EventPhotoLimits(
        max_photos=MAX_PHOTOS,
        max_files_per_batch=MAX_UPLOAD_BATCH,
        max_bytes_full=MAX_UPLOAD_BYTES_FULL,
        max_bytes_thumb=MAX_UPLOAD_BYTES_THUMB,
        url_ttl_seconds=URL_TTL_SECONDS,
        manifest_ttl_seconds=MANIFEST_TTL_SECONDS,
        default_retention_days=get_settings().event_photo_retention_days,
    )


def _config_response(event: Event, config: EventPhotoConfig) -> EventPhotoConfigResponse:
    """Build the configuration response, link and window state included."""
    service = get_event_photo_service()
    return EventPhotoConfigResponse(
        event_id=event.id,
        upload_token=config.upload_token,
        public_url=public_upload_url(event.id, config.upload_token),
        contact_name=config.contact_name,
        contact_email=config.contact_email,
        contact_telegram_url=config.contact_telegram_url,
        intro_text=config.intro_text,
        upload_open=config.upload_open,
        window_open=service.upload_window_open(config, event),
        closes_at=config.closes_at,
        retention_days=effective_retention_days(config),
        expires_at=collection_expires_at(event, config),
        photo_count=config.photo_count,
        created_at=config.created_at,
        updated_at=config.updated_at,
        limits=_limits(),
    )


def _photo_to_response(
    photo: EventPhoto,
    urls: dict[str, dict[str, str | None]],
    event: Event,
) -> EventPhotoResponse:
    """Convert a photo row plus its presigned URLs to the wire shape."""
    entry = urls.get(str(photo.photo_id), {})
    return EventPhotoResponse(
        photo_id=photo.photo_id,
        state=photo.state,
        thumb_url=entry.get("thumb_url"),
        full_url=entry.get("full_url"),
        download_url=entry.get("download_url"),
        width=photo.width,
        height=photo.height,
        bytes=photo.bytes,
        uploader_name=photo.uploader_name,
        note=photo.note,
        captured_at_hint=photo.captured_at_hint,
        uploaded_at=photo.uploaded_at,
        taken_at=plausible_capture_time(photo.captured_at_hint, event) or photo.uploaded_at,
        starred=photo.starred,
        faces_checked=photo.faces_checked,
        edited_at=photo.edited_at,
        uploader_ip_hash=photo.uploader_ip_hash,
    )


async def _read_photos(event: Event) -> list[EventPhoto]:
    """All rows of the collection, PENDING included, or a 503.

    A failed read fails the request. An empty grid presented as fact is how an
    organiser concludes „die Gäste haben nichts hochgeladen" and deletes a
    collection that was full — and here the deletion is irreversible, because
    the photos exist nowhere else.
    """
    try:
        return await get_event_photo_service().list_photos(
            event.id,
            include_pending=True,
            event=event,
        )
    except ClientError as e:
        logger.error(
            "Could not read the event photos for the admin grid",
            extra={"error": str(e), "event_id": str(event.id)},
        )
        raise _map_error("photos_unreadable") from e


async def _read_config(event_id: UUID) -> EventPhotoConfig:
    """The collection's configuration, or the right kind of failure.

    Two failures that must not be collapsed: no collection yet is a 404 the
    admin page renders as an empty form, while a failed read is a 503 the page
    retries. `get_config` keeps them apart by raising rather than answering
    None (see the service), and this is where that distinction becomes a status
    code — every admin handler that needs the config row goes through here.
    """
    try:
        config = await get_event_photo_service().get_config(event_id)
    except ClientError as e:
        logger.error(
            "Could not read the event photo collection",
            extra={"error": str(e), "event_id": str(event_id)},
        )
        raise _map_error("config_unreadable") from e

    if config is None:
        raise _map_error("page_not_found")
    return config


def _apply_filter(
    photos: list[EventPhoto],
    photo_filter: Literal["all", "starred", "unchecked", "unedited"],
) -> list[EventPhoto]:
    """The grid's views.

    `unchecked` is the working list for going through a collection on faces —
    what nobody has looked at yet. `unedited` answers the narrower question
    „where was pixelation actually applied", which is what a spot check needs;
    the two are different because most photos are checked and left alone.
    """
    if photo_filter == "starred":
        return [p for p in photos if p.starred]
    if photo_filter == "unchecked":
        return [p for p in photos if not p.faces_checked]
    if photo_filter == "unedited":
        return [p for p in photos if p.edited_at is None]
    return photos


def _manifest_filename(event: Event) -> str:
    """`fotos-{event}.txt`, reduced to what a quoted ASCII header survives."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", event.name.translate(_FILENAME_UMLAUTS))
    return f"fotos-{slug.strip('-').lower() or event.id}.txt"


# --- Configuration ---
#
# ROUTE ORDER MATTERS. `/{event_id}/photos/config`, `/{event_id}/photos/bulk-delete`
# and `/{event_id}/photos/download-manifest` are declared BEFORE
# `/{event_id}/photos/{photo_id}`, because FastAPI matches in declaration order:
# with the parameterised route first, „config" would be handed to it as a
# `photo_id` and answered with a 422 that nobody could explain. Anything new
# with a literal segment under `/photos/` belongs above that line too.


@router.get(
    "/{event_id}/photos/config",
    response_model=EventPhotoConfigResponse,
    dependencies=[RequireViewer],
)
async def get_event_photo_config(event_id: UUID, user: CurrentUser) -> EventPhotoConfigResponse:
    """Read the collection's configuration, link and window state.

    404 while no collection exists — there is no token, no link and no contact
    to report yet, and „configured: false" would be a second shape of the same
    response for the client to branch on. `PUT` is what brings a collection
    into being; the empty form needs nothing from the server but
    `limits.default_retention_days`, which it learns on the first save.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    config = await _read_config(event_id)

    return _config_response(event, config)


@router.put(
    "/{event_id}/photos/config",
    response_model=EventPhotoConfigResponse,
    dependencies=[RequireAdmin],
)
async def upsert_event_photo_config(
    event_id: UUID,
    patch: EventPhotoConfigUpdate,
    user: CurrentUser,
) -> EventPhotoConfigResponse:
    """Create the collection on the first save, update it afterwards.

    Patch semantics are the model's: an omitted field stays as it is, an
    explicit `null` clears it — which is how `retention_days: null` falls back
    to the environment default and how `closes_at: null` says „nie automatisch
    zumachen". `closes_at` is only defaulted to event end + 21 days when the
    field is absent altogether, which is why the event is passed down.

    The token is minted here, once, and only ever changes through
    `rotate-token`. Since a first save without a contact is refused, a
    half-finished collection is never reachable at all.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    try:
        config = await get_event_photo_service().upsert_config(event_id, patch, event)
    except ValueError as e:
        raise _map_error(str(e)) from e
    except ClientError as e:
        # `upsert_config` reads the row before it decides between create and
        # patch. A failed read there must come back as „try again", never as a
        # 500 the organiser reads as „my contact details were rejected".
        logger.error(
            "Could not save the event photo collection",
            extra={"error": str(e), "event_id": str(event_id)},
        )
        raise _map_error("config_unreadable") from e

    log_admin_action(
        "photos.config.save",
        user.email,
        str(event_id),
        {"upload_open": config.upload_open},
    )

    return _config_response(event, config)


@router.post(
    "/{event_id}/photos/rotate-token",
    response_model=EventPhotoConfigResponse,
    dependencies=[RequireAdmin],
)
async def rotate_event_photo_token(
    event_id: UUID,
    user: CurrentUser,
) -> EventPhotoConfigResponse:
    """Mint a fresh upload token, devaluing every printed slip and QR code.

    The emergency brake of the three switches (spec 024 §Sichtbarkeit): for a
    link that ended up somewhere it should not be. The photos stay; only the
    way in changes. `upload_open: false` is the gentler option and keeps the
    printed link alive.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    try:
        config = await get_event_photo_service().rotate_token(event_id)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action("photos.token.rotate", user.email, str(event_id))

    return _config_response(event, config)


# --- Bulk operations on literal paths (must precede /{photo_id}) ---


@router.post(
    "/{event_id}/photos/bulk-delete",
    response_model=EventPhotoBulkDeleteResponse,
    dependencies=[RequireAdmin],
)
async def bulk_delete_event_photos(
    event_id: UUID,
    body: EventPhotoBulkDeleteRequest,
    user: CurrentUser,
) -> EventPhotoBulkDeleteResponse:
    """Delete the named photos and their objects, in S3 batches.

    A POST rather than a DELETE because it carries a body, and bodies on DELETE
    are the kind of thing a proxy somewhere decides to strip.

    Idempotent and never a 404: an id that is already gone, or never existed,
    simply does not appear in `deleted`. Failing the whole call over one stale
    id would mean the organiser has to reload and reselect three hundred tiles.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    wanted = set(body.photo_ids)
    photos = [p for p in await _read_photos(event) if p.photo_id in wanted]

    deleted = await get_event_photo_service().delete_photos(
        event_id,
        photos,
        deadline=datetime.now(timezone.utc) + _DELETE_TIME_BUDGET,
    )

    log_admin_action(
        "photos.bulk_delete",
        user.email,
        str(event_id),
        {"requested": len(wanted), "matched": len(photos), "deleted": deleted},
    )

    return EventPhotoBulkDeleteResponse(
        requested=len(wanted),
        deleted=deleted,
        completed=deleted == len(photos),
    )


@router.get(
    "/{event_id}/photos/download-manifest",
    response_class=PlainTextResponse,
    dependencies=[RequireAdmin],
)
async def download_event_photo_manifest(
    event_id: UUID,
    user: CurrentUser,
    photo_filter: Literal["all", "starred"] = Query("all", alias="filter"),
) -> PlainTextResponse:
    """A text file with one presigned download URL per photo.

    Deliberately not a ZIP: API Gateway caps a response at 10 MB and cuts the
    integration off after 29 s, and a collection is two orders of magnitude
    above that. The alternative would be a batch-job or Step-Functions machine
    for a button that gets pressed once per event.

    The URLs are valid for one hour and cannot be longer: a presigned URL does
    not outlive the Lambda's temporary credentials it was signed with. The list
    costs nothing to regenerate.

    Admin, not viewer: this hands out the whole collection as files, which is
    the one action on this page that takes the photos out of our reach.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    service = get_event_photo_service()
    await _read_config(event_id)

    photos = [p for p in await _read_photos(event) if p.state == EventPhotoState.READY]
    if photo_filter == "starred":
        photos = [p for p in photos if p.starred]
    # MAX_PHOTOS is the collection's own cap, so this can only bite if the cap
    # were ever raised without revisiting the response size here.
    photos = photos[:MAX_PHOTOS]

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=MANIFEST_TTL_SECONDS)
    filename = _manifest_filename(event)

    lines = [
        f"# {len(photos)} Fotos — {event.name}",
        f"# Diese Links sind gültig bis {expires_at.isoformat(timespec='seconds')}.",
        "# Danach die Liste einfach neu herunterladen.",
        # The comment lines are why the one-liner filters them: `xargs` would
        # otherwise hand „#" to curl as a URL, once per comment line, and the
        # organiser's first impression of the download would be three errors.
        f"# grep -v '^#' {filename} | xargs -n1 -P4 curl -sOJ",
    ]
    # 1-based, zero-padded: the index is what keeps the chronological order
    # visible in a directory listing after curl has saved them all.
    for index, photo in enumerate(photos, start=1):
        url = service.presign_download(event_id, photo, index)
        if url:
            lines.append(url)

    log_admin_action(
        "photos.manifest",
        user.email,
        str(event_id),
        {"filter": photo_filter, "photos": len(photos)},
    )

    return PlainTextResponse(
        content="\n".join(lines) + "\n",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- The collection ---


@router.get(
    "/{event_id}/photos",
    response_model=EventPhotoListResponse,
    dependencies=[RequireViewer],
)
async def list_event_photos(
    event_id: UUID,
    user: CurrentUser,
    photo_filter: Literal["all", "starred", "unchecked", "unedited"] = Query(
        "all", alias="filter",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
) -> EventPhotoListResponse:
    """One page of the collection, chronologically ascending, with view URLs.

    Offset paging over the in-memory sorted list rather than a DynamoDB cursor,
    which spec 024 §Datenmodell settles: the collection is capped at
    MAX_PHOTOS, that is one Query page either way, and sorting has to happen in
    memory anyway because the order depends on `captured_at_hint`. A cursor
    would be an index and a second code path for no saved read.

    Paging is therefore about the *response*: 500 photos would be 1000
    presigned GETs to mint and 1000 URLs to ship.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    service = get_event_photo_service()
    await _read_config(event_id)

    all_rows = await _read_photos(event)
    pending = [p for p in all_rows if p.state == EventPhotoState.PENDING]
    ready = _apply_filter([p for p in all_rows if p.state == EventPhotoState.READY], photo_filter)

    page = ready[offset : offset + limit]
    urls = service.presign_view_urls(event_id, page)

    return EventPhotoListResponse(
        photos=[_photo_to_response(photo, urls, event) for photo in page],
        total=len(ready),
        offset=offset,
        limit=limit,
        pending_count=len(pending),
        url_ttl_seconds=URL_TTL_SECONDS,
    )


@router.delete(
    "/{event_id}/photos",
    response_model=EventPhotoDeleteResponse,
    dependencies=[RequireAdmin],
)
async def delete_event_photo_collection(
    event_id: UUID,
    user: CurrentUser,
) -> EventPhotoDeleteResponse:
    """Delete the collection: every object, every row, then the config row.

    Idempotent — deleting a collection that is already gone reports zero photos
    and `completed: true`.

    Bounded by `_DELETE_TIME_BUDGET`: two thousand rows answer `completed:
    false` when the budget runs out, and the client calls again. Without the
    budget the invocation is simply killed at the gateway's 29 s and the client
    gets a 504 instead of a resumable answer. The config row is the sweep's
    only handle on the collection, so it is never dropped while rows or objects
    may remain.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    result = await get_event_photo_service().delete_collection(
        event_id,
        deadline=datetime.now(timezone.utc) + _DELETE_TIME_BUDGET,
    )

    log_admin_action("photos.collection.delete", user.email, str(event_id), result)

    return EventPhotoDeleteResponse(**result)


# --- One photo ---


@router.patch(
    "/{event_id}/photos/{photo_id}",
    response_model=EventPhotoResponse,
    dependencies=[RequireAdmin],
)
async def update_event_photo(
    event_id: UUID,
    photo_id: UUID,
    body: EventPhotoPatch,
    user: CurrentUser,
) -> EventPhotoResponse:
    """Star a photo, or edit the note a guest left with it.

    Admin rather than viewer even for the star: `note` is a guest's words about
    other guests („das ist Katja mit dem Hund"), which is exactly the personal
    data an anonymised event is recorded as no longer holding.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    service = get_event_photo_service()
    try:
        photo = await service.update_photo(
            event_id,
            photo_id,
            starred=body.starred,
            faces_checked=body.faces_checked,
            note=body.note,
        )
    except ValueError as e:
        raise _map_error(str(e)) from e

    urls = service.presign_view_urls(event_id, [photo])
    return _photo_to_response(photo, urls, event)


@router.delete(
    "/{event_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RequireAdmin],
)
async def delete_event_photo(
    event_id: UUID,
    photo_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete one photo and its two objects.

    Nothing is burnt and nothing is left behind: there are no numbers here (see
    the model), so a deleted photo leaves no trace anyone could quote back. A
    refused S3 delete keeps the row — it is what makes the objects findable at
    all — and answers 503 so the organiser tries again instead of believing a
    face is gone.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    service = get_event_photo_service()
    photo = await service.get_photo(event_id, photo_id)
    if photo is None:
        raise _map_error("photo_not_found")

    deleted = await service.delete_photos(event_id, [photo])
    if deleted != 1:
        raise _map_error("objects_not_deleted")

    log_admin_action(
        "photos.photo.delete",
        user.email,
        str(event_id),
        {"photo_id": str(photo_id)},
    )


# --- Unkenntlich machen ---


@router.post(
    "/{event_id}/photos/{photo_id}/edit-uploads",
    response_model=EventPhotoUpload,
    dependencies=[RequireAdmin],
)
async def create_event_photo_edit_uploads(
    event_id: UUID,
    photo_id: UUID,
    user: CurrentUser,
) -> EventPhotoUpload:
    """Two presigned POSTs onto this photo's **existing** keys.

    The write half of „Unkenntlich machen": the browser pulls `full` onto a
    canvas over the presigned GET from the grid, pixelates the regions the
    organiser drew, and puts the result back over both keys. Both, because a
    thumbnail with an un-pixelated face would make the whole exercise
    pointless.

    Same keys and an unversioned bucket, so this is final — and the button in
    the UI says so. A kept original is precisely the image that is supposed to
    stop existing; anything else would be theatre.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        upload = await get_event_photo_service().create_edit_uploads(event_id, photo_id)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action(
        "photos.edit.mint",
        user.email,
        str(event_id),
        {"photo_id": str(photo_id)},
    )

    return upload


@router.post(
    "/{event_id}/photos/{photo_id}/edit-confirm",
    response_model=EventPhotoResponse,
    dependencies=[RequireAdmin],
)
async def confirm_event_photo_edit(
    event_id: UUID,
    photo_id: UUID,
    body: EventPhotoEditConfirm,
    user: CurrentUser,
) -> EventPhotoResponse:
    """Record that the pixelated version replaced the original.

    Sets `edited_at` and the new dimensions. `edited_at` is what marks the tile
    in the grid, drives the `unedited` filter, and — not incidentally — is what
    stops a replayed public `confirm` from writing the pre-edit dimensions back
    over a photo that has since been pixelated.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    service = get_event_photo_service()
    try:
        photo = await service.mark_edited(
            event_id,
            photo_id,
            width=body.width,
            height=body.height,
            bytes_=body.bytes,
        )
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action(
        "photos.edit.confirm",
        user.email,
        str(event_id),
        {"photo_id": str(photo_id)},
    )

    urls = service.presign_view_urls(event_id, [photo])
    return _photo_to_response(photo, urls, event)
