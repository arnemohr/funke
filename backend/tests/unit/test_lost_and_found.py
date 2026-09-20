"""Tests for the Fundsachen page: models, service, sweep (spec 023).

Three properties carry the feature and everything here circles them:

**Numbers are promises.** The number under a photo is what a guest quotes in a
mail, so a block is contiguous, two batches never overlap, and a deleted
photo's number is burnt forever.

**The token is the whole access control.** Every rejection on the public path
has to be indistinguishable from every other — the service returns ``None``,
never a reason, and never raises.

**Objects and rows die together.** Every delete path is asserted against both
the table and a real (moto) bucket, because an orphan object is the one failure
mode nothing in the system can find again.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

import app.services.config as config_module
import app.services.event_service as event_service_module
from app.models import Event, EventStatus, EventType
from app.models.lost_and_found import (
    CAPTION_MAX_LENGTH,
    INTRO_TEXT_MAX_LENGTH,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    LostAndFoundConfig,
    LostAndFoundConfigUpdate,
    LostAndFoundPhoto,
    LostAndFoundPhotoConfirm,
    LostAndFoundPhotoState,
)
from app.services.anonymization_service import AnonymizationService
from app.services.config import (
    EVENT_SK_LNF_CONFIG,
    EVENT_SK_LNF_PHOTO_PREFIX,
    DynamoDBSettings,
)
from app.services.event_service import EventService, _event_to_item
from app.services.lost_and_found_service import (
    MAX_UPLOAD_BATCH,
    MAX_UPLOAD_BYTES,
    PENDING_TTL,
    URL_TTL_SECONDS,
    LostAndFoundService,
    display_key,
    effective_retention_days,
    event_finished_at,
    is_page_expired,
    page_expires_at,
    public_page_url,
    thumb_key,
)

BUCKET = "funke-test-lostfound"
REGION = "eu-central-1"
BASE_URL = "https://fest.example.com"
NOW = datetime.now(timezone.utc)

# The contract keys of the two sweep summaries. Projected rather than compared
# whole because both are currently mutated by their own log line — see
# `test_the_summary_is_not_polluted_by_its_own_log_line`.
SWEEP_KEYS = (
    "pages_checked",
    "pages_deleted",
    "deleted_photos",
    "pending_pruned",
    "orphan_photos_deleted",
    "completed",
    "unfinished",
    "failed",
)
TASK_KEYS = (
    "task",
    "status",
    "pages_checked",
    "pages_deleted",
    "photos_deleted",
    "pending_pruned",
    "orphan_photos_deleted",
    "pages_unfinished",
    "pages_failed",
    "swept_completely",
)


def _policy(fields: dict) -> dict:
    """The decoded POST policy — where the upload's real limits live."""
    return json.loads(base64.b64decode(fields["policy"]))


# --- models ------------------------------------------------------------------


class TestModels:
    def test_config_defaults(self):
        config = LostAndFoundConfig(
            event_id=uuid4(),
            page_token="t" * 43,
            coordinator_email="fund@example.com",
        )
        assert config.published is False
        assert config.next_number == 0
        assert config.retention_days is None
        assert config.coordinator_name is None

    def test_photo_starts_pending_without_dimensions(self):
        photo = LostAndFoundPhoto(
            event_id=uuid4(),
            number=1,
            s3_key_display="a",
            s3_key_thumb="b",
        )
        assert photo.state == LostAndFoundPhotoState.PENDING
        assert photo.width is None and photo.height is None

    def test_photo_number_starts_at_one(self):
        with pytest.raises(ValidationError):
            LostAndFoundPhoto(
                event_id=uuid4(),
                number=0,
                s3_key_display="a",
                s3_key_thumb="b",
            )

    def test_caption_length_is_capped(self):
        photo_kwargs = dict(event_id=uuid4(), number=1, s3_key_display="a", s3_key_thumb="b")
        LostAndFoundPhoto(caption="x" * CAPTION_MAX_LENGTH, **photo_kwargs)
        with pytest.raises(ValidationError):
            LostAndFoundPhoto(caption="x" * (CAPTION_MAX_LENGTH + 1), **photo_kwargs)

    def test_intro_text_length_is_capped(self):
        with pytest.raises(ValidationError):
            LostAndFoundConfigUpdate(intro_text="x" * (INTRO_TEXT_MAX_LENGTH + 1))

    @pytest.mark.parametrize("days", [RETENTION_DAYS_MIN, RETENTION_DAYS_MAX, 90])
    def test_retention_bounds_accept(self, days):
        assert LostAndFoundConfigUpdate(retention_days=days).retention_days == days

    @pytest.mark.parametrize("days", [0, RETENTION_DAYS_MIN - 1, RETENTION_DAYS_MAX + 1])
    def test_retention_bounds_reject(self, days):
        with pytest.raises(ValidationError):
            LostAndFoundConfigUpdate(retention_days=days)

    def test_config_update_forbids_unknown_fields(self):
        with pytest.raises(ValidationError):
            LostAndFoundConfigUpdate(coordinator_email="a@b.de", publish=True)

    def test_config_update_tracks_what_was_set(self):
        """`exclude_unset` is the entire patch semantics — omitted vs. null."""
        patch = LostAndFoundConfigUpdate(coordinator_name=None)
        dumped = patch.model_dump(exclude_unset=True)
        assert dumped == {"coordinator_name": None}
        assert LostAndFoundConfigUpdate().model_dump(exclude_unset=True) == {}

    def test_confirm_forbids_unknown_fields_and_bounds_pixels(self):
        with pytest.raises(ValidationError):
            LostAndFoundPhotoConfirm(photo_id=uuid4(), width=1, height=1, state="READY")
        with pytest.raises(ValidationError):
            LostAndFoundPhotoConfirm(photo_id=uuid4(), width=0, height=100)
        with pytest.raises(ValidationError):
            LostAndFoundPhotoConfirm(photo_id=uuid4(), width=100, height=20001)


# --- shared fixture ----------------------------------------------------------


class LostFoundBase:
    """A service wired to moto's DynamoDB and a real (moto) photo bucket."""

    #: Overridden by the class that checks the unconfigured-bucket degradation.
    bucket: str | None = BUCKET

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb, monkeypatch):
        self.tables = mock_dynamodb
        self.events_table = mock_dynamodb["events_table"]

        monkeypatch.setattr(
            config_module,
            "_settings",
            DynamoDBSettings(
                lost_and_found_s3_bucket=self.bucket,
                lost_and_found_retention_days=90,
                base_url=BASE_URL,
            ),
        )

        self.s3 = boto3.client("s3", region_name=REGION)
        self.s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-central-1"},
        )

        self.service = LostAndFoundService()
        self.service._table = self.events_table

        event_service = EventService()
        event_service._table = self.events_table
        # Injected rather than left to the singleton, so the page its delete
        # paths remove is the one in this test's moto table.
        event_service._lost_and_found = self.service
        monkeypatch.setattr(event_service_module, "_event_service", event_service)
        self.event_service = event_service

    # -- factories ------------------------------------------------------------

    def _store_event(self, **overrides) -> Event:
        defaults = dict(
            id=uuid4(),
            org_id=uuid4(),
            name="Sommerfest an der Werft",
            start_at=NOW - timedelta(days=3),
            end_at=NOW - timedelta(days=2),
            registration_deadline=NOW - timedelta(days=10),
            status=EventStatus.COMPLETED,
            capacity=200,
            event_type=EventType.SINGLE,
        )
        defaults.update(overrides)
        event = Event(**defaults)
        self.events_table.put_item(Item=_event_to_item(event))
        return event

    async def _create_page(
        self,
        event: Event,
        *,
        put_up_late: bool = False,
        **patch,
    ) -> LostAndFoundConfig:
        """Create the page, by default as if it went up when the event ended.

        Retention runs from the later of event end and page creation, so a page
        minted *now* on a long-finished event gets a full fresh window — correct
        behaviour, but not what a test about retention windows usually means.
        The default therefore backdates `created_at` to the event's end, which
        is the normal case. `put_up_late=True` keeps the real creation time, for
        the tests that are specifically about a page added long afterwards.
        """
        body = {"coordinator_email": "fundsachen@example.com"}
        body.update(patch)
        config = await self.service.upsert_config(event.id, LostAndFoundConfigUpdate(**body))

        finished = event_finished_at(event)
        if not put_up_late and finished < datetime.now(timezone.utc):
            self.events_table.update_item(
                Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_LNF_CONFIG},
                UpdateExpression="SET created_at = :t",
                ExpressionAttributeValues={":t": finished.isoformat()},
            )
            config = config.model_copy(update={"created_at": finished})
        return config

    async def _upload(self, event: Event, count: int, *, confirm: bool = True, store: bool = True):
        """Mint `count` uploads, optionally put the objects and confirm them."""
        uploads = await self.service.create_upload_batch(event.id, count)

        if store:
            for upload in uploads:
                for key in (
                    display_key(event.id, upload.photo_id),
                    thumb_key(event.id, upload.photo_id),
                ):
                    self.s3.put_object(Bucket=BUCKET, Key=key, Body=b"jpeg-bytes")

        if confirm:
            await self.service.confirm_photos(
                event.id,
                [
                    LostAndFoundPhotoConfirm(photo_id=u.photo_id, width=1600, height=1200)
                    for u in uploads
                ],
            )
        return uploads

    # -- raw table/bucket access ---------------------------------------------

    def _config_item(self, event_id) -> dict | None:
        return self.events_table.get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
        ).get("Item")

    def _photo_items(self, event_id) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        return self.events_table.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with(EVENT_SK_LNF_PHOTO_PREFIX),
        )["Items"]

    def _object_keys(self) -> set[str]:
        listing = self.s3.list_objects_v2(Bucket=BUCKET)
        return {o["Key"] for o in listing.get("Contents", [])}

    def _age_page(self, event: Event, age: timedelta) -> None:
        """Backdate the page's own creation.

        Retention runs from the later of event end and page creation, so a test
        that wants an expired page has to age the *page*, not just the event —
        putting a page up today on a long-finished event deliberately buys it a
        full fresh window.
        """
        self.events_table.update_item(
            Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_LNF_CONFIG},
            UpdateExpression="SET created_at = :t",
            ExpressionAttributeValues={
                ":t": (datetime.now(timezone.utc) - age).isoformat(),
            },
        )

    def _age_photo(self, event: Event, photo_id, age: timedelta) -> None:
        self.events_table.update_item(
            Key={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo_id}",
            },
            UpdateExpression="SET uploaded_at = :t",
            ExpressionAttributeValues={
                ":t": (datetime.now(timezone.utc) - age).isoformat(),
            },
        )


