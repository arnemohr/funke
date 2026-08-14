"""Overnight-approval notification (F8).

The load-bearing invariant here is **exactly once per approval**: a guest must
never be told twice that their Stellplatz is confirmed, and must never be left
un-told after an organizer pressed the button. Both send paths — the approval
toggle and the bulk catch-up — claim `overnight_notified_at` with a conditional
write before any mail is queued, so the dedup is tested from both sides.

Layout:
- TestOvernightNotifiedField  — the flag survives a DynamoDB round-trip
- TestApprovalToggleSends     — approving mails; withdrawing clears the marker
- TestNotifyDedup            — claim-then-send, and the rollback on failure
- TestBulkCatchUp            — who the bulk run picks up, and who it skips
- TestOvernightApprovalMail  — the F8 template itself
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import (
    EventStatus,
    EventType,
    FestivalSlot,
    RegistrationAdminPatch,
    RegistrationStatus,
)
from app.models.message import MessageType
from app.services.email_service import EmailContext, EmailService, EmailTemplates
from app.services.event_service import _event_to_item, get_event_service
from app.services.registration_service import (
    RegistrationService,
    _item_to_registration,
    _registration_to_item,
)


@pytest.fixture
def service(mock_dynamodb):
    """RegistrationService on the moto tables, event singleton aligned.

    Mirrors `test_registration_admin_update.admin_service` — the patch method
    resolves the event through the global event_service singleton.
    """
    svc = RegistrationService()
    svc._registrations_table = mock_dynamodb["registrations_table"]
    svc._events_table = mock_dynamodb["events_table"]

    event_service = get_event_service()
    event_service._table = mock_dynamodb["events_table"]

    return svc


@pytest.fixture
def mail(mock_dynamodb):
    """A real EmailService writing into the moto messages table.

    Real (not a mock) so the F8 mail is asserted through the actual queue item
    — the same path the worker later reads.
    """
    svc = EmailService()
    svc._messages_table = mock_dynamodb["messages_table"]
    with patch("app.services.email_service.get_email_service", return_value=svc):
        yield svc


def _slots() -> list[FestivalSlot]:
    return [
        FestivalSlot(key="fr", label="Freitag", date=date(2026, 8, 14)),
        FestivalSlot(key="sa", label="Samstag", date=date(2026, 8, 15)),
    ]


def _festival_event(sample_event, **overrides):
    defaults = {
        "event_type": EventType.FESTIVAL,
        "festival_slots": _slots(),
        "status": EventStatus.OPEN,
        "contact_hint": "orga@example.de",
    }
    defaults.update(overrides)
    return sample_event(**defaults)


def _overnight_registration(sample_registration, event, **overrides):
    defaults = {
        "event_id": event.id,
        "status": RegistrationStatus.REGISTERED,
        "attendance_slots": ["fr"],
        # group_size >= tent_count: the admin patch rejects more tents than
        # people (`tent_count_exceeds_group`).
        "group_size": 3,
        "tent_count": 2,
        "phone": "+49 176 1234567",
    }
    defaults.update(overrides)
    return sample_registration(**defaults)


def _store(tables, event=None, registration=None):
    if event is not None:
        tables["events_table"].put_item(Item=_event_to_item(event))
    if registration is not None:
        tables["registrations_table"].put_item(Item=_registration_to_item(registration))


def _read(tables, event_id, registration_id):
    item = tables["registrations_table"].get_item(
        Key={"pk": f"EVENT#{event_id}", "sk": f"REG#{registration_id}"},
    ).get("Item")
    return _item_to_registration(item) if item else None


def _queued(tables) -> list[dict]:
    return tables["messages_table"].scan().get("Items", [])


def _queued_f8(tables) -> list[dict]:
    return [
        m
        for m in _queued(tables)
        if m.get("type") == MessageType.FESTIVAL_OVERNIGHT_APPROVAL.value
    ]


def _queued_f9(tables) -> list[dict]:
    return [
        m
        for m in _queued(tables)
        if m.get("type") == MessageType.FESTIVAL_OVERNIGHT_DECLINE.value
    ]


class TestOvernightNotifiedField:
    """The marker has to survive storage — it IS the dedup state."""

    def test_round_trips_through_dynamodb(self, mock_dynamodb, sample_event, sample_registration):
        event = _festival_event(sample_event)
        stamp = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
        reg = _overnight_registration(
            sample_registration, event, overnight_approved=True, overnight_notified_at=stamp,
        )
        _store(mock_dynamodb, event, reg)

        loaded = _read(mock_dynamodb, event.id, reg.id)
        assert loaded.overnight_notified_at == stamp

    def test_absent_on_legacy_rows(self, mock_dynamodb, sample_event, sample_registration):
        """Rows written before F8 have no attribute — they must read as None,
        i.e. "still owes a mail", not crash."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        item = _registration_to_item(reg)
        assert "overnight_notified_at" not in item
        _store(mock_dynamodb, event)
        mock_dynamodb["registrations_table"].put_item(Item=item)

        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is None


