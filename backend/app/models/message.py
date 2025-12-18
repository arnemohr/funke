"""Message domain model and schemas.

Represents email communications with threading support,
delivery status tracking, and retry handling.
"""

from datetime import datetime
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
    email_message_id: str | None = None  # RFC 822 Message-ID
    in_reply_to: str | None = None  # Parent Message-ID
    status: MessageStatus = MessageStatus.QUEUED
    retry_count: int = 0
    sent_at: datetime | None = None
    received_at: datetime | None = None
    error_code: str | None = None
    ttl: int | None = None  # DynamoDB TTL timestamp
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def mark_sent(self, email_message_id: str) -> "Message":
        """Mark message as sent."""
        return self.model_copy(
            update={
                "status": MessageStatus.SENT,
                "email_message_id": email_message_id,
                "sent_at": datetime.utcnow(),
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
