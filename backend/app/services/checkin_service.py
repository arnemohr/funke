"""Check-in log + scan orchestration for the festival gate (spec 019 §P3).

Scan rows (`SCAN#` sk prefix) live in the registrations table, co-located
under the same `EVENT#{event_id}` partition as `REG#` rows (T305's
`begins_with(sk, "REG#")` filter keeps them from leaking into registration
queries and stats). A scan row **never** flips the registration's own
status — `RegistrationStatus.CHECKED_IN` stays unused for festivals
(spec.md:256, :295); check-in is purely additive log data.

**Berlin-time sk — deliberate exception to the repo's UTC convention**: the
sk embeds `datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))`
rather than UTC, because the gate runs past midnight and a UTC timestamp
would mis-attribute a Saturday-morning arrival (Sa 00:30 CEST = Fr 22:30
UTC) to Friday. `scanned_at` on the item itself stays UTC (used for the
60s undo window, where wall-clock precision doesn't matter).

Row shape: `pk=EVENT#{event_id}`, `sk=SCAN#{iso_ts_berlin}#{registration_id}
#{person_index}` — the sk string itself is the `scan_id`, unique and
sortable, and addresses exactly one row (so concurrent gate lanes can each
undo their own scan without touching another's).

Distinct-person semantics: multi-device offline sync (T311) can create
duplicate rows for the same `(registration_id, person_index)` once back
online. Every read path here (`get_checked_in_map`, `count_arrivals`)
de-duplicates by that key — the first row wins, extra rows just don't
change the count.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import Event, Registration, RegistrationStatus
from .config import CHECKIN_SK_PREFIX, get_registrations_table
from .logging import get_logger
from .registration_service import get_registration_service
from .ticket_signing import verify_ticket

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)

UNDO_WINDOW = timedelta(seconds=60)


class CheckinService:
    """Service for the check-in scan log and one-tap gate orchestration."""

    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        """Get the registrations table (lazy initialization; scan rows are
        co-located there, see module docstring)."""
        if self._table is None:
            self._table = get_registrations_table()
        return self._table

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _parse_scan_key(sk: str) -> tuple[str, int]:
        """Parse `(registration_id, person_index)` out of a SCAN# sk."""
        parts = sk.split("#")
        # ["SCAN", iso_ts, registration_id, person_index]
        return (parts[2], int(parts[3]))

    async def _query_scan_items(self, event_id: UUID, sk_prefix: str) -> list[dict]:
        """Paginated query of SCAN# rows for one event, given an sk prefix."""
        try:
            query_kwargs = {
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with(sk_prefix),
            }
            response = self.table.query(**query_kwargs)
            items = response.get("Items", [])

            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            return items

        except ClientError as e:
            logger.error(
                "Failed to query check-in scans",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return []

    @staticmethod
    def _current_name(registration: Registration, person_index: int) -> str | None:
        """The person's current name at `person_index` (0 = contact, 1.. =
        `group_members[p-1]`), or None if the index is out of range or the
        entry is a tombstone (a removed member, spec.md:289)."""
        if person_index == 0:
            return registration.name
        members = registration.group_members or []
        idx = person_index - 1
        if idx < 0 or idx >= len(members):
            return None
        return members[idx]

    @staticmethod
    def _overnight_status(registration: Registration) -> str:
        """Ä17: tri-state overnight status from the CURRENT registration —
        never from a ticket payload snapshot, so a post-issuance approval
        shows correctly at the gate."""
        if not registration.has_overnight:
            return "none"
        return "approved" if registration.overnight_approved else "requested"

    def _build_card(
        self,
        registration: Registration,
        person_index: int,
        person_name: str,
        checked_in_map: dict[tuple[str, int], str],
    ) -> dict:
        """Build the gate display card. Group check-in flags reflect the
        current log state, with `person_index` forced True — the person
        being scanned right now either was already checked in or is about
        to be (the row is written in the same call)."""
        reg_id = str(registration.id)
        group = [
            {
                "person_index": 0,
                "name": registration.name,
                "checked_in": person_index == 0 or (reg_id, 0) in checked_in_map,
            },
        ]
        for i, member_name in enumerate(registration.group_members or []):
            if member_name is None:
                continue  # tombstoned member — no code was ever issued for them
            idx = i + 1
            group.append(
                {
                    "person_index": idx,
                    "name": member_name,
                    "checked_in": person_index == idx or (reg_id, idx) in checked_in_map,
                },
            )

        return {
            "person_index": person_index,
            "person_name": person_name,
            "contact_name": registration.name,
            "group": group,
            # Slots are never enforced at the gate (Ä13) — informational only,
            # rendered from the current registration (like overnight status).
            "attendance_slots": registration.attendance_slots or [],
            # Ä21: separate tent/camper counts — a group may bring both. Shown
            # at the gate so staff can verify pitches against the scarce
            # Stellplätze.
            "tent_count": registration.tent_count,
            "camper_count": registration.camper_count,
            "overnight_status": self._overnight_status(registration),
        }

    # -- log operations -------------------------------------------------------

    async def record_scan(
        self,
        event_id: UUID,
        registration_id: UUID,
        person_index: int,
        person_name: str,
        override: bool = False,
    ) -> str:
        """Write one check-in log row. Never touches the registration item
        (check-in rows never flip status, spec.md:295). Returns the scan_id
        (the sk itself)."""
        now_utc = datetime.now(timezone.utc)
        # Deliberate Europe/Berlin exception — see module docstring.
        berlin_ts = now_utc.astimezone(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")
        # Second-granularity sk (spec-mandated format): a double-scan/override
        # of the SAME person inside the same wall-clock second overwrites the
        # prior row rather than adding a second one. Harmless — distinct-
        # person counting only cares about key presence, not row count, and
        # this only ever affects re-scans of one person a second apart.
        sk = f"{CHECKIN_SK_PREFIX}{berlin_ts}#{registration_id}#{person_index}"

        item = {
            "pk": f"EVENT#{event_id}",
            "sk": sk,
            "entity_type": "CheckinScan",
            "person_name": person_name,
            "scanned_at": now_utc.isoformat(),  # UTC — used for the undo window
            "override": override,
        }
        self.table.put_item(Item=item)
        return sk

    async def get_checked_in_map(self, event_id: UUID) -> dict[tuple[str, int], str]:
        """Distinct `(registration_id, person_index) -> scan_id` map. Multi-
        device offline sync can create duplicate rows for the same person —
        the first scan_id encountered wins (query results come back sk-
        ascending, i.e. chronological)."""
        items = await self._query_scan_items(event_id, CHECKIN_SK_PREFIX)
        result: dict[tuple[str, int], str] = {}
        for item in items:
            key = self._parse_scan_key(item["sk"])
            if key not in result:
                result[key] = item["sk"]
        return result

    async def count_arrivals(self, event_id: UUID, day: str | None = None) -> int:
        """Distinct-person arrival count, overall or for one `day`
        (`YYYY-MM-DD`, matched against the Berlin-local sk prefix)."""
        prefix = f"{CHECKIN_SK_PREFIX}{day}" if day else CHECKIN_SK_PREFIX
        items = await self._query_scan_items(event_id, prefix)
        keys = {self._parse_scan_key(item["sk"]) for item in items}
        return len(keys)

    async def get_arrivals_summary(self, event_id: UUID) -> dict:
        """Admin arrival board (T313): distinct-person arrival totals, overall
        and per gate day — „Angekommen (Erst-Check-ins)", not a live
        headcount. Built on top of `get_checked_in_map`'s already-deduped
        keys (first winning scan per person, chronological); the day is
        read off each winning scan_id's Berlin-local date, so `per_day`
        values always sum to `total` exactly (each person is attributed to
        the day of their first-ever scan, never double-counted across
        days). Returns `{"total": int, "per_day": {"YYYY-MM-DD": int, ...}}`.
        """
        checked_in_map = await self.get_checked_in_map(event_id)
        per_day: dict[str, int] = {}
        for scan_id in checked_in_map.values():
            # sk = "SCAN#{iso_ts_berlin}#{registration_id}#{person_index}"
            day = scan_id.split("#")[1][:10]
            per_day[day] = per_day.get(day, 0) + 1
        return {"total": len(checked_in_map), "per_day": dict(sorted(per_day.items()))}

    async def undo_scan(self, event_id: UUID, scan_id: str) -> bool:
        """Undo a scan by its scan_id (the sk), within a ~60s window.
        Targeting by scan_id keeps concurrent gate lanes on one stateless
        gate token from undoing each other's scans."""
        try:
            response = self.table.get_item(Key={"pk": f"EVENT#{event_id}", "sk": scan_id})
            item = response.get("Item")
            if not item:
                logger.info(
                    "Festival check-in undo rejected — scan not found",
                    extra={
                        "flow": "festival", "step": "checkin_undo", "outcome": "rejected",
                        "reason": "not_found", "event_id": str(event_id), "scan_id": scan_id,
                    },
                )
                return False

            scanned_at = datetime.fromisoformat(item["scanned_at"])
            if datetime.now(timezone.utc) - scanned_at > UNDO_WINDOW:
                logger.info(
                    "Festival check-in undo rejected — window expired",
                    extra={
                        "flow": "festival", "step": "checkin_undo", "outcome": "rejected",
                        "reason": "window_expired", "event_id": str(event_id), "scan_id": scan_id,
                    },
                )
                return False

            self.table.delete_item(Key={"pk": f"EVENT#{event_id}", "sk": scan_id})
            logger.info(
                "Festival check-in undone",
                extra={
                    "flow": "festival", "step": "checkin_undo", "outcome": "ok",
                    "event_id": str(event_id), "scan_id": scan_id,
                },
            )
            return True

        except ClientError as e:
            logger.error(
                "Failed to undo check-in scan",
                extra={"error": str(e), "event_id": str(event_id), "scan_id": scan_id},
            )
            return False

    # -- one-tap orchestration ------------------------------------------------

    async def scan_ticket(self, event: Event, code: str, override: bool = False) -> dict:
        """The one-tap QR-scan orchestration.

        Returns a structured result dict — always, never raises — so the
        router can respond 200 unconditionally:
        - Rejected: `{"result": "invalid", "reason": "invalid_signature" |
          "unknown_registration" | "cancelled" | "stale_ticket"}`.
        - Accepted: `{"result": "green", "card": {...}, "scan_id": "...",
          "already_checked_in": bool}` (`already_checked_in` is only present
          when true — first-time scans omit it).
        """
        def _reject(reason: str, **extra: object) -> dict:
            self._log_scan_reject(event.id, reason, via="qr", override=override, **extra)
            return {"result": "invalid", "reason": reason}

        payload = verify_ticket(event.ticket_secret, code)
        if payload is None:
            return _reject("invalid_signature")

        registration_id_raw = payload.get("r")
        person_index = payload.get("p")
        ticket_name = payload.get("n")
        if registration_id_raw is None or person_index is None:
            return _reject("unknown_registration")

        # A validly-signed payload can still carry a non-int "p" (the
        # verification_secret is handed to every gate device, Risk 6) —
        # reject it here instead of letting `_current_name` raise and
        # break the router's always-200 contract. bool is excluded
        # explicitly (it's an int subclass, but never a valid index).
        if not isinstance(person_index, int) or isinstance(person_index, bool):
            return _reject("unknown_registration")

        try:
            registration_id = UUID(str(registration_id_raw))
        except (ValueError, TypeError):
            return _reject("unknown_registration")

        registration_service = get_registration_service()
        registration = await registration_service.get_registration(event.id, registration_id)
        if registration is None:
            return _reject("unknown_registration", registration_id=str(registration_id))

        if registration.status == RegistrationStatus.CANCELLED:
            return _reject(
                "cancelled",
                registration_id=str(registration_id),
                person_index=person_index,
            )

        current_name = self._current_name(registration, person_index)
        if current_name is None or current_name != ticket_name:
            return _reject(
                "stale_ticket",
                registration_id=str(registration_id),
                person_index=person_index,
            )

        return await self._checkin(
            event, registration, person_index, current_name, override, via="qr",
        )

    async def checkin_person(self, event: Event, registration_id: UUID, person_index: int) -> dict:
        """Name-search check-in target — always a specific
        `(registration_id, person_index)`, never a name (spec.md:313).
        Same result shape as `scan_ticket`, always with `override=True`."""
        registration_service = get_registration_service()
        registration = await registration_service.get_registration(event.id, registration_id)
        if registration is None:
            self._log_scan_reject(
                event.id, "unknown_registration", via="name_search",
                override=True, registration_id=str(registration_id),
            )
            return {"result": "invalid", "reason": "unknown_registration"}

        if registration.status == RegistrationStatus.CANCELLED:
            self._log_scan_reject(
                event.id, "cancelled", via="name_search", override=True,
                registration_id=str(registration_id), person_index=person_index,
            )
            return {"result": "invalid", "reason": "cancelled"}

        current_name = self._current_name(registration, person_index)
        if current_name is None:
            self._log_scan_reject(
                event.id, "stale_ticket", via="name_search", override=True,
                registration_id=str(registration_id), person_index=person_index,
            )
            return {"result": "invalid", "reason": "stale_ticket"}

        return await self._checkin(
            event, registration, person_index, current_name, override=True, via="name_search",
        )

    def _log_scan_reject(
        self,
        event_id: UUID,
        reason: str,
        via: str,
        override: bool,
        **extra: object,
    ) -> None:
        """Structured log for a rejected check-in (green never reaches here).

        `flow=festival step=checkin outcome=invalid` — filterable in the
        same CloudWatch query as the rest of the flow."""
        logger.info(
            "Festival check-in rejected",
            extra={
                "flow": "festival",
                "step": "checkin",
                "outcome": "invalid",
                "reason": reason,
                "via": via,
                "override": override,
                "event_id": str(event_id),
                **extra,
            },
        )

    async def _checkin(
        self,
        event: Event,
        registration: Registration,
        person_index: int,
        person_name: str,
        override: bool,
        via: str = "qr",
    ) -> dict:
        """Shared steps 6-7 of the scan/check-in flow: look up current
        check-in state, build the card, and — unless already checked in
        and not overriding — record the scan."""
        checked_in_map = await self.get_checked_in_map(event.id)
        key = (str(registration.id), person_index)
        already = key in checked_in_map

        card = self._build_card(registration, person_index, person_name, checked_in_map)

        def _log_green(scan_id: str | None) -> None:
            logger.info(
                "Festival check-in accepted",
                extra={
                    "flow": "festival",
                    "step": "checkin",
                    "outcome": "green",
                    "via": via,
                    "override": override,
                    "event_id": str(event.id),
                    "registration_id": str(registration.id),
                    "person_index": person_index,
                    "person_name": person_name,
                    "already_checked_in": already,
                    "scan_id": scan_id,
                },
            )

        if already and not override:
            # No second wristband — the shift lead decides via override.
            _log_green(None)
            return {"result": "green", "already_checked_in": True, "card": card}

        scan_id = await self.record_scan(event.id, registration.id, person_index, person_name, override=override)
        _log_green(scan_id)
        result: dict = {"result": "green", "scan_id": scan_id, "card": card}
        if already:
            result["already_checked_in"] = True
        return result

    async def search_names(self, event: Event, q: str) -> list[dict]:
        """Name-search fallback (no QR). Returns ALL matches (duplicate
        names expected) with disambiguation context; CANCELLED registrations
        are excluded, tombstoned group members never match."""
        registration_service = get_registration_service()
        registrations = await registration_service.list_registrations(event.id)
        checked_in_map = await self.get_checked_in_map(event.id)

        q_lower = q.lower()
        matches: list[dict] = []

        for registration in registrations:
            if registration.status == RegistrationStatus.CANCELLED:
                continue

            candidates = [(0, registration.name)]
            for i, member_name in enumerate(registration.group_members or []):
                if member_name is not None:
                    candidates.append((i + 1, member_name))

            for person_index, person_name in candidates:
                if q_lower not in person_name.lower():
                    continue
                key = (str(registration.id), person_index)
                matches.append(
                    {
                        "registration_id": registration.id,
                        "person_index": person_index,
                        "person_name": person_name,
                        "contact_name": registration.name,
                        "group_size": registration.group_size,
                        "invite_label": registration.invite_label,
                        "tier": registration.tier,
                        "checked_in": key in checked_in_map,
                    },
                )

        logger.info(
            "Festival gate name search",
            extra={
                "flow": "festival",
                "step": "checkin_search",
                "outcome": "ok",
                "event_id": str(event.id),
                "query_len": len(q),
                "match_count": len(matches),
            },
        )
        return matches


# Singleton instance
_checkin_service: CheckinService | None = None


def get_checkin_service() -> CheckinService:
    """Get or create CheckinService instance."""
    global _checkin_service
    if _checkin_service is None:
        _checkin_service = CheckinService()
    return _checkin_service
