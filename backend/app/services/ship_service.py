"""Ship state service (spec 011).

Singleton Schaluppe state. Overwritten by Fahrbericht submissions from spec
012 — notes & todos accumulate across tours, scalar fields are overwritten.
"""

from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from ..models import (
    Co2Level,
    KloLevel,
    Note,
    NoteInput,
    PersennigStatus,
    ShipState,
    ShipStatePatch,
    ShipStatusSnapshot,
    Todo,
    TodoInput,
)
from .config import (
    SHIP_PK,
    SHIP_SK_STATE,
    SHIP_SK_TOUR_MARKER_PREFIX,
    get_ship_state_table,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _ship_to_item(state: ShipState) -> dict:
    return {
        "pk": SHIP_PK,
        "sk": SHIP_SK_STATE,
        "entity_type": "ShipState",
        "tank1_pct": state.tank1_pct,
        "tank2_pct": state.tank2_pct,
        "kanister_aboard": state.kanister_aboard,
        "kanister_garage": state.kanister_garage,
        "water_filled_at": state.water_filled_at.isoformat() if state.water_filled_at else None,
        "co2_level": state.co2_level.value if state.co2_level else None,
        "battery_pct": state.battery_pct,
        "klo1_level": state.klo1_level.value if state.klo1_level else None,
        "klo2_level": state.klo2_level.value if state.klo2_level else None,
        "persennig_status": state.persennig_status.value if state.persennig_status else None,
        "general_notes": [_note_to_item(n) for n in state.general_notes],
        "open_todos": [_todo_to_item(t) for t in state.open_todos],
        "last_updated_from_tour_id": (
            str(state.last_updated_from_tour_id) if state.last_updated_from_tour_id else None
        ),
        "updated_at": state.updated_at.isoformat(),
    }


def _note_to_item(note: Note) -> dict:
    return {
        "id": str(note.id),
        "text": note.text,
        "author": note.author,
        "created_at": note.created_at.isoformat(),
    }


def _todo_to_item(todo: Todo) -> dict:
    return {
        "id": str(todo.id),
        "text": todo.text,
        "author": todo.author,
        "created_at": todo.created_at.isoformat(),
        "done": todo.done,
        "done_at": todo.done_at.isoformat() if todo.done_at else None,
        "done_by": todo.done_by,
    }


def _item_to_ship(item: dict | None) -> ShipState:
    if not item:
        return ShipState()
    return ShipState(
        tank1_pct=item.get("tank1_pct"),
        tank2_pct=item.get("tank2_pct"),
        kanister_aboard=item.get("kanister_aboard"),
        kanister_garage=item.get("kanister_garage"),
        water_filled_at=date_type.fromisoformat(item["water_filled_at"]) if item.get("water_filled_at") else None,
        co2_level=Co2Level(item["co2_level"]) if item.get("co2_level") else None,
        battery_pct=item.get("battery_pct"),
        klo1_level=KloLevel(item["klo1_level"]) if item.get("klo1_level") else None,
        klo2_level=KloLevel(item["klo2_level"]) if item.get("klo2_level") else None,
        persennig_status=PersennigStatus(item["persennig_status"]) if item.get("persennig_status") else None,
        general_notes=[
            Note(
                id=UUID(n["id"]),
                text=n["text"],
                author=n.get("author"),
                created_at=datetime.fromisoformat(n["created_at"]),
            )
            for n in item.get("general_notes") or []
        ],
        open_todos=[
            Todo(
                id=UUID(t["id"]),
                text=t["text"],
                author=t.get("author"),
                created_at=datetime.fromisoformat(t["created_at"]),
                done=bool(t.get("done", False)),
                done_at=datetime.fromisoformat(t["done_at"]) if t.get("done_at") else None,
                done_by=t.get("done_by"),
            )
            for t in item.get("open_todos") or []
        ],
        last_updated_from_tour_id=(
            UUID(item["last_updated_from_tour_id"]) if item.get("last_updated_from_tour_id") else None
        ),
        updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else datetime.now(timezone.utc),
    )


class ShipService:
    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_ship_state_table()
        return self._table

    async def get_state(self) -> ShipState:
        resp = self.table.get_item(Key={"pk": SHIP_PK, "sk": SHIP_SK_STATE})
        item = resp.get("Item")
        if not item:
            state = ShipState()
            self.table.put_item(Item=_ship_to_item(state))
            return state
        return _item_to_ship(item)

    async def patch_state(self, patch: ShipStatePatch) -> ShipState:
        state = await self.get_state()
        fields = patch.model_dump(exclude_none=True)
        if fields:
            fields["updated_at"] = datetime.now(timezone.utc)
            state = state.model_copy(update=fields)
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def append_note(self, text: str, author: str | None) -> ShipState:
        state = await self.get_state()
        note = Note(text=text, author=author)
        state = state.model_copy(
            update={
                "general_notes": [*state.general_notes, note],
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def remove_note(self, note_id: UUID) -> ShipState:
        state = await self.get_state()
        state = state.model_copy(
            update={
                "general_notes": [n for n in state.general_notes if n.id != note_id],
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def append_todo(self, text: str, author: str | None) -> ShipState:
        state = await self.get_state()
        todo = Todo(text=text, author=author)
        state = state.model_copy(
            update={
                "open_todos": [*state.open_todos, todo],
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def toggle_todo(self, todo_id: UUID, done: bool, author: str | None) -> ShipState:
        state = await self.get_state()
        todos = list(state.open_todos)
        for i, todo in enumerate(todos):
            if todo.id == todo_id:
                todos[i] = todo.model_copy(
                    update={
                        "done": done,
                        "done_at": datetime.now(timezone.utc) if done else None,
                        "done_by": author if done else None,
                    },
                )
        state = state.model_copy(
            update={"open_todos": todos, "updated_at": datetime.now(timezone.utc)},
        )
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def edit_todo(self, todo_id: UUID, text: str) -> ShipState:
        state = await self.get_state()
        todos = [
            t.model_copy(update={"text": text}) if t.id == todo_id else t
            for t in state.open_todos
        ]
        state = state.model_copy(update={"open_todos": todos})
        self.table.put_item(Item=_ship_to_item(state))
        return state

    async def remove_todo(self, todo_id: UUID) -> ShipState:
        state = await self.get_state()
        state = state.model_copy(
            update={"open_todos": [t for t in state.open_todos if t.id != todo_id]},
        )
        self.table.put_item(Item=_ship_to_item(state))
        return state

    # ---------------------------------------------------------- Apply flows
    async def apply_ship_status(
        self,
        *,
        tour_id: UUID,
        version: int,
        snapshot: ShipStatusSnapshot,
        new_notes: list[NoteInput],
        new_todos: list[TodoInput],
    ) -> tuple[ShipState, list[UUID], list[UUID]]:
        """First-submission path. Returns new state + appended note/todo ids."""
        if self._marker_exists(tour_id, version):
            state = await self.get_state()
            return state, [], []

        state = await self.get_state()
        snapshot_fields = snapshot.model_dump(exclude_none=True)
        notes_to_add = [
            Note(id=n.id or uuid4(), text=n.text, author=None) for n in new_notes
        ]
        todos_to_add = [
            Todo(id=t.id or uuid4(), text=t.text, author=None) for t in new_todos
        ]
        state = state.model_copy(
            update={
                **snapshot_fields,
                "general_notes": [*state.general_notes, *notes_to_add],
                "open_todos": [*state.open_todos, *todos_to_add],
                "last_updated_from_tour_id": tour_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_ship_to_item(state))
        self._write_marker(tour_id, version)
        return state, [n.id for n in notes_to_add], [t.id for t in todos_to_add]

    async def apply_ship_status_versioned(
        self,
        *,
        tour_id: UUID,
        version: int,
        snapshot: ShipStatusSnapshot,
        previously_applied_note_ids: list[UUID],
        previously_applied_todo_ids: list[UUID],
        new_notes: list[NoteInput],
        new_todos: list[TodoInput],
    ) -> tuple[ShipState, list[UUID], list[UUID]]:
        if self._marker_exists(tour_id, version):
            state = await self.get_state()
            return state, previously_applied_note_ids, previously_applied_todo_ids

        state = await self.get_state()

        # Keep user's current notes + remove any previously-applied that are dropped.
        new_note_ids = {n.id for n in new_notes if n.id}
        kept_notes = [
            n for n in state.general_notes
            if n.id not in set(previously_applied_note_ids) or n.id in new_note_ids
        ]
        # Append notes that are new (no id or id not already present).
        existing_ids = {n.id for n in kept_notes}
        appended_notes = [
            Note(id=n.id or uuid4(), text=n.text, author=None)
            for n in new_notes
            if (n.id or uuid4()) not in existing_ids
        ]

        new_todo_ids = {t.id for t in new_todos if t.id}
        kept_todos = [
            t for t in state.open_todos
            if t.id not in set(previously_applied_todo_ids) or t.id in new_todo_ids
        ]
        existing_todo_ids = {t.id for t in kept_todos}
        appended_todos = [
            Todo(id=t.id or uuid4(), text=t.text, author=None)
            for t in new_todos
            if (t.id or uuid4()) not in existing_todo_ids
        ]

        snapshot_fields = snapshot.model_dump(exclude_none=True)
        state = state.model_copy(
            update={
                **snapshot_fields,
                "general_notes": [*kept_notes, *appended_notes],
                "open_todos": [*kept_todos, *appended_todos],
                "last_updated_from_tour_id": tour_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_ship_to_item(state))
        self._write_marker(tour_id, version)

        applied_note_ids = [n.id for n in state.general_notes if n.id in (
            set(previously_applied_note_ids) | {n.id for n in appended_notes}
        )]
        applied_todo_ids = [t.id for t in state.open_todos if t.id in (
            set(previously_applied_todo_ids) | {t.id for t in appended_todos}
        )]
        return state, applied_note_ids, applied_todo_ids

    # ------------------------------------------------------------- Helpers
    def _marker_exists(self, tour_id: UUID, version: int) -> bool:
        resp = self.table.get_item(
            Key={"pk": SHIP_PK, "sk": f"{SHIP_SK_TOUR_MARKER_PREFIX}{tour_id}#v{version}"},
        )
        return "Item" in resp

    def _write_marker(self, tour_id: UUID, version: int) -> None:
        try:
            self.table.put_item(
                Item={
                    "pk": SHIP_PK,
                    "sk": f"{SHIP_SK_TOUR_MARKER_PREFIX}{tour_id}#v{version}",
                    "entity_type": "ShipApplyMarker",
                    "tour_id": str(tour_id),
                    "version": version,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise


_service: ShipService | None = None


def get_ship_service() -> ShipService:
    global _service
    if _service is None:
        _service = ShipService()
    return _service
