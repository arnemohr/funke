"""Worker handler for scheduled tasks.

Handles EventBridge-triggered tasks:
- send_confirmation_reminders: Send confirmation requests to attendees
- retry_failed_emails: Retry failed email deliveries
- anonymize_expired_data: Pseudonymise finished events past the retention window
- expire_lost_and_found: Delete lost & found pages past their retention window
- expire_event_photos: Delete event photo collections past their retention window
"""

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import EventStatus, EventType, RegistrationStatus
from ..services.email_service import get_email_service
from ..services.event_photo_service import get_event_photo_service
from ..services.event_service import get_event_service
from ..services.logging import get_logger, set_request_id, setup_logging

# `event_finished_at` keeps the private name this module has always used for it.
# Every retention sweep below counts from the same instant, so the rule has one
# definition — and it sits in the service that also expires by it.
from ..services.lost_and_found_service import event_finished_at as _event_finished_at
from ..services.lost_and_found_service import get_lost_and_found_service
from ..services.registration_service import get_registration_service

# Initialize logging
setup_logging()
logger = get_logger(__name__)

# Left on the clock when a deadline-aware task is told to stop: enough to finish
# the write in flight, log, and return a summary instead of being timed out.
_DEADLINE_RESERVE = timedelta(seconds=20)


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

    # Festivals never sit in CONFIRMED with a nag-worthy registration —
    # festival registrations are created directly in PARTICIPATING and
    # never enter CONFIRMED (spec 019 §T110). Already inert; this guard
    # just documents the invariant explicitly (defense in depth).
    events = [e for e in events if e.event_type != EventType.FESTIVAL]

    now = datetime.now(timezone.utc)
    total_sent = 0
    total_failed = 0
    events_processed = 0
    logger.info(
        "Processing confirmation reminders"
    )

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

        today = now.date()

        for registration in registrations:
            # Only send to CONFIRMED registrations (not yet responded)
            # PARTICIPATING or CANCELLED means they already responded
            if registration.status != RegistrationStatus.CONFIRMED:
                continue

            # Skip if already reminded today
            if registration.last_reminder_sent_at:
                reminded_date = registration.last_reminder_sent_at
                if reminded_date.tzinfo is None:
                    reminded_date = reminded_date.replace(tzinfo=timezone.utc)
                if reminded_date.date() >= today:
                    continue

            try:
                success = await email_service.send_confirmation_request(
                    event, registration, days_until_event
                )
                if success:
                    # Stamp last_reminder_sent_at to prevent duplicate sends
                    await registration_service.update_reminder_sent(
                        registration.event_id, registration.id, now
                    )
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


# A 4xx SMTP reply is the server saying „not now", not „never". Strato answers
# `450 4.7.0 Transmit rate limit exceeded, try again later (ACC)` once a sender
# passes roughly 250 mails an hour — the message was never transmitted, and the
# only correct response is to wait. Minutes are not enough: on 2026-08-20 a
# batch of 850 lost 92 mails to this, all of them abandoned inside 15 minutes
# by a 1/2/4-minute backoff against an hour-long limit.
_THROTTLE_MARKERS = (
    "rate limit",
    "try again later",
    "too many",
    "4.7.0",
    "451",
    "450",
)

# Backoff for a throttled message, by how often it has been throttled already.
# Scaled to the hour that the limit actually lasts.
THROTTLE_BACKOFF_SECONDS = (20 * 60, 45 * 60, 90 * 60)

# A throttle does not count against `max_retries`, so it needs its own ceiling:
# after this long the send is abandoned rather than retried forever.
THROTTLE_GIVE_UP_SECONDS = 24 * 60 * 60


