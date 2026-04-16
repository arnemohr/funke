"""Web Push notification service.

Provides:
- VAPID key management
- Push subscription CRUD in DynamoDB (admins table)
- Sending push notifications via pywebpush
"""

import json
from datetime import UTC, datetime

from pydantic_settings import BaseSettings

from .config import get_dynamodb_resource, get_settings
from .logging import get_logger

logger = get_logger(__name__)


class PushSettings(BaseSettings):
    """VAPID configuration settings."""

    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claim_email: str = "mailto:info@mobilemachenschaften.de"

    class Config:
        env_prefix = ""
        case_sensitive = False


_service = None


def get_push_service():
    """Get or create PushService singleton."""
    global _service
    if _service is None:
        _service = PushService()
    return _service


class PushService:
    """Web Push notification service using VAPID and DynamoDB."""

    def __init__(self):
        self.settings = PushSettings()
        self._table = None

    def _get_table(self):
        """Get admins DynamoDB table (lazy init)."""
        if self._table is None:
            db_settings = get_settings()
            dynamodb = get_dynamodb_resource()
            self._table = dynamodb.Table(f"{db_settings.dynamodb_table_prefix}-admins")
        return self._table

    def is_configured(self) -> bool:
        """Check if VAPID keys are configured."""
        return bool(self.settings.vapid_private_key and self.settings.vapid_public_key)

    def get_public_key(self) -> str:
        """Return the VAPID public key."""
        return self.settings.vapid_public_key

    async def save_subscription(
        self,
        admin_id: str,
        org_id: str,
        subscription: dict,
    ) -> None:
        """Store a push subscription for an admin user."""
        table = self._get_table()
        table.put_item(
            Item={
                "pk": f"ORG#{org_id}",
                "sk": f"PUSH#{admin_id}",
                "endpoint": subscription["endpoint"],
                "keys": subscription["keys"],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        logger.info(
            "Push subscription saved",
            extra={"admin_id": admin_id, "org_id": org_id},
        )

    async def delete_subscription(self, admin_id: str, org_id: str) -> None:
        """Remove a push subscription for an admin user."""
        table = self._get_table()
        table.delete_item(
            Key={"pk": f"ORG#{org_id}", "sk": f"PUSH#{admin_id}"},
        )
        logger.info(
            "Push subscription deleted",
            extra={"admin_id": admin_id, "org_id": org_id},
        )

    async def _get_all_subscriptions(self, org_id: str) -> list[dict]:
        """Get all push subscriptions for an organization."""
        table = self._get_table()
        response = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"ORG#{org_id}",
                ":prefix": "PUSH#",
            },
        )
        return [
            {
                "endpoint": item["endpoint"],
                "keys": item["keys"],
            }
            for item in response.get("Items", [])
        ]

    async def _delete_subscription_by_endpoint(self, org_id: str, endpoint: str) -> None:
        """Remove a subscription by endpoint (for cleanup on 404/410)."""
        table = self._get_table()
        # Query to find the item with this endpoint, then delete
        response = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"ORG#{org_id}",
                ":prefix": "PUSH#",
            },
        )
        for item in response.get("Items", []):
            if item.get("endpoint") == endpoint:
                table.delete_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                )
                logger.info("Cleaned up expired push subscription", extra={"endpoint": endpoint})
                break

    async def send_to_org_admins(
        self,
        org_id: str,
        title: str,
        body: str,
        url: str = "/",
    ) -> int:
        """Send a push notification to all subscribed admins in the org.

        Returns the number of successful sends.
        """
        from pywebpush import WebPushException, webpush

        subscriptions = await self._get_all_subscriptions(org_id)
        sent = 0

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=self.settings.vapid_private_key,
                    vapid_claims={"sub": self.settings.vapid_claim_email},
                )
                sent += 1
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    # Subscription expired/invalid, clean up
                    await self._delete_subscription_by_endpoint(org_id, sub["endpoint"])
                    logger.info("Removed expired push subscription")
                else:
                    logger.error("Push notification failed", extra={"error": str(e)})

        logger.info(
            "Push notifications sent",
            extra={"org_id": org_id, "sent": sent, "total": len(subscriptions)},
        )
        return sent