# --- helpers -----------------------------------------------------------------


class TestHelpers(LostFoundBase):
    def test_event_finished_at_prefers_end_at(self):
        event = self._store_event()
        assert event_finished_at(event) == event.end_at

    def test_event_finished_at_falls_back_to_start_at(self):
        event = self._store_event(end_at=None)
        assert event_finished_at(event) == event.start_at

    def test_event_finished_at_uses_cancellation_moment(self):
        """A cancelled event ends when it is called off, not on its date."""
        cancelled_at = NOW - timedelta(days=1)
        event = self._store_event(
            status=EventStatus.CANCELLED,
            cancelled_at=cancelled_at,
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        assert event_finished_at(event) == cancelled_at

    def test_event_finished_at_of_a_cancellation_without_a_timestamp(self):
        """Old rows have no `cancelled_at`; the planned end is the fallback."""
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=None)
        assert event_finished_at(event) == event.end_at

    def test_event_finished_at_ignores_cancelled_at_when_not_cancelled(self):
        event = self._store_event(cancelled_at=NOW - timedelta(days=1))
        assert event_finished_at(event) == event.end_at

    def test_event_finished_at_makes_naive_datetimes_utc(self):
        naive = datetime(2026, 8, 15, 12, 0, 0)  # noqa: DTZ001 - the case under test
        event = Event(
            org_id=uuid4(),
            name="Naiv",
            start_at=naive,
            registration_deadline=naive - timedelta(days=1),
            end_at=None,
        )
        assert event_finished_at(event).tzinfo is timezone.utc

    async def test_effective_retention_prefers_page_override(self):
        event = self._store_event()
        config = await self._create_page(event)
        assert effective_retention_days(config) == 90

        overridden = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(retention_days=14),
        )
        assert effective_retention_days(overridden) == 14

    async def test_page_expires_at_counts_from_the_event_end(self):
        event = self._store_event()
        config = await self._create_page(event, retention_days=7)
        assert page_expires_at(event, config) == event.end_at + timedelta(days=7)
        assert is_page_expired(event, config, now=event.end_at + timedelta(days=6)) is False
        assert is_page_expired(event, config, now=event.end_at + timedelta(days=8)) is True

    def test_public_page_url_shape(self):
        event_id, token = uuid4(), "t" * 43
        assert public_page_url(event_id, token) == f"{BASE_URL}/lostfound/{event_id}/{token}"

    def test_keys_are_exact(self):
        event_id, photo_id = uuid4(), uuid4()
        assert display_key(event_id, photo_id) == f"lostfound/{event_id}/{photo_id}/display.jpg"
        assert thumb_key(event_id, photo_id) == f"lostfound/{event_id}/{photo_id}/thumb.jpg"


# --- configuration -----------------------------------------------------------


class TestConfig(LostFoundBase):
    async def test_no_page_reads_as_none(self):
        event = self._store_event()
        assert await self.service.get_config(event.id) is None

    async def test_first_save_mints_a_43_character_token_unpublished(self):
        event = self._store_event()
        config = await self._create_page(event)

        assert len(config.page_token) == 43
        assert config.published is False
        assert config.next_number == 0
        assert config.coordinator_email == "fundsachen@example.com"
        assert self._config_item(event.id)["page_token"] == config.page_token

    async def test_first_save_without_any_contact_is_refused(self):
        event = self._store_event()
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                LostAndFoundConfigUpdate(published=True),
            )
        assert self._config_item(event.id) is None

    async def test_clearing_the_last_contact_is_refused(self):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                LostAndFoundConfigUpdate(coordinator_email=None),
            )
        assert (await self.service.get_config(event.id)).coordinator_email == (
            "fundsachen@example.com"
        )

    async def test_a_telegram_link_is_a_contact_on_its_own(self):
        """„Statt einer Mailadresse" — an organiser who runs everything through a
        Telegram group must not be forced to invent an address."""
        event = self._store_event()
        config = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(coordinator_telegram_url="@fundsachen", published=True),
        )
        assert config.coordinator_email is None
        assert config.coordinator_telegram_url == "https://t.me/fundsachen"
        assert self._config_item(event.id).get("coordinator_email") is None

    async def test_the_mail_can_be_cleared_once_telegram_is_set(self):
        event = self._store_event()
        await self._create_page(event)
        await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(coordinator_telegram_url="https://t.me/+AbCdEfGh"),
        )
        cleared = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(coordinator_email=None),
        )
        assert cleared.coordinator_email is None
        assert cleared.coordinator_telegram_url == "https://t.me/+AbCdEfGh"

    async def test_clearing_telegram_when_it_is_the_only_contact_is_refused(self):
        event = self._store_event()
        await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(coordinator_telegram_url="@fundsachen"),
        )
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                LostAndFoundConfigUpdate(coordinator_telegram_url=None),
            )

    async def test_omitted_fields_are_left_alone(self):
        event = self._store_event()
        await self._create_page(
            event,
            coordinator_name="Aline",
            intro_text="Kiste steht im Büro.",
        )

        patched = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(published=True),
        )
        assert patched.coordinator_name == "Aline"
        assert patched.intro_text == "Kiste steht im Büro."
        assert patched.published is True

    async def test_explicit_null_clears_the_field(self):
        event = self._store_event()
        await self._create_page(event, coordinator_name="Aline", retention_days=14)

        cleared = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(coordinator_name=None, retention_days=None),
        )
        assert cleared.coordinator_name is None
        # `retention_days: null` is how the form goes back to the environment
        # default — the attribute has to be gone, not zero.
        assert cleared.retention_days is None
        assert effective_retention_days(cleared) == 90
        assert "retention_days" not in self._config_item(event.id)

    async def test_saving_never_rewrites_token_or_counter(self):
        event = self._store_event()
        config = await self._create_page(event)
        await self._upload(event, 2)

        patched = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(intro_text="Neu"),
        )
        assert patched.page_token == config.page_token
        assert patched.next_number == 2

    async def test_updated_at_moves_created_at_does_not(self):
        event = self._store_event()
        config = await self._create_page(event)
        patched = await self.service.upsert_config(
            event.id,
            LostAndFoundConfigUpdate(published=True),
        )
        assert patched.created_at == config.created_at
        assert patched.updated_at >= config.updated_at

    async def test_losing_the_create_race_keeps_the_winners_token(self):
        """Two first saves at once: the loser must patch, not overwrite — the
        winner's token may already have been copied out of the form."""
        event = self._store_event()
        winner = await self._create_page(event)

        async def blind(_event_id):
            return None

        with pytest.MonkeyPatch.context() as mp:
            # The read that decides create-vs-patch, answered from before the
            # winner's write.
            mp.setattr(self.service, "get_config", blind)
            loser = await self.service.upsert_config(
                event.id,
                LostAndFoundConfigUpdate(
                    coordinator_email="zweite@example.com",
                    published=True,
                ),
            )

        assert loser.page_token == winner.page_token
        assert loser.coordinator_email == "zweite@example.com"
        assert loser.published is True

    async def test_rotate_token_replaces_the_token_and_keeps_the_photos(self):
        event = self._store_event()
        config = await self._create_page(event, published=True)
        await self._upload(event, 2)

        rotated = await self.service.rotate_token(event.id)
        assert rotated.page_token != config.page_token
        assert len(rotated.page_token) == 43
        assert rotated.next_number == 2
        assert len(await self.service.list_photos(event.id)) == 2

    async def test_rotate_token_without_a_page(self):
        event = self._store_event()
        with pytest.raises(ValueError, match="page_not_found"):
            await self.service.rotate_token(event.id)