def is_throttle_error(error: str | None) -> bool:
    """Whether an SMTP error means „ask again later" rather than „undeliverable"."""
    if not error:
        return False
    lowered = error.lower()
    return any(marker in lowered for marker in _THROTTLE_MARKERS)


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
    import base64
    import random

    logger.info("Starting email queue processing")

    from ..models import MessageStatus
    from ..services.config import get_messages_table
    from ..services.email_client import EmailMessage as SmtpEmailMessage
    from ..services.email_client import InlineImage as SmtpInlineImage
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
                inline_images = [
                    SmtpInlineImage(
                        content_id=img["content_id"],
                        content=base64.b64decode(img["content_b64"]),
                        content_type=img.get("content_type", "image/png"),
                    )
                    for img in item.get("inline_images", [])
                ]
                email_msg = SmtpEmailMessage(
                    to=recipient,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    inline_images=inline_images,
                    list_unsubscribe=item.get("list_unsubscribe"),
                )
                result = await smtp_client.send_email(email_msg)

                send_time = datetime.now(timezone.utc)

                logger.info(
                    "SMTP send result",
                    extra={
                        "to": recipient,
                        "success": result.success,
                        "smtp_message_id": result.message_id,
                        "error": result.error,
                    },
                )

                if result.success:
                    if result.message_id:
                        messages_table.update_item(
                            Key={"pk": item["pk"], "sk": item["sk"]},
                            UpdateExpression=(
                                "SET #status = :sent, sent_at = :now, last_attempt_at = :now, "
                                "email_message_id = :mid"
                            ),
                            ExpressionAttributeNames={"#status": "status"},
                            ExpressionAttributeValues={
                                ":sent": MessageStatus.SENT.value,
                                ":now": send_time.isoformat(),
                                ":mid": result.message_id,
                            },
                        )
                    else:
                        messages_table.update_item(
                            Key={"pk": item["pk"], "sk": item["sk"]},
                            UpdateExpression="SET #status = :sent, sent_at = :now",
                            ExpressionAttributeNames={"#status": "status"},
                            ExpressionAttributeValues={
                                ":sent": MessageStatus.SENT.value,
                                ":now": send_time.isoformat(),
                            },
                        )
                        logger.warning(
                            "SMTP send succeeded but no Message-ID returned",
                            extra={"to": recipient, "subject": subject},
                        )
                    sent += 1
                    logger.info(
                        "Queued email sent",
                        extra={"to": recipient, "subject": subject, "index": i, "total": len(items)},
                    )
                else:
                    error_str = result.error or "send_failed"
                    is_throttled = is_throttle_error(error_str)

                    # A throttle increments `throttle_count`, a real failure
                    # `retry_count`. Mixing them is what abandoned 92 mails on
                    # 2026-08-20: three throttles looked like three dead
                    # addresses. `sent_at` stays untouched — nothing was sent.
                    counter = "throttle_count" if is_throttled else "retry_count"
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression=(
                            f"SET #status = :failed, error_code = :err, {counter} = :n, "
                            "last_attempt_at = :now"
                        ),
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":err": error_str,
                            ":n": item.get(counter, 0) + 1,
                            ":now": send_time.isoformat(),
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
                        UpdateExpression=(
                            "SET #status = :failed, error_code = :err, retry_count = :rc, "
                            "last_attempt_at = :now"
                        ),
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":err": str(e)[:200],
                            ":rc": item.get("retry_count", 0) + 1,
                            ":now": datetime.now(timezone.utc).isoformat(),
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

    import base64

    from ..models import MessageStatus
    from ..services.config import get_messages_table
    from ..services.email_client import EmailMessage as GmailEmailMessage
    from ..services.email_client import InlineImage as SmtpInlineImage
    from ..services.email_client import get_gmail_client

    max_retries = 3
    retried = 0
    succeeded = 0
    failed = 0
    task_status = "completed"

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
            # DynamoDB hands numbers back as `Decimal`, and a Decimal cannot
            # index THROTTLE_BACKOFF_SECONDS: from 2026-08-21 every run of this
            # task died on the first throttled row with "tuple indices must be
            # integers", took the whole batch with it, and still reported
            # "completed". Coerce at the boundary.
            retry_count = int(item.get("retry_count", 0))
            throttle_count = int(item.get("throttle_count", 0))
            was_throttled = is_throttle_error(item.get("error_code"))

            # A throttled message is not a failing message, so `max_retries`
            # does not apply to it — it gets its own ceiling below instead.
            if not was_throttled and retry_count >= max_retries:
                continue

            # `last_attempt_at` is the real answer; `sent_at` is the fallback for
            # rows written before the two were separated (it used to be stamped
            # on failures as well).
            last_attempt_raw = item.get("last_attempt_at") or item.get("sent_at")
            if last_attempt_raw:
                # One unparseable timestamp used to raise out of the loop and
                # abandon every remaining message in the batch — the same
                # all-or-nothing failure shape as the Decimal crash above.
                # A row we cannot read is a row we skip, not a batch we drop.
                try:
                    last_attempt = datetime.fromisoformat(last_attempt_raw)
                except (TypeError, ValueError):
                    logger.warning(
                        "Skipping a message with an unreadable last_attempt_at",
                        extra={"pk": item.get("pk"), "value": str(last_attempt_raw)[:40]},
                    )
                    failed += 1
                    continue
                if last_attempt.tzinfo is None:
                    last_attempt = last_attempt.replace(tzinfo=timezone.utc)

                if was_throttled:
                    index = min(throttle_count, len(THROTTLE_BACKOFF_SECONDS) - 1)
                    backoff_seconds = THROTTLE_BACKOFF_SECONDS[index]
                else:
                    backoff_seconds = 60 * (2 ** retry_count)  # 1min, 2min, 4min

                if (now - last_attempt).total_seconds() < backoff_seconds:
                    continue

            # Give up on a message that has been throttled for a day — the
            # limit is hourly, so at that point something else is wrong.
            if was_throttled:
                created_raw = item.get("created_at")
                if created_raw:
                    created = datetime.fromisoformat(created_raw)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (now - created).total_seconds() > THROTTLE_GIVE_UP_SECONDS:
                        logger.warning(
                            "Abandoning a message that has been throttled for a day",
                            extra={
                                "to": item.get("recipient_email"),
                                "throttle_count": throttle_count,
                            },
                        )
                        continue

            recipient_email = item.get("recipient_email")
            if not recipient_email:
                continue

            retried += 1

            try:
                gmail_client = get_gmail_client()
                retry_inline_images = [
                    SmtpInlineImage(
                        content_id=img["content_id"],
                        content=base64.b64decode(img["content_b64"]),
                        content_type=img.get("content_type", "image/png"),
                    )
                    for img in item.get("inline_images", [])
                ]
                gmail_message = GmailEmailMessage(
                    to=recipient_email,
                    subject=item.get("subject", ""),
                    body_text=item.get("body", ""),
                    body_html=item.get("body_html"),
                    inline_images=retry_inline_images,
                    list_unsubscribe=item.get("list_unsubscribe"),
                )
                result = await gmail_client.send_email(gmail_message)

                if result.success:
                    if result.message_id:
                        messages_table.update_item(
                            Key={"pk": item["pk"], "sk": item["sk"]},
                            UpdateExpression=(
                                "SET #status = :sent, sent_at = :now, last_attempt_at = :now, "
                                "email_message_id = :mid"
                            ),
                            ExpressionAttributeNames={"#status": "status"},
                            ExpressionAttributeValues={
                                ":sent": MessageStatus.SENT.value,
                                ":now": now.isoformat(),
                                ":mid": result.message_id,
                            },
                        )
                    else:
                        messages_table.update_item(
                            Key={"pk": item["pk"], "sk": item["sk"]},
                            UpdateExpression="SET #status = :sent, sent_at = :now",
                            ExpressionAttributeNames={"#status": "status"},
                            ExpressionAttributeValues={
                                ":sent": MessageStatus.SENT.value,
                                ":now": now.isoformat(),
                            },
                        )
                    succeeded += 1
                else:
                    error_str = result.error or "retry_failed"
                    # Same split as the send path, and `sent_at` stays out of it:
                    # a retry that failed did not send anything either.
                    throttled = is_throttle_error(error_str)
                    counter = "throttle_count" if throttled else "retry_count"
                    next_count = (throttle_count if throttled else retry_count) + 1
                    messages_table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression=(
                            f"SET #status = :failed, {counter} = :n, error_code = :err, "
                            "last_attempt_at = :now"
                        ),
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":failed": MessageStatus.FAILED.value,
                            ":n": next_count,
                            ":err": error_str,
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
        task_status = "failed"

    result = {
        "task": "retry_failed_emails",
        "status": task_status,
        "retried": retried,
        "succeeded": succeeded,
        "failed": failed,
    }
    logger.info("Email retry task completed", extra=result)
    return result