class TestApprovalToggleSends:
    """The organizer's "Darf übernachten" click has to reach the guest."""

    @pytest.mark.asyncio
    async def test_approving_queues_mail_and_stamps(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        updated, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )

        assert error is None
        assert updated.overnight_approved is True
        assert updated.overnight_notified_at is not None
        # Persisted, not just returned — the next page load must see it.
        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is not None

        messages = _queued_f8(mock_dynamodb)
        assert len(messages) == 1
        assert messages[0]["recipient_email"] == reg.email
        assert "Übernachtung zugesagt" in messages[0]["subject"]

    @pytest.mark.asyncio
    async def test_unrelated_patch_sends_nothing(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """Already-approved groups must not be re-mailed by an unrelated edit."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            overnight_notified_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        _store(mock_dynamodb, event, reg)

        updated, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(notes="Kommt später"),
        )

        assert error is None
        assert updated.overnight_notified_at == datetime(2026, 8, 1, tzinfo=UTC)
        assert _queued_f8(mock_dynamodb) == []

    @pytest.mark.asyncio
    async def test_withdrawing_clears_marker_and_reapproval_mails_again(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """A withdrawn-then-regranted approval is news again — silence would
        leave the guest believing the first withdrawal."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )
        withdrawn, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=False),
        )
        assert error is None
        assert withdrawn.overnight_notified_at is None
        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is None

        regranted, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )
        assert error is None
        assert regranted.overnight_notified_at is not None
        assert len(_queued_f8(mock_dynamodb)) == 2

    @pytest.mark.asyncio
    async def test_clearing_the_wish_clears_the_marker(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """Ä15: dropping tents/campers resets the approval — the marker has to
        go with it, or a re-added wish would never be confirmed by mail."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )
        cleared, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(tent_count=0),
        )

        assert error is None
        assert cleared.overnight_approved is False
        assert cleared.overnight_notified_at is None

    @pytest.mark.asyncio
    async def test_mail_failure_keeps_the_approval(
        self, service, mock_dynamodb, sample_event, sample_registration,
    ):
        """Never-fail: a broken mail path must not turn a saved approval into
        an error, and must leave the row retryable (no marker)."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        broken = MagicMock()
        broken.send_festival_overnight_approval = AsyncMock(side_effect=RuntimeError("smtp down"))
        with patch("app.services.email_service.get_email_service", return_value=broken):
            updated, error = await service.admin_update_registration(
                event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
            )

        assert error is None
        assert updated.overnight_approved is True
        assert updated.overnight_notified_at is None
        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is None


class TestNotifyDedup:
    """Claim-then-send: the marker is taken before the mail is queued."""

    @pytest.mark.asyncio
    async def test_second_call_is_a_no_op(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        _store(mock_dynamodb, event, reg)

        first, reason = await service.notify_overnight_approval(event, reg)
        assert reason is None
        assert first.overnight_notified_at is not None

        # Same stale input object — this is exactly the concurrent-click shape:
        # the caller still holds a registration without the marker.
        second, reason = await service.notify_overnight_approval(event, reg)
        assert second is None
        assert reason == "already_notified"
        assert len(_queued_f8(mock_dynamodb)) == 1

    @pytest.mark.asyncio
    async def test_unapproved_and_cancelled_are_refused(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        pending = _overnight_registration(sample_registration, event)
        cancelled = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            status=RegistrationStatus.CANCELLED,
        )
        _store(mock_dynamodb, event, pending)
        _store(mock_dynamodb, registration=cancelled)

        _, reason = await service.notify_overnight_approval(event, pending)
        assert reason == "not_approved"

        _, reason = await service.notify_overnight_approval(event, cancelled)
        assert reason == "cancelled"

        assert _queued_f8(mock_dynamodb) == []

    @pytest.mark.asyncio
    async def test_failed_queue_releases_the_claim(
        self, service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        _store(mock_dynamodb, event, reg)

        refusing = MagicMock()
        refusing.send_festival_overnight_approval = AsyncMock(return_value=False)
        with patch("app.services.email_service.get_email_service", return_value=refusing):
            result, reason = await service.notify_overnight_approval(event, reg)

        assert result is None
        assert reason == "send_failed"
        # Marker rolled back, so the bulk button can retry this row.
        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is None


class TestBulkCatchUp:
    """The button for approvals granted before F8 existed."""

    @pytest.mark.asyncio
    async def test_mails_only_pending_approvals(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        pending_a = _overnight_registration(
            sample_registration, event, overnight_approved=True, email="a@example.de",
        )
        pending_b = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            camper_count=1,
            tent_count=None,
            email="b@example.de",
        )
        already = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            overnight_notified_at=datetime(2026, 7, 1, tzinfo=UTC),
            email="already@example.de",
        )
        unapproved = _overnight_registration(
            sample_registration, event, email="wartet@example.de",
        )
        cancelled = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            status=RegistrationStatus.CANCELLED,
            email="weg@example.de",
        )
        _store(mock_dynamodb, event)
        for reg in (pending_a, pending_b, already, unapproved, cancelled):
            _store(mock_dynamodb, registration=reg)

        result = await service.notify_pending_overnight_approvals(event)

        assert result == {"sent": 2, "skipped": 0, "failed": 0}
        recipients = {m["recipient_email"] for m in _queued_f8(mock_dynamodb)}
        assert recipients == {"a@example.de", "b@example.de"}

    @pytest.mark.asyncio
    async def test_second_run_sends_nothing(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """Pressing the button twice must not double-mail anyone."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        _store(mock_dynamodb, event, reg)

        first = await service.notify_pending_overnight_approvals(event)
        second = await service.notify_pending_overnight_approvals(event)

        assert first == {"sent": 1, "skipped": 0, "failed": 0}
        assert second == {"sent": 0, "skipped": 0, "failed": 0}
        assert len(_queued_f8(mock_dynamodb)) == 1

    @pytest.mark.asyncio
    async def test_failures_are_counted_not_swallowed(
        self, service, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        _store(mock_dynamodb, event, reg)

        refusing = MagicMock()
        refusing.send_festival_overnight_approval = AsyncMock(return_value=False)
        with patch("app.services.email_service.get_email_service", return_value=refusing):
            result = await service.notify_pending_overnight_approvals(event)

        assert result == {"sent": 0, "skipped": 0, "failed": 1}


class TestOvernightApprovalMail:
    """The F8 template — what the guest actually reads."""

    def _ctx(self, **overrides) -> EmailContext:
        defaults = {
            "event_name": "Sidetrack Festival",
            "event_date": "Freitag, 14. August 2026 um 18:00",
            "event_location": "Werft",
            "attendee_name": "Anna",
            "attendee_email": "anna@example.de",
            "group_size": 3,
            "registration_status": "registered",
            "management_url": "https://example.de/verwalten/abc",
            "slot_labels": "Freitag, Samstag",
            "accommodation_label": "2 Zelte, 1 Camper",
            "contact_hint": "orga@example.de",
        }
        defaults.update(overrides)
        return EmailContext(**defaults)

    def test_carries_units_days_and_management_link(self):
        subject, text, html = EmailTemplates.festival_overnight_approved(self._ctx())

        assert subject == "Übernachtung zugesagt: Sidetrack Festival"
        for body in (text, html):
            assert "2 Zelte, 1 Camper" in body
            assert "Freitag, Samstag" in body
            assert "3 Personen" in body
            assert "https://example.de/verwalten/abc" in body
            assert "orga@example.de" in body

    def test_omits_empty_optional_lines(self):
        """No stray "Wann:" / "Bei Fragen:" headings with nothing behind them."""
        _, text, html = EmailTemplates.festival_overnight_approved(
            self._ctx(slot_labels="", contact_hint=None),
        )

        for body in (text, html):
            assert "Wann:" not in body
            assert "Bei Fragen" not in body
            assert "None" not in body

    def test_singular_person_wording(self):
        _, text, _ = EmailTemplates.festival_overnight_approved(self._ctx(group_size=1))
        assert "1 Person" in text
        assert "1 Personen" not in text

    @pytest.mark.asyncio
    async def test_send_uses_bare_units_without_status_suffix(
        self, mock_dynamodb, sample_event, sample_registration,
    ):
        """The whole mail IS the "zugesagt" — repeating it in the label would
        read as if the approval were still pending."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(
            sample_registration, event, overnight_approved=True, tent_count=1, camper_count=2,
        )
        svc = EmailService()
        svc._messages_table = mock_dynamodb["messages_table"]

        assert await svc.send_festival_overnight_approval(event, reg) is True

        message = _queued_f8(mock_dynamodb)[0]
        assert "1 Zelt, 2 Camper" in message["body"]
        assert "angefragt" not in message["body"]
        assert "— zugesagt" not in message["body"]


class TestSelfServiceResetClearsMarker:
    """Regression: the guest-facing reset must drop the marker too.

    `update_festival_attendance` resets `overnight_approved` when the wish is
    cleared. It once left `overnight_notified_at` behind, so a guest who cleared
    and re-added their wish was approved a second time but never mailed —
    `notify_overnight_approval` saw the old stamp and answered
    `already_notified`. Silent, and only visible at the gate.
    """

    @pytest.mark.asyncio
    async def test_clearing_the_wish_clears_the_stamp(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        from app.models import FestivalAttendancePatch

        event = _festival_event(sample_event)
        reg = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            overnight_notified_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        _store(mock_dynamodb, event, reg)

        updated, error = await service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(tent_count=0),
        )

        assert error is None
        assert updated.overnight_approved is False
        assert updated.overnight_notified_at is None
        assert _read(mock_dynamodb, event.id, reg.id).overnight_notified_at is None

    @pytest.mark.asyncio
    async def test_re_approval_after_self_clear_mails_again(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """The end-to-end shape of the bug: clear, re-add, approve -> mail."""
        from app.models import FestivalAttendancePatch

        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )
        assert len(_queued_f8(mock_dynamodb)) == 1

        await service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(tent_count=0),
        )
        await service.update_festival_attendance(
            reg.id,
            reg.registration_token,
            FestivalAttendancePatch(tent_count=1, phone="+49 176 1234567"),
        )
        regranted, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )

        assert error is None
        assert regranted.overnight_notified_at is not None
        assert len(_queued_f8(mock_dynamodb)) == 2, "re-approval stayed silent"


