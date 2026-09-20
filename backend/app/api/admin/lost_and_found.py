"""Admin lost & found API endpoints (spec 023 — Fundsachen).

Provides the whole organiser side of one event's lost & found page:
configuration (address, copy, retention, publish switch), token rotation, the
presigned-POST upload handshake, captions, and deletion.

Mounted under `/api/admin/events`, so every route carries the event in its
path and every handler resolves it through `event_service.get_event(org_id, …)`
first — an event ID from another organisation is simply not found, exactly as
in `admin/events.py`. The photo routes then key on `EVENT#{event_id}`, which
makes a photo ID borrowed from another event a 404 rather than a 403.

The Lambda never carries an image byte: `POST .../uploads` hands the browser
presigned POSTs and `.../photos/confirm` takes the metadata back. See the
service module for why.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...models import (
    Event,
    LostAndFoundConfig,
    LostAndFoundConfigUpdate,
    LostAndFoundPhoto,
    LostAndFoundPhotoConfirm,
    LostAndFoundPhotoState,
    LostAndFoundUpload,
)
from ...models.lost_and_found import CAPTION_MAX_LENGTH
from ...services.auth import CurrentUser, RequireAdmin, RequireViewer
from ...services.config import get_settings
from ...services.event_service import get_event_service
from ...services.logging import get_logger, log_admin_action
from ...services.lost_and_found_service import (
    MAX_UPLOAD_BATCH,
    effective_retention_days,
    get_lost_and_found_service,
    page_expires_at,
    public_page_url,
)

logger = get_logger(__name__)

router = APIRouter()

# How long one DELETE pass may spend before it answers `completed: false` and
# asks to be called again. Well inside the HTTP API's 29 s integration cap and
# the Lambda's own 30 s, so a page with a thousand rows comes back with a
# partial result instead of being killed — the same budget spec 022's
# anonymise endpoint gives itself.
_DELETE_TIME_BUDGET = timedelta(seconds=20)


# The service raises exact, machine-readable strings; this maps each to the
# status the admin UI branches on plus the German line it shows.
_ERROR_RESPONSES: dict[str, tuple[int, str]] = {
    "page_not_found": (
        status.HTTP_404_NOT_FOUND,
        "Für dieses Event gibt es noch keine Fundsachen-Seite.",
    ),
    "photo_not_found": (
        status.HTTP_404_NOT_FOUND,
        "Dieses Foto gibt es nicht (mehr).",
    ),
    "contact_required": (
        status.HTTP_400_BAD_REQUEST,
        "Bitte gib an, wie sich Gäste melden können — eine E-Mail-Adresse oder "
        "einen Telegram-Link.",
    ),
    "bucket_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Fundsachen-Speicher ist in dieser Umgebung nicht eingerichtet.",
    ),
    "objects_not_deleted": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Die Bilddateien konnten nicht gelöscht werden — bitte versuch es noch einmal.",
    ),
    "photos_unreadable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Die Fotos konnten gerade nicht geladen werden — bitte lade die Seite neu.",
    ),
    "count_out_of_range": (
        status.HTTP_400_BAD_REQUEST,
        f"Pro Stapel sind 1 bis {MAX_UPLOAD_BATCH} Fotos möglich.",
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
    never resolves and its page can be neither read nor written.
    """
    event = await get_event_service().get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event nicht gefunden",
        )
    return event


# --- Request/response payloads ---


class LostFoundPhotoResponse(BaseModel):
    """One photo as the admin grid shows it, PENDING rows included.

    The two URLs are presigned GETs with the same 15-minute lifetime as the
    public page's; they are `None` when no bucket is configured (local dev).
    """

    photo_id: UUID
    number: int
    caption: str | None
    state: LostAndFoundPhotoState
    thumb_url: str | None
    display_url: str | None
    width: int | None
    height: int | None
    uploaded_at: datetime


class LostFoundAdminResponse(BaseModel):
    """The page as the admin form and grid need it.

    `configured` is false before the first save — then there is no token, no
    link and no address yet, but `retention_days` already carries the
    environment default so the form can pre-fill it.
    """

    configured: bool
    page_token: str | None
    public_url: str | None
    coordinator_name: str | None
    coordinator_email: str | None
    coordinator_telegram_url: str | None
    intro_text: str | None
    published: bool
    # The value in force, i.e. the per-page override or the environment default.
    retention_days: int
    expires_at: datetime | None
    photos: list[LostFoundPhotoResponse]


class LostFoundUploadRequest(BaseModel):
    """How many upload permissions to mint."""

    count: int = Field(..., ge=1, le=MAX_UPLOAD_BATCH)


class LostFoundUploadResponse(BaseModel):
    """The minted permissions, one entry per photo, in number order."""

    uploads: list[LostAndFoundUpload]


class LostFoundConfirmRequest(BaseModel):
    """The uploads that made it through, with the pixel sizes the browser
    produced. Deliberately unbounded in length: it mirrors whatever batch the
    browser managed to upload, and confirming an empty list is a no-op."""

    photos: list[LostAndFoundPhotoConfirm]