# --- numbers -----------------------------------------------------------------


class TestNumbers(LostFoundBase):
    async def test_first_photo_is_number_one(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self.service.create_upload_batch(event.id, 1)
        assert [u.number for u in uploads] == [1]

    async def test_a_batch_draws_a_contiguous_block(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self.service.create_upload_batch(event.id, 12)
        assert [u.number for u in uploads] == list(range(1, 13))
        assert (await self.service.get_config(event.id)).next_number == 12

    async def test_two_batches_never_overlap(self):
        import asyncio

        event = self._store_event()
        await self._create_page(event)

        first, second = await asyncio.gather(
            self.service.create_upload_batch(event.id, 5),
            self.service.create_upload_batch(event.id, 5),
        )
        block_a = {u.number for u in first}
        block_b = {u.number for u in second}

        assert not block_a & block_b
        assert block_a | block_b == set(range(1, 11))
        # Each caller's own block is still contiguous, whichever order the
        # counter increments landed in.
        for block in (block_a, block_b):
            assert max(block) - min(block) == 4

    async def test_deleting_a_photo_never_re_issues_its_number(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self._upload(event, 3)

        await self.service.delete_photo(event.id, uploads[1].photo_id)
        assert [p.number for p in await self.service.list_photos(event.id)] == [1, 3]

        fresh = await self.service.create_upload_batch(event.id, 1)
        assert fresh[0].number == 4
        assert (await self.service.get_config(event.id)).next_number == 4

    async def test_deleting_the_last_photo_does_not_rewind_the_counter(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self._upload(event, 2)
        await self.service.delete_photo(event.id, uploads[-1].photo_id)

        assert (await self.service.get_config(event.id)).next_number == 2
        assert (await self.service.create_upload_batch(event.id, 1))[0].number == 3

    async def test_photos_are_listed_by_number(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 5)
        numbers = [p.number for p in await self.service.list_photos(event.id)]
        assert numbers == sorted(numbers) == [1, 2, 3, 4, 5]

    @pytest.mark.parametrize("count", [0, -1, MAX_UPLOAD_BATCH + 1])
    async def test_count_outside_the_range_is_refused(self, count):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="count_out_of_range"):
            await self.service.create_upload_batch(event.id, count)
        assert (await self.service.get_config(event.id)).next_number == 0

    async def test_the_maximum_batch_is_allowed(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self.service.create_upload_batch(event.id, MAX_UPLOAD_BATCH)
        assert len(uploads) == MAX_UPLOAD_BATCH
        assert uploads[-1].number == MAX_UPLOAD_BATCH

    async def test_uploads_without_a_page_are_refused(self):
        event = self._store_event()
        with pytest.raises(ValueError, match="page_not_found"):
            await self.service.create_upload_batch(event.id, 1)


# --- upload policy -----------------------------------------------------------


class TestUploadPolicy(LostFoundBase):
    async def test_policy_carries_the_size_limit_type_and_exact_key(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        for variant, expected_key in (
            (upload.display, display_key(event.id, upload.photo_id)),
            (upload.thumb, thumb_key(event.id, upload.photo_id)),
        ):
            conditions = _policy(variant.fields)["conditions"]
            assert ["content-length-range", 1, MAX_UPLOAD_BYTES] in conditions
            assert {"Content-Type": "image/jpeg"} in conditions
            # Exact key, not a prefix: the signature is a permission to write
            # this one object and nothing else in the bucket.
            assert {"key": expected_key} in conditions
            assert {"bucket": BUCKET} in conditions
            assert variant.fields["key"] == expected_key
            assert variant.fields["Content-Type"] == "image/jpeg"
            assert variant.fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
            assert "x-amz-signature" in variant.fields

    async def test_the_upload_url_is_the_regional_endpoint(self):
        """boto3's default `bucket.s3.amazonaws.com` answers 307 to the regional
        host for any bucket outside us-east-1, and a browser will not replay a
        cross-origin multipart POST across that redirect — the upload fails with
        an opaque CORS/network error while curl follows it happily. The region
        has to be in the host the signature and the bucket CORS rule are scoped
        to."""
        event = self._store_event()
        await self._create_page(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        for variant in (upload.display, upload.thumb):
            assert variant.url == f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"

        urls = self.service.presign_view_urls(event.id, await self.service.list_photos(
            event.id, include_pending=True,
        ))
        for pair in urls.values():
            for url in pair.values():
                assert url.startswith(f"https://{BUCKET}.s3.{REGION}.amazonaws.com/")

    async def test_size_limit_is_three_megabytes(self):
        assert MAX_UPLOAD_BYTES == 3 * 1024 * 1024

    async def test_signature_expires_after_the_url_ttl(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        expiration = datetime.fromisoformat(
            _policy(upload.display.fields)["expiration"].replace("Z", "+00:00"),
        )
        remaining = expiration - datetime.now(timezone.utc)
        assert (
            timedelta(seconds=URL_TTL_SECONDS - 60)
            < remaining
            <= timedelta(
                seconds=URL_TTL_SECONDS,
            )
        )

    async def test_the_row_exists_before_the_upload_happens(self):
        """A failed presign may leave a prunable row; it may never leave an
        object nothing points at."""
        event = self._store_event()
        await self._create_page(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        photo = await self.service.get_photo(event.id, upload.photo_id)
        assert photo is not None
        assert photo.state == LostAndFoundPhotoState.PENDING
        assert photo.s3_key_display == display_key(event.id, upload.photo_id)
        assert self._object_keys() == set()

    async def test_the_two_variants_get_different_signatures(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]
        assert upload.display.fields["key"] != upload.thumb.fields["key"]
        assert upload.display.fields["x-amz-signature"] != upload.thumb.fields["x-amz-signature"]


# --- photo state machine -----------------------------------------------------


class TestPhotoStates(LostFoundBase):
    async def test_pending_is_hidden_from_the_public_list(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2, confirm=False)

        assert await self.service.list_photos(event.id) == []
        assert len(await self.service.list_photos(event.id, include_pending=True)) == 2

    async def test_confirm_flips_to_ready_with_dimensions(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        confirmed, not_confirmed = await self.service.confirm_photos(
            event.id,
            [
                LostAndFoundPhotoConfirm(
                    photo_id=upload.photo_id,
                    width=1600,
                    height=1200,
                    caption="Blaue Jacke",
                ),
            ],
        )
        assert not_confirmed == []
        assert [p.state for p in confirmed] == [LostAndFoundPhotoState.READY]
        assert confirmed[0].width == 1600
        assert confirmed[0].height == 1200
        assert confirmed[0].caption == "Blaue Jacke"
        assert confirmed[0].number == upload.number
        assert len(await self.service.list_photos(event.id)) == 1

    async def test_confirm_is_idempotent(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1, confirm=False))[0]
        entry = LostAndFoundPhotoConfirm(photo_id=upload.photo_id, width=800, height=600)

        first, _ = await self.service.confirm_photos(event.id, [entry])
        second, _ = await self.service.confirm_photos(event.id, [entry])
        assert first[0].model_dump() == second[0].model_dump()
        assert len(await self.service.list_photos(event.id)) == 1

    async def test_confirm_of_an_unknown_photo_id(self):
        """Named, not raised — the router turns „nothing confirmed" into the 404.

        Reporting per row is what lets a partial batch keep the rows that did
        flip; see `test_a_partial_batch_keeps_what_it_confirmed`.
        """
        event = self._store_event()
        await self._create_page(event)
        stranger = uuid4()

        confirmed, not_confirmed = await self.service.confirm_photos(
            event.id,
            [LostAndFoundPhotoConfirm(photo_id=stranger, width=10, height=10)],
        )

        assert confirmed == []
        assert not_confirmed == [stranger]

    async def test_a_partial_batch_keeps_what_it_confirmed(self):
        """One vanished row must not fail 49 photos that are already public.

        Each entry is its own write, so by the time entry 2 turns out to be gone
        entry 1 is READY and live under a number a guest may have been given.
        Reporting the batch as failed makes the client re-upload it, and the page
        then lists the same jacket twice under two different numbers.
        """
        event = self._store_event()
        await self._create_page(event)
        first, third = await self._upload(event, 2, confirm=False)
        missing = uuid4()

        confirmed, not_confirmed = await self.service.confirm_photos(
            event.id,
            [
                LostAndFoundPhotoConfirm(photo_id=first.photo_id, width=10, height=10),
                LostAndFoundPhotoConfirm(photo_id=missing, width=10, height=10),
                LostAndFoundPhotoConfirm(photo_id=third.photo_id, width=10, height=10),
            ],
        )

        assert [p.photo_id for p in confirmed] == [first.photo_id, third.photo_id]
        assert not_confirmed == [missing]
        assert {p.photo_id for p in await self.service.list_photos(event.id)} == {
            first.photo_id,
            third.photo_id,
        }

    async def test_a_refusal_on_the_first_row_is_still_raised(self):
        """Nothing is public yet, so a systemic refusal is the honest answer —
        „unknown photo" would send the admin looking for the wrong problem."""
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        def throttled(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "no"}},
                "UpdateItem",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "update_item", throttled)
            with pytest.raises(ClientError):
                await self.service.confirm_photos(
                    event.id,
                    [
                        LostAndFoundPhotoConfirm(
                            photo_id=upload.photo_id, width=10, height=10,
                        ),
                    ],
                )

    async def test_confirm_of_another_events_photo_id(self):
        """Rows are keyed by event, so a borrowed id is simply not there."""
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_page(mine)
        await self._create_page(theirs)
        foreign = (await self._upload(theirs, 1, confirm=False))[0]

        confirmed, not_confirmed = await self.service.confirm_photos(
            mine.id,
            [LostAndFoundPhotoConfirm(photo_id=foreign.photo_id, width=10, height=10)],
        )
        assert confirmed == []
        assert not_confirmed == [foreign.photo_id]
        # And the foreign row is untouched.
        assert (
            await self.service.get_photo(theirs.id, foreign.photo_id)
        ).state == LostAndFoundPhotoState.PENDING

    async def test_confirm_of_an_empty_list_is_a_no_op(self):
        event = self._store_event()
        await self._create_page(event)
        assert await self.service.confirm_photos(event.id, []) == ([], [])

    async def test_caption_can_be_set_cleared_and_blank_counts_as_cleared(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1))[0]

        with_caption = await self.service.update_caption(
            event.id,
            upload.photo_id,
            "  Autoschlüssel  ",
        )
        assert with_caption.caption == "Autoschlüssel"

        blanked = await self.service.update_caption(event.id, upload.photo_id, "   ")
        assert blanked.caption is None
        assert "caption" not in self._photo_items(event.id)[0]

        again = await self.service.update_caption(event.id, upload.photo_id, "Schuh")
        assert again.caption == "Schuh"
        assert (await self.service.update_caption(event.id, upload.photo_id, None)).caption is None

    async def test_caption_on_an_unknown_photo(self):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.update_caption(event.id, uuid4(), "Hut")

    async def test_caption_of_another_events_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_page(mine)
        await self._create_page(theirs)
        foreign = (await self._upload(theirs, 1))[0]

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.update_caption(mine.id, foreign.photo_id, "Meins")


# --- deletion ----------------------------------------------------------------


class TestDeletion(LostFoundBase):
    async def test_deleting_a_photo_takes_both_objects(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self._upload(event, 2)
        keep, drop = uploads[0], uploads[1]

        await self.service.delete_photo(event.id, drop.photo_id)

        assert await self.service.get_photo(event.id, drop.photo_id) is None
        assert self._object_keys() == {
            display_key(event.id, keep.photo_id),
            thumb_key(event.id, keep.photo_id),
        }

    async def test_deleting_an_unknown_photo(self):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.delete_photo(event.id, uuid4())

    async def test_deleting_another_events_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_page(mine)
        await self._create_page(theirs)
        foreign = (await self._upload(theirs, 1))[0]

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.delete_photo(mine.id, foreign.photo_id)
        assert await self.service.get_photo(theirs.id, foreign.photo_id) is not None
        assert len(self._object_keys()) == 2

    async def test_deleting_the_page_takes_rows_and_objects(self):
        event = self._store_event()
        await self._create_page(event, published=True)
        await self._upload(event, 3)
        pending = await self._upload(event, 1, confirm=False)

        result = await self.service.delete_page(event.id)

        assert result == {"deleted_photos": 4, "completed": True}
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        # The PENDING row's objects were never uploaded; S3 reports a missing
        # key as a successful delete, which is what makes this idempotent.
        assert self._object_keys() == set()
        assert pending  # the abandoned row was swept up with the rest

    async def test_deleting_the_page_leaves_other_events_alone(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_page(mine)
        await self._create_page(theirs)
        await self._upload(mine, 1)
        keep = (await self._upload(theirs, 1))[0]

        await self.service.delete_page(mine.id)

        assert self._config_item(theirs.id) is not None
        assert len(self._photo_items(theirs.id)) == 1
        assert self._object_keys() == {
            display_key(theirs.id, keep.photo_id),
            thumb_key(theirs.id, keep.photo_id),
        }

    async def test_deleting_twice_is_idempotent(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)

        first = await self.service.delete_page(event.id)
        second = await self.service.delete_page(event.id)

        assert first["deleted_photos"] == 2
        assert second == {"deleted_photos": 0, "completed": True}

    async def test_deleting_a_page_that_never_existed(self):
        event = self._store_event()
        assert await self.service.delete_page(event.id) == {
            "deleted_photos": 0,
            "completed": True,
        }

    async def test_a_hit_deadline_reports_incomplete_and_keeps_the_page(self):
        """The config row has to survive, or the sweep can never find the
        leftovers again."""
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)

        result = await self.service.delete_page(
            event.id,
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert result["completed"] is False
        assert result["deleted_photos"] == 0
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2

        # And a second, unhurried pass finishes the job.
        assert (await self.service.delete_page(event.id))["completed"] is True
        assert self._config_item(event.id) is None

    async def test_a_swallowed_read_failure_must_not_orphan_the_rows(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)

        async def blind(*_args, **_kwargs):
            return []

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "list_photos", blind)
            await self.service.delete_page(event.id)

        if self._photo_items(event.id):
            assert (
                self._config_item(event.id) is not None
            ), "photo rows survived under a deleted config row"


class _RefusingS3:
    """An S3 client that takes the delete and reports every key as failed.

    `Quiet: True` makes S3 answer with the failures *only*, which is the shape a
    per-key `AccessDenied`, `InternalError` or `SlowDown` arrives in — the call
    itself succeeds, so it is invisible to anything that ignores the response.
    """

    def __init__(self):
        self.calls = 0

    def delete_objects(self, Bucket, Delete):  # noqa: N803 - boto3's own casing
        self.calls += 1
        return {
            "Errors": [
                {"Key": entry["Key"], "Code": "InternalError", "Message": "nope"}
                for entry in Delete["Objects"]
            ],
        }


class _ThrowingS3:
    """An S3 client that fails the whole batch."""

    def delete_objects(self, **_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}},
            "DeleteObjects",
        )


class TestS3RefusesToDelete(LostFoundBase):
    """A photo object that outlives its row is unreachable: nothing knows it
    exists any more, so no admin action, no sweep and no anonymisation pass can
    ever remove it. Every delete path therefore keeps its row unless S3 has
    confirmed the objects are gone."""

    async def test_the_page_and_its_rows_survive_a_refused_delete(self):
        event = self._store_event()
        await self._create_page(event, published=True)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()

        result = await self.service.delete_page(event.id)

        assert result == {"deleted_photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4

    async def test_a_batch_level_client_error_counts_as_a_refusal(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 1)
        self.service._s3 = _ThrowingS3()

        result = await self.service.delete_page(event.id)

        assert result["completed"] is False
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 1

    async def test_the_next_pass_finishes_the_job(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()
        assert (await self.service.delete_page(event.id))["completed"] is False

        # S3 is back: the page is still findable, so the retry works.
        self.service._s3 = None
        result = await self.service.delete_page(event.id)

        assert result == {"deleted_photos": 2, "completed": True}
        assert self._config_item(event.id) is None
        assert self._object_keys() == set()

    async def test_deleting_one_photo_refuses_instead_of_orphaning_it(self):
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1))[0]
        self.service._s3 = _RefusingS3()

        with pytest.raises(ValueError, match="objects_not_deleted"):
            await self.service.delete_photo(event.id, upload.photo_id)

        assert await self.service.get_photo(event.id, upload.photo_id) is not None
        assert len(self._object_keys()) == 2

    async def test_pruning_keeps_a_row_whose_objects_would_not_go(self):
        event = self._store_event()
        await self._create_page(event)
        stale = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL + timedelta(hours=1))
        self.service._s3 = _RefusingS3()

        assert await self.service.prune_pending(event.id) == 0
        assert len(self._photo_items(event.id)) == 1

    async def test_the_sweep_names_the_page_it_could_not_delete(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        summary = await self.service.expire_pages()

        assert summary["pages_deleted"] == 0
        assert summary["completed"] is False
        assert summary["unfinished"] == [str(event.id)]
        assert self._config_item(event.id) is not None


# --- view URLs ---------------------------------------------------------------


class TestViewUrls(LostFoundBase):
    async def test_every_photo_gets_two_signed_urls(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)
        photos = await self.service.list_photos(event.id)

        urls = self.service.presign_view_urls(event.id, photos)

        assert set(urls) == {str(p.photo_id) for p in photos}
        for photo in photos:
            entry = urls[str(photo.photo_id)]
            assert photo.s3_key_thumb in entry["thumb_url"]
            assert photo.s3_key_display in entry["display_url"]
            assert "X-Amz-Signature" in entry["display_url"]
            assert "inline" in entry["display_url"]
            assert f"X-Amz-Expires={URL_TTL_SECONDS}" in entry["display_url"]

    async def test_no_photos_no_urls(self):
        event = self._store_event()
        assert self.service.presign_view_urls(event.id, []) == {}


class TestWithoutABucket(LostFoundBase):
    """Local dev has no photo bucket: writes are refused, reads degrade."""

    bucket = None

    async def test_minting_uploads_is_refused(self):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="bucket_not_configured"):
            await self.service.create_upload_batch(event.id, 1)
        # No number was drawn for an upload that cannot happen.
        assert (await self.service.get_config(event.id)).next_number == 0

    async def test_count_is_validated_before_the_bucket(self):
        event = self._store_event()
        await self._create_page(event)
        with pytest.raises(ValueError, match="count_out_of_range"):
            await self.service.create_upload_batch(event.id, 0)

    async def test_read_paths_degrade_to_null_urls(self):
        event = self._store_event()
        await self._create_page(event)
        photo = LostAndFoundPhoto(
            event_id=event.id,
            number=1,
            s3_key_display=display_key(event.id, uuid4()),
            s3_key_thumb=thumb_key(event.id, uuid4()),
            state=LostAndFoundPhotoState.READY,
        )
        self.events_table.put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo.photo_id}",
                "photo_id": str(photo.photo_id),
                "event_id": str(event.id),
                "number": 1,
                "state": "READY",
                "s3_key_display": photo.s3_key_display,
                "s3_key_thumb": photo.s3_key_thumb,
                "uploaded_at": photo.uploaded_at.isoformat(),
            },
        )

        urls = self.service.presign_view_urls(event.id, [photo])
        # Indexable either way — the page renders a placeholder, not a crash.
        assert urls[str(photo.photo_id)] == {"thumb_url": None, "display_url": None}

    async def test_deleting_still_removes_the_rows(self):
        event = self._store_event()
        await self._create_page(event)
        assert (await self.service.delete_page(event.id))["completed"] is True
        assert self._config_item(event.id) is None


