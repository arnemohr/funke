"""Admin event API endpoints.

Provides:
- Create event (DRAFT)
- Publish event (DRAFT -> OPEN)
- Clone event
- Get/List events
- Update event (DRAFT only)
- Cancel event
"""

import io
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ...models import (
    CharterContractSummary,
    CustomMessageRequest,
    Event,
    EventCreate,
    EventStatus,
    EventType,
    EventUpdate,
    Registration,
    RegistrationAdminPatch,
    RegistrationStatus,
)
from ...services.anonymization_service import (
    ANONYMIZED_BLOCK_DETAIL,
    get_anonymization_service,
)
from ...services.auth import AdminRole, CurrentUser, require_role
from ...services.charter_service import get_charter_service
from ...services.email_service import get_email_service
from ...services.event_service import (
    CHARTER_NOT_DELETED,
    LOSTFOUND_NOT_DELETED,
    PHOTOS_NOT_DELETED,
    get_event_service,
)
from ...services.logging import get_logger, log_admin_action
from ...services.registration_service import (
    CompanionRecipient,
    companion_recipients,
    get_registration_service,
)

logger = get_logger(__name__)

router = APIRouter()


class CloneEventRequest(BaseModel):
    """Request body for cloning an event."""

    start_at: datetime = Field(..., description="Start date/time for the cloned event")


class EventResponse(BaseModel):
    """Event response with registration stats."""

    id: UUID
    name: str
    description: str | None
    location: str | None
    start_at: datetime
    capacity: int
    registration_deadline: datetime
    status: EventStatus
    reminder_schedule_days: list[int]
    autopromote_waitlist: bool
    registration_link_token: str | None
    created_at: datetime
    published_at: datetime | None
    cancelled_at: datetime | None
    # Spec 022 — set once the event's personal data has been pseudonymised.
    # The UI uses it to badge the event and to stop offering the mail actions.
    anonymized_at: datetime | None = None
    # Spec 025 — {status, uebergabe_at, signed_on} of the event's charter
    # contract, so the detail page can render its section and its „not signed
    # yet" banner without a second request. Only the single-event GET fills it;
    # everywhere else (and on every event that has no contract) it stays None.
    charter_contract: CharterContractSummary | None = None
    registration_count: int = 0
    registration_spots: int = 0
    confirmed_spots: int = 0
    waitlist_count: int = 0
    waitlist_spots: int = 0
    promoted_count: int = 0
    promoted_spots: int = 0


class EventListResponse(BaseModel):
    """Response for list events endpoint."""

    items: list[EventResponse]
    total: int


def _get_org_id(user: CurrentUser) -> UUID:
    """Extract organization ID from user token."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization ID not found in token",
        )
    return UUID(user.org_id)


def _get_admin_id(user: CurrentUser) -> UUID:
    """Convert Auth0 sub to a UUID. Auth0 uses format like 'auth0|123456'."""
    import hashlib
    return UUID(hashlib.md5(user.sub.encode()).hexdigest())


async def _event_to_response(
    event: Event,
    charter_contract: CharterContractSummary | None = None,
) -> EventResponse:
    """Convert Event model to response with stats.

    `charter_contract` is passed by the single-event GET only — the list route
    would pay one read per event for a block no list renders.
    """
    registration_service = get_registration_service()
    stats = await registration_service.get_registration_stats(event.id)

    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        capacity=event.capacity,
        registration_deadline=event.registration_deadline,
        status=event.status,
        reminder_schedule_days=event.reminder_schedule_days,
        autopromote_waitlist=event.autopromote_waitlist,
        registration_link_token=event.registration_link_token,
        created_at=event.created_at,
        published_at=event.published_at,
        cancelled_at=event.cancelled_at,
        anonymized_at=event.anonymized_at,
        charter_contract=charter_contract,
        registration_count=stats.get("total_registrations", 0),
        registration_spots=stats.get("total_registration_spots", 0),
        confirmed_spots=stats.get("confirmed_spots", 0),
        waitlist_count=stats.get("waitlist_registrations", 0),
        waitlist_spots=stats.get("waitlist_spots", 0),
        promoted_count=stats.get("promoted_count", 0),
        promoted_spots=stats.get("promoted_spots", 0),
    )


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def create_event(
    event_data: EventCreate,
    user: CurrentUser,
) -> EventResponse:
    """Create a new event in DRAFT status.

    Returns the created event with a shareable registration link token.
    """
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)

    event_service = get_event_service()
    event = await event_service.create_event(org_id, event_data, admin_id)

    log_admin_action("event.create", user.email, str(event.id), {"event_name": event.name})

    return await _event_to_response(event)


@router.get(
    "",
    response_model=EventListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_events(
    user: CurrentUser,
    status_filter: Annotated[EventStatus | None, Query(alias="status")] = None,
) -> EventListResponse:
    """List all events for the organization.

    Optionally filter by status. Festival events are excluded — they only
    ever appear via `GET /api/admin/festival/events` (spec 019 §Isolation).
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    events = await event_service.list_events(org_id, status_filter)

    # Festival events live in their own admin section (spec 019 §Isolation)
    # — never shown in the regular events UI.
    events = [event for event in events if event.event_type != EventType.FESTIVAL]

    # Convert to responses with stats
    items = []
    for event in events:
        items.append(await _event_to_response(event))

    return EventListResponse(items=items, total=len(items))


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Get event details by ID."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # A FESTIVAL can never carry a contract (the charter router refuses to
    # create one), so the read is skipped rather than answered with None.
    charter_contract = None
    if event.event_type != EventType.FESTIVAL:
        charter_contract = await get_charter_service().get_summary(event_id)

    return await _event_to_response(event, charter_contract)