class LostFoundConfirmResponse(BaseModel):
    """Confirmation result, including the rows as they now stand.

    `not_confirmed` names the ids that did not flip — a row deleted or pruned
    while its upload was running. The rest of the batch is live and must not be
    uploaded again, so the client marks only these as failed.
    """

    confirmed: int
    photos: list[LostFoundPhotoResponse]
    not_confirmed: list[UUID] = []


class LostFoundCaptionUpdate(BaseModel):
    """New caption for one photo; `null` or empty clears it."""

    caption: str | None = Field(None, max_length=CAPTION_MAX_LENGTH)


class LostFoundDeleteResponse(BaseModel):
    """Result of deleting the page.

    `completed: false` means the pass ran out of time and has to be repeated —
    same contract as a spec 022 anonymisation pass.
    """

    deleted_photos: int
    completed: bool


def _photo_to_response(
    photo: LostAndFoundPhoto,
    urls: dict[str, dict[str, str | None]],
) -> LostFoundPhotoResponse:
    """Convert a photo row plus its presigned URLs to the wire shape."""
    entry = urls.get(str(photo.photo_id), {})
    return LostFoundPhotoResponse(
        photo_id=photo.photo_id,
        number=photo.number,
        caption=photo.caption,
        state=photo.state,
        thumb_url=entry.get("thumb_url"),
        display_url=entry.get("display_url"),
        width=photo.width,
        height=photo.height,
        uploaded_at=photo.uploaded_at,
    )


def _unconfigured_response() -> LostFoundAdminResponse:
    """The answer for an event that has no page yet."""
    return LostFoundAdminResponse(
        configured=False,
        page_token=None,
        public_url=None,
        coordinator_name=None,
        coordinator_email=None,
        coordinator_telegram_url=None,
        intro_text=None,
        published=False,
        retention_days=get_settings().lost_and_found_retention_days,
        expires_at=None,
        photos=[],
    )


async def _page_response(event: Event, config: LostAndFoundConfig) -> LostFoundAdminResponse:
    """Build the full page response, minting view URLs for the grid.

    Includes PENDING rows: the admin grid is where an aborted upload has to be
    visible, so it can be deleted or retried instead of quietly waiting for the
    24-hour sweep.

    A failed read fails the request. An empty grid presented as fact invites the
    organiser to upload the whole box a second time, and every re-upload draws
    fresh numbers — the page then lists each item twice and the number a guest
    was already given points at one of a pair.
    """
    service = get_lost_and_found_service()
    try:
        photos = await service.list_photos(event.id, include_pending=True)
    except ClientError as e:
        logger.error(
            "Could not read the lost & found photos for the admin grid",
            extra={"error": str(e), "event_id": str(event.id)},
        )
        raise _map_error("photos_unreadable") from e
    urls = service.presign_view_urls(event.id, photos)

    return LostFoundAdminResponse(
        configured=True,
        page_token=config.page_token,
        public_url=public_page_url(event.id, config.page_token),
        coordinator_name=config.coordinator_name,
        coordinator_email=config.coordinator_email,
        coordinator_telegram_url=config.coordinator_telegram_url,
        intro_text=config.intro_text,
        published=config.published,
        retention_days=effective_retention_days(config),
        expires_at=page_expires_at(event, config),
        photos=[_photo_to_response(photo, urls) for photo in photos],
    )


# --- Page configuration ---


@router.get(
    "/{event_id}/lostfound",
    response_model=LostFoundAdminResponse,
    dependencies=[RequireViewer],
)
async def get_lost_and_found(event_id: UUID, user: CurrentUser) -> LostFoundAdminResponse:
    """Read the page configuration and all photos, PENDING included."""
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    config = await get_lost_and_found_service().get_config(event_id)
    if config is None:
        return _unconfigured_response()

    return await _page_response(event, config)


@router.put(
    "/{event_id}/lostfound",
    response_model=LostFoundAdminResponse,
    dependencies=[RequireAdmin],
)
async def upsert_lost_and_found(
    event_id: UUID,
    patch: LostAndFoundConfigUpdate,
    user: CurrentUser,
) -> LostFoundAdminResponse:
    """Create the page on the first save, update it afterwards.

    Patch semantics are the model's: an omitted field stays as it is, an
    explicit `null` clears it — which is how `retention_days: null` falls back
    to the environment default. The page token is minted once here and only
    ever changes through `rotate-token`.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    try:
        config = await get_lost_and_found_service().upsert_config(event_id, patch)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action(
        "lostfound.config.save",
        user.email,
        str(event_id),
        {"published": config.published},
    )

    return await _page_response(event, config)


@router.delete(
    "/{event_id}/lostfound",
    response_model=LostFoundDeleteResponse,
    dependencies=[RequireAdmin],
)
async def delete_lost_and_found(event_id: UUID, user: CurrentUser) -> LostFoundDeleteResponse:
    """Delete the page: every S3 object, every photo row, then the config row.

    Idempotent — deleting a page that is already gone reports zero photos and
    `completed: true`.

    Bounded by `_DELETE_TIME_BUDGET`: a page with hundreds of rows answers
    `completed: false` when the budget runs out, and the client calls again.
    Without the budget the invocation is simply killed at the gateway's 29 s and
    the client gets a 504 instead of a resumable answer.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    result = await get_lost_and_found_service().delete_page(
        event_id,
        deadline=datetime.now(timezone.utc) + _DELETE_TIME_BUDGET,
    )

    log_admin_action("lostfound.page.delete", user.email, str(event_id), result)

    return LostFoundDeleteResponse(**result)


