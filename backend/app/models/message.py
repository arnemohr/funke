"""Message domain model and schemas.

Represents email communications with threading support,
delivery status tracking, and retry handling.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MessageType(str, Enum):
    """Type of message."""

    REGISTRATION_CONFIRMATION = "registration_confirmation"
    WAITLIST_NOTIFICATION = "waitlist_notification"
    LOTTERY_RESULT = "lottery_result"
    REMINDER = "reminder"
    CONFIRMATION_REQUEST = "confirmation_request"
    CANCELLATION = "cancellation"
    CUSTOM = "custom"
    FESTIVAL_INVITATION = "festival_invitation"
    FESTIVAL_CONFIRMATION = "festival_confirmation"
    FESTIVAL_UPDATE = "festival_update"
    FESTIVAL_CANCELLATION = "festival_cancellation"
    # Spec 020 — one mail per companion who supplied an address: F5 carries
    # only that person's QR, F6 tells them their code died with the group's
    # cancellation.
    FESTIVAL_COMPANION_TICKET = "festival_companion_ticket"
    FESTIVAL_COMPANION_CANCELLATION = "festival_companion_cancellation"
    # F8 — the overnight wish was granted. Sent once per approval to the
    # person who registered (never to companions), tracked by
    # `Registration.overnight_notified_at`.
    FESTIVAL_OVERNIGHT_APPROVAL = "festival_overnight_approval"
    # F9 — the overnight wish could not be granted. Sent once per refusal,
    # tracked by `Registration.overnight_declined_at`.
    FESTIVAL_OVERNIGHT_DECLINE = "festival_overnight_decline"


class MessageDirection(str, Enum):
    """Direction of message."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"


class MessageStatus(str, Enum):
    """Delivery status of message."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    RECEIVED = "received"


class MessageCreate(BaseModel):
    """Schema for creating a message."""

    registration_id: UUID | None = None
    type: MessageType
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=50000)
    in_reply_to: str | None = None  # Parent message ID for threading


class InlineImageData(BaseModel):
    """A queued email's inline (Content-ID referenced) image, e.g. a QR code.

    Content is base64-encoded for DynamoDB round-tripping through the
    message queue — decoded back to bytes only at actual SMTP send time.
    """

    content_id: str
    content_b64: str
    content_type: str = "image/png"


class Message(BaseModel):
    """Full message model with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    registration_id: UUID | None = None
    type: MessageType
    direction: MessageDirection = MessageDirection.OUTBOUND
    subject: str
    body: str
    body_html: str | None = None  # HTML version for queued sending
    inline_images: list[InlineImageData] = Field(default_factory=list)
    list_unsubscribe: str | None = None  # RFC 2369 List-Unsubscribe value (bulk mail only)
    email_message_id: str | None = None  # RFC 822 Message-ID
    in_reply_to: str | None = None  # Parent Message-ID
    status: MessageStatus = MessageStatus.QUEUED
    retry_count: int = 0
    sent_at: datetime | None = None
    received_at: datetime | None = None
    recipient_email: str | None = None
    error_code: str | None = None
    ttl: int | None = None  # DynamoDB TTL timestamp
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_sent(self, email_message_id: str) -> "Message":
        """Mark message as sent."""
        return self.model_copy(
            update={
                "status": MessageStatus.SENT,
                "email_message_id": email_message_id,
                "sent_at": datetime.now(timezone.utc),
            },
        )

    def mark_failed(self, error_code: str) -> "Message":
        """Mark message as failed."""
        return self.model_copy(
            update={
                "status": MessageStatus.FAILED,
                "error_code": error_code,
                "retry_count": self.retry_count + 1,
            },
        )

    def can_retry(self, max_retries: int = 3) -> bool:
        """Check if message can be retried."""
        return (
            self.status == MessageStatus.FAILED
            and self.retry_count < max_retries
        )

    def reset_for_retry(self) -> "Message":
        """Reset status for retry."""
        if not self.can_retry():
            raise ValueError("Message cannot be retried")
        return self.model_copy(update={"status": MessageStatus.QUEUED})


class CustomMessageRequest(BaseModel):
    """Request to send a custom message to registrations."""

    registration_ids: list[UUID]
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=50000)
    include_links: bool = False
    # Spec 020 — also mail every companion who supplied an address. Default ON:
    # the whole point of collecting those addresses is that the Orga-Rundmail
    # reaches them. Their copy carries the read-only ticket link, never the
    # group's manage link.
    include_companions: bool = True
