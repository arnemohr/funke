"""Invite service for festival registration links (spec 019).

Invites live in the events table as co-located rows (FAHRBERICHT
precedent): ``pk=EVENT#{event_id}``, ``sk=INVITE#{invite_id}``. A GSI
(`invite-token-index`) allows public lookup by the redeemable token.

Provides:
- Batch creation of invites (a Kontingent)
- CRUD + token lookup
- Atomic use-count consume/release (conditional updates — the race-critical
  path that guards against overbooking a capped multi-use invite)
"""

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import Invite, InviteBatchCreate, InviteUpdate
from .config import EVENT_SK_INVITE_PREFIX, get_events_table
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _generate_invite_token() -> str:
    """Generate a unique, URL-safe invite redemption token."""
    return secrets.token_urlsafe(16)


def _invite_to_item(invite: Invite) -> dict:
    """Convert Invite model to DynamoDB item."""
    item = {
        "pk": f"EVENT#{invite.event_id}",
        "sk": f"{EVENT_SK_INVITE_PREFIX}{invite.id}",
        "id": str(invite.id),
        "event_id": str(invite.event_id),
        "org_id": str(invite.org_id),
        "invite_token": invite.token,  # GSI key
        "label": invite.label,
        "tier": invite.tier,
        "max_uses": invite.max_uses,
        "use_count": invite.use_count,
        "max_group_size": invite.max_group_size,
        "created_at": invite.created_at.isoformat(),
        "entity_type": "Invite",
    }

    # Optional fields
    if invite.batch_label:
        item["batch_label"] = invite.batch_label

    if invite.email:
        item["email"] = invite.email

    if invite.expires_at:
        item["expires_at"] = invite.expires_at.isoformat()

    if invite.revoked_at:
        item["revoked_at"] = invite.revoked_at.isoformat()

    if invite.created_by_admin_id:
        item["created_by_admin_id"] = str(invite.created_by_admin_id)

    if invite.sent_at:
        item["sent_at"] = invite.sent_at.isoformat()

    if invite.last_registered_at:
        item["last_registered_at"] = invite.last_registered_at.isoformat()

    return item


def _item_to_invite(item: dict) -> Invite:
    """Convert DynamoDB item to Invite model."""
    return Invite(
        id=UUID(item["id"]),
        event_id=UUID(item["event_id"]),
        org_id=UUID(item["org_id"]),
        token=item["invite_token"],
        label=item["label"],
        batch_label=item.get("batch_label"),
        email=item.get("email"),
        tier=item["tier"],
        max_uses=int(item["max_uses"]),
        use_count=int(item["use_count"]),
        max_group_size=int(item["max_group_size"]),
        expires_at=datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None,
        revoked_at=datetime.fromisoformat(item["revoked_at"]) if item.get("revoked_at") else None,
        created_at=datetime.fromisoformat(item["created_at"]),
        created_by_admin_id=(
            UUID(item["created_by_admin_id"]) if item.get("created_by_admin_id") else None
        ),
        sent_at=datetime.fromisoformat(item["sent_at"]) if item.get("sent_at") else None,
        last_registered_at=(
            datetime.fromisoformat(item["last_registered_at"])
            if item.get("last_registered_at")
            else None
        ),
    )