async def anonymize_expired_data(deadline: datetime | None = None) -> dict:
    """Pseudonymise finished events past the retention window (FR-037).

    Replaces the old `cleanup_expired_data`, which hard-deleted registrations
    and messages for COMPLETED events 90 days after `start_at`. That threw away
    the aggregate history — headcounts, tier splits, check-in totals — along
    with the personal data, and it never touched invites or gate-log rows, so
    names survived in two places the sweep did not know about.

    This one calls `AnonymizationService.anonymize_event` instead: every row
    stays, every personal field becomes a stable pseudonym, and the invite and
    scan rows are covered too. The two exceptions are the event's lost & found
    page (spec 023) and its photo collection (spec 024), which are deleted
    rather than pseudonymised — a photo of a stranger's jacket has no pseudonym,
    and neither has a guest's face.

    CANCELLED events are swept as well as COMPLETED ones — a cancelled event
    still holds every address that was collected before it fell through, and
    nothing else would ever clean it up. Each is measured from when it actually
    finished: `cancelled_at` for a cancellation, `end_at` (festivals) or
    `start_at` (single events) otherwise.

    Args:
        deadline: when to stop and leave the rest for the next run. The handler
            derives it from the Lambda's remaining time, so a backlog of large
            festivals drains over several nights instead of being killed
            mid-event on the first. Unfinished events keep `anonymized_at`
            unset, and a resumed run skips the rows already scrubbed.
    """
    logger.info("Starting anonymization sweep")

    from ..services.anonymization_service import (
        ANONYMIZABLE_STATUSES,
        get_anonymization_service,
    )
    from ..services.config import get_settings

    retention_days = get_settings().anonymization_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    events_anonymized = 0
    events_skipped = 0
    events_unfinished: list[str] = []
    registrations = 0
    scans = 0
    invites = 0
    messages = 0
    lost_and_found_photos = 0
    lost_and_found_failures: list[str] = []
    event_photos = 0
    event_photo_failures: list[str] = []
    failures: list[str] = []

    try:
        event_service = get_event_service()
        anonymization_service = get_anonymization_service()

        candidates: list = []
        for status in sorted(ANONYMIZABLE_STATUSES, key=lambda s: s.value):
            candidates.extend(await event_service.get_events_by_status(status))

        for event in candidates:
            if event.is_anonymized:
                continue

            finished_at = _event_finished_at(event)
            if finished_at > cutoff:
                events_skipped += 1
                continue

            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                # Out of Lambda time. Everything still owed is reported, and
                # tomorrow's run starts with it.
                events_unfinished.append(str(event.id))
                continue

            try:
                result = await anonymization_service.anonymize_event(
                    event,
                    deadline=deadline,
                )
            except Exception as e:
                # One bad event must not stop the sweep — the next daily run
                # retries it, and `anonymized_at` is only stamped on success.
                failures.append(str(event.id))
                logger.error(
                    "Anonymization failed for event",
                    extra={"event_id": str(event.id), "error": str(e)},
                )
                continue

            if result.already_anonymized:
                continue

            registrations += result.registrations
            scans += result.scans
            invites += result.invites
            messages += result.messages
            lost_and_found_photos += result.lost_and_found_photos
            if result.lost_and_found_failed:
                # The event may still have been stamped: a page that refuses to
                # go is left for `expire_lost_and_found` rather than blocking the
                # scrub. Reported so it is visible in the run's log.
                lost_and_found_failures.append(str(event.id))
            event_photos += result.event_photos
            if result.event_photos_failed:
                # Same deal for the photo collection (spec 024): a collection
                # whose objects refused to go is left for `expire_event_photos`.
                # Counted separately from the lost & found pair because the two
                # live in different buckets, and „which one is stuck" is the
                # first question anyone reading this log will ask.
                event_photo_failures.append(str(event.id))

            if not result.completed:
                # Partially scrubbed: the rows it got are done for good, the
                # event stays a candidate until a later run finishes it.
                events_unfinished.append(str(event.id))
                logger.info(
                    "Anonymization of event is unfinished, resuming next run",
                    extra={
                        "event_id": str(event.id),
                        "rows_touched": result.rows_touched,
                    },
                )
                continue

            events_anonymized += 1

            logger.info(
                "Anonymized expired event",
                extra={
                    "event_id": str(event.id),
                    "event_name": event.name,
                    "finished_at": finished_at.isoformat(),
                    "rows_touched": result.rows_touched,
                },
            )

    except Exception as e:
        logger.error("Anonymization sweep failed", extra={"error": str(e)})

    result_summary = {
        "task": "anonymize_expired_data",
        "status": "completed",
        "retention_days": retention_days,
        "events_anonymized": events_anonymized,
        "events_within_retention": events_skipped,
        "events_unfinished": events_unfinished,
        "registrations_anonymized": registrations,
        "scans_anonymized": scans,
        "invites_anonymized": invites,
        "messages_anonymized": messages,
        "lost_and_found_photos_deleted": lost_and_found_photos,
        "lost_and_found_failed_event_ids": lost_and_found_failures,
        "event_photos_deleted": event_photos,
        "event_photos_failed_event_ids": event_photo_failures,
        "failed_event_ids": failures,
    }
    logger.info("Anonymization sweep completed", extra=result_summary)
    return result_summary


