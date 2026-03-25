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


async def process_email_queue() -> dict:
    """Process queued emails with pacing to protect deliverability.

    Sends one email at a time with a random 4-10 second delay between sends.
    This keeps us well under typical SMTP provider limits (~30 emails/min).

    Uses claim-before-send: each message is atomically transitioned from
    QUEUED → SENDING before the SMTP call. This prevents duplicate sends
    if two worker invocations overlap.

    Processes a fixed batch per invocation (max 20) to stay within Lambda
    timeout limits. The scheduler should run every 1-2 minutes to drain
    the queue steadily.
    """
    import asyncio
    import random

    logger.info("Starting email queue processing")

    from ..models import MessageStatus
    from ..services.config import get_messages_table
    from ..services.email_client import EmailMessage as SmtpEmailMessage
    from ..services.email_client import get_gmail_client

    MAX_BATCH = 20  # Stay well within Lambda timeout (~3-4 min at 10s spacing)
    sent = 0
    failed = 0
    skipped = 0
    smtp_not_configured = False

    try:
        messages_table = get_messages_table()

        # Check SMTP availability once upfront
        smtp_client = get_gmail_client()
        try:
            # send_email raises ValueError if credentials are missing,
            # so validate by checking settings directly
            from ..services.email_client import get_email_settings

            settings = get_email_settings()
            if not all([settings.smtp_username, settings.smtp_password, settings.smtp_sender_email]):
                raise ValueError("SMTP credentials not configured")
        except ValueError:
            smtp_not_configured = True
            smtp_client = None
            logger.info("SMTP not configured — will mark emails as sent (dev mode)")

        # Scan for QUEUED messages
        scan_kwargs = {
            "FilterExpression": "#status = :queued",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":queued": MessageStatus.QUEUED.value},
        }

        response = messages_table.scan(**scan_kwargs)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = messages_table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))

        if not items:
            logger.info("No queued emails to process")
            return {"task": "process_email_queue", "status": "completed", "sent": 0, "failed": 0, "skipped": 0}

        # Sort by created_at to send in FIFO order, take only MAX_BATCH
        items.sort(key=lambda x: x.get("created_at", ""))
        items = items[:MAX_BATCH]

        logger.info(f"Processing {len(items)} queued emails")

        now = datetime.now(timezone.utc)

        for i, item in enumerate(items):
            recipient = item.get("recipient_email")
            subject = item.get("subject", "")
            body_text = item.get("body", "")
            body_html = item.get("body_html")

            if not recipient:
                skipped += 1
                continue

            # Claim: atomically transition QUEUED → SENDING to prevent duplicates
            try:
                messages_table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #status = :sending",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":sending": "sending",
                        ":queued": MessageStatus.QUEUED.value,
                    },
                    ConditionExpression="#status = :queued",
                )
            except Exception:
                # Another worker already claimed this message
                skipped += 1
                continue

            if smtp_not_configured:
                # Dev mode: mark as sent without sending
                logger.info(f"[LOG-ONLY] queued email to {recipient} (SMTP not configured)")
                messages_table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #status = :sent, sent_at = :now",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":sent": MessageStatus.SENT.value,
                        ":now": now.isoformat(),
                    },
                )
                sent += 1
                continue

            try:
                email_msg = SmtpEmailMessage(
                    to=recipient,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                )
                result = await smtp_client.send_email(email_msg)

                send_time = datetime.now(timezone.utc)

                if result.success:
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #status = :sent, sent_at = :now, email_message_id = :mid",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":sent": MessageStatus.SENT.value,
                            ":now": send_time.isoformat(),
                            ":mid": result.message_id,
                        },
                    )
                    sent += 1
                    logger.info(
                        "Queued email sent",
                        extra={"to": recipient, "subject": subject, "index": i, "total": len(items)},
                    )
                else:
                    error_str = result.error or "send_failed"
                    is_throttled = "4." in error_str or "try again" in error_str.lower()

                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #status = :failed, error_code = :err, retry_count = :rc",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":err": error_str,
                            ":rc": item.get("retry_count", 0) + 1,
                        },
                    )
                    failed += 1

                    if is_throttled:
                        logger.warning(
                            "SMTP throttling detected, stopping batch — remaining emails will be picked up next run",
                            extra={"error": error_str, "to": recipient},
                        )
                        break  # Stop this batch, let the next invocation continue

            except Exception as e:
                # Unexpected error: mark as FAILED so retry worker can pick it up
                logger.error("Failed to process queued email", extra={"error": str(e), "to": recipient})
                try:
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #status = :failed, error_code = :err, retry_count = :rc",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":err": str(e)[:200],
                            ":rc": item.get("retry_count", 0) + 1,
                        },
                    )
                except Exception:
                    pass  # Best effort
                failed += 1

            # Pace: random 4-10 second delay between sends (skip after last)
            if i < len(items) - 1:
                delay = random.uniform(4.0, 10.0)
                await asyncio.sleep(delay)

    except Exception as e:
        logger.error("Email queue processing failed", extra={"error": str(e)})

    result = {
        "task": "process_email_queue",
        "status": "completed",
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info("Email queue processing completed", extra=result)
    return result


async def recover_stale_sending() -> dict:
    """Recover messages stuck in 'sending' status.

    If a worker dies mid-send, messages stay in 'sending' forever.
    This task resets them to QUEUED so the queue worker picks them up again.
    Only resets messages that have been in 'sending' for more than 5 minutes.
    """
    logger.info("Starting stale sending recovery")

    from ..models import MessageStatus
    from ..services.config import get_messages_table

    recovered = 0

    try:
        messages_table = get_messages_table()

        response = messages_table.scan(
            FilterExpression="#status = :sending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":sending": "sending"},
        )
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = messages_table.scan(
                FilterExpression="#status = :sending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":sending": "sending"},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        now = datetime.now(timezone.utc)
        stale_threshold = timedelta(minutes=5)

        for item in items:
            created_at_str = item.get("created_at")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if (now - created_at) < stale_threshold:
                    continue  # Not stale yet, worker may still be processing

            try:
                messages_table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #status = :queued",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":queued": MessageStatus.QUEUED.value},
                    ConditionExpression="#status = :sending",
                )
                recovered += 1
            except Exception:
                pass

    except Exception as e:
        logger.error("Stale sending recovery failed", extra={"error": str(e)})

    result = {"task": "recover_stale_sending", "status": "completed", "recovered": recovered}
    logger.info("Stale sending recovery completed", extra=result)
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
        "process_email_queue": process_email_queue,
        "recover_stale_sending": recover_stale_sending,
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
