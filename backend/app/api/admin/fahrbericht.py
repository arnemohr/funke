"""Fahrbericht admin routes (spec 014 — keyed by event_id)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import FahrberichtPatch, FahrberichtResponse, SubmitResult
from ...services.auth import CurrentUser
from ...services.charter_service import get_charter_service
from ...services.event_service import get_event_service
from ...services.fahrbericht_service import get_fahrbericht_service

router = APIRouter(
    prefix="/events/{event_id}/fahrbericht",
    tags=["admin.fahrbericht"],
)


def _org_id(user: CurrentUser) -> UUID:
    if not user.org_id:
        raise HTTPException(403, "org_id missing")
    return UUID(user.org_id)


async def _check_access(event_id: UUID, user: CurrentUser) -> None:
    org_id = _org_id(user)
    event = await get_event_service().get_event(org_id, event_id)
    if not event:
        raise HTTPException(404, "event_not_found")


@router.get("")
async def get_fahrbericht(event_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(event_id, user)
    resp = await get_fahrbericht_service().build_response(event_id)
    if not resp:
        raise HTTPException(404, "not_found")
    return resp


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(event_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(event_id, user)
    try:
        await get_fahrbericht_service().create_draft(event_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(event_id)  # type: ignore[return-value]


@router.put("")
async def upsert_draft(
    event_id: UUID,
    patch: FahrberichtPatch,
    user: CurrentUser,
) -> FahrberichtResponse:
    await _check_access(event_id, user)
    try:
        await get_fahrbericht_service().upsert_draft(event_id, patch)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(event_id)  # type: ignore[return-value]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(event_id: UUID, user: CurrentUser) -> None:
    await _check_access(event_id, user)
    try:
        await get_fahrbericht_service().delete_draft(event_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


class SubmitRequest(BaseModel):
    """Optional body of the submit call (spec 025).

    `ohne_vertrag_abgeben` files the trip report even though the event's charter
    contract has no signed scan yet. The whole body stays optional so the
    existing callers — the Fahrbericht page posts nothing — keep working.
    """

    ohne_vertrag_abgeben: bool = False


@router.post("/submit")
async def submit(
    event_id: UUID,
    user: CurrentUser,
    body: SubmitRequest | None = None,
) -> SubmitResult:
    await _check_access(event_id, user)

    # Spec 025 hangs the reminder for a missing signed contract on the one habit
    # that follows every trip anyway. `blocks_fahrbericht` is False whenever the
    # event has no contract row at all, so an ordinary trip pays one get_item
    # and nothing else.
    charter_service = get_charter_service()
    contract_unsigned = await charter_service.blocks_fahrbericht(event_id)

    if contract_unsigned and not (body and body.ohne_vertrag_abgeben):
        raise HTTPException(409, "chartervertrag_fehlt")

    try:
        result = await get_fahrbericht_service().submit(
            event_id,
            org_id=_org_id(user),
            submitted_by=user.sub,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    if contract_unsigned:
        # Stamped only once the report is actually filed — the override records
        # that this happened, and nothing happened if the submission failed. A
        # failure here is not swallowed: the whole point is that the waiver is
        # visible on the contract page, so it is better to answer 500 (the
        # report is filed either way) than to wave the trip through unrecorded.
        await charter_service.stamp_fahrbericht_override(event_id, submitted_by=user.email)

    return result


@router.post("/reopen")
async def reopen(event_id: UUID, user: CurrentUser) -> FahrberichtResponse:
    await _check_access(event_id, user)
    try:
        await get_fahrbericht_service().reopen(event_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await get_fahrbericht_service().build_response(event_id)  # type: ignore[return-value]


@router.post("/reapply-side-effects")
async def reapply(event_id: UUID, user: CurrentUser) -> SubmitResult:
    await _check_access(event_id, user)
    try:
        return await get_fahrbericht_service().reapply_side_effects(event_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
