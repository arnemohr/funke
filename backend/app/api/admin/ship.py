"""Ship state admin routes (spec 011)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import ShipState, ShipStatePatch
from ...services.auth import CurrentUser
from ...services.ship_service import get_ship_service

router = APIRouter(prefix="/ship", tags=["admin.ship"])


@router.get("/state")
async def get_state(_: CurrentUser) -> ShipState:
    return await get_ship_service().get_state()


@router.patch("/state")
async def patch_state(patch: ShipStatePatch, _: CurrentUser) -> ShipState:
    return await get_ship_service().patch_state(patch)


class NoteInputBody(BaseModel):
    text: str


@router.post("/notes")
async def add_note(body: NoteInputBody, user: CurrentUser) -> ShipState:
    return await get_ship_service().append_note(body.text, user.sub)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_note(note_id: UUID, _: CurrentUser) -> None:
    await get_ship_service().remove_note(note_id)


@router.post("/todos")
async def add_todo(body: NoteInputBody, user: CurrentUser) -> ShipState:
    return await get_ship_service().append_todo(body.text, user.sub)


class TodoPatch(BaseModel):
    done: bool | None = None
    text: str | None = None


@router.patch("/todos/{todo_id}")
async def patch_todo(todo_id: UUID, body: TodoPatch, user: CurrentUser) -> ShipState:
    service = get_ship_service()
    state = await service.get_state()
    if body.text is not None:
        state = await service.edit_todo(todo_id, body.text)
    if body.done is not None:
        state = await service.toggle_todo(todo_id, body.done, user.sub)
    return state


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_todo(todo_id: UUID, _: CurrentUser) -> None:
    await get_ship_service().remove_todo(todo_id)