class TestEventDeletionTakesThePage(LostFoundBase):
    """Deleting an event deletes its Fundsachen page then and there.

    The expiry sweep would find the orphan eventually, but „eventually" is up to
    a day of retained photos of guests' belongings after an operator explicitly
    asked for the event to be gone.
    """

    async def test_deleting_a_single_event_takes_the_page_with_it(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_page(event, published=True)
        await self._upload(event, 2)

        assert await self.event_service.delete_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_deleting_a_festival_takes_the_page_with_it(self):
        event = self._store_event(
            event_type=EventType.FESTIVAL,
            status=EventStatus.CANCELLED,
            cancelled_at=NOW,
        )
        await self._create_page(event, published=True)
        await self._upload(event, 3)

        assert await self.event_service.delete_festival_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_an_event_without_a_page_deletes_as_before(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        assert await self.event_service.delete_event(event.org_id, event.id) is True

    async def test_another_events_page_is_left_alone(self):
        doomed = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        neighbour = self._store_event()
        await self._create_page(doomed)
        await self._create_page(neighbour)
        keep = (await self._upload(neighbour, 1))[0]

        await self.event_service.delete_event(doomed.org_id, doomed.id)

        assert self._config_item(neighbour.id) is not None
        assert self._object_keys() == {
            display_key(neighbour.id, keep.photo_id),
            thumb_key(neighbour.id, keep.photo_id),
        }


class TestEventDeleteRefusesToOrphanThePage(LostFoundBase):
    """An event is the only way back to its page.

    `expire_pages` deliberately skips a page whose event does not resolve, and
    the admin API 404s once the ORG#/EVENT# row is gone — so an event deleted
    while its page still owns S3 objects leaves photos of guests' belongings in
    the bucket until the 400-day lifecycle rule, with nothing able to find them
    again. A single transient refusal (AccessDenied, SlowDown, InternalError)
    must therefore fail the event delete, not be logged and walked past.
    """

    async def test_a_single_event_survives_a_refused_page_delete(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_page(event, published=True)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()

        with pytest.raises(ValueError, match="lostfound_not_deleted"):
            await self.event_service.delete_event(event.org_id, event.id)

        assert await self.event_service.get_event(event.org_id, event.id) is not None
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4

    async def test_a_festival_survives_a_refused_page_delete(self):
        event = self._store_event(
            event_type=EventType.FESTIVAL,
            status=EventStatus.CANCELLED,
            cancelled_at=NOW,
        )
        await self._create_page(event, published=True)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        with pytest.raises(ValueError, match="lostfound_not_deleted"):
            await self.event_service.delete_festival_event(event.org_id, event.id)

        assert await self.event_service.get_event(event.org_id, event.id) is not None
        assert self._config_item(event.id) is not None

    async def test_the_retry_goes_through_once_s3_is_back(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_page(event, published=True)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()
        with pytest.raises(ValueError, match="lostfound_not_deleted"):
            await self.event_service.delete_event(event.org_id, event.id)

        self.service._s3 = None
        assert await self.event_service.delete_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()


class TestEventLookupIsPaginated(LostFoundBase):
    """`get_event_by_id` is a filtered scan, and DynamoDB's 1 MB page limit
    counts items *evaluated*, not returned. This table also holds every invite
    row and now every photo row, so a single scan page stopped covering it long
    ago — and a miss here reads as „the event is gone": a spurious 404 on the
    public page, and before the sweep learnt better, a deleted page."""

    async def test_an_event_on_the_second_scan_page_still_resolves(self):
        event = self._store_event()
        config = await self._create_page(event, published=True)

        real_scan = self.events_table.scan
        calls: list[dict] = []

        def paged_scan(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                # A page that was all evaluated and all filtered out — what
                # DynamoDB returns when the limit hits before the match.
                return {"Items": [], "LastEvaluatedKey": {"pk": "x", "sk": "y"}}
            return real_scan(**{k: v for k, v in kwargs.items() if k != "ExclusiveStartKey"})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "scan", paged_scan)
            resolved = await self.service.resolve_public_page(event.id, config.page_token)

        assert resolved is not None
        assert len(calls) == 2
        assert "ExclusiveStartKey" in calls[1]

    async def test_an_event_that_really_is_absent_still_reads_as_absent(self):
        assert await self.event_service.get_event_by_id(uuid4()) is None


# --- the public gate ---------------------------------------------------------


class TestPublicGate(LostFoundBase):
    async def _published(self, **event_overrides):
        event = self._store_event(**event_overrides)
        config = await self._create_page(event, published=True)
        return event, config

    async def test_happy_path_returns_config_and_ready_photos(self):
        event, config = await self._published()
        await self._upload(event, 2)
        await self._upload(event, 1, confirm=False)

        resolved = await self.service.resolve_public_page(event.id, config.page_token)
        assert resolved is not None
        got_config, photos = resolved
        assert got_config.page_token == config.page_token
        assert [p.number for p in photos] == [1, 2]
        assert all(p.state == LostAndFoundPhotoState.READY for p in photos)

    async def test_the_event_comes_along_for_free(self):
        event, config = await self._published()
        resolved = await self.service.resolve_public_page_with_event(
            event.id,
            config.page_token,
        )
        assert resolved is not None
        assert resolved[2].id == event.id
        assert resolved[2].name == event.name

    async def test_wrong_token(self):
        event, _config = await self._published()
        assert await self.service.resolve_public_page(event.id, "x" * 43) is None

    async def test_a_prefix_of_the_token_is_not_enough(self):
        event, config = await self._published()
        assert (
            await self.service.resolve_public_page(
                event.id,
                config.page_token[:-1],
            )
            is None
        )

    async def test_an_empty_token(self):
        event, _config = await self._published()
        assert await self.service.resolve_public_page(event.id, "") is None

    async def test_unknown_event(self):
        _event, config = await self._published()
        assert await self.service.resolve_public_page(uuid4(), config.page_token) is None

    async def test_a_page_whose_event_vanished(self):
        event, config = await self._published()
        self.events_table.delete_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        )
        assert await self.service.resolve_public_page(event.id, config.page_token) is None

    async def test_unpublished_page(self):
        event = self._store_event()
        config = await self._create_page(event)
        assert await self.service.resolve_public_page(event.id, config.page_token) is None

    async def test_unpublishing_closes_the_page_without_losing_photos(self):
        event, config = await self._published()
        await self._upload(event, 2)

        await self.service.upsert_config(event.id, LostAndFoundConfigUpdate(published=False))
        assert await self.service.resolve_public_page(event.id, config.page_token) is None
        assert len(await self.service.list_photos(event.id)) == 2

        await self.service.upsert_config(event.id, LostAndFoundConfigUpdate(published=True))
        assert await self.service.resolve_public_page(event.id, config.page_token) is not None

    async def test_expired_page(self):
        event, config = await self._published(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        assert await self.service.resolve_public_page(event.id, config.page_token) is None

    async def test_a_page_override_can_outlive_the_default(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=120),
            end_at=NOW - timedelta(days=119),
        )
        config = await self._create_page(event, published=True, retention_days=365)
        assert await self.service.resolve_public_page(event.id, config.page_token) is not None

    async def test_a_page_override_can_expire_before_the_default(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=20),
            end_at=NOW - timedelta(days=19),
        )
        config = await self._create_page(event, published=True, retention_days=7)
        assert await self.service.resolve_public_page(event.id, config.page_token) is None

    async def test_an_anonymised_event_still_shows_its_page(self):
        """The page is not guest data the anonymisation removed — it is a box of
        objects the organiser is still trying to return, and its only address is
        the coordinator's."""
        event, config = await self._published()
        self.events_table.update_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
            UpdateExpression="SET anonymized_at = :t",
            ExpressionAttributeValues={":t": NOW.isoformat()},
        )
        assert await self.service.resolve_public_page(event.id, config.page_token) is not None

    async def test_rotation_invalidates_the_old_link(self):
        event, config = await self._published()
        rotated = await self.service.rotate_token(event.id)

        assert await self.service.resolve_public_page(event.id, config.page_token) is None
        assert await self.service.resolve_public_page(event.id, rotated.page_token) is not None

    async def test_the_comparison_is_constant_time(self):
        """`compare_digest`, not `==`: the habit costs nothing and the token is
        the only thing between a stranger and the page."""
        import app.services.lost_and_found_service as module

        calls: list[tuple[str, str]] = []
        real = module.secrets.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        event, config = await self._published()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(module.secrets, "compare_digest", spy)
            await self.service.resolve_public_page(event.id, config.page_token)

        assert calls == [(config.page_token, config.page_token)]

    async def test_a_non_ascii_token_is_a_rejection_not_a_crash(self):
        """`compare_digest` raises TypeError on non-ASCII strings, and this is
        the one path where a raise is a disclosure: a 500 here versus a 404 on
        an unknown event tells a prober which events have a page. The gate
        therefore rejects a non-ASCII token before the comparison.
        """
        event, _config = await self._published()
        assert await self.service.resolve_public_page(event.id, "ö" * 43) is None

    async def test_a_deleted_page_is_gone(self):
        event, config = await self._published()
        await self.service.delete_page(event.id)
        assert await self.service.resolve_public_page(event.id, config.page_token) is None


# --- sweep -------------------------------------------------------------------


class TestExpirySweep(LostFoundBase):
    async def test_a_page_inside_its_window_survives(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=10),
            end_at=NOW - timedelta(days=9),
        )
        await self._create_page(event, published=True)
        await self._upload(event, 2)

        summary = await self.service.expire_pages()

        assert summary["pages_checked"] == 1
        assert summary["pages_deleted"] == 0
        assert summary["completed"] is True
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2

    async def test_a_page_past_its_window_is_deleted_with_its_objects(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True)
        await self._upload(event, 3)

        summary = await self.service.expire_pages()

        assert summary["pages_deleted"] == 1
        assert summary["deleted_photos"] == 3
        assert summary["unfinished"] == []
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_the_page_override_beats_the_setting_in_both_directions(self):
        # 100 days after the event: the 90-day default would expire it.
        long_event = self._store_event(
            start_at=NOW - timedelta(days=101),
            end_at=NOW - timedelta(days=100),
        )
        await self._create_page(long_event, retention_days=365)

        # 10 days after the event: the default would keep it.
        short_event = self._store_event(
            start_at=NOW - timedelta(days=11),
            end_at=NOW - timedelta(days=10),
        )
        await self._create_page(short_event, retention_days=7)

        summary = await self.service.expire_pages()

        assert summary["pages_checked"] == 2
        assert summary["pages_deleted"] == 1
        assert self._config_item(long_event.id) is not None
        assert self._config_item(short_event.id) is None

    async def test_retention_of_a_cancelled_event_runs_from_the_cancellation(self):
        """The date it would have run is irrelevant — the box exists from the
        moment the event was called off."""
        long_dead = self._store_event(
            status=EventStatus.CANCELLED,
            cancelled_at=NOW - timedelta(days=100),
            start_at=NOW + timedelta(days=30),
            end_at=NOW + timedelta(days=31),
            registration_deadline=NOW + timedelta(days=20),
        )
        await self._create_page(long_dead)

        just_cancelled = self._store_event(
            status=EventStatus.CANCELLED,
            cancelled_at=NOW - timedelta(days=1),
            start_at=NOW - timedelta(days=300),
            end_at=NOW - timedelta(days=299),
        )
        await self._create_page(just_cancelled)

        await self.service.expire_pages()

        assert self._config_item(long_dead.id) is None
        assert self._config_item(just_cancelled.id) is not None

    async def test_a_page_whose_event_does_not_resolve_is_kept(self):
        """„The event lookup came back empty" is not „the event is gone".

        `get_event_by_id` is a scan that also answers None when the read failed,
        so deleting on that signal would destroy a live page mid-window over a
        throttled scan. Events deleted properly take their page with them
        (`test_deleting_the_event_takes_the_page_with_it`).
        """
        event = self._store_event()
        await self._create_page(event)
        upload = (await self._upload(event, 1))[0]
        self.events_table.delete_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        )

        summary = await self.service.expire_pages()

        assert summary["pages_deleted"] == 0
        assert self._config_item(event.id) is not None
        assert self._object_keys() == {
            display_key(event.id, upload.photo_id),
            thumb_key(event.id, upload.photo_id),
        }

    async def test_a_page_on_an_anonymised_event_lives_out_its_window(self):
        """Anonymisation is not an expiry trigger. A page put up on a long-past
        event — which anonymisation guarantees it is, being 90 days after the
        end — would otherwise be deleted by the very next sweep, before anyone
        could open the link."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, put_up_late=True)
        self.events_table.update_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
            UpdateExpression="SET anonymized_at = :t",
            ExpressionAttributeValues={":t": NOW.isoformat()},
        )

        assert (await self.service.expire_pages())["pages_deleted"] == 0
        assert self._config_item(event.id) is not None

    async def test_a_page_created_long_after_the_event_is_not_born_expired(self):
        """The retention anchor is the later of event end and page creation, so
        a page on a 199-day-old event still gets its full window — and is swept
        once that window, counted from creation, runs out."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, retention_days=7, put_up_late=True)

        assert (await self.service.expire_pages())["pages_deleted"] == 0

        later = datetime.now(timezone.utc) + timedelta(days=8)
        assert (await self.service.expire_pages(now=later))["pages_deleted"] == 1
        assert self._config_item(event.id) is None

    async def test_the_sweep_prunes_abandoned_uploads_on_pages_it_keeps(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=2),
            end_at=NOW - timedelta(days=1),
        )
        await self._create_page(event, published=True)
        ready = (await self._upload(event, 1))[0]
        stale = (await self._upload(event, 1, confirm=False))[0]
        fresh = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL + timedelta(hours=1))

        summary = await self.service.expire_pages()

        assert summary["pending_pruned"] == 1
        remaining = {
            p.photo_id for p in await self.service.list_photos(event.id, include_pending=True)
        }
        assert remaining == {ready.photo_id, fresh.photo_id}
        assert display_key(event.id, stale.photo_id) not in self._object_keys()

    async def test_the_sweep_accepts_an_explicit_now(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=10),
            end_at=NOW - timedelta(days=9),
        )
        await self._create_page(event)

        assert (await self.service.expire_pages(now=NOW))["pages_deleted"] == 0
        assert (await self.service.expire_pages(now=NOW + timedelta(days=100)))[
            "pages_deleted"
        ] == 1

    async def test_a_hit_deadline_stops_and_names_what_is_left(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event)
        await self._upload(event, 2)

        summary = await self.service.expire_pages(
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert summary["completed"] is False
        assert summary["pages_deleted"] == 0
        assert self._config_item(event.id) is not None

    async def test_an_empty_table_sweeps_cleanly(self):
        summary = await self.service.expire_pages()
        assert {key: summary[key] for key in SWEEP_KEYS} == {
            "pages_checked": 0,
            "pages_deleted": 0,
            "deleted_photos": 0,
            "pending_pruned": 0,
            "orphan_photos_deleted": 0,
            "completed": True,
            "unfinished": [],
            "failed": [],
        }

    async def test_the_summary_is_not_polluted_by_its_own_log_line(self, caplog):
        import logging

        from app.services.logging import request_id_var

        token = request_id_var.set("abc12345")
        try:
            # The mutation happens inside the log call, so INFO has to be
            # reachable for it — as it is in the worker.
            with caplog.at_level(logging.INFO):
                summary = await self.service.expire_pages()
        finally:
            request_id_var.reset(token)

        assert set(summary) == set(SWEEP_KEYS)


class TestOnePageDoesNotBlockTheSweep(LostFoundBase):
    """One page that throws must cost only itself.

    Without isolation the exception leaves `expire_pages` entirely: the worker's
    blanket except turns it into `status: failed` with no counts, every page
    after the failing one in scan order is never examined, and a permanent fault
    (an unparseable row) blocks them again tomorrow and every night after —
    which is exactly the stiller Ausfall the bucket's 400-day rule is only meant
    to be a backstop for. `anonymize_expired_data` isolates each event for the
    same reason.
    """

    async def _expired_page(self, photos: int = 1):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True)
        uploads = await self._upload(event, photos)
        return event, uploads

    async def test_an_unreadable_photo_row_does_not_save_the_other_pages(self):
        broken, uploads = await self._expired_page()
        healthy, _ = await self._expired_page(2)

        # A state no enum member matches — `_item_to_photo` raises ValueError on
        # it, out of `list_photos`, out of `delete_page`.
        self.events_table.update_item(
            Key={
                "pk": f"EVENT#{broken.id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{uploads[0].photo_id}",
            },
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":s": "WEIRD"},
        )

        summary = await self.service.expire_pages()

        assert summary["failed"] == [str(broken.id)]
        assert summary["completed"] is False
        assert summary["pages_deleted"] == 1
        # The healthy page was swept even though the broken one came first or
        # last — scan order must not decide whose photos come down.
        assert self._config_item(healthy.id) is None
        assert self._photo_items(healthy.id) == []
        assert self._config_item(broken.id) is not None

    async def test_a_throttled_row_delete_does_not_save_the_other_pages(self):
        doomed, _ = await self._expired_page()
        other, _ = await self._expired_page()
        real_delete = self.events_table.delete_item

        def flaky(Key, **kwargs):  # noqa: N803 - boto3's own casing
            if Key["pk"] == f"EVENT#{doomed.id}" and Key["sk"].startswith(
                EVENT_SK_LNF_PHOTO_PREFIX,
            ):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ProvisionedThroughputExceededException",
                            "Message": "slow down",
                        },
                    },
                    "DeleteItem",
                )
            return real_delete(Key=Key, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "delete_item", flaky)
            summary = await self.service.expire_pages()

        assert summary["failed"] == [str(doomed.id)]
        assert summary["pages_deleted"] == 1
        assert self._config_item(other.id) is None
        assert self._config_item(doomed.id) is not None