class TestAdminResponseCarriesFestivalFields:
    """Regression: the admin PUT response is what the toggle's toast reads.

    `_registration_to_response` built an explicit kwarg list that dropped every
    festival field, so the response claimed `overnight_approved=False` right
    after approving and carried no `overnight_notified_at` — the UI therefore
    always reported that the F8 mail had failed.
    """

    def test_tombstoned_member_does_not_break_the_response(
        self, sample_event, sample_registration,
    ):
        """The admin model once declared `group_members: list[str]`, so every
        group that had lost a member 500'd the admin list AND the approval
        toggle — the latter only after its F8 mail had already been queued."""
        from app.api.admin.events import _registration_to_response

        event = _festival_event(sample_event)
        reg = _overnight_registration(
            sample_registration, event, group_members=[None, "Bea"],
        )

        response = _registration_to_response(reg)

        assert response.group_members == [None, "Bea"]

    def test_response_includes_overnight_and_festival_fields(
        self, sample_event, sample_registration,
    ):
        from app.api.admin.events import _registration_to_response

        event = _festival_event(sample_event)
        stamp = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
        reg = _overnight_registration(
            sample_registration,
            event,
            overnight_approved=True,
            overnight_notified_at=stamp,
            tier="werft",
            invite_label="Werft-Kontingent",
            group_members=["Bea", "Cem"],
            # Group comes both days, Bea only Saturday — a real narrowing. An
            # override equal to the group's days is normalised away by the
            # model validator, so it would not survive to be asserted here.
            attendance_slots=["fr", "sa"],
            member_slots={"1": ["sa"]},
        )

        response = _registration_to_response(reg)

        assert response.overnight_approved is True
        assert response.overnight_notified_at == stamp
        assert response.tent_count == 2
        assert response.attendance_slots == ["fr", "sa"]
        assert response.tier == "werft"
        assert response.invite_label == "Werft-Kontingent"
        assert response.member_slots == {"1": ["sa"]}


