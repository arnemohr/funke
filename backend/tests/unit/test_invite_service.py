"""Tests for invite_service (spec 019 — T105).

Covers CRUD, token lookup (GSI), atomic consume/release of use_count
(the race-critical guard against overbooking a capped multi-use invite),
and Invite.is_expired (T104, tested here per the task note).
"""

import asyncio
import concurrent.futures
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Invite, InviteBatchCreate, InviteCreate, InviteUpdate
from app.services.invite_service import InviteService


class TestInviteBatchCreateAndList:
    """Batch create + list_invites (pk query, begins_with sk)."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = InviteService()
        self.service._table = mock_dynamodb["events_table"]
        self.event_id = uuid4()
        self.org_id = uuid4()
        self.admin_id = uuid4()

    @pytest.mark.asyncio
    async def test_batch_create_yields_three_shared_batch_label_unique_tokens(self):
        batch = InviteBatchCreate(
            batch_label="Welle 1 – Werft",
            invites=[
                InviteCreate(label="Person A", tier="werft"),
                InviteCreate(label="Person B", tier="werft"),
                InviteCreate(label="Person C", tier="werft"),
            ],
        )

        created = await self.service.create_invites_batch(
            self.org_id, self.event_id, batch, self.admin_id,
        )
        assert len(created) == 3

        listed = await self.service.list_invites(self.event_id)
        assert len(listed) == 3

        assert all(inv.batch_label == "Welle 1 – Werft" for inv in listed)

        tokens = {inv.token for inv in listed}
        assert len(tokens) == 3

    @pytest.mark.asyncio
    async def test_list_invites_empty_for_unknown_event(self):
        assert await self.service.list_invites(uuid4()) == []


class TestGetInviteByToken:
    """get_invite_by_token via the invite-token-index GSI."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = InviteService()
        self.service._table = mock_dynamodb["events_table"]
        self.event_id = uuid4()
        self.org_id = uuid4()
        self.admin_id = uuid4()

    @pytest.mark.asyncio
    async def test_get_by_token_finds_invite(self):
        batch = InviteBatchCreate(invites=[InviteCreate(label="Solo", tier="open")])
        [created] = await self.service.create_invites_batch(
            self.org_id, self.event_id, batch, self.admin_id,
        )

        found = await self.service.get_invite_by_token(created.token)
        assert found is not None
        assert found.id == created.id
        assert found.label == "Solo"

    @pytest.mark.asyncio
    async def test_get_by_token_unknown_returns_none(self):
        assert await self.service.get_invite_by_token("does-not-exist") is None


class TestConsumeAndReleaseUse:
    """Atomic consume_use / release_use — the race-critical exhaustion guard."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = InviteService()
        self.service._table = mock_dynamodb["events_table"]
        self.event_id = uuid4()
        self.org_id = uuid4()
        self.admin_id = uuid4()

    async def _make_invite(self, max_uses: int = 1) -> Invite:
        entry = InviteCreate(label="Group", tier="volunteer", max_uses=max_uses)
        batch = InviteBatchCreate(invites=[entry])
        [created] = await self.service.create_invites_batch(
            self.org_id, self.event_id, batch, self.admin_id,
        )
        return created

    @pytest.mark.asyncio
    async def test_consume_exhaust_third_fails_use_count_stays_at_max(self):
        invite = await self._make_invite(max_uses=2)

        assert await self.service.consume_use(self.event_id, invite.id) is True
        assert await self.service.consume_use(self.event_id, invite.id) is True
        assert await self.service.consume_use(self.event_id, invite.id) is False

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.use_count == 2

    @pytest.mark.asyncio
    async def test_consume_after_revoke_fails(self):
        invite = await self._make_invite(max_uses=5)
        await self.service.revoke_invite(self.event_id, invite.id)

        assert await self.service.consume_use(self.event_id, invite.id) is False

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.use_count == 0

    @pytest.mark.asyncio
    async def test_consume_unknown_invite_returns_false(self):
        assert await self.service.consume_use(self.event_id, uuid4()) is False

    @pytest.mark.asyncio
    async def test_release_use_decrements(self):
        invite = await self._make_invite(max_uses=3)
        await self.service.consume_use(self.event_id, invite.id)
        await self.service.consume_use(self.event_id, invite.id)

        assert await self.service.release_use(self.event_id, invite.id) is True

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.use_count == 1

    @pytest.mark.asyncio
    async def test_release_at_zero_returns_false_no_negative_counts(self):
        invite = await self._make_invite(max_uses=3)

        assert await self.service.release_use(self.event_id, invite.id) is False

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.use_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_consume_race_never_overshoots_max_uses(self):
        """Fire more concurrent consumes than the invite allows.

        This drives ``consume_use`` from real OS threads (not just
        sequential coroutines) against the same moto-backed table, so the
        DynamoDB conditional-update guard — not Python's GIL scheduling —
        is what has to hold the line. Exactly ``max_uses`` calls may win;
        every other racer must observe the exhaustion and back off, and
        the stored ``use_count`` must land exactly on the cap, never over.
        """
        max_uses = 3
        concurrent_attempts = 12
        invite = await self._make_invite(max_uses=max_uses)

        def _consume_sync() -> bool:
            return asyncio.run(self.service.consume_use(self.event_id, invite.id))

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_attempts) as pool:
            results = list(pool.map(lambda _: _consume_sync(), range(concurrent_attempts)))

        successes = sum(1 for r in results if r)
        assert successes == max_uses

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.use_count == max_uses  # never exceeds the cap, never falls short


class TestMarkSentIdempotent:
    """mark_sent stamps sent_at once (Ä7): a second call is a no-op."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = InviteService()
        self.service._table = mock_dynamodb["events_table"]
        self.event_id = uuid4()
        self.org_id = uuid4()
        self.admin_id = uuid4()

    @pytest.mark.asyncio
    async def test_mark_sent_twice_keeps_first_timestamp(self):
        batch = InviteBatchCreate(invites=[InviteCreate(label="Solo", tier="open")])
        [invite] = await self.service.create_invites_batch(
            self.org_id, self.event_id, batch, self.admin_id,
        )
        assert invite.sent_at is None

        first = await self.service.mark_sent(self.event_id, invite.id)
        assert first.sent_at is not None

        second = await self.service.mark_sent(self.event_id, invite.id)
        assert second.sent_at == first.sent_at


