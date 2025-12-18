"""Worker handler for scheduled tasks.

Handles EventBridge-triggered tasks:
- send_confirmation_reminders: Send confirmation requests to attendees
- retry_failed_emails: Retry failed email deliveries
- cleanup_expired_data: Handle TTL-based data cleanup
"""

from datetime import datetime, timezone
from typing import Any

from ..models import EventStatus, RegistrationStatus
from ..services.email_service import get_email_service
from ..services.event_service import get_event_service
from ..services.logging import get_logger, set_request_id, setup_logging
from ..services.registration_service import get_registration_service

# Initialize logging
setup_logging()
logger = get_logger(__name__)


async def send_confirmation_reminders() -> dict:
    """Send confirmation reminders for upcoming events.

    Checks for registrations that need confirmation requests
    based on the event's reminder schedule.

    The worker:
    1. Finds all events in CONFIRMED status (lottery finalized)
    2. For each event, calculates days until event start
    3. If today matches a reminder day, sends confirmation requests
       to all registrations in CONFIRMED status (not yet responded)
    """
    logger.info("Starting confirmation reminder task")

    event_service = get_event_service()
    registration_service = get_registration_service()
    email_service = get_email_service()

    # Get all events in CONFIRMED status
    # We need to iterate through all orgs, but since we don't have a cross-org query,
    # we'll query by status using a GSI scan (or iterate events table)
    events = await event_service.get_events_by_status(EventStatus.CONFIRMED)

    now = datetime.now(timezone.utc)
    total_sent = 0
    total_failed = 0
    events_processed = 0

    for event in events:
        # Calculate days until event
        event_start = event.start_at
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=timezone.utc)

        days_until_event = (event_start.date() - now.date()).days

        # Check if today is a reminder day
        if days_until_event not in event.reminder_schedule_days:
            continue

        if days_until_event < 0:
            # Event has already passed
            continue

        events_processed += 1
        logger.info(
            f"Processing event for reminders",
            extra={
                "event_id": str(event.id),
                "event_name": event.name,
                "days_until_event": days_until_event,
            },
        )

        # Get all confirmed registrations with pending confirmation
        registrations = await registration_service.list_registrations(event.id)

        for registration in registrations:
            # Only send to CONFIRMED registrations (not yet responded)
            # PARTICIPATING or CANCELLED means they already responded
            if registration.status != RegistrationStatus.CONFIRMED:
                continue

            try:
                success = await email_service.send_confirmation_request(
                    event, registration, days_until_event
                )
                if success:
                    total_sent += 1
                    logger.info(
                        "Confirmation request sent",
                        extra={
                            "registration_id": str(registration.id),
                            "email": registration.email,
                            "days_until_event": days_until_event,
                        },
                    )
                else:
                    total_failed += 1
                    logger.warning(
                        "Failed to send confirmation request",
                        extra={
                            "registration_id": str(registration.id),
                            "email": registration.email,
                        },
                    )
            except Exception as e:
                total_failed += 1
                logger.error(
                    "Error sending confirmation request",
                    extra={
                        "registration_id": str(registration.id),
                        "email": registration.email,
                        "error": str(e),
                    },
                )

    result = {
        "task": "send_confirmation_reminders",
        "status": "completed",
        "events_processed": events_processed,
        "emails_sent": total_sent,
        "emails_failed": total_failed,
    }

    logger.info("Confirmation reminder task completed", extra=result)
    return result


async def retry_failed_emails() -> dict:
    """Retry failed email deliveries.

    Processes messages with FAILED status and retry_count < max_retries.
    Uses exponential backoff for retry timing.
    """
    logger.info("Starting email retry task")
    # Implementation will be added in Phase 3 (US1)
    return {"task": "retry_failed_emails", "status": "not_implemented"}


async def cleanup_expired_data() -> dict:
    """Clean up expired data for GDPR compliance.

    Handles:
    - TTL-expired records verification
    - Personal data scrubbing for completed events
    """
    logger.info("Starting data cleanup task")
    # Implementation will be added in Phase 9 (Polish)
    return {"task": "cleanup_expired_data", "status": "not_implemented"}


def handler(event: dict[str, Any], context: Any) -> dict:
    """Lambda handler for worker tasks.

    Args:
        event: EventBridge event with task specification.
        context: Lambda context.

    Returns:
        Task execution result.
    """
    import asyncio

    # Set request ID for tracing
    request_id = event.get("id", "")
    set_request_id(request_id[:8] if request_id else None)

    task_name = event.get("task", "unknown")
    logger.info(f"Worker invoked for task: {task_name}", extra={"event": event})

    # Task dispatch
    tasks = {
        "send_confirmation_reminders": send_confirmation_reminders,
        "retry_failed_emails": retry_failed_emails,
        "cleanup_expired_data": cleanup_expired_data,
    }

    task_fn = tasks.get(task_name)
    if not task_fn:
        logger.error(f"Unknown task: {task_name}")
        return {"error": f"Unknown task: {task_name}"}

    try:
        result = asyncio.get_event_loop().run_until_complete(task_fn())
        logger.info(f"Task {task_name} completed", extra={"result": result})
        return result
    except Exception as e:
        logger.error(f"Task {task_name} failed", exc_info=True)
        return {"error": str(e), "task": task_name}