@router.post(
    "/{event_id}/lostfound/rotate-token",
    response_model=LostFoundAdminResponse,
    dependencies=[RequireAdmin],
)
async def rotate_lost_and_found_token(
    event_id: UUID,
    user: CurrentUser,
) -> LostFoundAdminResponse:
    """Mint a fresh page token, invalidating every link already handed out.

    The emergency brake for a link that ended up somewhere public. The photos
    stay; only the way in changes.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    try:
        config = await get_lost_and_found_service().rotate_token(event_id)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action("lostfound.token.rotate", user.email, str(event_id))

    return await _page_response(event, config)


# --- Photos ---


@router.post(
    "/{event_id}/lostfound/uploads",
    response_model=LostFoundUploadResponse,
    dependencies=[RequireAdmin],
)
async def create_lost_and_found_uploads(
    event_id: UUID,
    body: LostFoundUploadRequest,
    user: CurrentUser,
) -> LostFoundUploadResponse:
    """Reserve `count` numbers and mint a presigned POST per photo variant.

    The browser uploads straight to S3 against these and reports back through
    `.../photos/confirm`; a whole box of photos therefore costs two calls.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        uploads = await get_lost_and_found_service().create_upload_batch(event_id, body.count)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action(
        "lostfound.uploads.mint",
        user.email,
        str(event_id),
        {"count": len(uploads)},
    )

    return LostFoundUploadResponse(uploads=uploads)


@router.post(
    "/{event_id}/lostfound/photos/confirm",
    response_model=LostFoundConfirmResponse,
    dependencies=[RequireAdmin],
)
async def confirm_lost_and_found_photos(
    event_id: UUID,
    body: LostFoundConfirmRequest,
    user: CurrentUser,
) -> LostFoundConfirmResponse:
    """Flip the uploads that made it through to READY.

    A photo ID that does not belong to this event's page is a 404 — the row is
    keyed by event, so there is nothing to distinguish „not yours" from
    „does not exist" and nothing gained by trying.

    But only when *nothing* was confirmed. A batch is dozens of rows and each
    one is its own write: if row 30 has meanwhile been deleted or pruned, rows
    1..29 are already READY and public under numbers a guest may have been
    given. Answering 404 for the whole call would make the client re-upload
    them, so a partial batch is a 200 that names the shortfall.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    service = get_lost_and_found_service()
    try:
        photos, not_confirmed = await service.confirm_photos(event_id, body.photos)
    except ValueError as e:
        raise _map_error(str(e)) from e

    if not photos and not_confirmed:
        raise _map_error("photo_not_found")

    urls = service.presign_view_urls(event_id, photos)

    log_admin_action(
        "lostfound.photos.confirm",
        user.email,
        str(event_id),
        {"count": len(photos), "not_confirmed": len(not_confirmed)},
    )

    return LostFoundConfirmResponse(
        confirmed=len(photos),
        photos=[_photo_to_response(photo, urls) for photo in photos],
        not_confirmed=not_confirmed,
    )


@router.patch(
    "/{event_id}/lostfound/photos/{photo_id}",
    response_model=LostFoundPhotoResponse,
    dependencies=[RequireAdmin],
)
async def update_lost_and_found_caption(
    event_id: UUID,
    photo_id: UUID,
    body: LostFoundCaptionUpdate,
    user: CurrentUser,
) -> LostFoundPhotoResponse:
    """Set or clear one photo's caption.

    A write path like the others: „Handy von Lena, am Bühnenrand" is exactly the
    personal data an anonymised event is recorded as no longer holding, and
    anonymisation is allowed to leave a page standing when its deletion failed.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    service = get_lost_and_found_service()
    try:
        photo = await service.update_caption(event_id, photo_id, body.caption)
    except ValueError as e:
        raise _map_error(str(e)) from e

    urls = service.presign_view_urls(event_id, [photo])
    return _photo_to_response(photo, urls)


@router.delete(
    "/{event_id}/lostfound/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RequireAdmin],
)
async def delete_lost_and_found_photo(
    event_id: UUID,
    photo_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete one photo and its two objects.

    Its number stays burnt: a guest answering a three-day-old mail still means
    the old „Nummer 14", so nothing new ever inherits it.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        await get_lost_and_found_service().delete_photo(event_id, photo_id)
    except ValueError as e:
        raise _map_error(str(e)) from e

    log_admin_action(
        "lostfound.photo.delete",
        user.email,
        str(event_id),
        {"photo_id": str(photo_id)},
    )