async def expire_lost_and_found(deadline: datetime | None = None) -> dict:
    """Delete Fundsachen pages past their retention window (spec 023).

    A lost & found page is a public gallery of other people's belongings, so it
    is on a clock: `LOST_AND_FOUND_RETENTION_DAYS` (default 90, overridable per
    page between 7 and 365) counted from when the event actually finished. Past
    that, the config row, every photo row and every S3 object go. Pages whose
    event has vanished or has already been anonymised go too — nothing else
    would ever expire them.

    `expire_pages` also prunes the leftovers of aborted uploads (PENDING rows
    older than 24 h) on the pages it keeps; the pages it deletes take theirs
    with them. That is why this task is a single call and not two: a separate
    `prune_pending()` would re-scan the whole table to find nothing.

    Args:
        deadline: when to stop and leave the rest for tomorrow, derived by the
            handler from the Lambda's remaining time. A page whose deletion is
            cut short keeps its config row, so the next run finds it again —
            same resumability contract as the anonymisation sweep.
    """
    logger.info("Starting lost & found expiry sweep")

    try:
        sweep = await get_lost_and_found_service().expire_pages(deadline=deadline)
    except Exception as e:
        # Nothing here is urgent enough to be worth an alarming exit: the pages
        # are still there tomorrow, and the bucket's 400-day lifecycle rule is
        # the backstop if this sweep ever stops running for good.
        logger.error("Lost & found expiry sweep failed", extra={"error": str(e)})
        return {"task": "expire_lost_and_found", "status": "failed", "error": str(e)}

    result = {
        "task": "expire_lost_and_found",
        "status": "completed",
        "pages_checked": sweep["pages_checked"],
        "pages_deleted": sweep["pages_deleted"],
        "photos_deleted": sweep["deleted_photos"],
        "pending_pruned": sweep["pending_pruned"],
        # Rows whose page no longer exists — invisible to every other path, so
        # a non-zero count here is worth noticing rather than only counting.
        "orphan_photos_deleted": sweep["orphan_photos_deleted"],
        "pages_unfinished": sweep["unfinished"],
        # Pages whose own sweep raised. Each one is isolated so the rest of the
        # run continues, which only helps if the failure is still visible.
        "pages_failed": sweep["failed"],
        # `status` says the task ran; this says whether it got all the way
        # through — deadline, a failed page, or a scan that could not be read.
        "swept_completely": sweep["completed"],
    }
    logger.info("Lost & found expiry task completed", extra=result)
    return result


