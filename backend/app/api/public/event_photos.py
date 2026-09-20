"""Public event photo upload endpoints (spec 024 — Eventfotos).

Three routes, no authentication: the `upload_token` in the URL *is* the
permission, like the gate's `gate_token`, a companion's personal ticket and the
lost & found page. The `event_id` alongside it is deliberately not a secret — it
lets the config row be fetched with a plain `GetItem` instead of paying for
another GSI, and it opens nothing on its own.

**This module is the one-way street** (spec 024 §Die Einbahnstraße). It is the
mirror image of `public/lost_and_found.py`: there the public direction reads,
here it writes, and guests must never be able to read. No response in this file
may carry an image URL, an S3 key, or — outside the mint call, where the caller
needs the id of the row it is about to fill — a `photo_id`. The presigned POSTs
that go out are write permissions on exactly one key each; a POST grants no
`GetObject`, not even on the object it just created, and the bucket is
`BlockPublicAccess.BLOCK_ALL`. Adding a field here is how that invariant gets
lost, so `EventPhotoUploadPageResponse` says as much in its own docstring.

Every rejection that falls at or before the token comparison answers the same
bare 404 with the same sentence — wrong token, unknown event, no collection, an
event that vanished. A 403, or a second distinguishable message, would confirm
that a collection exists for this event and turn the endpoint into an oracle for
probing which events collect photos. Only *after* the token has matched are the
answers allowed to differ, because by then they reveal nothing new: 409 for a
closed window or a full collection, 429 for the hourly quota.

Unlike spec 023 this is also where the abuse surface lives, because anyone with
the link may write into our bucket. Five layers hold it (spec 024 §Missbrauch);
the two this module is responsible for are calling the window check before
minting anything, and passing the client's address down as a *hash* only.
"""

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ...models import EventPhotoConfirm, EventPhotoUpload, EventPhotoUploadRequest
from ...services.event_photo_service import (
    MAX_UPLOAD_BATCH,
    MAX_UPLOAD_BYTES_FULL,
    URL_TTL_SECONDS,
    effective_retention_days,
    get_event_photo_service,
    hash_uploader_ip,
)
from ...services.logging import get_logger, token_hint

logger = get_logger(__name__)

router = APIRouter()

# The single answer to every rejection at or before the token comparison. Kept
# as one constant so no future branch can accidentally grow its own, more
# informative, wording.
_NOT_FOUND_DETAIL = "Diese Seite gibt es nicht (mehr)."

# „Could not be read" is not a rejection: it is only reachable once the token
# has already matched, so it confirms nothing to a prober — and a guest with
# thirty photos on a festival connection needs to know the difference between
# „gib auf" and „nochmal probieren".
_UNAVAILABLE_DETAIL = "Das klappt gerade nicht — bitte versuch es in ein paar Minuten nochmal."

# Distinguishable answers, all of them after the token matched.
_CLOSED_DETAIL = "Der Upload für dieses Event ist geschlossen."
_FULL_DETAIL = "Diese Sammlung ist voll — bitte melde dich bei der Orga."
_RATE_LIMITED_DETAIL = (
    "Gerade laden zu viele Leute hoch — bitte versuch es in ein paar Minuten nochmal."
)
_BATCH_DETAIL = f"Bitte lade höchstens {MAX_UPLOAD_BATCH} Fotos auf einmal hoch."
_CONFIRM_LOST_DETAIL = "Diese Fotos sind nicht angekommen — bitte lade sie noch einmal hoch."
_STORAGE_DETAIL = "Der Fotospeicher ist gerade nicht erreichbar — bitte später nochmal."