class TestAFailedScanIsNotAnEmptyTable(LostFoundBase):
    """„Nothing to do" and „could not look" must not be the same log line.

    A scan that answered `[]` on a `ClientError` made a permanently broken sweep
    report `pages_checked: 0, completed: True` — and `swept_completely: True` in
    the task result, the one field whose documented meaning is whether it got
    all the way through. Every page past its retention window then stays up with
    nothing to notice.
    """

    def _breaking_scan(self):
        def scan(**_kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ProvisionedThroughputExceededException",
                        "Message": "slow down",
                    },
                },
                "Scan",
            )
        return scan

    async def test_the_sweep_admits_it_could_not_read_the_table(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True)
        await self._upload(event, 1)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "scan", self._breaking_scan())
            summary = await self.service.expire_pages()

        assert summary["completed"] is False
        assert summary["pages_checked"] == 0
        # And it kept its hands off everything it could not see.
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 1

    async def test_the_task_says_it_did_not_sweep_completely(self):
        import app.services.lost_and_found_service as module
        from app.workers.handler import expire_lost_and_found

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(module, "_lost_and_found_service", self.service)
            mp.setattr(self.events_table, "scan", self._breaking_scan())
            result = await expire_lost_and_found()

        assert result["status"] == "completed"
        assert result["swept_completely"] is False

    async def test_an_unreadable_config_row_is_admitted_too(self):
        event = self._store_event()
        await self._create_page(event)
        self.events_table.update_item(
            Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_LNF_CONFIG},
            UpdateExpression="REMOVE page_token",
        )

        summary = await self.service.expire_pages()

        assert summary["completed"] is False
        assert summary["pages_checked"] == 0


