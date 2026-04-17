"""Fahrbericht admin routes (spec 012)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from ...models import FahrberichtPatch, FahrberichtResponse, SubmitResult
from ...services.auth import CurrentUser
from ...services.fahrbericht_service import get_fahrbericht_service
from ...services.tour_service import get_tour_service

router = APIRouter(prefix="/tours/{tour_id}/fahrbericht", tags=["admin.fahrbericht"])


async def _check_access(tour_id: UUID, user: CurrentUser) -> None:
    tour = await get_tour_service().get_tour(tour_id)
    if not tour or (user.org_id and str(tour.org_id) != user.org_id):
        raise HTTPException(404, "tour_not_found")


@router.get("")
async def get_fahrbericht(tour_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(tour_id, user)
    resp = await get_fahrbericht_service().build_response(tour_id)
    if not resp:
        raise HTTPException(404, "not_found")
    return resp


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(tour_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(tour_id, user)
    try:
        await get_fahrbericht_service().create_draft(tour_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(tour_id)  # type: ignore[return-value]


@router.put("")
async def upsert_draft(
    tour_id: UUID,
    patch: FahrberichtPatch,
    user: CurrentUser,
) -> FahrberichtResponse:
    await _check_access(tour_id, user)
    try:
        await get_fahrbericht_service().upsert_draft(tour_id, patch)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(tour_id)  # type: ignore[return-value]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(tour_id: UUID, user: CurrentUser) -> None:
    await _check_access(tour_id, user)
    try:
        await get_fahrbericht_service().delete_draft(tour_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/submit")
async def submit(tour_id: UUID, user: CurrentUser) -> SubmitResult:
    await _check_access(tour_id, user)
    try:
        return await get_fahrbericht_service().submit(tour_id, submitted_by=user.sub)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/reopen")
async def reopen(tour_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(tour_id, user)
    try:
        await get_fahrbericht_service().reopen(tour_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(tour_id)  # type: ignore[return-value]


@router.post("/reapply-side-effects")
async def reapply(tour_id: UUID, user: CurrentUser) -> SubmitResult:
    await _check_access(tour_id, user)
    try:
        return await get_fahrbericht_service().reapply_side_effects(tour_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