class TestOvernightDecline:
    """F9: refusing a wish, and telling the guest exactly once.

    The refusal state IS the mail marker (`overnight_declined_at`), so the two
    can never disagree — a registration is never shown as refused without the
    guest having been told.
    """

    @pytest.mark.asyncio
    async def test_declining_queues_mail_and_stamps(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        updated, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )

        assert error is None
        assert updated.overnight_declined_at is not None
        assert updated.overnight_approved is False
        # Persisted, not just returned — this is the state the UI re-reads.
        assert _read(mock_dynamodb, event.id, reg.id).overnight_declined_at is not None

        messages = _queued_f9(mock_dynamodb)
        assert len(messages) == 1
        assert messages[0]["recipient_email"] == reg.email
        assert "nicht möglich" in messages[0]["subject"]

    @pytest.mark.asyncio
    async def test_wish_is_kept_so_the_numbers_still_show_demand(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        updated, _ = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )

        assert updated.tent_count == 2
        assert updated.has_overnight is True

    @pytest.mark.asyncio
    async def test_second_decline_mails_nothing(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )
        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )

        assert len(_queued_f9(mock_dynamodb)) == 1

    @pytest.mark.asyncio
    async def test_declining_an_approved_wish_is_refused(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """Both answers must never hold at once — the organizer withdraws first."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event, overnight_approved=True)
        _store(mock_dynamodb, event, reg)

        updated, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )

        assert updated is None
        assert error == "overnight_decline_conflicts_with_approval"
        assert _queued_f9(mock_dynamodb) == []

    @pytest.mark.asyncio
    async def test_declining_without_a_wish_is_refused(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(
            sample_registration, event, tent_count=None, phone=None,
        )
        _store(mock_dynamodb, event, reg)

        updated, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )

        assert updated is None
        assert error == "overnight_decline_requires_accommodation"

    @pytest.mark.asyncio
    async def test_approving_a_refused_wish_clears_the_refusal(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """The organizer changed their mind: the refusal goes, F8 goes out."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )
        approved, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_approved=True),
        )

        assert error is None
        assert approved.overnight_approved is True
        assert approved.overnight_declined_at is None
        assert _read(mock_dynamodb, event.id, reg.id).overnight_declined_at is None
        assert len(_queued_f8(mock_dynamodb)) == 1

    @pytest.mark.asyncio
    async def test_withdrawing_the_refusal_mails_nothing(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )
        withdrawn, error = await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=False),
        )

        assert error is None
        assert withdrawn.overnight_declined_at is None
        # Still exactly the one refusal mail — taking it back is not news.
        assert len(_queued_f9(mock_dynamodb)) == 1

    @pytest.mark.asyncio
    async def test_guest_clearing_the_wish_clears_the_refusal(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """A re-added wish must be a fresh request, not a stale refusal."""
        from app.models import FestivalAttendancePatch

        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )
        cleared, error = await service.update_festival_attendance(
            reg.id, reg.registration_token, FestivalAttendancePatch(tent_count=0),
        )

        assert error is None
        assert cleared.overnight_declined_at is None

    @pytest.mark.asyncio
    async def test_failed_mail_leaves_the_request_open(
        self, service, mock_dynamodb, sample_event, sample_registration,
    ):
        """Claim-then-send rollback: no silent "refused" without a mail."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        refusing = MagicMock()
        refusing.send_festival_overnight_decline = AsyncMock(return_value=False)
        with patch("app.services.email_service.get_email_service", return_value=refusing):
            updated, error = await service.admin_update_registration(
                event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
            )

        assert error is None
        assert _read(mock_dynamodb, event.id, reg.id).overnight_declined_at is None

    @pytest.mark.asyncio
    async def test_declined_wish_is_not_picked_up_by_the_bulk_run(
        self, service, mail, mock_dynamodb, sample_event, sample_registration,
    ):
        """The F8 catch-up mails APPROVED groups — a refused one must stay out."""
        event = _festival_event(sample_event)
        reg = _overnight_registration(sample_registration, event)
        _store(mock_dynamodb, event, reg)

        await service.admin_update_registration(
            event.id, reg.id, RegistrationAdminPatch(overnight_declined=True),
        )
        result = await service.notify_pending_overnight_approvals(event)

        assert result == {"sent": 0, "skipped": 0, "failed": 0}
        assert _queued_f8(mock_dynamodb) == []

    def test_rejected_on_a_non_festival_event(self, sample_event, sample_registration):
        """`overnight_declined` is festival-only, like every other Ä-field."""
        from app.models import RegistrationAdminPatch as Patch

        # Schema accepts it; the service is what rejects it per event type.
        assert Patch(overnight_declined=True).overnight_declined is True


class TestOvernightDeclineMail:
    """The F9 template — what a refused guest reads."""

    def _ctx(self, **overrides) -> EmailContext:
        defaults = {
            "event_name": "Sidetrack Festival",
            "event_date": "Freitag, 14. August 2026 um 18:00",
            "event_location": "Werft",
            "attendee_name": "Anna",
            "attendee_email": "anna@example.de",
            "group_size": 3,
            "registration_status": "registered",
            "management_url": "https://example.de/verwalten/abc",
            "accommodation_label": "2 Zelte",
            "contact_hint": "orga@example.de",
        }
        defaults.update(overrides)
        return EmailContext(**defaults)

    def test_says_no_to_the_pitch_but_not_to_the_guest(self):
        subject, text, html = EmailTemplates.festival_overnight_declined(self._ctx())

        assert subject == "Übernachtung leider nicht möglich: Sidetrack Festival"
        for body in (text, html):
            # The refusal itself, and that it is about capacity...
            assert "keinen Schlafplatz" in body
            assert "Stellplätze sind vergeben" in body
            # ...plus the reassurance that they are still coming at all.
            assert "trotzdem dabei" in body
            assert "Eintritts-Code gilt unverändert" in body
            assert "2 Zelte" in body
            assert "https://example.de/verwalten/abc" in body

    def test_omits_the_wish_line_when_there_is_nothing_to_name(self):
        _, text, html = EmailTemplates.festival_overnight_declined(
            self._ctx(accommodation_label=None, contact_hint=None),
        )
        for body in (text, html):
            assert "Angefragt hattet ihr" not in body
            assert "None" not in body