class TestOrphanPhotoRows(LostFoundBase):
    """Photo rows whose page is gone are invisible to everything else.

    Both sweeps enumerate pages through `_scan_configs`, and the admin GET
    answers `configured: false` without a config row — so an orphan lives until
    the bucket's 400-day rule and collides on `number` with a page created later
    for the same event. Two tiles labelled „9" is the one thing the counter
    exists to prevent.
    """

    async def _orphan(self, count: int = 2, *, age: timedelta = PENDING_TTL * 2):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self._upload(event, count)
        # Whatever the cause — a batch minted while the page was being deleted,
        # an event row removed by hand — this is the state it leaves behind.
        self.events_table.delete_item(
            Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_LNF_CONFIG},
        )
        for upload in uploads:
            self._age_photo(event, upload.photo_id, age)
        return event, uploads

    async def test_the_sweep_takes_orphans_and_their_objects(self):
        event, _ = await self._orphan()

        summary = await self.service.expire_pages()

        assert summary["orphan_photos_deleted"] == 2
        assert summary["completed"] is True
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_a_live_page_is_never_mistaken_for_an_orphan(self):
        keeper = self._store_event()
        await self._create_page(keeper, published=True)
        await self._upload(keeper, 2)
        orphaned, _ = await self._orphan(1)

        summary = await self.service.expire_pages()

        assert summary["orphan_photos_deleted"] == 1
        assert len(self._photo_items(keeper.id)) == 2
        assert self._photo_items(orphaned.id) == []

    async def test_a_batch_from_this_minute_is_never_an_orphan(self):
        """The page list was taken before the loop, so a page created *during*
        the sweep is legitimately missing from it. Its rows are minutes old — the
        age guard is what keeps an upload in progress from being swept away."""
        event, uploads = await self._orphan(2, age=timedelta(minutes=3))

        summary = await self.service.expire_pages()

        assert summary["orphan_photos_deleted"] == 0
        assert len(self._photo_items(event.id)) == 2

    async def test_a_page_that_exists_after_all_is_left_alone(self):
        """The confirming read: between the page scan and this pass the page may
        have been created, and then its photos are not orphans at all."""
        event = self._store_event()
        await self._create_page(event)
        uploads = await self._upload(event, 1)
        self._age_photo(event, uploads[0].photo_id, PENDING_TTL * 2)

        orphans, complete = self.service._scan_orphan_photos(set())

        assert orphans == []
        # A page created between the two scans is a correct exclusion, not a
        # shortfall — the nightly „swept completely" must not go red for it.
        assert complete is True
        assert len(self._photo_items(event.id)) == 1

    async def test_a_page_list_that_could_not_be_read_deletes_nothing(self):
        """The interlock: against a partial page list every photo looks orphaned."""
        event = self._store_event()
        await self._create_page(event, published=True)
        await self._upload(event, 2)

        def scan(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "InternalServerError", "Message": "no"}},
                "Scan",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "scan", scan)
            summary = await self.service.expire_pages()

        assert summary["orphan_photos_deleted"] == 0
        assert summary["completed"] is False
        assert len(self._photo_items(event.id)) == 2