async def expire_event_photos(deadline: datetime | None = None) -> dict:
    """Delete event photo collections past their retention window (spec 024).

    A collection is an Umschlagstelle, not an archive: guests hand in photos of
    each other, and keeping those in our bucket for years is a liability with
    no matching benefit. `EVENT_PHOTO_RETENTION_DAYS` (default 90, overridable
    per collection between 7 and 365) counts from the later of the event
    finishing and the collection being created — the same anchor and the same
    helper as spec 023, so a collection opened weeks after the event is not
    swept the night it appears.

    One call for the three duties in spec 024 § Aufbewahrung, because
    `expire_collections` already performs all three: it deletes the collections
    past their window, prunes the aborted uploads (PENDING rows older than 24 h)
    of the ones it keeps — the ones it deletes take theirs along — and mops up
    the hourly `PHOTOS#QUOTA#` rows the table's TTL has not got to yet. Calling
    `prune_pending()` or `prune_quota_rows()` again from here would re-scan the
    whole table to find nothing, which is why `expire_lost_and_found` is a
    single call too.

    Of the three, the PENDING prune is the one that hurts soonest if it stops:
    those rows hold reservations against `MAX_PHOTOS`, so a collection whose
    guests kept retrying over a festival's WLAN would report itself full at a
    few hundred actual photos.

    Args:
        deadline: when to stop and leave the rest for tomorrow, derived by the
            handler from the Lambda's remaining time. A collection whose
            deletion is cut short keeps its config row, so the next run finds
            it again — the same resumability contract as the anonymisation
            sweep and spec 023's page expiry.
    """
    logger.info("Starting event photo expiry sweep")

    try:
        sweep = await get_event_photo_service().expire_collections(deadline=deadline)
    except Exception as e:
        # Same judgement as the Fundsachen sweep: nothing in here is urgent
        # enough to be worth an alarming exit. The collections are still there
        # tomorrow, and the bucket's 400-day lifecycle rule is the backstop if
        # this sweep ever stops running for good.
        logger.error("Event photo expiry sweep failed", extra={"error": str(e)})
        return {"task": "expire_event_photos", "status": "failed", "error": str(e)}

    result = {
        "task": "expire_event_photos",
        "status": "completed",
        "collections_checked": sweep["collections_checked"],
        "collections_deleted": sweep["collections_deleted"],
        "photos_deleted": sweep["deleted_photos"],
        "pending_pruned": sweep["pending_pruned"],
        # Belt to the table's own TTL, so a count that stays high says the TTL
        # is lagging — worth seeing rather than merely counted.
        "quota_rows_pruned": sweep["quota_rows_pruned"],
        "collections_unfinished": sweep["unfinished"],
        # Collections whose own sweep raised. Each is isolated so the rest of
        # the run continues, which only helps if the failure stays visible.
        "collections_failed": sweep["failed"],
        # `status` says the task ran; this says whether it got all the way
        # through — deadline, a failed collection, or a scan that could not be
        # read.
        "swept_completely": sweep["completed"],
    }
    logger.info("Event photo expiry task completed", extra=result)
    return result


