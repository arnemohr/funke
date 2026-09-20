"""Tests for `CheckinService` (spec 019 §P3, T306) and the T307 public
checkin router's boot lazy-generation behavior (a thin HTTP shim, so
covered here at the service level rather than via a TestClient suite).

Covers scan semantics (first scan commits, double-scan writes nothing,
distinct rejection reasons, stale-ticket index stability, Ä13 slots-never-
checked, Ä17 current-state overnight status), the Europe/Berlin sk
exception (midnight attribution), distinct-person counting, undo-within-
window, override, and that a registration's own status is never touched.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from boto3.dynamodb.conditions import Key

import app.services.registration_service as registration_service_module
from app.models import (
    Event,
    EventStatus,
    Registration,
    RegistrationStatus,
)
from app.services.checkin_service import CheckinService
from app.services.event_service import EventService, _event_to_item
from app.services.registration_service import RegistrationService, _registration_to_item
from app.services.ticket_signing import sign_ticket

NOW = datetime.now(timezone.utc)


def _festival_event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Betriebsfeier Julius Grube Schiffswerft",
        "start_at": NOW + timedelta(days=30),
        "registration_deadline": NOW + timedelta(days=32),
        "end_at": NOW + timedelta(days=32),
        "status": EventStatus.CONFIRMED,
        "gate_token": "gate-tok",
        "ticket_secret": "s3cr3t-ticket-secret",
    }
    defaults.update(overrides)
    return Event(**defaults)


def _registration(event_id, **overrides) -> Registration:
    defaults = {
        "id": uuid4(),
        "event_id": event_id,
        "name": "Max Mustermann",
        "email": "max@example.com",
        "group_size": 1,
        "status": RegistrationStatus.PARTICIPATING,
        "registration_token": f"tok-{uuid4()}",
        "registered_at": NOW,
    }
    defaults.update(overrides)
    return Registration(**defaults)


class CheckinServiceTestBase:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = CheckinService()
        self.service._table = mock_dynamodb["registrations_table"]

        reg_service = RegistrationService()
        reg_service._registrations_table = mock_dynamodb["registrations_table"]
        registration_service_module._registration_service = reg_service

        yield

        registration_service_module._registration_service = None

    def _seed(self, registration: Registration):
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))

    def _stored(self, event_id, registration_id) -> Registration:
        from app.services.registration_service import _item_to_registration

        response = self.tables["registrations_table"].get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"REG#{registration_id}"},
        )
        return _item_to_registration(response["Item"])

    def _scan_rows(self, event_id) -> list[dict]:
        response = self.tables["registrations_table"].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("SCAN#"),
        )
        return response.get("Items", [])


class TestScanSemantics(CheckinServiceTestBase):
    """First scan commits, double-scan writes nothing, override re-records."""

    @pytest.mark.asyncio
    async def test_first_scan_commits_and_returns_scan_id(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result["result"] == "green"
        assert "scan_id" in result
        assert result.get("already_checked_in") is None
        assert len(self._scan_rows(event.id)) == 1

    @pytest.mark.asyncio
    async def test_second_scan_is_already_checked_in_and_writes_nothing(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        await self.service.scan_ticket(event, code)
        second = await self.service.scan_ticket(event, code)

        assert second["already_checked_in"] is True
        assert "scan_id" not in second
        assert len(self._scan_rows(event.id)) == 1

    @pytest.mark.asyncio
    async def test_override_records_row_even_when_already_checked_in(self):
        # Two calls back-to-back within the same wall-clock second share the
        # same (registration_id, person_index) key and second-granularity sk,
        # so the override write lands on the same row rather than a fresh
        # one — the row that survives must carry override=True regardless.
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        await self.service.scan_ticket(event, code)
        overridden = await self.service.scan_ticket(event, code, override=True)

        assert overridden["result"] == "green"
        assert overridden["already_checked_in"] is True
        assert "scan_id" in overridden
        rows = self._scan_rows(event.id)
        assert len(rows) >= 1
        assert any(row["override"] for row in rows)

    @pytest.mark.asyncio
    async def test_registration_status_never_flips(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        await self.service.scan_ticket(event, code)
        await self.service.scan_ticket(event, code, override=True)

        stored = self._stored(event.id, registration.id)
        assert stored.status == RegistrationStatus.PARTICIPATING


class TestScanRejectionReasons(CheckinServiceTestBase):
    """Three distinct rejection reasons, never confused with each other."""

    @pytest.mark.asyncio
    async def test_tampered_code_is_invalid_signature(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)
        # Flip the first char of the payload segment (T304 precedent) — flipping
        # a base64 char in the tail of the mac segment can land on a padding
        # bit the decoder discards, leaving the digest unchanged and the test
        # flaky.
        prefix, payload_b64, mac_b64 = code.split(".")
        flipped_char = "A" if payload_b64[0] != "A" else "B"
        tampered = f"{prefix}.{flipped_char}{payload_b64[1:]}.{mac_b64}"

        result = await self.service.scan_ticket(event, tampered)

        assert result == {"result": "invalid", "reason": "invalid_signature"}

    @pytest.mark.asyncio
    async def test_unknown_registration(self):
        event = _festival_event()
        code = sign_ticket(event.ticket_secret, uuid4(), 0, "Nobody", None)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "unknown_registration"}

    @pytest.mark.asyncio
    async def test_validly_signed_non_int_person_index_is_rejected_not_500(self):
        """Review fix: the verification_secret is handed to every gate device
        (Risk 6), so a holder can sign a payload with p as a string ("0") —
        that must come back as a structured rejection, never raise out of
        scan_ticket (the router promises always-200)."""
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        # sign_ticket doesn't enforce the int annotation — this produces a
        # VALIDLY signed payload with {"p": "0"}.
        code = sign_ticket(event.ticket_secret, registration.id, "0", registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "unknown_registration"}
        assert self._scan_rows(event.id) == []

    @pytest.mark.asyncio
    async def test_validly_signed_bool_person_index_is_rejected(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, False, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "unknown_registration"}

    @pytest.mark.asyncio
    async def test_cancelled_registration(self):
        event = _festival_event()
        registration = _registration(event.id, status=RegistrationStatus.CANCELLED)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "cancelled"}


class TestStaleTicket(CheckinServiceTestBase):
    """Index-stability check (spec.md:289): a renamed/removed member is stale."""

    @pytest.mark.asyncio
    async def test_stale_after_rename(self):
        event = _festival_event()
        registration = _registration(
            event.id,
            group_size=2,
            group_members=["Anna Meier"],
        )
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 1, "Anna Meier", None)

        renamed = registration.model_copy(update={"group_members": ["Anna Schmidt"]})
        self._seed(renamed)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "stale_ticket"}

    @pytest.mark.asyncio
    async def test_stale_after_tombstone(self):
        event = _festival_event()
        registration = _registration(
            event.id,
            group_size=2,
            group_members=["Anna Meier"],
        )
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 1, "Anna Meier", None)

        removed = registration.model_copy(update={"group_members": [None]})
        self._seed(removed)

        result = await self.service.scan_ticket(event, code)

        assert result == {"result": "invalid", "reason": "stale_ticket"}


class TestMidnightAttribution(CheckinServiceTestBase):
    """Berlin-local sk (deliberate exception): Sa 00:30 CEST attributes to Saturday."""

    @pytest.mark.asyncio
    async def test_scan_after_midnight_attributes_to_saturday(self, monkeypatch):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)

        class _FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = datetime(2026, 8, 14, 22, 30, tzinfo=timezone.utc)
                return fixed.astimezone(tz) if tz else fixed

        monkeypatch.setattr("app.services.checkin_service.datetime", _FrozenDateTime)

        scan_id = await self.service.record_scan(event.id, registration.id, 0, registration.name)

        assert scan_id.startswith("SCAN#2026-08-15")
        assert await self.service.count_arrivals(event.id, day="2026-08-15") == 1
        assert await self.service.count_arrivals(event.id, day="2026-08-14") == 0


class TestDistinctCounting(CheckinServiceTestBase):
    """Simulated offline-sync duplicates never double-count."""

    @pytest.mark.asyncio
    async def test_duplicate_rows_for_same_person_count_once(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)

        for suffix in ("2026-08-15T00:30:00+02:00", "2026-08-15T00:30:05+02:00"):
            self.tables["registrations_table"].put_item(
                Item={
                    "pk": f"EVENT#{event.id}",
                    "sk": f"SCAN#{suffix}#{registration.id}#0",
                    "entity_type": "CheckinScan",
                    "person_name": registration.name,
                    "scanned_at": NOW.isoformat(),
                    "override": False,
                },
            )

        assert await self.service.count_arrivals(event.id) == 1
        checked_in_map = await self.service.get_checked_in_map(event.id)
        assert len(checked_in_map) == 1
        assert (str(registration.id), 0) in checked_in_map


class TestArrivalsSummary(CheckinServiceTestBase):
    """T313: admin arrival board — distinct persons, total + per gate day."""

    @pytest.mark.asyncio
    async def test_total_and_per_day_match_count_arrivals(self):
        event = _festival_event()
        reg1 = _registration(event.id)
        reg2 = _registration(event.id)
        self._seed(reg1)
        self._seed(reg2)

        self.tables["registrations_table"].put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"SCAN#2026-08-14T20:00:00+02:00#{reg1.id}#0",
                "entity_type": "CheckinScan",
                "person_name": reg1.name,
                "scanned_at": NOW.isoformat(),
                "override": False,
            },
        )
        self.tables["registrations_table"].put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"SCAN#2026-08-15T09:00:00+02:00#{reg2.id}#0",
                "entity_type": "CheckinScan",
                "person_name": reg2.name,
                "scanned_at": NOW.isoformat(),
                "override": False,
            },
        )

        summary = await self.service.get_arrivals_summary(event.id)

        assert summary["total"] == 2 == await self.service.count_arrivals(event.id)
        assert summary["per_day"] == {"2026-08-14": 1, "2026-08-15": 1}
        assert summary["per_day"]["2026-08-14"] == await self.service.count_arrivals(event.id, day="2026-08-14")
        assert summary["per_day"]["2026-08-15"] == await self.service.count_arrivals(event.id, day="2026-08-15")

    @pytest.mark.asyncio
    async def test_duplicate_sync_row_pair_still_counts_once(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)

        for suffix in ("2026-08-15T00:30:00+02:00", "2026-08-15T00:30:05+02:00"):
            self.tables["registrations_table"].put_item(
                Item={
                    "pk": f"EVENT#{event.id}",
                    "sk": f"SCAN#{suffix}#{registration.id}#0",
                    "entity_type": "CheckinScan",
                    "person_name": registration.name,
                    "scanned_at": NOW.isoformat(),
                    "override": False,
                },
            )

        summary = await self.service.get_arrivals_summary(event.id)

        assert summary["total"] == 1
        assert summary["per_day"] == {"2026-08-15": 1}

    @pytest.mark.asyncio
    async def test_no_scans_returns_zero_total_and_empty_per_day(self):
        event = _festival_event()
        summary = await self.service.get_arrivals_summary(event.id)
        assert summary == {"total": 0, "per_day": {}}


class TestUndoScan(CheckinServiceTestBase):
    @pytest.mark.asyncio
    async def test_undo_within_window_deletes_row(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)
        result = await self.service.scan_ticket(event, code)

        ok = await self.service.undo_scan(event.id, result["scan_id"])

        assert ok is True
        assert self._scan_rows(event.id) == []

    @pytest.mark.asyncio
    async def test_undo_outside_window_returns_false_and_row_survives(self):
        event = _festival_event()
        registration = _registration(event.id)
        self._seed(registration)

        backdated = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        sk = f"SCAN#2026-08-15T00:30:00+02:00#{registration.id}#0"
        self.tables["registrations_table"].put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": sk,
                "entity_type": "CheckinScan",
                "person_name": registration.name,
                "scanned_at": backdated,
                "override": False,
            },
        )

        ok = await self.service.undo_scan(event.id, sk)

        assert ok is False
        assert len(self._scan_rows(event.id)) == 1

    @pytest.mark.asyncio
    async def test_undo_unknown_scan_id_returns_false(self):
        event = _festival_event()
        ok = await self.service.undo_scan(event.id, "SCAN#nope#nope#0")
        assert ok is False


class TestOvernightStatus(CheckinServiceTestBase):
    """Ä17: card renders the CURRENT registration's overnight status, not the ticket payload."""

    @pytest.mark.asyncio
    async def test_approved_camper(self):
        event = _festival_event()
        registration = _registration(
            event.id,
            camper_count=2,
            overnight_approved=True,
        )
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result["card"]["overnight_status"] == "approved"
        # Ä21: separate counts reach the gate card so staff can verify pitches.
        assert result["card"]["camper_count"] == 2
        assert result["card"]["tent_count"] is None

    @pytest.mark.asyncio
    async def test_requested_not_approved(self):
        event = _festival_event()
        registration = _registration(
            event.id, tent_count=1, overnight_approved=False,
        )
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result["card"]["overnight_status"] == "requested"

    @pytest.mark.asyncio
    async def test_none_when_no_accommodation(self):
        event = _festival_event()
        registration = _registration(event.id, tent_count=None, camper_count=None)
        self._seed(registration)
        code = sign_ticket(event.ticket_secret, registration.id, 0, registration.name, None)

        result = await self.service.scan_ticket(event, code)

        assert result["card"]["overnight_status"] == "none"
        assert result["card"]["tent_count"] is None
        assert result["card"]["camper_count"] is None

    @pytest.mark.asyncio
    async def test_approval_after_signing_flips_the_card_on_next_scan(self):
        event = _festival_event()
        registration = _registration(
            event.id, tent_count=1, overnight_approved=False,
        )
        self._seed(registration)
        # Signed while only "requested" — the offline `o` flag would be False.
        code = sign_ticket(
            event.ticket_secret, registration.id, 0, registration.name, None,
            overnight_approved=False,
        )

        first = await self.service.scan_ticket(event, code)
        assert first["card"]["overnight_status"] == "requested"

        approved = registration.model_copy(update={"overnight_approved": True})
        self._seed(approved)

        second = await self.service.scan_ticket(event, code, override=True)
        assert second["card"]["overnight_status"] == "approved"