# Service error string -> (status, German detail). Deliberately its own map,
# not the admin router's: `page_not_found` has to come out as the shared 404
# sentence here (it means „the collection went away between the token check and
# the write" — a race, and a guest has no use for the distinction), while the
# admin router says „für dieses Event gibt es noch keine Fotosammlung".
_ERROR_RESPONSES: dict[str, tuple[int, str]] = {
    "count_out_of_range": (status.HTTP_400_BAD_REQUEST, _BATCH_DETAIL),
    "page_not_found": (status.HTTP_404_NOT_FOUND, _NOT_FOUND_DETAIL),
    "photo_not_found": (status.HTTP_404_NOT_FOUND, _CONFIRM_LOST_DETAIL),
    "collection_full": (status.HTTP_409_CONFLICT, _FULL_DETAIL),
    "rate_limited": (status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED_DETAIL),
    "bucket_not_configured": (status.HTTP_503_SERVICE_UNAVAILABLE, _STORAGE_DETAIL),
}


def _map_error(error: str) -> HTTPException:
    """Turn a service error string into its HTTP status and German detail.

    An unmapped string becomes the flat 404 rather than being echoed: on a
    public endpoint an unexpected error string is exactly the kind of thing
    that should not travel outwards.
    """
    status_code, detail = _ERROR_RESPONSES.get(
        error,
        (status.HTTP_404_NOT_FOUND, _NOT_FOUND_DETAIL),
    )
    return HTTPException(status_code=status_code, detail=detail)


def _not_found(event_id: UUID, upload_token: str) -> HTTPException:
    """The one rejection every gate failure gets."""
    logger.info(
        "Event photo upload page access denied",
        extra={"event_id": str(event_id), "token_hint": token_hint(upload_token)},
    )
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)


def _client_ip(request: Request) -> str | None:
    """The uploader's address, taken from the one source a guest cannot write.

    Under Mangum `request.client.host` is **not** the socket peer: the adapter
    fills the ASGI scope's `client` from the event's
    `requestContext.http.sourceIp` (v2) resp. `identity.sourceIp` (v1), i.e.
    the address the gateway itself observed. That value is produced by AWS
    infrastructure and is not reachable from a request header.

    `X-Forwarded-For` is deliberately **not** consulted. Every hop in front of
    us — CloudFront, then API Gateway — *appends* to that header, so a client
    that sends `X-Forwarded-For: 203.0.113.7` gets its forgery placed at the
    front of the list and the real address behind it. Reading the first entry
    would therefore hash whatever the caller typed, and `uploader_ip_hash` is
    the only abuse-detection signal this feature has: „are these 400 photos
    from 30 people or from one?" answers itself the wrong way as soon as one
    header per request can change the answer. Counting from the right-hand end
    instead would mean hard-coding how many hops sit in front of the Lambda —
    a number that changes the day a WAF or a second distribution is added, and
    changes silently. The gateway's own view needs no such count.

    Returns None when the scope carries no client at all (a bare ASGI test
    harness), which `hash_uploader_ip` reads as „store nothing".
    """
    return request.client.host if request.client else None


