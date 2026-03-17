"""Worker handler for scheduled tasks.

Handles EventBridge-triggered tasks:
- send_confirmation_reminders: Send confirmation requests to attendees
- retry_failed_emails: Retry failed email deliveries
- cleanup_expired_data: Handle TTL-based data cleanup
"""

from datetime import datetime, timedelta, timezone
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

    from ..services.config import get_messages_table
    from ..services.email_client import EmailMessage as GmailEmailMessage
    from ..services.email_client import get_gmail_client
    from ..models import MessageStatus

    max_retries = 3
    retried = 0
    succeeded = 0
    failed = 0

    try:
        messages_table = get_messages_table()

        # Scan for FAILED messages with retry_count < max_retries
        scan_kwargs = {
            "FilterExpression": "#status = :failed",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":failed": MessageStatus.FAILED.value},
        }

        response = messages_table.scan(**scan_kwargs)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = messages_table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))

        now = datetime.now(timezone.utc)

        for item in items:
            retry_count = item.get("retry_count", 0)
            if retry_count >= max_retries:
                continue

            # Exponential backoff: skip if too recent
            sent_at = item.get("sent_at")
            if sent_at:
                last_attempt = datetime.fromisoformat(sent_at)
                if last_attempt.tzinfo is None:
                    last_attempt = last_attempt.replace(tzinfo=timezone.utc)
                backoff_seconds = 60 * (2 ** retry_count)  # 1min, 2min, 4min
                if (now - last_attempt).total_seconds() < backoff_seconds:
                    continue

            recipient_email = item.get("recipient_email")
            if not recipient_email:
                continue

            retried += 1

            try:
                gmail_client = get_gmail_client()
                gmail_message = GmailEmailMessage(
                    to=recipient_email,
                    subject=item.get("subject", ""),
                    body_text=item.get("body", ""),
                )
                result = await gmail_client.send_email(gmail_message)

                if result.success:
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #status = :sent, sent_at = :now, email_message_id = :mid",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":sent": MessageStatus.SENT.value,
                            ":now": now.isoformat(),
                            ":mid": result.message_id,
                        },
                    )
                    succeeded += 1
                else:
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #status = :failed, retry_count = :rc, error_code = :err, sent_at = :now",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":rc": retry_count + 1,
                            ":err": result.error or "retry_failed",
                            ":now": now.isoformat(),
                        },
                    )
                    failed += 1
            except ValueError:
                # Gmail not configured
                logger.warning("Gmail not configured, skipping retry")
                break
            except Exception as e:
                failed += 1
                logger.error("Failed to retry email", extra={"error": str(e), "pk": item["pk"]})

    except Exception as e:
        logger.error("Email retry task failed", extra={"error": str(e)})

    result = {
        "task": "retry_failed_emails",
        "status": "completed",
        "retried": retried,
        "succeeded": succeeded,
        "failed": failed,
    }
    logger.info("Email retry task completed", extra=result)
    return result


async def cleanup_expired_data() -> dict:
    """Clean up expired data for GDPR compliance (FR-037).

    Handles:
    - Find COMPLETED events older than 90 days
    - Batch-delete associated registrations and messages
    """
    logger.info("Starting data cleanup task")

    from ..services.config import get_events_table, get_messages_table, get_registrations_table
    from boto3.dynamodb.conditions import Key as DKey

    retention_days = 90
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    events_deleted = 0
    registrations_deleted = 0
    messages_deleted = 0

    try:
        events_table = get_events_table()
        registrations_table = get_registrations_table()
        messages_table = get_messages_table()

        event_service = get_event_service()
        events = await event_service.get_events_by_status(EventStatus.COMPLETED)

        for event in events:
            # Only clean up events completed more than 90 days ago
            # Use start_at as proxy for completion time
            event_date = event.start_at
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)
            if event_date > cutoff:
                continue

            event_id = str(event.id)

            # Delete registrations for this event
            reg_response = registrations_table.query(
                KeyConditionExpression=DKey("pk").eq(f"EVENT#{event_id}"),
            )
            for item in reg_response.get("Items", []):
                registrations_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                registrations_deleted += 1

            # Handle pagination
            while "LastEvaluatedKey" in reg_response:
                reg_response = registrations_table.query(
                    KeyConditionExpression=DKey("pk").eq(f"EVENT#{event_id}"),
                    ExclusiveStartKey=reg_response["LastEvaluatedKey"],
                )
                for item in reg_response.get("Items", []):
                    registrations_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                    registrations_deleted += 1

            # Delete messages for this event
            msg_response = messages_table.query(
                KeyConditionExpression=DKey("pk").eq(f"EVENT#{event_id}"),
            )
            for item in msg_response.get("Items", []):
                messages_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                messages_deleted += 1

            while "LastEvaluatedKey" in msg_response:
                msg_response = messages_table.query(
                    KeyConditionExpression=DKey("pk").eq(f"EVENT#{event_id}"),
                    ExclusiveStartKey=msg_response["LastEvaluatedKey"],
                )
                for item in msg_response.get("Items", []):
                    messages_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                    messages_deleted += 1

            events_deleted += 1
            logger.info(
                "Cleaned up expired event data",
                extra={"event_id": event_id, "event_name": event.name},
            )

    except Exception as e:
        logger.error("Data cleanup task failed", extra={"error": str(e)})

    result = {
        "task": "cleanup_expired_data",
        "status": "completed",
        "events_processed": events_deleted,
        "registrations_deleted": registrations_deleted,
        "messages_deleted": messages_deleted,
    }
    logger.info("Data cleanup task completed", extra=result)
    return result


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
        result = asyncio.run(task_fn())
        logger.info(f"Task {task_name} completed", extra={"result": result})
        return result
    except Exception as e:
        logger.error(f"Task {task_name} failed", exc_info=True)
        return {"error": str(e), "task": task_name}
