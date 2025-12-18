"""Lottery run domain model and schemas.

Represents lottery executions with seed storage for
deterministic replay and audit compliance.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class LotteryRun(BaseModel):
    """Full lottery run model with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    executed_by_admin_id: UUID
    seed: str  # Hex-encoded seed for reproducibility
    shuffled_order: list[str]  # Registration IDs in shuffled order
    winners: list[str]  # Registration IDs of winners
    waitlist: list[str]  # Registration IDs of waitlisted (ordered)
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    finalized_at: datetime | None = None
    finalization_by_admin_id: UUID | None = None
    ttl: int | None = None  # DynamoDB TTL timestamp

    @property
    def is_finalized(self) -> bool:
        """Check if lottery has been finalized."""
        return self.finalized_at is not None

    def finalize(self, admin_id: UUID) -> "LotteryRun":
        """Finalize the lottery run.

        Raises:
            ValueError: If already finalized.
        """
        if self.is_finalized:
            raise ValueError("Lottery has already been finalized")
        return self.model_copy(
            update={
                "finalized_at": datetime.utcnow(),
                "finalization_by_admin_id": admin_id,
            },
        )


class LotteryResult(BaseModel):
    """Lottery result response for API."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    seed: str
    winners: list[dict]  # Registration data for winners
    waitlist: list[dict]  # Registration data for waitlist
    is_finalized: bool
    executed_at: datetime
    finalized_at: datetime | None