class InviteService:
    """Service for invite management operations."""

    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        """Get the events table (lazy initialization) — invites are co-located rows."""
        if self._table is None:
            self._table = get_events_table()
        return self._table

    async def create_invites_batch(
        self,
        org_id: UUID,
        event_id: UUID,
        batch: InviteBatchCreate,
        admin_id: UUID,
    ) -> list[Invite]:
        """Create one invite per batch entry (a Kontingent).

        Args:
            org_id: Organization ID.
            event_id: Festival event ID.
            batch: Batch of invite entries, sharing ``batch_label``.
            admin_id: ID of the admin creating the batch.

        Returns:
            The created Invite models, in the same order as the request.
        """
        invites: list[Invite] = []

        try:
            for entry in batch.invites:
                invite = Invite(
                    event_id=event_id,
                    org_id=org_id,
                    token=_generate_invite_token(),
                    label=entry.label,
                    batch_label=batch.batch_label,
                    email=entry.email,
                    tier=entry.tier,
                    max_uses=entry.max_uses,
                    max_group_size=entry.max_group_size,
                    expires_at=entry.expires_at,
                    created_by_admin_id=admin_id,
                )

                self.table.put_item(
                    Item=_invite_to_item(invite),
                    ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
                )

                invites.append(invite)

            logger.info(
                "Invite batch created",
                extra={
                    "event_id": str(event_id),
                    "org_id": str(org_id),
                    "admin_id": str(admin_id),
                    "count": len(invites),
                    "batch_label": batch.batch_label,
                },
            )

            return invites

        except ClientError as e:
            logger.error(
                "Failed to create invite batch",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    async def list_invites(self, event_id: UUID) -> list[Invite]:
        """List all invites for an event.

        Args:
            event_id: Festival event ID.

        Returns:
            List of invites.
        """
        try:
            query_kwargs = {
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with(EVENT_SK_INVITE_PREFIX),
            }

            response = self.table.query(**query_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            # Stable, deterministic order — the raw DynamoDB order is by
            # sk (`INVITE#{uuid}`), i.e. effectively random, which makes a
            # freshly created list jump around in the chase view. Oldest-first
            # by creation keeps existing rows put and appends new ones at the
            # end (the frontend groups by batch_label preserving this order).
            invites = [_item_to_invite(item) for item in items]
            invites.sort(key=lambda inv: inv.created_at)
            return invites

        except ClientError as e:
            logger.error(
                "Failed to list invites",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return []

    async def get_invite(self, event_id: UUID, invite_id: UUID) -> Invite | None:
        """Get an invite by ID.

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            Invite if found, None otherwise.
        """
        try:
            response = self.table.get_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
            )
            item = response.get("Item")
            return _item_to_invite(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get invite",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            return None

    async def get_invite_by_token(self, token: str) -> Invite | None:
        """Get an invite by its redemption token.

        Args:
            token: The public invite token.

        Returns:
            Invite if found, None otherwise.
        """
        try:
            response = self.table.query(
                IndexName="invite-token-index",
                KeyConditionExpression="invite_token = :token",
                ExpressionAttributeValues={":token": token},
            )
            items = response.get("Items", [])
            if not items:
                return None

            return _item_to_invite(items[0])

        except ClientError as e:
            logger.error(
                "Failed to get invite by token",
                extra={"error": str(e)},
            )
            return None

    async def update_invite(
        self,
        event_id: UUID,
        invite_id: UUID,
        patch: InviteUpdate,
    ) -> Invite | None:
        """Partial-update an invite.

        Reducing ``max_group_size`` never touches existing registrations —
        enforcement of "grow to max(current_size, invite.max_group_size)"
        lives in the registration service (T109).

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.
            patch: Fields to update.

        Returns:
            Updated Invite, or None if not found.
        """
        updates = patch.model_dump(exclude_unset=True)
        if not updates:
            return await self.get_invite(event_id, invite_id)

        # Targeted SET/REMOVE expression — never a full put_item, which
        # would rewrite a stale use_count read moments earlier and undo a
        # concurrent atomic consume_use (T105 race safety).
        set_parts: list[str] = []
        remove_parts: list[str] = []
        names: dict[str, str] = {}
        values: dict[str, object] = {}

        for field, value in updates.items():
            attr_name = f"#{field}"
            names[attr_name] = field

            if value is None:
                # _invite_to_item omits unset optionals — mirror that shape.
                remove_parts.append(attr_name)
                continue

            if isinstance(value, datetime):
                value = value.isoformat()

            placeholder = f":{field}"
            values[placeholder] = value
            set_parts.append(f"{attr_name} = {placeholder}")

        expression = ""
        if set_parts:
            expression = "SET " + ", ".join(set_parts)
        if remove_parts:
            expression += (" " if expression else "") + "REMOVE " + ", ".join(remove_parts)

        update_kwargs = {
            "Key": {
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
            },
            "UpdateExpression": expression,
            "ExpressionAttributeNames": names,
            "ConditionExpression": "attribute_exists(pk)",
            "ReturnValues": "ALL_NEW",
        }
        if values:
            update_kwargs["ExpressionAttributeValues"] = values

        try:
            response = self.table.update_item(**update_kwargs)
            return _item_to_invite(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            logger.error(
                "Failed to update invite",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise

    async def revoke_invite(self, event_id: UUID, invite_id: UUID) -> Invite | None:
        """Revoke an invite, blocking future redemptions only.

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            Updated Invite, or None if not found.
        """
        try:
            # Targeted single-attribute stamp — never a full put_item, so a
            # concurrently consumed use_count is never overwritten (T105).
            response = self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
                UpdateExpression="SET revoked_at = :now",
                ExpressionAttributeValues={":now": datetime.now(timezone.utc).isoformat()},
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_NEW",
            )
            return _item_to_invite(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            logger.error(
                "Failed to revoke invite",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise

    async def mark_sent(self, event_id: UUID, invite_id: UUID) -> Invite | None:
        """Stamp ``sent_at`` — idempotent (Ä7): a second call is a no-op.

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            Updated (or unchanged) Invite, or None if not found.
        """
        try:
            # if_not_exists keeps the Ä7 idempotency (a second call is a
            # no-op) without a read-modify-write full put_item, which would
            # rewrite a stale use_count (T105 race safety).
            response = self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
                UpdateExpression="SET sent_at = if_not_exists(sent_at, :now)",
                ExpressionAttributeValues={":now": datetime.now(timezone.utc).isoformat()},
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_NEW",
            )
            return _item_to_invite(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            logger.error(
                "Failed to mark invite as sent",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise

    async def touch_last_registered(self, event_id: UUID, invite_id: UUID) -> Invite | None:
        """Stamp ``last_registered_at`` after a successful redemption.

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            Updated Invite, or None if not found.
        """
        try:
            # Runs after EVERY successful redemption — must never rewrite
            # the whole item: a full put_item carrying a use_count read
            # before a concurrent consume_use would regress the atomic
            # counter and let an exhausted link accept another registration.
            response = self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
                UpdateExpression="SET last_registered_at = :now",
                ExpressionAttributeValues={":now": datetime.now(timezone.utc).isoformat()},
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_NEW",
            )
            return _item_to_invite(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            logger.error(
                "Failed to touch invite last_registered_at",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise

    async def consume_use(self, event_id: UUID, invite_id: UUID) -> bool:
        """Atomically consume one use of the invite.

        Guards against overbooking a capped multi-use invite under
        concurrent redemption: the conditional update is evaluated by
        DynamoDB against the item's *current* ``use_count``, not a value
        read earlier by this process, so two racing calls can never both
        succeed once the invite is exhausted.

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            True if a use was consumed, False if the invite is exhausted,
            revoked, or not found.
        """
        invite = await self.get_invite(event_id, invite_id)
        if not invite:
            return False

        try:
            self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
                UpdateExpression="ADD use_count :one",
                ConditionExpression="use_count < :max AND attribute_not_exists(revoked_at)",
                ExpressionAttributeValues={":one": 1, ":max": invite.max_uses},
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            logger.error(
                "Failed to consume invite use",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise

    async def release_use(self, event_id: UUID, invite_id: UUID) -> bool:
        """Atomically release one use of the invite (e.g. on cancellation).

        Args:
            event_id: Festival event ID.
            invite_id: Invite ID.

        Returns:
            True if a use was released, False if ``use_count`` is already 0.
        """
        try:
            self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_INVITE_PREFIX}{invite_id}",
                },
                UpdateExpression="ADD use_count :neg",
                ConditionExpression="use_count > :zero",
                ExpressionAttributeValues={":neg": -1, ":zero": 0},
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            logger.error(
                "Failed to release invite use",
                extra={"error": str(e), "invite_id": str(invite_id)},
            )
            raise


# Singleton instance
_invite_service: InviteService | None = None


def get_invite_service() -> InviteService:
    """Get or create InviteService instance."""
    global _invite_service
    if _invite_service is None:
        _invite_service = InviteService()
    return _invite_service
