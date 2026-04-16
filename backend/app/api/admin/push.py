"""Push notification endpoints for admin users.

Provides:
- VAPID public key retrieval
- Push subscription management (subscribe/unsubscribe)
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from ...models.admin import AdminRole
from ...services.auth import CurrentUser, require_role
from ...services.push_service import get_push_service

router = APIRouter(prefix="/push", tags=["push"])


class VapidKeyResponse(BaseModel):
    """VAPID public key response."""

    public_key: str


class PushSubscriptionCreate(BaseModel):
    """Push subscription data from the browser."""

    endpoint: str
    keys: dict  # {p256dh: str, auth: str}


@router.get("/vapid-key", response_model=VapidKeyResponse)
async def get_vapid_key(user: CurrentUser):
    """Return the VAPID public key for push subscription."""
    service = get_push_service()
    return VapidKeyResponse(public_key=service.get_public_key())


@router.post(
    "/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def subscribe(
    subscription: PushSubscriptionCreate,
    user: CurrentUser,
):
    """Store a push subscription for the authenticated admin."""
    service = get_push_service()
    await service.save_subscription(
        admin_id=user.sub,
        org_id=user.org_id,
        subscription=subscription.model_dump(),
    )
    return {"status": "subscribed"}


@router.delete(
    "/subscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def unsubscribe(user: CurrentUser):
    """Remove push subscription for the authenticated admin."""
    service = get_push_service()
    await service.delete_subscription(admin_id=user.sub, org_id=user.org_id)