class TestUpdateInviteAndRevoke:
    """update_invite (model_copy + put) and revoke_invite."""

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.service = InviteService()
        self.service._table = mock_dynamodb["events_table"]
        self.event_id = uuid4()
        self.org_id = uuid4()
        self.admin_id = uuid4()

    async def _create_one(self, **entry_overrides) -> Invite:
        entry_defaults = {"label": "Solo", "tier": "open"}
        entry_defaults.update(entry_overrides)
        batch = InviteBatchCreate(invites=[InviteCreate(**entry_defaults)])
        [invite] = await self.service.create_invites_batch(
            self.org_id, self.event_id, batch, self.admin_id,
        )
        return invite

    @pytest.mark.asyncio
    async def test_update_invite_changes_label(self):
        invite = await self._create_one(label="Old Label")

        patch = InviteUpdate(label="New Label")
        updated = await self.service.update_invite(self.event_id, invite.id, patch)
        assert updated.label == "New Label"

        refreshed = await self.service.get_invite(self.event_id, invite.id)
        assert refreshed.label == "New Label"

    @pytest.mark.asyncio
    async def test_update_invite_reducing_max_group_size_does_not_touch_use_count(self):
        invite = await self._create_one(label="Group", max_group_size=10)
        await self.service.consume_use(self.event_id, invite.id)

        patch = InviteUpdate(max_group_size=2)
        updated = await self.service.update_invite(self.event_id, invite.id, patch)
        assert updated.max_group_size == 2
        assert updated.use_count == 1  # grandfathering: existing use is untouched

    @pytest.mark.asyncio
    async def test_update_invite_unknown_returns_none(self):
        patch = InviteUpdate(label="x")
        assert await self.service.update_invite(self.event_id, uuid4(), patch) is None

    @pytest.mark.asyncio
    async def test_revoke_invite_sets_revoked_at(self):
        invite = await self._create_one()

        revoked = await self.service.revoke_invite(self.event_id, invite.id)
        assert revoked.revoked_at is not None


class TestIsExpired:
    """Invite.is_expired (T104) — all three implicit/explicit triggers."""

    def _invite(self, **overrides) -> Invite:
        defaults = {
            "event_id": uuid4(),
            "org_id": uuid4(),
            "token": "tok",
            "label": "Test",
            "tier": "open",
        }
        defaults.update(overrides)
        return Invite(**defaults)

    def test_expired_via_revoked_at(self):
        future_deadline = datetime.now(timezone.utc) + timedelta(days=1)
        invite = self._invite(revoked_at=datetime.now(timezone.utc))
        assert invite.is_expired(future_deadline) is True

    def test_expired_via_own_expires_at(self):
        future_deadline = datetime.now(timezone.utc) + timedelta(days=1)
        invite = self._invite(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        assert invite.is_expired(future_deadline) is True

    def test_expired_via_registration_deadline_passed(self):
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        invite = self._invite(expires_at=None, revoked_at=None)
        assert invite.is_expired(past_deadline) is True

    def test_not_expired_when_all_clear(self):
        future_deadline = datetime.now(timezone.utc) + timedelta(days=1)
        invite = self._invite(expires_at=None, revoked_at=None)
        assert invite.is_expired(future_deadline) is False
