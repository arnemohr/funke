"""Public cancellation API endpoints.

Provides:
- Cancel registration via unique token (no auth required)
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import RegistrationResponse
from ...services.email_service import get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger
from ...services.registration_service import get_registration_service

logger = get_logger(__name__)

router = APIRouter()


class CancellationResponse(BaseModel):
    """Response for successful cancellation."""

    registration: RegistrationResponse
    message: str


@router.post(
    "/registrations/{registration_id}/cancel",
    response_model=CancellationResponse,
)
async def cancel_registration(
    registration_id: UUID,
    token: str,
) -> CancellationResponse:
    """Cancel a registration using the cancellation token.

    The token is provided in the confirmation email.
    Cancellation triggers automatic waitlist promotion if enabled.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.cancel_registration(
        registration_id,
        token,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registration not found or invalid token",
            )
        if "cannot cancel" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    logger.info(
        "Registration cancelled via public API",
        extra={
            "registration_id": str(registration_id),
            "event_id": str(registration.event_id),
        },
    )

    # Send cancellation confirmation email
    try:
        event_service = get_event_service()
        event = await event_service.get_event_by_id(registration.event_id)
        if event:
            email_service = get_email_service()
            await email_service.send_cancellation_confirmation(event, registration)
        else:
            logger.warning(
                "Could not send cancellation email: event not found",
                extra={
                    "event_id": str(registration.event_id),
                    "registration_id": str(registration_id),
                },
            )
    except Exception as e:
        # Don't fail the cancellation if email fails
        logger.error(
            "Failed to send cancellation email",
            extra={"error": str(e), "registration_id": str(registration_id)},
        )

    return CancellationResponse(
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
        ),
        message="Your registration has been successfully cancelled.",
    )


@router.get(
    "/registrations/{registration_id}",
)
async def get_registration_info(
    registration_id: UUID,
    token: str,
) -> RegistrationResponse:
    """Get registration info for the cancellation page.

    Validates the token before returning registration details.
    """
    registration_service = get_registration_service()

    registration = await registration_service.get_registration_by_token(token)

    if not registration or registration.id != registration_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found or invalid token",
        )

    return RegistrationResponse(
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
    )