@router.patch(
    "/{event_id}",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def update_event(
    event_id: UUID,
    update_data: EventUpdate,
    user: CurrentUser,
) -> EventResponse:
    """Update event details (only allowed in DRAFT or OPEN status)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    try:
        event = await event_service.update_event(org_id, event_id, update_data)
    except ValueError as e:
        # Ä8: capacity exceeds the persisted event type's cap
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Event nicht gefunden oder nicht mehr änderbar — abgeschlossene "
                "und abgesagte Veranstaltungen sind eingefroren."
            ),
        )

    log_admin_action("event.update", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/publish",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def publish_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Publish an event (DRAFT -> OPEN).

    After publishing, the event accepts registrations via the public link.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.publish_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be published (not in DRAFT status)",
        )

    log_admin_action("event.publish", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/clone",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def clone_event(
    event_id: UUID,
    clone_data: CloneEventRequest,
    user: CurrentUser,
) -> EventResponse:
    """Clone an existing event with a new start date.

    Creates a new DRAFT event with the same settings but updated dates.
    """
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)

    event_service = get_event_service()
    new_event = await event_service.clone_event(
        org_id,
        event_id,
        clone_data.start_at,
        admin_id,
    )

    if not new_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source event not found",
        )

    log_admin_action(
        "event.clone", user.email, str(new_event.id),
        {"source_event_id": str(event_id)},
    )

    return await _event_to_response(new_event)


@router.post(
    "/{event_id}/close-registration",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def close_registration(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Manually close registration for an event (OPEN -> REGISTRATION_CLOSED)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.close_registration(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot close registration (not in OPEN status)",
        )

    log_admin_action("event.close_registration", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/reopen-registration",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def reopen_registration(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Reopen registration for an event (REGISTRATION_CLOSED -> OPEN)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.reopen_registration(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot reopen registration (not in REGISTRATION_CLOSED status)",
        )

    log_admin_action("event.reopen_registration", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/complete",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def complete_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Mark event as completed (CONFIRMED -> COMPLETED)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.complete_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be completed (not in CONFIRMED status)",
        )

    log_admin_action("event.complete", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/cancel",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def cancel_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Cancel an event.

    Cancellation is final and cannot be undone.
    All registrants will be notified via email.
    """
    org_id = _get_org_id(user)
    registration_service = get_registration_service()
    email_service = get_email_service()

    # Fetch active registrations BEFORE cancelling (so we have their details for notifications)
    active_registrations = [
        r
        for r in await registration_service.list_registrations(event_id)
        if r.status != RegistrationStatus.CANCELLED
    ]

    # Cancel the event
    event_service = get_event_service()
    event = await event_service.cancel_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be cancelled",
        )

    log_admin_action("event.cancel", user.email, str(event_id))

    # Cancel all registrations for this event
    cancelled_count = await registration_service.cancel_all_registrations_for_event(event_id)
    logger.info(
        "All registrations cancelled for event",
        extra={
            "event_id": str(event_id),
            "cancelled_count": cancelled_count,
        },
    )

    # Notify using pre-fetched list (registrations already cancelled in DB)
    notified_count = 0
    failed_count = 0

    for registration in active_registrations:
        try:
            await email_service.send_event_cancellation(event, registration)
            notified_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                "Failed to send event cancellation email",
                extra={
                    "registration_id": str(registration.id),
                    "email": registration.email,
                    "error": str(e),
                },
            )

    logger.info(
        "Event cancellation notifications sent",
        extra={
            "event_id": str(event_id),
            "notified_count": notified_count,
            "failed_count": failed_count,
        },
    )

    return await _event_to_response(event)