class TestAFailedPhotoReadIsNotAnEmptyPage(LostFoundBase):
    """`list_photos` answering `[]` for a failed query is a lie its readers
    cannot see through: the public page renders „Hier ist noch nichts
    eingetragen" for a page with forty photos, and the admin grid comes back
    empty — which invites a second upload of the whole box under a second set of
    numbers."""

    def _breaking_query(self):
        def query(**_kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ProvisionedThroughputExceededException",
                        "Message": "slow down",
                    },
                },
                "Query",
            )
        return query

    async def test_listing_raises_instead_of_reporting_an_empty_page(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", self._breaking_query())
            with pytest.raises(ClientError):
                await self.service.list_photos(event.id)

    async def test_the_public_gate_does_not_serve_a_page_it_could_not_read(self):
        event = self._store_event()
        config = await self._create_page(event, published=True)
        await self._upload(event, 2)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", self._breaking_query())
            with pytest.raises(ClientError):
                await self.service.resolve_public_page(event.id, config.page_token)

    async def test_a_delete_whose_work_list_failed_keeps_everything(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 2)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", self._breaking_query())
            result = await self.service.delete_page(event.id)

        assert result == {"deleted_photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4


class TestABatchOutlivingItsPage(LostFoundBase):
    """A reservation proves the page existed when the block was drawn, not that
    it still exists when the last signature is minted — and a row written after
    a concurrent `delete_page` dropped the config row is invisible to every
    sweep and a duplicate number waiting to happen."""

    async def test_a_batch_whose_page_vanished_mid_mint_is_taken_back(self):
        event = self._store_event()
        await self._create_page(event)
        real_presign = self.service._presign_upload
        drops = {"n": 0}

        def presign_then_delete(bucket, key):
            drops["n"] += 1
            if drops["n"] == 1:
                # Another admin's DELETE (or the sweep) lands here.
                self.events_table.delete_item(
                    Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_LNF_CONFIG},
                )
            return real_presign(bucket, key)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "_presign_upload", presign_then_delete)
            with pytest.raises(ValueError, match="page_not_found"):
                await self.service.create_upload_batch(event.id, 3)

        # Nothing was uploaded against those signatures — they never left the
        # process — so taking the rows back is safe, and leaving them would burn
        # numbers a later page would hand out again.
        assert self._photo_items(event.id) == []

    async def test_a_page_that_is_still_there_mints_as_before(self):
        event = self._store_event()
        await self._create_page(event)
        uploads = await self.service.create_upload_batch(event.id, 3)
        assert [u.number for u in uploads] == [1, 2, 3]
        assert len(self._photo_items(event.id)) == 3