def _invocation_deadline(context: Any) -> datetime | None:
    """When a long task must stop, from the Lambda's own remaining time.

    Reserves `_DEADLINE_RESERVE` for finishing the current chunk, logging and
    returning the summary — the point of the deadline is a clean stop with a
    reported result, which a hard timeout would not give us. Returns None
    outside Lambda (local runs, tests), where the task may run to completion.
    """
    remaining_ms = getattr(context, "get_remaining_time_in_millis", None)
    if not callable(remaining_ms):
        return None
    try:
        remaining = timedelta(milliseconds=remaining_ms())
    except Exception:  # pragma: no cover - defensive, context is AWS-provided
        return None
    return datetime.now(timezone.utc) + max(remaining - _DEADLINE_RESERVE, timedelta(0))


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
        "anonymize_expired_data": anonymize_expired_data,
        "expire_lost_and_found": expire_lost_and_found,
        "expire_event_photos": expire_event_photos,
        # Legacy alias: the deployed EventBridge rule still fires this name
        # until the scheduler stack rolls out. Keeping it mapped means the
        # Lambda and the rule can be deployed in either order without a day of
        # "Unknown task" errors — and it now anonymises rather than deletes,
        # so the old name can never resurrect the old destructive behaviour.
        "cleanup_expired_data": anonymize_expired_data,
    }

    task_fn = tasks.get(task_name)
    if not task_fn:
        logger.error(f"Unknown task: {task_name}")
        return {"error": f"Unknown task: {task_name}"}

    # Tasks that can outlive one invocation take a `deadline` and stop there
    # instead of being killed mid-write. Passed by signature so the other tasks
    # stay zero-argument.
    kwargs = {}
    if "deadline" in inspect.signature(task_fn).parameters:
        kwargs["deadline"] = _invocation_deadline(context)

    try:
        result = asyncio.run(task_fn(**kwargs))
        logger.info(f"Task {task_name} completed", extra={"result": result})
        return result
    except Exception as e:
        logger.error(f"Task {task_name} failed", exc_info=True)
        return {"error": str(e), "task": task_name}