class TestCheckinPerson(CheckinServiceTestBase):
    """Name-search check-in target: always a specific (registration_id, person_index)."""

    @pytest.mark.asyncio
    async def test_checkin_person_records_scan(self):
        event = _festival_event()
        registration = _registration(event.id, group_size=2, group_members=["Ben Otto"])
        self._seed(registration)

        result = await self.service.checkin_person(event, registration.id, 1)

        assert result["result"] == "green"
        assert "scan_id" in result
        checked_in_map = await self.service.get_checked_in_map(event.id)
        assert (str(registration.id), 1) in checked_in_map


class TestSearchNames(CheckinServiceTestBase):
    @pytest.mark.asyncio
    async def test_search_returns_all_matches_with_context(self):
        event = _festival_event()
        r1 = _registration(event.id, name="Anna Meier", invite_label="Werft", tier="werft")
        r2 = _registration(event.id, name="Anna Schmidt", email="anna2@example.com")
        self._seed(r1)
        self._seed(r2)

        matches = await self.service.search_names(event, "anna")

        assert len(matches) == 2
        names = {m["person_name"] for m in matches}
        assert names == {"Anna Meier", "Anna Schmidt"}

    @pytest.mark.asyncio
    async def test_search_excludes_cancelled(self):
        event = _festival_event()
        registration = _registration(event.id, name="Anna Meier", status=RegistrationStatus.CANCELLED)
        self._seed(registration)

        matches = await self.service.search_names(event, "anna")

        assert matches == []


class TestBootLazyGeneration(CheckinServiceTestBase):
    """T307: the checkin boot endpoint is a thin shim over
    `ensure_gate_credentials` — this is the service-level equivalent of
    exercising `GET /checkin/{gate_token}` on an event that has never had
    its gate link opened before (no `ticket_secret` set yet)."""

    @pytest.mark.asyncio
    async def test_boot_lazily_generates_ticket_secret(self):
        event = _festival_event(gate_token=None, ticket_secret=None)
        event_service = EventService()
        event_service._table = self.tables["events_table"]
        event_service.table.put_item(Item=_event_to_item(event))

        assert event.ticket_secret is None

        ensured = await event_service.ensure_gate_credentials(event.org_id, event.id)

        assert ensured.gate_token is not None
        assert ensured.ticket_secret is not None

        # Idempotent — a second boot call returns the same secret.
        again = await event_service.ensure_gate_credentials(event.org_id, event.id)
        assert again.ticket_secret == ensured.ticket_secret