class TestPrunePending(LostFoundBase):
    async def test_only_pending_rows_older_than_the_ttl_go(self):
        event = self._store_event()
        await self._create_page(event)
        old_ready = (await self._upload(event, 1))[0]
        old_pending = (await self._upload(event, 1, confirm=False))[0]
        young_pending = (await self._upload(event, 1, confirm=False))[0]

        self._age_photo(event, old_ready.photo_id, PENDING_TTL * 3)
        self._age_photo(event, old_pending.photo_id, PENDING_TTL + timedelta(minutes=1))

        assert await self.service.prune_pending(event.id) == 1

        left = {p.photo_id for p in await self.service.list_photos(event.id, include_pending=True)}
        assert left == {old_ready.photo_id, young_pending.photo_id}
        # A confirmed photo is never a leftover, however old it is.
        assert self._object_keys() >= {display_key(event.id, old_ready.photo_id)}

    async def test_pruning_leaves_the_numbers_burnt(self):
        event = self._store_event()
        await self._create_page(event)
        stale = await self._upload(event, 2, confirm=False)
        for upload in stale:
            self._age_photo(event, upload.photo_id, PENDING_TTL * 2)

        assert await self.service.prune_pending(event.id) == 2
        assert (await self.service.create_upload_batch(event.id, 1))[0].number == 3

    async def test_pruning_without_an_event_id_walks_every_page(self):
        first = self._store_event()
        second = self._store_event()
        await self._create_page(first)
        await self._create_page(second)
        for event in (first, second):
            for upload in await self._upload(event, 1, confirm=False):
                self._age_photo(event, upload.photo_id, PENDING_TTL * 2)

        assert await self.service.prune_pending() == 2
        assert self._photo_items(first.id) == []
        assert self._photo_items(second.id) == []

    async def test_pruning_stops_at_its_deadline(self):
        """A page whose upload was retried over a bad festival link can hold
        hundreds of PENDING rows; without a deadline that loop is what gets the
        invocation killed mid-write, losing the whole sweep summary."""
        event = self._store_event()
        await self._create_page(event)
        stale = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL * 2)

        pruned = await self.service.prune_pending(
            event.id,
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert pruned == 0
        assert len(self._photo_items(event.id)) == 1
        # And an unhurried pass still gets it.
        assert await self.service.prune_pending(event.id) == 1

    async def test_pruning_a_page_with_nothing_to_prune(self):
        event = self._store_event()
        await self._create_page(event)
        await self._upload(event, 1)
        assert await self.service.prune_pending(event.id) == 0


# --- spec 022 interaction ----------------------------------------------------


class TestAnonymizationDeletesThePage(LostFoundBase):
    @pytest.fixture(autouse=True)
    def setup_anonymization(self, setup_env):
        self.anonymization = AnonymizationService()
        self.anonymization._events_table = self.tables["events_table"]
        self.anonymization._registrations_table = self.tables["registrations_table"]
        self.anonymization._messages_table = self.tables["messages_table"]
        # Injected rather than left to the singleton, so the page rows land in
        # the same moto table as everything else.
        self.anonymization._lost_and_found = self.service

    async def test_the_page_is_deleted_outright_not_pseudonymised(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        config = await self._create_page(
            event,
            published=True,
            coordinator_name="Aline",
            retention_days=365,
        )
        await self._upload(event, 2)

        result = await self.anonymization.anonymize_event(event)

        assert result.completed is True
        assert result.lost_and_found_photos == 2
        assert result.lost_and_found_failed is False
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()
        # A photo of a stranger's jacket cannot be pseudonymised, so the whole
        # page goes — and the link dies with it.
        assert await self.service.resolve_public_page(event.id, config.page_token) is None

    async def test_a_refused_object_delete_leaves_the_event_unstamped(self):
        """The page is the one thing anonymisation deletes instead of rewriting,
        so „the objects are still there" has to hold the whole pass open."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        result = await self.anonymization.anonymize_event(event)

        assert result.completed is False
        assert result.lost_and_found_failed is True
        assert result.anonymized_at is None
        assert self._config_item(event.id) is not None
        assert len(self._object_keys()) == 2

    async def test_an_event_without_a_page_is_unaffected(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        result = await self.anonymization.anonymize_event(event)
        assert result.completed is True
        assert result.lost_and_found_photos == 0
        assert result.lost_and_found_failed is False

    async def test_a_page_that_survives_anonymisation_lives_out_its_window(self):
        """A page anonymisation could not delete is no longer swept the next
        night — anonymisation stopped being an expiry trigger when Fundsachen
        became creatable afterwards, so this page now runs out its own window
        like any other. The narrowing is deliberate: the alternative deletes the
        pages organisers put up *after* anonymisation, which is the whole point
        of allowing them."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(event, published=True, retention_days=365)
        await self._upload(event, 1)

        async def exploding_delete(*_args, **_kwargs):
            raise RuntimeError("S3 unreachable")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "delete_page", exploding_delete)
            result = await self.anonymization.anonymize_event(event)

        assert result.lost_and_found_failed is True
        assert self._config_item(event.id) is not None

        # Tonight's sweep leaves it alone — its 365-day window is still open.
        assert (await self.service.expire_pages())["pages_deleted"] == 0
        assert self._config_item(event.id) is not None

        # Once that window closes, the ordinary retention path takes it.
        past_the_window = datetime.now(timezone.utc) + timedelta(days=200)
        summary = await self.service.expire_pages(now=past_the_window)
        assert summary["pages_deleted"] == 1
        assert self._config_item(event.id) is None


# --- the daily worker task ---------------------------------------------------


class TestWorkerTask(LostFoundBase):
    """`expire_lost_and_found` is one service call and a rename of its keys."""

    @pytest.fixture(autouse=True)
    def use_the_singleton(self, setup_env, monkeypatch):
        import app.services.lost_and_found_service as module

        monkeypatch.setattr(module, "_lost_and_found_service", self.service)

    async def test_the_task_reports_what_the_sweep_did(self):
        from app.workers.handler import expire_lost_and_found

        expired = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_page(expired, published=True)
        await self._upload(expired, 2)

        kept = self._store_event()
        await self._create_page(kept, published=True)
        stale = (await self._upload(kept, 1, confirm=False))[0]
        self._age_photo(kept, stale.photo_id, PENDING_TTL * 2)

        result = await expire_lost_and_found()

        assert {key: result[key] for key in TASK_KEYS} == {
            "task": "expire_lost_and_found",
            "status": "completed",
            "pages_checked": 2,
            "pages_deleted": 1,
            "photos_deleted": 2,
            "pending_pruned": 1,
            "orphan_photos_deleted": 0,
            "pages_unfinished": [],
            "pages_failed": [],
            "swept_completely": True,
        }
        assert self._config_item(expired.id) is None
        assert self._config_item(kept.id) is not None

    async def test_the_task_result_is_not_polluted_by_its_own_log_line(self, caplog):
        import logging

        from app.services.logging import request_id_var
        from app.workers.handler import expire_lost_and_found

        token = request_id_var.set("abc12345")
        try:
            with caplog.at_level(logging.INFO):
                result = await expire_lost_and_found()
        finally:
            request_id_var.reset(token)

        assert set(result) == set(TASK_KEYS)

    async def test_a_failing_sweep_is_reported_not_raised(self):
        """The pages are still there tomorrow — this must never fail loudly."""
        from app.workers.handler import expire_lost_and_found

        async def exploding(*_args, **_kwargs):
            raise RuntimeError("DynamoDB unreachable")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "expire_pages", exploding)
            result = await expire_lost_and_found()

        assert result["status"] == "failed"
        assert "DynamoDB unreachable" in result["error"]
