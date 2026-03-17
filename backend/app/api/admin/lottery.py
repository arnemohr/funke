"""Admin lottery endpoints for executing and finalizing event lotteries."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ...models import LotteryResult
from ...services.auth import AdminRole, CurrentUser, require_role
from ...services.logging import get_logger
from ...services.lottery_service import get_lottery_service

logger = get_logger(__name__)
router = APIRouter()


def _get_org_id(user: CurrentUser) -> UUID:
    """Extract organization ID from user token."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization ID not found in token",
        )
    return UUID(user.org_id)


def _get_admin_id(user: CurrentUser) -> UUID:
    """Convert Auth0 subject to deterministic UUID for audit tracking."""
    import hashlib
    return UUID(hashlib.md5(user.sub.encode()).hexdigest())


@router.post(
    "/events/{event_id}/lottery/run",
    response_model=LotteryResult,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def run_lottery(
    event_id: UUID,
    user: CurrentUser,
) -> LotteryResult:
    """Run lottery for an event after registration is closed."""
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)
    service = get_lottery_service()

    try:
        return await service.run_lottery(org_id, event_id, admin_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        logger.error("Unexpected error running lottery", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run lottery",
        ) from e


@router.get(
    "/events/{event_id}/lottery",
    response_model=LotteryResult,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_lottery_result(
    event_id: UUID,
    user: CurrentUser,
) -> LotteryResult:
    """Get latest lottery result for review."""
    org_id = _get_org_id(user)
    _ = org_id  # Org ID currently unused but validates presence

    service = get_lottery_service()
    result = await service.get_result(event_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No lottery run found for this event",
        )

    return result


@router.post(
    "/events/{event_id}/lottery/finalize",
    response_model=LotteryResult,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def finalize_lottery(
    event_id: UUID,
    user: CurrentUser,
) -> LotteryResult:
    """Finalize lottery results and send notifications."""
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)
    service = get_lottery_service()

    try:
        return await service.finalize_lottery(org_id, event_id, admin_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        logger.error("Unexpected error finalizing lottery", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to finalize lottery",
        ) from e