# How long one anonymization request may spend rewriting rows. API Gateway cuts
# the connection at 29s and the Lambda dies at 30s, so a big event has to come
# back before then with `completed: false` instead of a 504 — the client calls
# again and the run picks up where it stopped. The remainder is headroom for
# fetching the event, the last query page and serialising the response.
_ANONYMIZE_TIME_BUDGET = timedelta(seconds=20)


class AnonymizeResponse(BaseModel):
    """What one anonymization pass touched.

    `completed` false means the event still holds personal data: the pass hit
    its time budget and the caller has to POST again. The counters are per
    pass, not cumulative.
    """

    event_id: UUID
    event_name: str
    anonymized_at: datetime | None
    already_anonymized: bool
    completed: bool
    registrations: int
    scans: int
    invites: int
    messages: int
    rows_touched: int


@router.post(
    "/{event_id}/anonymize",
    response_model=AnonymizeResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def anonymize_event(
    event_id: UUID,
    user: CurrentUser,
) -> AnonymizeResponse:
    """Pseudonymise every personal field this event owns (spec 022).

    Serves SINGLE and FESTIVAL events alike — the work is identical, and both
    kinds live in the same partition. Only COMPLETED and CANCELLED events
    qualify; anything else 409s, since an event that might still mail somebody
    needs its addresses.

    Permanent and irreversible: names and addresses are overwritten in place
    with digests that cannot be turned back. The rows themselves survive, so
    every headcount, tier split and check-in total stays intact. Calling it
    twice is a no-op — the second call returns `already_anonymized`.

    An event too large to finish inside the request window returns
    `completed: false` after scrubbing as much as it could, and the client
    repeats the call until it flips true. Each pass is a complete, consistent
    step: only whole rows are rewritten, and `anonymized_at` is stamped on the
    last pass alone.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    try:
        result = await get_anonymization_service().anonymize_event(
            event,
            deadline=datetime.now(timezone.utc) + _ANONYMIZE_TIME_BUDGET,
        )
    except ValueError as e:
        # Wrong status — German detail, mirrors the delete guard's 409.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    # Logged once per event, on the pass that finishes it — a five-pass scrub of
    # one festival is one admin action, not five.
    if result.completed and not result.already_anonymized:
        log_admin_action("event.anonymize", user.email, str(event_id))

    return AnonymizeResponse(
        event_id=event_id,
        event_name=result.event_name,
        anonymized_at=result.anonymized_at,
        already_anonymized=result.already_anonymized,
        completed=result.completed,
        registrations=result.registrations,
        scans=result.scans,
        invites=result.invites,
        messages=result.messages,
        rows_touched=result.rows_touched,
    )


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def delete_event(
    event_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete an event (only allowed for CANCELLED events).

    Deletion is permanent and cannot be undone.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    try:
        deleted = await event_service.delete_event(org_id, event_id)
    except ValueError as e:
        # One of the two photo buckets kept its objects, so the event has to
        # stay: it is the only way back to them. Retryable, hence 503 — and
        # named, because the two buckets are cleaned up by different sweeps.
        if str(e) == LOSTFOUND_NOT_DELETED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Die Fundsachen-Bilder konnten nicht gelöscht werden — das Event "
                    "bleibt bestehen. Bitte versuch es noch einmal."
                ),
            ) from e
        if str(e) == PHOTOS_NOT_DELETED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Die Eventfotos konnten nicht gelöscht werden — das Event "
                    "bleibt bestehen. Bitte versuch es noch einmal."
                ),
            ) from e
        if str(e) == CHARTER_NOT_DELETED:
            # 409, not 503: the signed contract (spec 025) is an accounting
            # record and retrying changes nothing until the retention year has
            # passed. The year is read back here rather than carried in the
            # exception, so the refusal can name it — one extra read, only ever
            # on this path.
            blocked_until = await get_charter_service().deletion_block_year(event_id)
            deadline = f"bis {blocked_until} " if blocked_until else ""
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Das Event hat einen unterschriebenen Chartervertrag und kann "
                    f"{deadline}nicht gelöscht werden."
                ),
            ) from e
        raise

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be deleted (must be in CANCELLED status)",
        )

    log_admin_action("event.delete", user.email, str(event_id))

    # Push notification: test trigger for PWA (spec 009)
    try:
        from ...services.push_service import get_push_service

        push_service = get_push_service()
        logger.info(
            "Push check after event delete",
            extra={"configured": push_service.is_configured(), "org_id": str(org_id)},
        )
        if push_service.is_configured():
            sent = await push_service.send_to_org_admins(
                org_id=str(org_id),
                title="Veranstaltung gelöscht",
                body="Eine Veranstaltung wurde dauerhaft gelöscht.",
                url="/admin/events",
            )
            logger.info("Push notifications sent after event delete", extra={"sent": sent})
    except Exception:
        logger.warning("Push notification failed after event deletion", exc_info=True)


@router.delete(
    "/{event_id}/registrations/{registration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def delete_registration(
    event_id: UUID,
    registration_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete a registration permanently."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    deleted = await registration_service.delete_registration(event_id, registration_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    log_admin_action(
        "registration.delete",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "registrant_name": deleted.name},
    )


class RegistrationResponse(BaseModel):
    """Registration response for admin view.

    Admin-specific on purpose — it carries `notes`, `page_viewed_at` and
    `promoted_from_waitlist`, which the public `models.RegistrationResponse`
    deliberately withholds. Do not merge the two.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    name: str
    email: str
    phone: str | None
    notes: str | None
    group_size: int
    # `None` entries are tombstones for removed festival members (T109) —
    # indices never shift. This MUST stay `str | None`: with a bare `list[str]`
    # every endpoint below returned 500 for any group that had lost a member,
    # including the approval toggle (whose F8 mail had already gone out by then).
    group_members: list[str | None] | None = None
    status: RegistrationStatus
    waitlist_position: int | None
    registration_token: str
    registered_at: datetime
    responded_at: datetime | None
    page_viewed_at: datetime | None = None
    promoted_from_waitlist: bool
    promoted: bool
    # Festival fields (spec 019/021). Without them the admin PUT answered every
    # approval with `overnight_approved=False` and no `overnight_notified_at`,
    # so the toggle in the UI could not tell whether its F8 mail was queued.
    attendance_slots: list[str] | None = None
    member_slots: dict[str, list[str]] | None = None
    tent_count: int | None = None
    camper_count: int | None = None
    overnight_approved: bool = False
    overnight_notified_at: datetime | None = None
    overnight_declined_at: datetime | None = None
    invite_label: str | None = None
    tier: str | None = None


class RegistrationListResponse(BaseModel):
    """Response for list registrations endpoint."""

    items: list[RegistrationResponse]
    total: int


def _registration_to_response(registration: Registration) -> RegistrationResponse:
    """Convert Registration model to response.

    Deliberately `model_validate` (the model sets `from_attributes=True`)
    rather than a hand-written kwarg list: the explicit list this replaced
    silently dropped every festival field, so the admin PUT answered with
    `overnight_approved=False` even right after approving and the approval
    toggle could not tell whether its F8 mail had been queued. A field added to
    the model above now reaches all seven admin endpoints that use this helper,
    instead of defaulting silently in each of them.
    """
    return RegistrationResponse.model_validate(registration)


@router.get(
    "/{event_id}/registrations",
    response_model=RegistrationListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_registrations(
    event_id: UUID,
    user: CurrentUser,
    status_filter: Annotated[RegistrationStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query()] = None,
) -> RegistrationListResponse:
    """List all registrations for an event.

    Supports filtering by status and searching by name/email.
    """
    org_id = _get_org_id(user)

    # Verify event belongs to org
    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(
        event_id, status_filter, search,
    )

    return RegistrationListResponse(
        items=[_registration_to_response(r) for r in registrations],
        total=len(registrations),
    )


@router.get(
    "/{event_id}/registrations/unacknowledged",
    response_model=RegistrationListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_unacknowledged(
    event_id: UUID,
    user: CurrentUser,
) -> RegistrationListResponse:
    """List unacknowledged (CONFIRMED) registrations for preview before discard."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(
        event_id, status_filter=RegistrationStatus.CONFIRMED,
    )

    return RegistrationListResponse(
        items=[_registration_to_response(r) for r in registrations],
        total=len(registrations),
    )


class DiscardRequest(BaseModel):
    """Request body for discarding unacknowledged registrations."""

    registration_ids: list[UUID] | None = None
    reason: str | None = None
    subject: str | None = None


class DiscardResponse(BaseModel):
    """Response for discard unacknowledged endpoint."""

    discarded_count: int
    discarded_spots: int


@router.post(
    "/{event_id}/registrations/discard-unacknowledged",
    response_model=DiscardResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def discard_unacknowledged(
    event_id: UUID,
    user: CurrentUser,
    body: DiscardRequest = DiscardRequest(),
) -> DiscardResponse:
    """Discard unacknowledged (CONFIRMED) registrations.

    Cancels selected (or all) registrations and sends notification emails.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    discarded_count, discarded_spots = await registration_service.discard_unacknowledged(
        event_id, body.registration_ids, body.reason, body.subject,
    )

    log_admin_action(
        "registrations.discard_unacknowledged",
        user.email,
        str(event_id),
        {"discarded_count": discarded_count, "discarded_spots": discarded_spots},
    )

    return DiscardResponse(
        discarded_count=discarded_count,
        discarded_spots=discarded_spots,
    )


class PromoteFromWaitlistRequest(BaseModel):
    """Request body for manual waitlist promotion."""

    target_status: str = "CONFIRMED"  # "CONFIRMED" or "PARTICIPATING"


@router.post(
    "/{event_id}/registrations/{registration_id}/promote-from-waitlist",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def promote_from_waitlist(
    event_id: UUID,
    registration_id: UUID,
    body: PromoteFromWaitlistRequest,
    user: CurrentUser,
) -> RegistrationResponse:
    """Manually promote a waitlisted registration.

    target_status can be CONFIRMED (user must acknowledge) or PARTICIPATING (direct).
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    target = RegistrationStatus(body.target_status)
    if target not in (RegistrationStatus.CONFIRMED, RegistrationStatus.PARTICIPATING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_status must be CONFIRMED or PARTICIPATING",
        )

    registration_service = get_registration_service()

    # Check capacity before promoting
    reg = await registration_service.get_registration(event_id, registration_id)
    if not reg or reg.status != RegistrationStatus.WAITLISTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in WAITLISTED status",
        )
    stats = await registration_service.get_registration_stats(event_id)
    remaining = event.capacity - stats["confirmed_spots"]
    if reg.group_size > remaining:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Nicht genügend Plätze: {remaining} frei, {reg.group_size} benötigt",
        )

    registration = await registration_service.promote_single_from_waitlist(
        event_id, registration_id, target,
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in WAITLISTED status",
        )

    log_admin_action(
        "registration.promote_from_waitlist",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "target_status": body.target_status},
    )

    return _registration_to_response(registration)


class TogglePromotedRequest(BaseModel):
    """Request body for toggling promoted flag."""

    promoted: bool


@router.patch(
    "/{event_id}/registrations/{registration_id}/promote",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def toggle_promoted(
    event_id: UUID,
    registration_id: UUID,
    body: TogglePromotedRequest,
    user: CurrentUser,
) -> RegistrationResponse:
    """Toggle the promoted flag on a registration.

    Only allowed when event is OPEN or REGISTRATION_CLOSED.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    if event.status not in (EventStatus.OPEN, EventStatus.REGISTRATION_CLOSED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Promoted flag can only be changed when event is OPEN or REGISTRATION_CLOSED",
        )

    registration_service = get_registration_service()
    registration = await registration_service.set_promoted(
        event_id, registration_id, body.promoted,
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in REGISTERED status",
        )

    log_admin_action(
        "registration.toggle_promoted",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "promoted": body.promoted},
    )

    return _registration_to_response(registration)


_PATCH_ERROR_STATUS = {
    "not_found": (status.HTTP_404_NOT_FOUND, "Registration not found"),
    "frozen_registration": (
        status.HTTP_400_BAD_REQUEST,
        "Registration is frozen (CANCELLED or CHECKED_IN)",
    ),
    "frozen_event": (status.HTTP_400_BAD_REQUEST, "Event is completed"),
    "invalid_group_size": (
        status.HTTP_400_BAD_REQUEST,
        "group_size cannot grow and must be ≥ 1",
    ),
    "invalid_group_members": (
        status.HTTP_400_BAD_REQUEST,
        "group_members payload is inconsistent with group_size",
    ),
    # Festival sidetrack (spec 019, T205) — the frontend surfaces `detail`
    # verbatim in toasts, so these are German user-facing strings.
    "not_festival_event": (
        status.HTTP_400_BAD_REQUEST,
        "Zeitfenster und Übernachtung gibt es nur bei Festival-Veranstaltungen",
    ),
    "invalid_slots": (
        status.HTTP_400_BAD_REQUEST,
        "Ungültige Zeitfenster-Auswahl — mindestens ein gültiges Zeitfenster wählen",
    ),
    "phone_required_for_accommodation": (
        status.HTTP_400_BAD_REQUEST,
        "Für einen Übernachtungswunsch wird eine Telefonnummer benötigt",
    ),
    "overnight_approval_requires_accommodation": (
        status.HTTP_400_BAD_REQUEST,
        "Übernachtung kann nur zugesagt werden, wenn ein Übernachtungswunsch vorliegt",
    ),
    "overnight_decline_requires_accommodation": (
        status.HTTP_400_BAD_REQUEST,
        "Übernachtung kann nur abgelehnt werden, wenn ein Übernachtungswunsch vorliegt",
    ),
    "overnight_decline_conflicts_with_approval": (
        status.HTTP_400_BAD_REQUEST,
        "Bitte zuerst die Zusage zurücknehmen, dann ablehnen",
    ),
    "tent_count_exceeds_group": (
        status.HTTP_400_BAD_REQUEST,
        "Es können nicht mehr Zelte als Personen sein",
    ),
    "camper_count_exceeds_group": (
        status.HTTP_400_BAD_REQUEST,
        "Es können nicht mehr Camper als Personen sein",
    ),
    "update_failed": (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Failed to update registration",
    ),
}


@router.put(
    "/{event_id}/registrations/{registration_id}",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def update_registration(
    event_id: UUID,
    registration_id: UUID,
    patch: RegistrationAdminPatch,
    user: CurrentUser,
):
    """Admin: partial update of a single registration (spec 018).

    Replaces the prior ``…/group-members`` endpoint. Returns 409 with the
    current ``RegistrationResponse`` body when an optimistic-concurrency
    check fails.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    registration_service = get_registration_service()
    registration, error = await registration_service.admin_update_registration(
        event_id, registration_id, patch,
    )

    if error == "conflict":
        current = await registration_service.get_registration(event_id, registration_id)
        body = {
            "detail": "conflict",
            "registration": _registration_to_response(current).model_dump(mode="json")
            if current
            else None,
        }
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body)

    if error:
        code, detail = _PATCH_ERROR_STATUS.get(
            error, (status.HTTP_400_BAD_REQUEST, "Invalid update"),
        )
        raise HTTPException(status_code=code, detail=detail)

    assert registration is not None  # for type-checkers; service contract
    changed_fields = sorted(patch.model_dump(exclude_unset=True).keys())
    log_admin_action(
        "registration.update",
        user.email,
        str(registration_id),
        {"event_id": str(event_id), "changed_fields": changed_fields},
    )

    return _registration_to_response(registration)


@router.get(
    "/{event_id}/registrations/export",
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def export_registrations_pdf(
    event_id: UUID,
    user: CurrentUser,
) -> StreamingResponse:
    """Export boarding list as PDF with disclaimer + single-column signature grid.

    Layout per page (A4 portrait):
    - Header block: title, ``Datum / Ort/Fahrt / Seite`` row, two-paragraph
      liability disclaimer.
    - Single-column table with Nr | Name | Unterschrift / Signature, sized so
      the signature has the bulk of the page width.

    Empty cells beyond the guest list render as blank numbered rows ready to
    sign manually. One additional fully-blank page is always appended for
    crew or last-minute walk-ons; numbering continues across pages. A floor
    of 95 numbered rows is always rendered so the form is usable as a print
    template even before the lottery has been drawn.
    """
    from fpdf import FPDF

    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(event_id)

    # Collect all guest names (one per person, not per registration)
    guests: list[str] = []
    for reg in registrations:
        if reg.status.value != "PARTICIPATING":
            continue
        if reg.group_members and len(reg.group_members) > 0:
            guests.extend(reg.group_members)
        elif reg.group_size == 1:
            guests.append(reg.name)
        else:
            guests.append(reg.name)
            guests.extend(f"(Gast {i + 2} von {reg.name})" for i in range(reg.group_size - 1))

    guests.sort(key=str.casefold)

    # Layout constants ------------------------------------------------------
    PAGE_WIDTH = 210  # A4 portrait
    LEFT_MARGIN = 12
    RIGHT_MARGIN = 12
    BOTTOM_MARGIN = 14
    TABLE_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN  # 186

    COL_NR = 12
    COL_NAME = 64
    COL_SIG = TABLE_WIDTH - COL_NR - COL_NAME  # 110
    HEADER_HEIGHT = 9
    ROW_HEIGHT = 12
    ROWS_PER_PAGE = 17
    MIN_TOTAL_ROWS = 95  # render at least this many numbered rows even when empty

    DISCLAIMER_PARA_1 = (
        "Mit meiner Unterschrift erkläre ich als Mitglied oder Gast eines Mitgliedes "
        "des Verein für mobile Machenschaften e.V. oder Gast eines Charterers der "
        "Schaluppe persönlich eingeladen worden zu sein, eine Sicherheitseinweisung "
        "erhalten zu haben und über mögliche Risiken und Gefahren während des "
        "Aufenthalts aufgeklärt worden zu sein."
    )
    DISCLAIMER_PARA_2 = (
        '"Hiermit stelle ich im gesetzlich weitest möglichen Umfang die/den '
        "Schiffsführer*in und den/die Schiffscharterin*er von der Haftung frei. "
        "Die Freistellung gilt auch für von mir mitgeführte Kinder. Insbesondere "
        'ist eine Haftung wegen einfacher Fahrlässigkeit ausgeschlossen."'
    )

    # Compute pages: at least one for guests, plus one fully-blank trailing
    # page for walk-ons. Floor at MIN_TOTAL_ROWS so the form is printable as a
    # template even when there are no PARTICIPATING registrations yet.
    guest_count = len(guests)
    pages_for_guests = max(1, (guest_count + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
    min_pages = (MIN_TOTAL_ROWS + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
    total_pages = max(pages_for_guests + 1, min_pages)

    event_date = event.start_at.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
    event_name = event.name
    event_location = event.location or "-"
    ort_fahrt = f"{event_location} ({event_name})" if event.location else event_name

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(LEFT_MARGIN, 12, RIGHT_MARGIN)
    pdf.set_auto_page_break(auto=False)  # manual layout

    def _render_header(page_num: int) -> None:
        pdf.set_y(12)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 9, "Boardingzettel", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 10)
        col_w = TABLE_WIDTH / 3
        pdf.cell(col_w, 6, f"Datum: {event_date}", border=0)
        pdf.cell(col_w, 6, f"Ort/Fahrt: {ort_fahrt}", border=0)
        pdf.cell(
            col_w, 6, f"Seite: {page_num}/{total_pages}",
            border=0, align="R", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(TABLE_WIDTH, 3.8, DISCLAIMER_PARA_1, border=0)
        pdf.ln(1.5)
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.multi_cell(TABLE_WIDTH, 3.8, DISCLAIMER_PARA_2, border=0)
        pdf.ln(4)

    def _render_table_header() -> None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(COL_NR, HEADER_HEIGHT, "Nr", border=1, fill=True, align="C")
        pdf.cell(COL_NAME, HEADER_HEIGHT, "Name", border=1, fill=True)
        pdf.cell(COL_SIG, HEADER_HEIGHT, "Unterschrift / Signature",
                 border=1, fill=True, align="C")
        pdf.ln()

    def _render_row(num: int, name: str) -> None:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(COL_NR, ROW_HEIGHT, str(num), border=1, align="C")
        pdf.cell(COL_NAME, ROW_HEIGHT, name, border=1)
        pdf.cell(COL_SIG, ROW_HEIGHT, "", border=1)
        pdf.ln()

    for page_idx in range(total_pages):
        pdf.add_page()
        _render_header(page_idx + 1)
        _render_table_header()

        page_offset = page_idx * ROWS_PER_PAGE
        for row_idx in range(ROWS_PER_PAGE):
            entry_idx = page_offset + row_idx
            name = guests[entry_idx] if entry_idx < guest_count else ""
            _render_row(entry_idx + 1, name)

            if pdf.get_y() + ROW_HEIGHT > pdf.h - BOTTOM_MARGIN:
                break

    log_admin_action("registrations.export", user.email, str(event_id))

    pdf_bytes = pdf.output()
    filename_map = str.maketrans(
        {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"},
    )
    safe_name = (
        event.name.translate(filename_map)
        .replace(" ", "_")
        .encode("ascii", "replace")
        .decode("ascii")
    )
    filename = f"boardingzettel_{safe_name}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{event_id}/registrations/{registration_id}",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_registration(
    event_id: UUID,
    registration_id: UUID,
    user: CurrentUser,
) -> RegistrationResponse:
    """Admin: fetch a single registration for the detail page (spec 018).

    Registered after the literal ``/registrations/export`` route so the UUID
    path param does not shadow it.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    registration_service = get_registration_service()
    registration = await registration_service.get_registration(event_id, registration_id)
    if not registration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    return _registration_to_response(registration)


class CustomMessageResponse(BaseModel):
    """Response for custom message sending."""

    sent: int
    failed: int
    total: int


@router.post(
    "/{event_id}/messages",
    response_model=CustomMessageResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def send_custom_message(
    event_id: UUID,
    message_data: CustomMessageRequest,
    user: CurrentUser,
) -> CustomMessageResponse:
    """Send a custom message to selected registrations."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    if event.is_anonymized:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ANONYMIZED_BLOCK_DETAIL,
        )

    registration_service = get_registration_service()
    email_service = get_email_service()

    sent = 0
    failed = 0
    total = 0

    for reg_id in message_data.registration_ids:
        registration = await registration_service.get_registration(event_id, reg_id)
        if not registration:
            failed += 1
            total += 1
            continue

        # Spec 020: the contact plus every companion who supplied an address.
        # Each is its own recipient with its own Message row, so the message log
        # and the sent/failed counters stay honest about how many mails went out.
        targets: list[CompanionRecipient | None] = [None]
        if message_data.include_companions:
            targets.extend(companion_recipients(registration))

        for companion in targets:
            total += 1
            try:
                success = await email_service.send_custom_message(
                    event, registration, message_data.subject, message_data.body,
                    include_links=message_data.include_links,
                    companion=companion,
                )
                if success:
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                # Per-recipient: one bad companion address must not cost the
                # rest of the group — or the contact — their copy.
                failed += 1
                logger.error(
                    "Failed to send custom message",
                    extra={
                        "registration_id": str(reg_id),
                        "person_index": companion.person_index if companion else 0,
                        "error": str(e),
                    },
                )

    log_admin_action(
        "message.send_custom",
        user.email,
        str(event_id),
        {
            "sent": sent,
            "failed": failed,
            "total": total,
            "registrations": len(message_data.registration_ids),
            "include_companions": message_data.include_companions,
        },
    )

    return CustomMessageResponse(
        sent=sent,
        failed=failed,
        total=total,
    )


class MessageLogEntry(BaseModel):
    """Single message in the log."""

    id: str | None
    type: str | None
    subject: str | None
    recipient_email: str | None
    status: str | None
    sent_at: str | None


class MessageListResponse(BaseModel):
    """Response for messages list endpoint."""

    items: list[MessageLogEntry]
    total: int


@router.get(
    "/{event_id}/messages",
    response_model=MessageListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_messages(
    event_id: UUID,
    user: CurrentUser,
) -> MessageListResponse:
    """List sent messages for an event."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    email_service = get_email_service()
    messages = await email_service.list_messages_for_event(event_id)

    return MessageListResponse(
        items=[MessageLogEntry(**m) for m in messages],
        total=len(messages),
    )
