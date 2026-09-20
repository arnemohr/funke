"""Public lost & found page endpoint (spec 023 — Fundsachen).

One route, no authentication: the `page_token` in the URL *is* the permission,
like the gate's `gate_token` and a companion's personal ticket. The `event_id`
alongside it is deliberately not a secret — it lets the config row be fetched
with a plain `GetItem` instead of paying for a fifth GSI, and it opens nothing
on its own.

Every rejection — wrong token, unknown event, not published yet, expired,
anonymised — answers with the same bare 404 and the same sentence. A 403, or a
second distinguishable message, would confirm that the page exists and turn the
endpoint into an oracle for probing events.
"""

from datetime import date
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...services.logging import get_logger, token_hint
from ...services.lost_and_found_service import (
    URL_TTL_SECONDS,
    effective_retention_days,
    get_lost_and_found_service,
)

logger = get_logger(__name__)

router = APIRouter()

# The single answer to every rejection. Kept as one constant so no future
# branch can accidentally grow its own, more informative, wording.
_NOT_FOUND_DETAIL = "Diese Seite gibt es nicht (mehr)."

# „The page is empty" and „the photos could not be read" must not look the same
# to a guest who was told to look up number 14: one means give up, the other
# means try again. The 404-for-everything rule covers *rejections* — this is a
# read failure, and it is only reachable once the token has already matched, so
# it confirms nothing to a prober.
_UNAVAILABLE_DETAIL = "Die Fundsachen können gerade nicht geladen werden — bitte später nochmal."


class LostFoundPublicPhoto(BaseModel):
    """One photo on the public page.

    Carries the `number` a guest quotes in a mail, but never the `photo_id`,
    the S3 keys or the upload time — none of which a guest has any use for.
    The dimensions are here so the grid can reserve the right aspect ratio
    before the image arrives.
    """

    number: int
    caption: str | None
    thumb_url: str | None
    display_url: str | None
    width: int | None
    height: int | None


class LostFoundPublicResponse(BaseModel):
    """The public page, everything it needs to render in one response.

    `url_ttl_seconds` is how long the two URLs per photo stay valid; the page
    refreshes them shortly before that runs out, so a tab left open overnight
    does not end up as a grid of broken images.
    """

    event_name: str
    event_date: date
    coordinator_name: str | None
    # Either may be null, never both — the page always has one way to reach a
    # human, and which one is the organiser's choice.
    coordinator_email: str | None
    coordinator_telegram_url: str | None
    intro_text: str | None
    retention_days: int
    url_ttl_seconds: int
    photos: list[LostFoundPublicPhoto]


@router.get(
    "/lostfound/{event_id}/{page_token}",
    response_model=LostFoundPublicResponse,
)
async def get_public_lost_and_found(
    event_id: UUID,
    page_token: str,
) -> LostFoundPublicResponse:
    """Render data for the public lost & found page.

    The service's gate does the token comparison (`compare_digest`) and every
    other check, and returns `None` rather than raising, precisely so that this
    handler has exactly one failure branch.
    """
    service = get_lost_and_found_service()
    try:
        resolved = await service.resolve_public_page_with_event(event_id, page_token)
    except ClientError as e:
        logger.error(
            "Lost & found page could not be read",
            extra={"event_id": str(event_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        ) from e

    if resolved is None:
        logger.info(
            "Lost & found page access denied",
            extra={"event_id": str(event_id), "token_hint": token_hint(page_token)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )

    config, photos, event = resolved

    # READY rows only — the gate list excludes PENDING, so an aborted upload
    # never becomes a public tile with an unreadable image behind it.
    urls = service.presign_view_urls(event_id, photos)

    return LostFoundPublicResponse(
        event_name=event.name,
        event_date=event.start_at.date(),
        coordinator_name=config.coordinator_name,
        coordinator_email=config.coordinator_email,
        coordinator_telegram_url=config.coordinator_telegram_url,
        intro_text=config.intro_text,
        retention_days=effective_retention_days(config),
        url_ttl_seconds=URL_TTL_SECONDS,
        photos=[
            LostFoundPublicPhoto(
                number=photo.number,
                caption=photo.caption,
                thumb_url=urls[str(photo.photo_id)]["thumb_url"],
                display_url=urls[str(photo.photo_id)]["display_url"],
                width=photo.width,
                height=photo.height,
            )
            for photo in photos
        ],
    )
