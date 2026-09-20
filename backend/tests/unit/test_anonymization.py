"""Tests for `AnonymizationService` (spec 022).

Anonymisation is the replacement for the old hard-delete sweep: every row
survives, every personal field becomes a stable pseudonym. So the tests come
in two halves — "nothing identifying is left" and "everything countable is
still there" — plus the guards that decide when it may run at all.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from boto3.dynamodb.conditions import Key

from app.models import (
    Event,
    EventStatus,
    EventType,
    Invite,
    Message,
    MessageStatus,
    MessageType,
    Registration,
    RegistrationStatus,
)
from app.services import anonymization_service
from app.services.anonymization_service import (
    AnonymizationService,
    _Pass,
    person_pseudonym,
    person_pseudonym_email,
)
from app.services.checkin_service import CheckinService
from app.services.email_service import _message_to_item
from app.services.event_service import EventService, _event_to_item
from app.services.invite_service import _invite_to_item
from app.services.registration_service import _item_to_registration, _registration_to_item

NOW = datetime.now(timezone.utc)

# Every string a scrubbed table must not contain any more.
PERSONAL_STRINGS = [
    "Max Mustermann",
    "max@example.com",
    "Erika Beispiel",
    "erika@example.com",
    "+49 170 1234567",
    "Bringt einen Hund mit",
    "Aline Werft",
    "aline@example.com",
]


def _festival_event(**overrides) -> Event:
    defaults = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Betriebsfeier Julius Grube Schiffswerft",
        "event_type": EventType.FESTIVAL,
        "start_at": NOW - timedelta(days=200),
        "registration_deadline": NOW - timedelta(days=198),
        "end_at": NOW - timedelta(days=198),
        "status": EventStatus.COMPLETED,
        "capacity": 500,
        "registration_link_token": f"link-{uuid4()}",
        "gate_token": f"gate-{uuid4()}",
        "ticket_secret": f"secret-{uuid4()}",
        "festival_slots": [
            {"key": "fr", "label": "Freitag", "date": (NOW - timedelta(days=199)).date()},
        ],
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestAnonymizeEvent:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.tables = mock_dynamodb
        self.service = AnonymizationService()
        self.service._events_table = mock_dynamodb["events_table"]
        self.service._registrations_table = mock_dynamodb["registrations_table"]
        self.service._messages_table = mock_dynamodb["messages_table"]

        self.event_service = EventService()
        self.event_service._table = mock_dynamodb["events_table"]

        self.checkin_service = CheckinService()
        self.checkin_service._table = mock_dynamodb["registrations_table"]

    # -- seeding --------------------------------------------------------------

    def _seed_event(self, event: Event) -> None:
        self.tables["events_table"].put_item(Item=_event_to_item(event))

    def _seed_invite(self, event: Event) -> Invite:
        invite = Invite(
            event_id=event.id,
            org_id=event.org_id,
            token=f"tok-{uuid4()}",
            label="Aline Werft",
            batch_label="Werft 2026",
            email="aline@example.com",
            tier="werft",
            max_uses=12,
            use_count=7,
        )
        self.tables["events_table"].put_item(Item=_invite_to_item(invite))
        return invite

    def _seed_registration(self, event: Event, **overrides) -> Registration:
        defaults = {
            "id": uuid4(),
            "event_id": event.id,
            "name": "Max Mustermann",
            "email": "max@example.com",
            "phone": "+49 170 1234567",
            "notes": "Bringt einen Hund mit",
            "group_size": 3,
            "group_members": ["Erika Beispiel", None, "Aline Werft"],
            "group_member_emails": ["erika@example.com", None, None],
            "status": RegistrationStatus.PARTICIPATING,
            "registration_token": f"tok-{uuid4()}",
            "registered_at": NOW - timedelta(days=210),
            "attendance_slots": ["fr"],
            "tent_count": 2,
            "overnight_approved": True,
            "tier": "werft",
            "invite_label": "Aline Werft",
        }
        defaults.update(overrides)
        registration = Registration(**defaults)
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))
        return registration

    def _seed_message(self, event: Event, **overrides) -> Message:
        defaults = {
            "event_id": event.id,
            "type": MessageType.FESTIVAL_CONFIRMATION,
            "subject": "Dein Ticket, Max Mustermann",
            "body": "Moin Max Mustermann, hier ist dein Code.",
            "body_html": "<p>Moin Max Mustermann</p>",
            "recipient_email": "max@example.com",
            "list_unsubscribe": "<https://example.com/u/secret-token>",
            "status": MessageStatus.SENT,
            "sent_at": NOW - timedelta(days=205),
        }
        defaults.update(overrides)
        message = Message(**defaults)
        self.tables["messages_table"].put_item(Item=_message_to_item(message))
        return message

    async def _seed_scan(self, event: Event, registration: Registration, index: int = 0) -> str:
        name = registration.name if index == 0 else (registration.group_members or [])[index - 1]
        return await self.checkin_service.record_scan(event.id, registration.id, index, name)

    # -- reading back ---------------------------------------------------------

    def _rows(self, table_key: str, event_id, prefix: str) -> list[dict]:
        resp = self.tables[table_key].query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with(prefix),
        )
        return resp.get("Items", [])

    def _event_row(self, event: Event) -> dict:
        resp = self.tables["events_table"].get_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        )
        return resp["Item"]

    def _all_text(self, event_id) -> str:
        """Everything the event owns, flattened to one blob for substring checks."""
        chunks = [
            self._rows("registrations_table", event_id, "REG#"),
            self._rows("registrations_table", event_id, "SCAN#"),
            self._rows("events_table", event_id, "INVITE#"),
            self._rows("messages_table", event_id, "MSG#"),
        ]
        return repr(chunks)

    # -- the scrub ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_personal_data_survives_anywhere(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_invite(event)
        registration = self._seed_registration(event)
        await self._seed_scan(event, registration, 0)
        await self._seed_scan(event, registration, 1)
        self._seed_message(event)

        result = await self.service.anonymize_event(event)

        blob = self._all_text(event.id)
        for needle in PERSONAL_STRINGS:
            assert needle not in blob, f"{needle!r} survived anonymization"

        assert result.registrations == 1
        assert result.scans == 2
        assert result.invites == 1
        assert result.messages == 1
        assert result.rows_touched == 5

    @pytest.mark.asyncio
    async def test_aggregate_data_survives(self):
        """The whole point of anonymising instead of deleting."""
        event = _festival_event()
        self._seed_event(event)
        self._seed_invite(event)
        self._seed_registration(event)

        await self.service.anonymize_event(event)

        reg = _item_to_registration(self._rows("registrations_table", event.id, "REG#")[0])
        assert reg.group_size == 3
        assert reg.status == RegistrationStatus.PARTICIPATING
        assert reg.attendance_slots == ["fr"]
        assert reg.tent_count == 2
        assert reg.overnight_approved is True
        assert reg.tier == "werft"

        invite_row = self._rows("events_table", event.id, "INVITE#")[0]
        assert invite_row["tier"] == "werft"
        assert invite_row["batch_label"] == "Werft 2026"
        assert int(invite_row["use_count"]) == 7
        assert int(invite_row["max_uses"]) == 12

    @pytest.mark.asyncio
    async def test_registration_pseudonyms_and_tombstones(self):
        event = _festival_event()
        self._seed_event(event)
        registration = self._seed_registration(event)

        await self.service.anonymize_event(event)

        reg = _item_to_registration(self._rows("registrations_table", event.id, "REG#")[0])
        reg_id = str(registration.id)

        assert reg.name == person_pseudonym(reg_id, 0)
        assert reg.email == person_pseudonym_email(reg_id, 0)
        assert reg.phone is None
        assert reg.notes is None
        # Index stability: the tombstone at index 1 stays a tombstone, so
        # person_index 3 still refers to the third companion.
        assert reg.group_members == [
            person_pseudonym(reg_id, 1),
            None,
            person_pseudonym(reg_id, 3),
        ]
        assert reg.group_member_emails is None
        assert reg.invite_label is None

    @pytest.mark.asyncio
    async def test_pseudonym_is_two_words_so_patches_still_validate(self):
        """`FestivalAttendancePatch` rejects single-word names — an anonymised
        registration must not become un-editable."""
        assert len(person_pseudonym(str(uuid4()), 0).split()) >= 2

    @pytest.mark.asyncio
    async def test_scan_log_gets_the_same_pseudonym_as_the_registration(self):
        event = _festival_event()
        self._seed_event(event)
        registration = self._seed_registration(event)
        await self._seed_scan(event, registration, 0)
        await self._seed_scan(event, registration, 1)

        await self.service.anonymize_event(event)

        reg = _item_to_registration(self._rows("registrations_table", event.id, "REG#")[0])
        scan_names = {row["person_name"] for row in self._rows("registrations_table", event.id, "SCAN#")}
        assert scan_names == {reg.name, (reg.group_members or [])[0]}

    @pytest.mark.asyncio
    async def test_tokens_are_rotated_so_old_links_die(self):
        event = _festival_event()
        self._seed_event(event)
        invite = self._seed_invite(event)
        registration = self._seed_registration(event)

        await self.service.anonymize_event(event)

        reg_row = self._rows("registrations_table", event.id, "REG#")[0]
        assert reg_row["registration_token"] != registration.registration_token
        assert reg_row["registration_token"].startswith("anon-")

        invite_row = self._rows("events_table", event.id, "INVITE#")[0]
        assert invite_row["invite_token"] != invite.token
        assert invite_row["revoked_at"]

        event_row = self._event_row(event)
        assert "registration_link_token" not in event_row
        assert "gate_token" not in event_row
        assert "ticket_secret" not in event_row

    @pytest.mark.asyncio
    async def test_message_content_stripped_metadata_kept(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_message(event)

        await self.service.anonymize_event(event)

        row = self._rows("messages_table", event.id, "MSG#")[0]
        assert row["subject"] == "[anonymisiert]"
        assert row["body"] == ""
        assert "body_html" not in row
        assert "recipient_email" not in row
        assert "list_unsubscribe" not in row
        # The send audit trail survives — it names nobody.
        assert row["type"] == MessageType.FESTIVAL_CONFIRMATION.value
        assert row["status"] == MessageStatus.SENT.value
        assert row["sent_at"]

    @pytest.mark.asyncio
    async def test_unsent_messages_are_neutralised(self):
        """A scrubbed message must never reach the wire: the queue worker picks
        up QUEUED, and the retry worker needs retry_count < 3."""
        event = _festival_event()
        self._seed_event(event)
        self._seed_message(event, status=MessageStatus.QUEUED, sent_at=None)

        await self.service.anonymize_event(event)

        row = self._rows("messages_table", event.id, "MSG#")[0]
        assert row["status"] == MessageStatus.FAILED.value
        assert row["error_code"] == "anonymized"
        assert int(row["retry_count"]) >= 3

    # -- guards ---------------------------------------------------------------

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_status",
        [EventStatus.DRAFT, EventStatus.OPEN, EventStatus.REGISTRATION_CLOSED,
         EventStatus.LOTTERY_PENDING, EventStatus.CONFIRMED],
    )
    async def test_refuses_unfinished_events(self, bad_status):
        event = _festival_event(status=bad_status)
        self._seed_event(event)
        self._seed_registration(event)

        with pytest.raises(ValueError, match="anonymisiert"):
            await self.service.anonymize_event(event)

        row = self._rows("registrations_table", event.id, "REG#")[0]
        assert row["name"] == "Max Mustermann"

    @pytest.mark.asyncio
    async def test_cancelled_events_qualify(self):
        event = _festival_event(status=EventStatus.CANCELLED, cancelled_at=NOW - timedelta(days=100))
        self._seed_event(event)
        self._seed_registration(event)

        result = await self.service.anonymize_event(event)
        assert result.registrations == 1

    @pytest.mark.asyncio
    async def test_second_run_is_a_noop(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_registration(event)

        first = await self.service.anonymize_event(event)
        reloaded = await self.event_service.get_event(event.org_id, event.id)
        assert reloaded.anonymized_at is not None

        token_after_first = self._rows("registrations_table", event.id, "REG#")[0][
            "registration_token"
        ]

        second = await self.service.anonymize_event(reloaded)
        assert second.already_anonymized is True
        assert second.rows_touched == 0
        assert second.anonymized_at == first.anonymized_at
        # Crucially, the token was not rotated a second time.
        assert (
            self._rows("registrations_table", event.id, "REG#")[0]["registration_token"]
            == token_after_first
        )

    @pytest.mark.asyncio
    async def test_other_events_are_untouched(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_registration(event)

        other = _festival_event()
        self._seed_event(other)
        self._seed_invite(other)
        other_reg = self._seed_registration(other)
        await self._seed_scan(other, other_reg, 0)
        self._seed_message(other)

        await self.service.anonymize_event(event)

        assert self._rows("registrations_table", other.id, "REG#")[0]["name"] == "Max Mustermann"
        assert self._rows("events_table", other.id, "INVITE#")[0]["email"] == "aline@example.com"
        assert self._rows("messages_table", other.id, "MSG#")[0]["recipient_email"] == "max@example.com"
        assert self._rows("registrations_table", other.id, "SCAN#")[0]["person_name"] == "Max Mustermann"
        assert self._event_row(other)["gate_token"]

    @pytest.mark.asyncio
    async def test_registration_without_group_still_works(self):
        event = _festival_event()
        self._seed_event(event)
        self._seed_registration(event, group_size=1, group_members=None, group_member_emails=None)

        await self.service.anonymize_event(event)

        reg = _item_to_registration(self._rows("registrations_table", event.id, "REG#")[0])
        assert reg.group_members is None
        assert reg.name.startswith("Gast ")

    @pytest.mark.asyncio
    async def test_anonymized_at_round_trips_through_the_event_item(self):
        event = _festival_event()
        self._seed_event(event)

        assert (await self.event_service.get_event(event.org_id, event.id)).is_anonymized is False
        await self.service.anonymize_event(event)
        reloaded = await self.event_service.get_event(event.org_id, event.id)
        assert reloaded.is_anonymized is True
        assert isinstance(reloaded.anonymized_at, datetime)

    # -- passes over a big event ----------------------------------------------
    #
    # An event with thousands of rows cannot be rewritten inside one API Gateway
    # request; it comes back `completed=False` and gets called again. Rather than
    # seeding thousands of rows and racing a real clock, these tests cut the pass
    # short at a chosen point by faking the deadline check.

    def _truncate_after(self, monkeypatch, checks: int) -> None:
        """Let `checks` deadline checks pass, then behave as if time ran out."""
        seen = {"n": 0}

        def fake_stop(pass_state):
            seen["n"] += 1
            if seen["n"] > checks:
                pass_state.truncated = True
            return pass_state.truncated

        monkeypatch.setattr(_Pass, "stop", fake_stop)
        # One row per write chunk, so the cut can land between two rows.
        monkeypatch.setattr(anonymization_service, "_WRITE_CHUNK", 1)

    @pytest.mark.asyncio
    async def test_expired_deadline_does_not_stamp_the_event(self, monkeypatch):
        event = _festival_event()
        self._seed_event(event)
        self._seed_registration(event)

        result = await self.service.anonymize_event(
            event,
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert result.completed is False
        assert result.anonymized_at is None
        assert result.rows_touched == 0
        # Not stamped, so the event stays a candidate — and its own tokens live.
        reloaded = await self.event_service.get_event(event.org_id, event.id)
        assert reloaded.is_anonymized is False
        assert self._event_row(event)["gate_token"]

    @pytest.mark.asyncio
    async def test_truncated_pass_keeps_the_rows_it_finished(self, monkeypatch):
        event = _festival_event()
        self._seed_event(event)
        for _ in range(3):
            self._seed_registration(event)
        self._seed_message(event)

        self._truncate_after(monkeypatch, checks=2)
        first = await self.service.anonymize_event(event, deadline=NOW)

        assert first.completed is False
        # Registrations come first, so a short pass spends its budget on the
        # rows that hold the names.
        assert first.registrations == 1
        assert first.messages == 0
        scrubbed = [
            row for row in self._rows("registrations_table", event.id, "REG#")
            if row["name"] != "Max Mustermann"
        ]
        assert len(scrubbed) == 1

    @pytest.mark.asyncio
    async def test_a_resumed_pass_finishes_the_event(self, monkeypatch):
        event = _festival_event()
        self._seed_event(event)
        registration = self._seed_registration(event)
        for _ in range(2):
            self._seed_registration(event)
        await self._seed_scan(event, registration, 0)
        self._seed_invite(event)
        self._seed_message(event)

        self._truncate_after(monkeypatch, checks=2)
        first = await self.service.anonymize_event(event, deadline=NOW)
        assert first.completed is False

        monkeypatch.undo()
        second = await self.service.anonymize_event(event)

        assert second.completed is True
        assert second.anonymized_at is not None
        # Only what pass one left over — the counters are per pass, so the two
        # add up to the event's row count instead of double-counting it.
        assert second.registrations == 2
        assert second.scans == 1
        assert second.invites == 1
        assert second.messages == 1
        for personal in PERSONAL_STRINGS:
            assert personal not in self._all_text(event.id)

    @pytest.mark.asyncio
    async def test_a_resumed_pass_leaves_finished_rows_alone(self, monkeypatch):
        """Re-reading a scrubbed row must not rotate its token a second time.

        The done-check is "this row already holds the pseudonym I was going to
        write" — if it ever stopped matching, every pass would churn every row
        it had already done.
        """
        event = _festival_event()
        self._seed_event(event)
        for _ in range(3):
            self._seed_registration(event)

        self._truncate_after(monkeypatch, checks=2)
        await self.service.anonymize_event(event, deadline=NOW)
        done = {
            row["sk"]: row["registration_token"]
            for row in self._rows("registrations_table", event.id, "REG#")
            if row["name"] != "Max Mustermann"
        }
        assert len(done) == 1

        monkeypatch.undo()
        await self.service.anonymize_event(event)

        after = {
            row["sk"]: row["registration_token"]
            for row in self._rows("registrations_table", event.id, "REG#")
        }
        for sk, token in done.items():
            assert after[sk] == token

    @pytest.mark.asyncio
    async def test_many_rows_are_scrubbed_concurrently(self):
        """Exercises the write pool with more rows than it has threads.

        Small counts never leave the first worker, so this is the one test that
        would notice the concurrent path mangling or dropping a row.
        """
        event = _festival_event()
        self._seed_event(event)
        registrations = [self._seed_registration(event) for _ in range(40)]
        for registration in registrations[:10]:
            await self._seed_scan(event, registration, 0)

        result = await self.service.anonymize_event(event)

        assert result.completed is True
        assert result.registrations == 40
        assert result.scans == 10
        rows = self._rows("registrations_table", event.id, "REG#")
        assert len(rows) == 40
        # Every row got its own pseudonym, and no row was left behind.
        assert {row["name"] for row in rows} == {
            person_pseudonym(str(registration.id), 0) for registration in registrations
        }
        for personal in PERSONAL_STRINGS:
            assert personal not in self._all_text(event.id)

    @pytest.mark.asyncio
    async def test_repeating_an_unfinished_event_is_idempotent(self):
        """A full re-run before the stamp lands must be a no-op, not a rewrite."""
        event = _festival_event()
        self._seed_event(event)
        registration = self._seed_registration(event)
        await self._seed_scan(event, registration, 2)
        self._seed_invite(event)
        self._seed_message(event)

        await self.service.anonymize_event(event)
        before = self._all_text(event.id)

        # `event` is the pre-scrub object, so this walks every row again exactly
        # as a resumed pass would.
        again = await self.service.anonymize_event(event)

        assert again.rows_touched == 0
        assert self._all_text(event.id) == before


class TestPseudonyms:
    def test_deterministic(self):
        reg_id = str(uuid4())
        assert person_pseudonym(reg_id, 2) == person_pseudonym(reg_id, 2)

    def test_distinct_per_person_and_per_registration(self):
        a, b = str(uuid4()), str(uuid4())
        assert person_pseudonym(a, 0) != person_pseudonym(a, 1)
        assert person_pseudonym(a, 0) != person_pseudonym(b, 0)

    def test_email_uses_the_reserved_tld(self):
        """RFC 2606 `.invalid` never resolves — and pydantic's EmailStr rejects
        it, so nothing in the codebase can accidentally try to send there."""
        assert person_pseudonym_email(str(uuid4()), 0).endswith("@invalid")
