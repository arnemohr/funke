"""Lottery service for fair selection of attendees on overbooked events.

Provides:
- Cryptographically-seeded shuffle with deterministic replay
- Lottery run storage for audit
- Finalization that updates registration statuses and waitlist positions
- Helpers to fetch latest lottery result for review
"""

import random
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from ..models import Event, EventStatus, LotteryResult, LotteryRun, Registration, RegistrationStatus
from .config import get_lottery_runs_table
from .email_service import get_email_service
from .event_service import get_event_service
from .logging import get_logger
from .registration_service import get_registration_service

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _lottery_run_to_item(run: LotteryRun) -> dict:
    """Convert LotteryRun model to DynamoDB item."""
    item = {
        "pk": f"EVENT#{run.event_id}",
        "sk": f"LOTTERY#{run.id}",
        "id": str(run.id),
        "event_id": str(run.event_id),
        "executed_by_admin_id": str(run.executed_by_admin_id),
        "seed": run.seed,
        "shuffled_order": run.shuffled_order,
        "winners": run.winners,
        "waitlist": run.waitlist,
        "executed_at": run.executed_at.isoformat(),
        "entity_type": "LotteryRun",
    }

    if run.finalized_at:
        item["finalized_at"] = run.finalized_at.isoformat()

    if run.finalization_by_admin_id:
        item["finalization_by_admin_id"] = str(run.finalization_by_admin_id)

    if run.ttl:
        item["ttl"] = run.ttl

    return item


def _item_to_lottery_run(item: dict) -> LotteryRun:
    """Convert DynamoDB item to LotteryRun model."""
    return LotteryRun(
        id=UUID(item["id"]),
        event_id=UUID(item["event_id"]),
        executed_by_admin_id=UUID(item["executed_by_admin_id"]),
        seed=item["seed"],
        shuffled_order=item.get("shuffled_order", []),
        winners=item.get("winners", []),
        waitlist=item.get("waitlist", []),
        executed_at=datetime.fromisoformat(item["executed_at"]),
        finalized_at=datetime.fromisoformat(item["finalized_at"]) if item.get("finalized_at") else None,
        finalization_by_admin_id=UUID(item["finalization_by_admin_id"])
        if item.get("finalization_by_admin_id")
        else None,
        ttl=item.get("ttl"),
    )


def _serialize_registration(registration: Registration) -> dict:
    """Serialize registration for API response."""
    return {
        "id": str(registration.id),
        "event_id": str(registration.event_id),
        "name": registration.name,
        "email": registration.email,
        "group_size": registration.group_size,
        "status": registration.status.value,
        "waitlist_position": registration.waitlist_position,
        "registered_at": registration.registered_at.isoformat(),
        "responded_at": registration.responded_at.isoformat()
        if registration.responded_at
        else None,
    }


