"""Public registration API endpoints.

Provides:
- Get event info for registration form
- Submit registration (no auth required)
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import (
    EventPublic,
    RegistrationCreate,
    RegistrationResponse,
)
from ...services.email_service import get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger
from ...services.registration_service import get_registration_service

logger = get_logger(__name__)

router = APIRouter()


class RegistrationSubmitResponse(BaseModel):
    """Response for successful registration submission."""

    registration: RegistrationResponse
    message: str


@router.get(
    "/events/{link_token}",
    response_model=EventPublic,
)
async def get_event_info(link_token: str) -> EventPublic:
    """Get public event info for the registration form.

    Uses the registration link token (not the event ID).
    Returns 410 Gone if event is closed or cancelled.
    """
    event_service = get_event_service()
    event = await event_service.get_event_by_link_token(link_token)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # Return 410 if event is not accepting registrations
    if event.status.value != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Event registration is closed (status: {event.status.value})",
        )

    # Return limited public info
    return EventPublic(
        name=event.name,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        capacity=event.capacity,
        registration_deadline=event.registration_deadline,
        status=event.status.value,
        autopromote_waitlist=event.autopromote_waitlist,
    )


@router.post(
    "/events/{link_token}/registrations",
    response_model=RegistrationSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_registration(
    link_token: str,
    registration_data: RegistrationCreate,
) -> RegistrationSubmitResponse:
    """Submit a registration for an event.

    All registrations start as REGISTERED. Capacity enforcement is
    deferred to the lottery phase after registration closes.

    Returns 409 Conflict if email is already registered for this event.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.create_registration(
        link_token,
        registration_data,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error,
            )
        if "already registered" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error,
            )
        if "deadline" in error.lower() or "not open" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    logger.info(
        "Registration submitted via public API",
        extra={
            "registration_id": str(registration.id),
            "event_id": str(registration.event_id),
            "status": registration.status.value,
        },
    )

    # Send confirmation email
    try:
        event_service = get_event_service()
        event = await event_service.get_event_by_link_token(link_token)
        if event:
            email_service = get_email_service()
            await email_service.send_registration_confirmation(event, registration)
        else:
            logger.warning(
                "Could not send email: event not found by link token",
                extra={"link_token": link_token, "registration_id": str(registration.id)},
            )
    except Exception as e:
        # Don't fail the registration if email fails
        logger.error(
            "Failed to send registration email",
            extra={"error": str(e), "registration_id": str(registration.id)},
        )

    message = "Deine Anmeldung ist eingegangen! Du erhältst in Kürze eine Bestätigungsmail."

    return RegistrationSubmitResponse(
        registration=RegistrationResponse(
            id=registration.id,
            event_id=registration.event_id,
            name=registration.name,
            email=registration.email,
            group_size=registration.group_size,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        message=message,
    )