class EventPhotoUploadPageResponse(BaseModel):
    """Everything the upload page needs to render — and nothing more.

    **Rule for every future editor of this model:** it must never gain a field
    that can carry a `photo_id`, an S3 key, an image URL, a filename, an
    uploader name, or a timestamp belonging to an individual photo. That is not
    a preference, it is the invariant the feature is built on (spec 024 §Die
    Einbahnstraße): guests upload and see nothing, not even their own uploads.
    A test asserts against this *schema* rather than a sample response, so a
    field added here fails the build.

    `photo_count` is the single exception and an aggregate one: „bisher ca. 143
    Fotos" names no image, no person and no moment, while measurably making
    people join in. Anything finer-grained than a total would be a reading path.

    `upload_open` is the *computed* window state — the organiser's switch AND
    `closes_at` AND the retention window — not the stored flag. The page has
    one question („kann ich jetzt hochladen?") and gets one answer; a closed
    collection still renders, with the contact, so a guest holding a printed
    slip is told why rather than shown a 404.
    """

    event_name: str
    event_date: date
    intro_text: str | None
    upload_open: bool
    closes_at: datetime | None
    retention_days: int
    contact_name: str | None
    # Either may be null, never both — the page always names one way to reach a
    # human. On a page where people hand in photos *of other people* this is
    # the load-bearing field: it is how a photo gets removed again.
    contact_email: str | None
    contact_telegram_url: str | None
    photo_count: int
    max_files_per_batch: int
    max_bytes: int
    url_ttl_seconds: int

    @field_validator("closes_at")
    @classmethod
    def pin_the_timezone(cls, value: datetime | None) -> datetime | None:
        """Never hand `closes_at` out without an offset.

        The organiser's form may post it naive (`<input
        type="datetime-local">`), and the service reads a naive value as UTC
        throughout. A guest's browser reading the same string would take it as
        *local* time, so „offen bis 22:00" would be off by the visitor's own
        offset — on the one line of this page that tells them how long they
        have. Same normalisation as the admin response, for the same reason.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class EventPhotoUploadMintResponse(BaseModel):
    """The minted upload permissions, one entry per photo in the batch.

    Carries `photo_id` on purpose and only here: it is the id of a row the
    caller is about to fill and must name again in `confirm`. It is a fresh
    UUID4 for an empty `PENDING` row — it identifies nothing that exists yet,
    and it grants no read.
    """

    uploads: list[EventPhotoUpload]


class EventPhotoConfirmResponse(BaseModel):
    """How many uploads were recorded, and nothing else.

    Not the rows, not the ids, not which ones failed — a shortfall is the
    client's own bookkeeping (it knows which POSTs it completed), and telling
    the page anything about photo rows is the first step towards a reading
    path. „12 Fotos angekommen. Danke!" is the entire vocabulary of this
    response.
    """

    confirmed: int


@router.get(
    "/photos/{event_id}/{upload_token}",
    response_model=EventPhotoUploadPageResponse,
)
async def get_public_event_photo_page(
    event_id: UUID,
    upload_token: str,
) -> EventPhotoUploadPageResponse:
    """Render data for the public upload page.

    The service's gate does the ASCII check, the `compare_digest` comparison
    and the event lookup, and returns `None` rather than raising — precisely so
    that this handler has exactly one failure branch and cannot grow a second
    one by accident.

    It deliberately does *not* fold the window into the gate: a closed
    collection has to render „der Upload ist zu, schreib an …" rather than a
    404 that leaves a guest with a printed slip and no explanation.
    """
    service = get_event_photo_service()
    try:
        resolved = await service.resolve_public_page_with_event(event_id, upload_token)
    except ClientError as e:
        logger.error(
            "Event photo upload page could not be read",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    if resolved is None:
        raise _not_found(event_id, upload_token)

    config, event = resolved

    return EventPhotoUploadPageResponse(
        event_name=event.name,
        event_date=event.start_at.date(),
        intro_text=config.intro_text,
        upload_open=service.upload_window_open(config, event),
        closes_at=config.closes_at,
        retention_days=effective_retention_days(config),
        contact_name=config.contact_name,
        contact_email=config.contact_email,
        contact_telegram_url=config.contact_telegram_url,
        photo_count=config.photo_count,
        max_files_per_batch=MAX_UPLOAD_BATCH,
        max_bytes=MAX_UPLOAD_BYTES_FULL,
        url_ttl_seconds=URL_TTL_SECONDS,
    )


@router.post(
    "/photos/{event_id}/{upload_token}/uploads",
    response_model=EventPhotoUploadMintResponse,
)
async def create_public_event_photo_uploads(
    event_id: UUID,
    upload_token: str,
    body: EventPhotoUploadRequest,
    request: Request,
) -> EventPhotoUploadMintResponse:
    """Mint one presigned POST pair per photo of the batch.

    Two Lambda calls per batch no matter how big it is: this one, then
    `confirm`. Everything in between goes straight from the browser to S3, four
    uploads at a time, so a stapel of forty photos over mobile data costs us
    two invocations and no image bytes.

    The window is checked *here*, not in the gate, and before anything is
    minted — a signature handed out after `closes_at` is a write permission
    that outlives the reason it existed. It is the strongest of the five abuse
    controls precisely because it is the cheapest one to enforce.
    """
    service = get_event_photo_service()
    try:
        resolved = await service.resolve_public_page_with_event(event_id, upload_token)
    except ClientError as e:
        logger.error(
            "Event photo upload could not read its collection",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    if resolved is None:
        raise _not_found(event_id, upload_token)

    config, event = resolved

    if not service.upload_window_open(config, event):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CLOSED_DETAIL)

    try:
        uploads = await service.create_upload_batch(
            event_id,
            body.count,
            uploader_name=body.uploader_name,
            note=body.note,
            ip_hash=hash_uploader_ip(_client_ip(request)),
        )
    except ValueError as e:
        raise _map_error(str(e)) from e
    except ClientError as e:
        # `create_upload_batch` re-reads the config row and writes the PENDING
        # rows, so a throttled or refused table call lands here. „Try again in
        # a moment" rather than the flat 404: the token already matched, so
        # this reveals nothing new, and a guest with thirty photos queued must
        # not be told the page is gone.
        logger.error(
            "Event photo upload permissions could not be minted",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    logger.info(
        "Event photo upload permissions minted",
        extra={"event_id": str(event_id), "count": len(uploads)},
    )

    return EventPhotoUploadMintResponse(uploads=uploads)


@router.post(
    "/photos/{event_id}/{upload_token}/confirm",
    response_model=EventPhotoConfirmResponse,
)
async def confirm_public_event_photos(
    event_id: UUID,
    upload_token: str,
    confirmations: Annotated[
        list[EventPhotoConfirm],
        # The cap belongs on the body, not in the handler: a batch is bounded
        # by what one mint call can hand out, and a 4 MB array of confirmations
        # is an unauthenticated caller making us parse for free.
        Body(max_length=MAX_UPLOAD_BATCH),
    ],
) -> EventPhotoConfirmResponse:
    """Flip the uploads that made it through from PENDING to READY.

    The only path into READY, and the only write an anonymous caller may
    perform on an existing row. `EventPhotoConfirm` forbids extra fields and
    holds only what a browser can know, so there is nothing here to escalate
    with: never `starred`, never a key, never a `state` other than READY.

    Deliberately **not** gated on the upload window. The batch was authorised
    when it was minted; a collection that closed while forty photos were in
    flight would otherwise leave every one of them a PENDING row with a real
    object behind it, swept away 24 hours later without anybody being told.

    A batch never fails as a whole (spec 024 §Skalieren im Browser): rows that
    were swept or deleted mid-upload are skipped, and only a batch in which
    *nothing* could be confirmed is a 404. Answering 404 for a partly-good
    batch would make a guest on a festival connection re-upload thirty photos
    we already have.
    """
    service = get_event_photo_service()
    try:
        resolved = await service.resolve_public_page_with_event(event_id, upload_token)
    except ClientError as e:
        logger.error(
            "Event photo confirm could not read its collection",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    if resolved is None:
        raise _not_found(event_id, upload_token)

    _config, event = resolved

    # An empty batch is a no-op, not a 404. It is what a browser sends when
    # every file in the stapel turned out to be undecodable (HEIC on Chrome) —
    # the service treats „nothing confirmed" as a foreign id, which is the right
    # answer for a list of ids and the wrong one for no list at all.
    if not confirmations:
        return EventPhotoConfirmResponse(confirmed=0)

    try:
        photos = await service.confirm_photos(event_id, confirmations, event)
    except ValueError as e:
        raise _map_error(str(e)) from e
    except ClientError as e:
        logger.error(
            "Event photo confirm failed",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    logger.info(
        "Event photos confirmed",
        extra={
            "event_id": str(event_id),
            "confirmed": len(photos),
            "requested": len(confirmations),
        },
    )

    return EventPhotoConfirmResponse(confirmed=len(photos))