class LotteryService:
    """Service handling lottery execution and finalization."""

    def __init__(self):
        self._table = None
        self.registration_service = get_registration_service()
        self.event_service = get_event_service()
        self.email_service = get_email_service()

    @property
    def table(self) -> "Table":
        """Get the lottery runs table (lazy initialization)."""
        if self._table is None:
            self._table = get_lottery_runs_table()
        return self._table

    async def get_latest_run(self, event_id: UUID) -> LotteryRun | None:
        """Get the most recent lottery run for an event."""
        try:
            response = self.table.query(
                IndexName="event-index",
                KeyConditionExpression="event_id = :event_id",
                ExpressionAttributeValues={":event_id": str(event_id)},
                ScanIndexForward=False,  # latest first
                Limit=1,
            )
            items = response.get("Items", [])
            if not items:
                return None
            return _item_to_lottery_run(items[0])
        except ClientError as e:
            logger.error("Failed to fetch latest lottery run", extra={"error": str(e)})
            return None

    async def run_lottery(
        self,
        org_id: UUID,
        event_id: UUID,
        admin_id: UUID,
    ) -> LotteryResult:
        """Execute lottery shuffle for an event."""
        event = await self.event_service.get_event(org_id, event_id)
        if not event:
            raise ValueError("Event not found")

        if event.status not in [EventStatus.REGISTRATION_CLOSED, EventStatus.LOTTERY_PENDING]:
            raise ValueError("Lottery can only run after registration is closed")

        existing_run = await self.get_latest_run(event_id)
        if existing_run and existing_run.is_finalized:
            raise ValueError("Lottery already finalized for this event")

        registrations = await self.registration_service.list_registrations(event_id)
        candidates = [
            r
            for r in registrations
            if r.status in (
                RegistrationStatus.REGISTERED,
                RegistrationStatus.WAITLISTED,
            )
        ]

        if not candidates:
            raise ValueError("No eligible registrations available for lottery")

        # Deterministic but high-entropy seed for reproducible shuffle
        seed = secrets.token_hex(32)
        rng = random.Random(seed)

        ordered = sorted(
            candidates,
            key=lambda r: (r.registered_at, str(r.id)),
        )
        rng.shuffle(ordered)

        winners: list[Registration] = []
        waitlist: list[Registration] = []
        remaining_capacity = event.capacity

        for registration in ordered:
            if registration.group_size <= remaining_capacity:
                winners.append(registration)
                remaining_capacity -= registration.group_size
            else:
                waitlist.append(registration)

        run = LotteryRun(
            id=uuid4(),
            event_id=event_id,
            executed_by_admin_id=admin_id,
            seed=seed,
            shuffled_order=[str(r.id) for r in ordered],
            winners=[str(r.id) for r in winners],
            waitlist=[str(r.id) for r in waitlist],
            executed_at=datetime.now(timezone.utc),
        )

        try:
            self.table.put_item(
                Item=_lottery_run_to_item(run),
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
        except ClientError as e:
            logger.error("Failed to store lottery run", extra={"error": str(e)})
            raise

        # Move event into LOTTERY_PENDING to reflect pending finalization
        await self.event_service.mark_lottery_pending(org_id, event_id)

        registrations_by_id = {str(r.id): r for r in registrations}
        return self._build_result(run, registrations_by_id)

    async def get_result(self, event_id: UUID) -> LotteryResult | None:
        """Fetch the latest lottery result for review."""
        run = await self.get_latest_run(event_id)
        if not run:
            return None

        registrations = await self.registration_service.list_registrations(event_id)
        registrations_by_id = {str(r.id): r for r in registrations}
        return self._build_result(run, registrations_by_id)

    async def finalize_lottery(
        self,
        org_id: UUID,
        event_id: UUID,
        admin_id: UUID,
    ) -> LotteryResult:
        """Finalize lottery results, update registrations, and send notifications."""
        run = await self.get_latest_run(event_id)
        if not run:
            raise ValueError("No lottery run found")

        if run.is_finalized:
            result = await self.get_result(event_id)
            if result:
                return result
            raise ValueError("Lottery already finalized")

        event = await self.event_service.get_event(org_id, event_id)
        if not event:
            raise ValueError("Event not found")

        if event.status not in [EventStatus.LOTTERY_PENDING, EventStatus.REGISTRATION_CLOSED]:
            raise ValueError("Lottery can only be finalized after it has been run")

        registrations = await self.registration_service.list_registrations(event_id)
        registrations_by_id: dict[str, Registration] = {str(r.id): r for r in registrations}

        winners: list[Registration] = []
        losers: list[Registration] = []

        # Update winners -> CONFIRMED
        for reg_id in run.winners:
            reg = registrations_by_id.get(reg_id)
            if not reg or reg.status == RegistrationStatus.CANCELLED:
                continue

            try:
                self.registration_service.registrations_table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"REG#{reg.id}",
                    },
                    UpdateExpression="SET #status = :status, waitlist_position = :null, promoted_from_waitlist = :false",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":status": RegistrationStatus.CONFIRMED.value,
                        ":null": None,
                        ":false": False,
                    },
                )
                updated = reg.model_copy(
                    update={
                        "status": RegistrationStatus.CONFIRMED,
                        "waitlist_position": None,
                        "promoted_from_waitlist": False,
                    },
                )
                registrations_by_id[reg_id] = updated
                winners.append(updated)
            except ClientError as e:
                logger.error("Failed to update winner", extra={"registration_id": reg_id, "error": str(e)})

        # Update losers -> WAITLISTED (if autopromote) or CANCELLED
        loser_status = RegistrationStatus.WAITLISTED if event.autopromote_waitlist else RegistrationStatus.CANCELLED

        for position, reg_id in enumerate(run.waitlist, start=1):
            reg = registrations_by_id.get(reg_id)
            if not reg or reg.status == RegistrationStatus.CANCELLED:
                continue

            try:
                update_expr = "SET #status = :status"
                expr_values = {":status": loser_status.value}

                # Only set waitlist_position if going to WAITLISTED
                if loser_status == RegistrationStatus.WAITLISTED:
                    update_expr += ", waitlist_position = :pos"
                    expr_values[":pos"] = position

                self.registration_service.registrations_table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"REG#{reg.id}",
                    },
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues=expr_values,
                )

                update_dict = {"status": loser_status}
                if loser_status == RegistrationStatus.WAITLISTED:
                    update_dict["waitlist_position"] = position

                updated = reg.model_copy(update=update_dict)
                registrations_by_id[reg_id] = updated
                losers.append(updated)
            except ClientError as e:
                logger.error("Failed to update loser", extra={"registration_id": reg_id, "error": str(e)})

        # Mark run as finalized
        finalized_run = run.finalize(admin_id)
        try:
            self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"LOTTERY#{run.id}",
                },
                UpdateExpression="SET finalized_at = :finalized_at, finalization_by_admin_id = :admin_id",
                ExpressionAttributeValues={
                    ":finalized_at": finalized_run.finalized_at.isoformat() if finalized_run.finalized_at else None,
                    ":admin_id": str(admin_id),
                },
            )
        except ClientError as e:
            logger.error("Failed to finalize lottery run", extra={"error": str(e)})
            raise

        # Move event to CONFIRMED
        await self.event_service.mark_confirmed_after_lottery(org_id, event_id)

        # Send notifications for winners and losers
        await self._notify_outcomes(event, winners, losers)

        return self._build_result(finalized_run, registrations_by_id)

    async def _notify_outcomes(
        self,
        event: Event,
        winners: list[Registration],
        losers: list[Registration],
    ) -> None:
        """Send outcome emails; failures are logged but do not block finalization."""
        for reg in winners:
            try:
                await self.email_service.send_lottery_winner(event, reg)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Failed to send winner email",
                    extra={"registration_id": str(reg.id), "error": str(e)},
                )

        # Send appropriate email to losers based on their status
        for reg in losers:
            try:
                if reg.status == RegistrationStatus.WAITLISTED:
                    await self.email_service.send_lottery_waitlist(event, reg)
                else:
                    # CANCELLED - send lottery rejection email
                    await self.email_service.send_lottery_rejection(event, reg)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Failed to send loser email",
                    extra={"registration_id": str(reg.id), "status": reg.status.value, "error": str(e)},
                )

        # Send confirmation requests to all winners (they are in CONFIRMED status)
        await self._send_confirmation_requests(event, winners)

    async def _send_confirmation_requests(
        self,
        event: Event,
        winners: list[Registration],
    ) -> None:
        """Send confirmation request emails to lottery winners in CONFIRMED status."""
        # Calculate days until event
        now = datetime.now(timezone.utc)
        event_start = event.start_at
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=timezone.utc)
        days_until_event = (event_start.date() - now.date()).days

        sent_count = 0
        skipped_count = 0
        failed_count = 0

        for reg in winners:
            # Only send to registrations in CONFIRMED status (not yet responded)
            if reg.status != RegistrationStatus.CONFIRMED:
                skipped_count += 1
                continue

            try:
                success = await self.email_service.send_confirmation_request(
                    event, reg, days_until_event
                )
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:  # noqa: BLE001
                failed_count += 1
                logger.error(
                    "Failed to send confirmation request",
                    extra={"registration_id": str(reg.id), "error": str(e)},
                )

        logger.info(
            "Confirmation requests sent after lottery finalization",
            extra={
                "event_id": str(event.id),
                "sent": sent_count,
                "skipped": skipped_count,
                "failed": failed_count,
            },
        )

    def _build_result(
        self,
        run: LotteryRun,
        registrations_by_id: dict[str, Registration],
    ) -> LotteryResult:
        """Build LotteryResult response with registration data."""
        winners = []
        waitlist = []

        logger.info(
            "Building lottery result",
            extra={
                "run_winners": run.winners,
                "run_waitlist": run.waitlist,
                "registration_ids": list(registrations_by_id.keys()),
            },
        )

        for reg_id in run.winners:
            reg = registrations_by_id.get(reg_id)
            if reg:
                winners.append(_serialize_registration(reg))
            else:
                logger.warning(
                    "Winner registration not found",
                    extra={"reg_id": reg_id},
                )

        for reg_id in run.waitlist:
            reg = registrations_by_id.get(reg_id)
            if reg:
                waitlist.append(_serialize_registration(reg))

        return LotteryResult(
            event_id=run.event_id,
            seed=run.seed,
            winners=winners,
            waitlist=waitlist,
            is_finalized=run.is_finalized,
            executed_at=run.executed_at,
            finalized_at=run.finalized_at,
        )


_lottery_service: LotteryService | None = None


def get_lottery_service() -> LotteryService:
    """Get or create LotteryService instance."""
    global _lottery_service
    if _lottery_service is None:
        _lottery_service = LotteryService()
    return _lottery_service
