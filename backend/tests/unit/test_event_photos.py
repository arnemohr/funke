"""Tests for the Eventfotos collection: models, service, sweep (spec 024).

Spec 024 is spec 023 held up to a mirror, and every test here circles the one
difference:

**The public direction is writing.** Anyone holding the printed link may put
objects in our bucket, so the five caps that make that survivable — the window,
the upload policy, the per-batch and per-collection ceilings, the hourly quota —
are the load-bearing part of the feature and not decoration. Most of this file
is about them.

**The one-way street is an invariant.** Nothing the service hands back on a
public path may carry a key, a URL or somebody else's `photo_id`. The gate
therefore answers `None` on every rejection, never a reason, and never raises —
including on the non-ASCII token that made spec 023's gate throw a 500.

**Objects and rows die together.** Every delete path is asserted against both
the table and a real (moto) bucket. An orphan row is a cosmetic bug a re-run
fixes; an orphan object is a photo of a guest's face that nothing in the system
can find again.
"""

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

import app.services.config as config_module
import app.services.event_service as event_service_module
from app.models import Event, EventStatus, EventType
from app.models.event_photos import (
    EventPhoto,
    EventPhotoConfig,
    EventPhotoConfigUpdate,
    EventPhotoConfirm,
    EventPhotoState,
    EventPhotoUploadRequest,
)
from app.services.anonymization_service import AnonymizationService
from app.services.config import (
    EVENT_SK_PHOTO_CONFIG,
    EVENT_SK_PHOTO_ITEM_PREFIX,
    EVENT_SK_PHOTO_QUOTA_PREFIX,
    DynamoDBSettings,
)
from app.services.event_photo_service import (
    DEFAULT_UPLOAD_WINDOW_DAYS,
    HOURLY_MINT_CEILING,
    MANIFEST_TTL_SECONDS,
    MAX_PHOTOS,
    MAX_UPLOAD_BATCH,
    MAX_UPLOAD_BYTES_FULL,
    MAX_UPLOAD_BYTES_THUMB,
    PENDING_TTL,
    QUOTA_ROW_TTL,
    URL_TTL_SECONDS,
    EventPhotoService,
    collection_expires_at,
    default_closes_at,
    effective_retention_days,
    full_key,
    hash_uploader_ip,
    is_collection_expired,
    plausible_capture_time,
    public_upload_url,
    thumb_key,
)
from app.services.event_service import EventService, _event_to_item

BUCKET = "funke-test-eventphotos"
REGION = "eu-central-1"
BASE_URL = "https://fest.example.com"
PEPPER = "ein-langer-pfeffer"
NOW = datetime.now(timezone.utc)

# The contract keys of the sweep summary. Projected rather than compared whole,
# for the same reason as in spec 023: the summary doubles as the `extra` of its
# own log line, and a logging handler is free to add to that dict.
SWEEP_KEYS = (
    "collections_checked",
    "collections_deleted",
    "deleted_photos",
    "pending_pruned",
    "quota_rows_pruned",
    "completed",
    "unfinished",
    "failed",
)
# The contract keys of the worker task's summary. Same projection and the same
# reason: the result dict doubles as the `extra` of its own log line.
TASK_KEYS = (
    "task",
    "status",
    "collections_checked",
    "collections_deleted",
    "photos_deleted",
    "pending_pruned",
    "quota_rows_pruned",
    "collections_unfinished",
    "collections_failed",
    "swept_completely",
)


def _policy(fields: dict) -> dict:
    """The decoded POST policy — where the upload's real limits live."""
    return json.loads(base64.b64decode(fields["policy"]))


# --- models ------------------------------------------------------------------


class TestModels:
    def test_config_defaults(self):
        config = EventPhotoConfig(
            event_id=uuid4(),
            upload_token="t" * 43,
            contact_email="fotos@example.com",
        )
        assert config.upload_open is True
        assert config.closes_at is None
        assert config.photo_count == 0
        assert config.retention_days is None

    def test_photo_starts_pending_without_dimensions(self):
        photo = EventPhoto(event_id=uuid4(), s3_key_full="a", s3_key_thumb="b")
        assert photo.state == EventPhotoState.PENDING
        assert photo.width is None and photo.height is None
        assert photo.starred is False
        assert photo.edited_at is None

    def test_photo_count_cannot_be_negative(self):
        """The guard that makes an underflowing counter loud instead of a
        collection that never fills up again."""
        with pytest.raises(ValidationError):
            EventPhotoConfig(
                event_id=uuid4(),
                upload_token="t" * 43,
                contact_email="a@b.de",
                photo_count=-1,
            )

    def test_a_javascript_url_is_not_a_contact(self):
        """The value ends up as an `href` on a page anyone can open, so only
        `https://t.me/…` survives the normaliser."""
        with pytest.raises(ValidationError):
            EventPhotoConfigUpdate(contact_telegram_url="javascript:alert(1)")

    def test_a_telegram_handle_is_normalised(self):
        patch = EventPhotoConfigUpdate(contact_telegram_url="@fotocrew")
        assert patch.contact_telegram_url == "https://t.me/fotocrew"

    def test_config_update_forbids_unknown_fields(self):
        with pytest.raises(ValidationError):
            EventPhotoConfigUpdate(contact_email="a@b.de", photo_count=99)

    def test_config_update_tracks_what_was_set(self):
        """`exclude_unset` is the entire patch semantics — omitted vs. null, and
        for `closes_at` the two mean genuinely different things."""
        assert EventPhotoConfigUpdate(closes_at=None).model_dump(exclude_unset=True) == {
            "closes_at": None,
        }
        assert EventPhotoConfigUpdate().model_dump(exclude_unset=True) == {}

    @pytest.mark.parametrize("extra", [{"starred": True}, {"state": "READY"}, {"s3_key_full": "x"}])
    def test_confirm_cannot_carry_a_privilege(self, extra):
        """`extra="forbid"` is what turns „confirm sets only what the browser
        knows" from a promise in the service into a 422 at the edge."""
        with pytest.raises(ValidationError):
            EventPhotoConfirm(photo_id=uuid4(), width=10, height=10, bytes=10, **extra)

    def test_confirm_bounds_pixels_and_bytes(self):
        with pytest.raises(ValidationError):
            EventPhotoConfirm(photo_id=uuid4(), width=0, height=10, bytes=10)
        with pytest.raises(ValidationError):
            EventPhotoConfirm(photo_id=uuid4(), width=10, height=20001, bytes=10)
        with pytest.raises(ValidationError):
            EventPhotoConfirm(photo_id=uuid4(), width=10, height=10, bytes=0)

    def test_the_upload_request_leaves_the_batch_ceiling_to_the_service(self):
        """A pydantic 422 is an opaque wall of JSON on a phone; the service's
        `count_out_of_range` becomes a German sentence."""
        assert EventPhotoUploadRequest(count=MAX_UPLOAD_BATCH + 1).count == MAX_UPLOAD_BATCH + 1
        with pytest.raises(ValidationError):
            EventPhotoUploadRequest(count=0)


# --- shared fixture ----------------------------------------------------------


class PhotoBase:
    """A service wired to moto's DynamoDB and a real (moto) photo bucket."""

    #: Overridden by the class that checks the unconfigured-bucket degradation.
    bucket: str | None = BUCKET
    #: Overridden by the class that checks the un-peppered IP hash.
    pepper: str | None = PEPPER

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb, monkeypatch):
        self.tables = mock_dynamodb
        self.events_table = mock_dynamodb["events_table"]

        monkeypatch.setattr(
            config_module,
            "_settings",
            DynamoDBSettings(
                event_photo_s3_bucket=self.bucket,
                event_photo_retention_days=90,
                photo_ip_pepper=self.pepper,
                base_url=BASE_URL,
            ),
        )

        self.s3 = boto3.client("s3", region_name=REGION)
        self.s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )

        self.service = EventPhotoService()
        self.service._table = self.events_table

        event_service = EventService()
        event_service._table = self.events_table
        # Injected rather than left to the singleton, because the sweep resolves
        # every collection's event through it and has to find this test's rows.
        # Injected rather than left to the singleton, so the collection its
        # delete paths remove is the one in this test's moto table.
        event_service._event_photos = self.service
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

    async def _create_collection(
        self,
        event: Event,
        *,
        put_up_late: bool = False,
        **patch,
    ) -> EventPhotoConfig:
        """Create the collection, by default as if it went up at the event's end.

        Retention runs from the later of event end and collection creation, so a
        collection minted *now* on a long-finished event gets a full fresh window
        — correct behaviour, but never what a test about retention means. The
        default therefore backdates `created_at` to the event's end;
        `put_up_late=True` keeps the real creation time for the tests that are
        specifically about a collection added long afterwards.
        """
        body = {"contact_email": "fotos@example.com"}
        body.update(patch)
        config = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(**body),
            event,
        )

        from app.services.lost_and_found_service import event_finished_at

        finished = event_finished_at(event)
        if not put_up_late and finished < datetime.now(timezone.utc):
            self.events_table.update_item(
                Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_PHOTO_CONFIG},
                UpdateExpression="SET created_at = :t",
                ExpressionAttributeValues={":t": finished.isoformat()},
            )
            config = config.model_copy(update={"created_at": finished})
        return config

    async def _upload(
        self,
        event: Event,
        count: int,
        *,
        confirm: bool = True,
        store: bool = True,
        **mint_kwargs,
    ):
        """Mint `count` uploads, optionally put the objects and confirm them."""
        uploads = await self.service.create_upload_batch(event.id, count, **mint_kwargs)

        if store:
            for upload in uploads:
                for key in (
                    full_key(event.id, upload.photo_id),
                    thumb_key(event.id, upload.photo_id),
                ):
                    self.s3.put_object(Bucket=BUCKET, Key=key, Body=b"jpeg-bytes")

        if confirm:
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=u.photo_id, width=2560, height=1707, bytes=1_200_000,
                    )
                    for u in uploads
                ],
                event,
            )
        return uploads

    # -- raw table/bucket access ---------------------------------------------

    def _config_item(self, event_id) -> dict | None:
        return self.events_table.get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
        ).get("Item")

    def _photo_items(self, event_id) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        return self.events_table.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with(EVENT_SK_PHOTO_ITEM_PREFIX),
        )["Items"]

    def _quota_items(self, event_id) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        return self.events_table.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with(EVENT_SK_PHOTO_QUOTA_PREFIX),
        )["Items"]

    def _object_keys(self) -> set[str]:
        listing = self.s3.list_objects_v2(Bucket=BUCKET)
        return {o["Key"] for o in listing.get("Contents", [])}

    async def _photo_count(self, event_id) -> int:
        return (await self.service.get_config(event_id)).photo_count

    def _set_photo_count(self, event_id, value: int) -> None:
        self.events_table.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
            UpdateExpression="SET photo_count = :n",
            ExpressionAttributeValues={":n": value},
        )

    def _age_photo(self, event: Event, photo_id, age: timedelta) -> None:
        self.events_table.update_item(
            Key={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo_id}",
            },
            UpdateExpression="SET uploaded_at = :t",
            ExpressionAttributeValues={
                ":t": (datetime.now(timezone.utc) - age).isoformat(),
            },
        )


# --- helpers -----------------------------------------------------------------


class TestHelpers(PhotoBase):
    def test_keys_are_exact(self):
        """The key is the one part of a presigned POST that is nailed down, and
        the folder layout is what makes a whole collection one prefix."""
        event_id, photo_id = uuid4(), uuid4()
        assert full_key(event_id, photo_id) == f"eventphotos/{event_id}/{photo_id}/full.jpg"
        assert thumb_key(event_id, photo_id) == f"eventphotos/{event_id}/{photo_id}/thumb.jpg"

    def test_the_two_variants_share_one_folder_per_photo(self):
        event_id, photo_id = uuid4(), uuid4()
        prefix = f"eventphotos/{event_id}/{photo_id}/"
        assert full_key(event_id, photo_id).startswith(prefix)
        assert thumb_key(event_id, photo_id).startswith(prefix)

    def test_public_upload_url_shape(self):
        """German path on purpose — this one is printed on a slip at the exit."""
        event_id, token = uuid4(), "t" * 43
        assert public_upload_url(event_id, token) == f"{BASE_URL}/fotos/{event_id}/{token}"

    def test_default_closes_at_is_three_weeks_after_the_event(self):
        """For an event still ahead of us, the event end is the anchor."""
        event = self._store_event(
            start_at=NOW + timedelta(days=10),
            end_at=NOW + timedelta(days=11),
        )
        assert default_closes_at(event) == event.end_at + timedelta(
            days=DEFAULT_UPLOAD_WINDOW_DAYS,
        )
        assert DEFAULT_UPLOAD_WINDOW_DAYS == 21

    def test_default_closes_at_never_lands_in_the_past(self):
        """Regression: a collection put up late must not be born closed.

        With the event end as the only anchor, any collection created more than
        21 days after its event got a `closes_at` in the past — so the very
        first `GET` of the freshly printed link answered `upload_open: false`,
        while the form had promised „leer lassen — dann setzen wir 21 Tage nach
        dem Event". It broke exactly the case spec 024 names as the point of
        re-creatable collections: the late round after an event's guest data was
        anonymised at 90 days.
        """
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        closes_at = default_closes_at(event)

        assert closes_at > datetime.now(timezone.utc)
        # Anchored on today, not on the event — the same „later of the two" rule
        # `collection_expires_at` uses, and for the same reason.
        assert closes_at - datetime.now(timezone.utc) > timedelta(days=20)
        assert closes_at - datetime.now(timezone.utc) < timedelta(days=22)

    async def test_a_late_collection_can_actually_be_uploaded_to(self):
        """The end of the same regression, one level up: the window the config
        row was born with has to be open."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        config = await self._create_collection(event, put_up_late=True)

        assert config.closes_at > datetime.now(timezone.utc)
        assert self.service.upload_window_open(config, event) is True

    async def test_effective_retention_prefers_the_collection_override(self):
        event = self._store_event()
        config = await self._create_collection(event)
        assert effective_retention_days(config) == 90

        overridden = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(retention_days=14),
            event,
        )
        assert effective_retention_days(overridden) == 14

    async def test_expiry_counts_from_the_event_end(self):
        event = self._store_event()
        config = await self._create_collection(event, retention_days=7)
        assert collection_expires_at(event, config) == event.end_at + timedelta(days=7)
        assert is_collection_expired(event, config, now=event.end_at + timedelta(days=6)) is False
        assert is_collection_expired(event, config, now=event.end_at + timedelta(days=8)) is True

    async def test_a_late_collection_is_not_born_expired(self):
        """The anchor is the later of event end and creation — otherwise a „nun
        schickt doch mal eure Fotos" round on a six-month-old event would be
        swept in the night after it was set up."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        config = await self._create_collection(event, retention_days=7, put_up_late=True)
        assert is_collection_expired(event, config) is False


class TestCaptureHint(PhotoBase):
    """`file.lastModified` is all that survives the canvas downscale, and on a
    forwarded file it is the save time, not the capture time — so it is judged
    before it is trusted."""

    def test_no_hint_is_no_hint(self):
        event = self._store_event()
        assert plausible_capture_time(None, event) is None

    def test_a_hint_in_the_future_is_discarded(self):
        event = self._store_event()
        assert plausible_capture_time(NOW + timedelta(hours=1), event) is None

    def test_a_hint_a_week_before_the_event_is_discarded(self):
        event = self._store_event()
        assert plausible_capture_time(event.start_at - timedelta(days=7), event) is None

    def test_a_hint_during_the_event_is_used(self):
        event = self._store_event()
        moment = event.start_at + timedelta(hours=5)
        assert plausible_capture_time(moment, event) == moment

    def test_the_travel_day_is_still_the_event(self):
        """A day of slack covers the „wir sind schon Freitag losgefahren" photos
        and the time zone of a phone that never left home."""
        event = self._store_event()
        moment = event.start_at - timedelta(hours=20)
        assert plausible_capture_time(moment, event) == moment

    def test_a_naive_hint_is_read_as_utc(self):
        event = self._store_event()
        naive = (event.start_at + timedelta(hours=2)).replace(tzinfo=None)
        assert plausible_capture_time(naive, event).tzinfo is timezone.utc


class TestUploaderIpHash(PhotoBase):
    def test_the_hash_is_stable_and_is_not_the_address(self):
        first = hash_uploader_ip("203.0.113.7")
        assert first == hash_uploader_ip("203.0.113.7")
        assert first != hash_uploader_ip("203.0.113.8")
        assert "203.0.113.7" not in first
        assert len(first) == 16
        assert all(c in "0123456789abcdef" for c in first)

    def test_no_address_no_hash(self):
        assert hash_uploader_ip(None) is None
        assert hash_uploader_ip("") is None

    async def test_the_hash_lands_on_every_row_of_the_batch(self):
        event = self._store_event()
        await self._create_collection(event)
        digest = hash_uploader_ip("198.51.100.4")

        await self._upload(event, 2, ip_hash=digest)

        rows = self._photo_items(event.id)
        assert {row["uploader_ip_hash"] for row in rows} == {digest}


class TestUploaderIpHashWithoutPepper(PhotoBase):
    """For a privacy field the safe default is storing nothing — never
    „unpeppered if need be", because a bare hash over the IPv4 space is
    reversible in seconds on a laptop."""

    pepper = None

    def test_without_a_pepper_nothing_is_hashed(self):
        assert hash_uploader_ip("203.0.113.7") is None

    def test_an_empty_pepper_counts_as_unset(self):
        """This is the case that actually ships. CloudFormation renders an
        unconfigured secret into the Lambda environment as `""`, not as an
        absent variable, so a check for `is None` would let every deploy
        without a pepper store `HMAC(b"", ip)` — a keyless hash over the IPv4
        space, which is exactly what the pepper exists to prevent."""
        settings = config_module.get_settings()
        assert settings.photo_ip_pepper is None
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "photo_ip_pepper", "")
            assert hash_uploader_ip("203.0.113.7") is None

    async def test_and_nothing_is_stored(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1, ip_hash=hash_uploader_ip("203.0.113.7"))
        assert "uploader_ip_hash" not in self._photo_items(event.id)[0]


# --- configuration -----------------------------------------------------------


class TestConfig(PhotoBase):
    async def test_no_collection_reads_as_none(self):
        event = self._store_event()
        assert await self.service.get_config(event.id) is None

    async def test_the_first_save_mints_the_token_and_the_default_window(self):
        event = self._store_event()
        config = await self._create_collection(event)

        assert len(config.upload_token) == 43
        assert config.upload_open is True
        assert config.photo_count == 0
        # Later of event end and now, plus 21 days — for this event, which ended
        # three days ago, that is 21 days from today.
        assert config.closes_at > datetime.now(timezone.utc) + timedelta(days=20)
        assert config.closes_at < datetime.now(timezone.utc) + timedelta(days=22)
        assert self.service.upload_window_open(config, event) is True
        assert self._config_item(event.id)["upload_token"] == config.upload_token

    async def test_the_first_save_without_any_contact_is_refused(self):
        """On a page where people hand in photos *of other people* it has to say
        who to ask to get one removed — so there is no first save without a
        contact, and therefore no valid token for a half-finished collection."""
        event = self._store_event()
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                EventPhotoConfigUpdate(intro_text="Her mit den Fotos"),
                event,
            )
        assert self._config_item(event.id) is None

    async def test_a_telegram_link_is_a_contact_on_its_own(self):
        event = self._store_event()
        config = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_telegram_url="@fotocrew"),
            event,
        )
        assert config.contact_email is None
        assert config.contact_telegram_url == "https://t.me/fotocrew"
        assert self._config_item(event.id).get("contact_email") is None

    async def test_clearing_the_last_contact_is_refused(self):
        event = self._store_event()
        await self._create_collection(event)
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                EventPhotoConfigUpdate(contact_email=None),
                event,
            )
        assert (await self.service.get_config(event.id)).contact_email == "fotos@example.com"

    async def test_the_mail_can_go_once_telegram_is_there(self):
        event = self._store_event()
        await self._create_collection(event)
        await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_telegram_url="https://t.me/+AbCdEfGh"),
            event,
        )
        cleared = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_email=None),
            event,
        )
        assert cleared.contact_email is None
        assert cleared.contact_telegram_url == "https://t.me/+AbCdEfGh"

    async def test_clearing_telegram_when_it_is_the_only_contact_is_refused(self):
        event = self._store_event()
        await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_telegram_url="@fotocrew"),
            event,
        )
        with pytest.raises(ValueError, match="contact_required"):
            await self.service.upsert_config(
                event.id,
                EventPhotoConfigUpdate(contact_telegram_url=None),
                event,
            )

    async def test_omitted_fields_are_left_alone(self):
        event = self._store_event()
        await self._create_collection(
            event,
            contact_name="Katja",
            intro_text="Wir sammeln alles ein.",
        )
        patched = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(upload_open=False),
            event,
        )
        assert patched.contact_name == "Katja"
        assert patched.intro_text == "Wir sammeln alles ein."
        assert patched.upload_open is False

    async def test_an_explicit_null_closes_at_means_never_close_by_itself(self):
        """„I did not touch this" and „this should not close automatically" are
        different statements, and only the first one gets the 21-day default."""
        event = self._store_event()
        config = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_email="fotos@example.com", closes_at=None),
            event,
        )
        assert config.closes_at is None
        assert "closes_at" not in self._config_item(event.id)

    async def test_an_explicit_null_clears_a_stored_field(self):
        event = self._store_event()
        await self._create_collection(event, contact_name="Katja", retention_days=14)

        cleared = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(contact_name=None, retention_days=None, closes_at=None),
            event,
        )
        assert cleared.contact_name is None
        assert cleared.retention_days is None
        assert cleared.closes_at is None
        # `retention_days: null` is how the form goes back to the environment
        # default — the attribute has to be gone, not zero.
        assert effective_retention_days(cleared) == 90
        assert "retention_days" not in self._config_item(event.id)

    async def test_saving_never_rewrites_the_token_or_the_counter(self):
        """A full `put_item` here would hand an in-flight batch's reservations
        away and could resurrect a rotated token."""
        event = self._store_event()
        config = await self._create_collection(event)
        await self._upload(event, 2)

        patched = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(intro_text="Neu"),
            event,
        )
        assert patched.upload_token == config.upload_token
        assert patched.photo_count == 2

    async def test_losing_the_create_race_keeps_the_winners_token(self):
        """Two first saves at once: the loser must patch, not overwrite — the
        winner's token may already have been copied onto a printed slip, and its
        `photo_count` may already carry reservations."""
        event = self._store_event()
        winner = await self._create_collection(event)
        await self._upload(event, 1, confirm=False)

        async def blind(_event_id):
            return None

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "get_config", blind)
            loser = await self.service.upsert_config(
                event.id,
                EventPhotoConfigUpdate(contact_email="zweite@example.com"),
                event,
            )

        assert loser.upload_token == winner.upload_token
        assert loser.photo_count == 1
        assert loser.contact_email == "zweite@example.com"

    async def test_rotate_token_replaces_the_token_and_keeps_the_photos(self):
        event = self._store_event()
        config = await self._create_collection(event)
        await self._upload(event, 2)

        rotated = await self.service.rotate_token(event.id)

        assert rotated.upload_token != config.upload_token
        assert len(rotated.upload_token) == 43
        assert rotated.photo_count == 2
        assert len(await self.service.list_photos(event.id)) == 2

    async def test_rotate_token_without_a_collection(self):
        event = self._store_event()
        with pytest.raises(ValueError, match="page_not_found"):
            await self.service.rotate_token(event.id)

    async def test_updated_at_moves_created_at_does_not(self):
        event = self._store_event()
        config = await self._create_collection(event, put_up_late=True)
        patched = await self.service.upsert_config(
            event.id,
            EventPhotoConfigUpdate(upload_open=False),
            event,
        )
        assert patched.created_at == config.created_at
        assert patched.updated_at >= config.updated_at


# --- the upload window -------------------------------------------------------


class TestUploadWindow(PhotoBase):
    """The window is the strongest of the five abuse controls, because it limits
    the write permission to the weeks in which it has a purpose."""

    async def test_an_ordinary_collection_is_open(self):
        event = self._store_event()
        config = await self._create_collection(event)
        assert self.service.upload_window_open(config, event) is True

    async def test_the_switch_closes_it_without_devaluing_the_link(self):
        event = self._store_event()
        config = await self._create_collection(event, upload_open=False)
        assert self.service.upload_window_open(config, event) is False
        # And the link still resolves, so the closed page can explain itself.
        assert await self.service.resolve_public_page(event.id, config.upload_token) is not None

    async def test_a_closes_at_in_the_past_closes_it(self):
        event = self._store_event()
        config = await self._create_collection(
            event,
            closes_at=NOW - timedelta(hours=1),
        )
        assert self.service.upload_window_open(config, event) is False
        assert (
            self.service.upload_window_open(config, event, now=NOW - timedelta(days=1))
            is True
        )

    async def test_a_collection_past_its_retention_is_closed(self):
        """Photos due for deletion tonight must not attract more of them."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        config = await self._create_collection(event, closes_at=None)
        assert config.closes_at is None
        assert self.service.upload_window_open(config, event) is False

    async def test_a_collection_that_never_closes_by_itself_stays_open(self):
        event = self._store_event()
        config = await self._create_collection(event, closes_at=None)
        assert self.service.upload_window_open(config, event) is True


# --- the public gate ---------------------------------------------------------


class TestPublicGate(PhotoBase):
    async def test_the_happy_path_returns_the_config(self):
        event = self._store_event()
        config = await self._create_collection(event)

        resolved = await self.service.resolve_public_page(event.id, config.upload_token)

        assert resolved is not None
        assert resolved.upload_token == config.upload_token

    async def test_the_event_comes_along_for_free(self):
        event = self._store_event()
        config = await self._create_collection(event)

        resolved = await self.service.resolve_public_page_with_event(
            event.id,
            config.upload_token,
        )

        assert resolved is not None
        assert resolved[1].id == event.id
        assert resolved[1].name == event.name

    async def test_a_collection_whose_event_vanished_is_not_resolvable(self):
        """Without the event there is no way to tell whether the window is still
        open, and „no answer" must not become „upload away"."""
        event = self._store_event()
        config = await self._create_collection(event)
        self.events_table.delete_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        )
        assert (
            await self.service.resolve_public_page_with_event(event.id, config.upload_token)
            is None
        )

    async def test_a_wrong_token(self):
        event = self._store_event()
        await self._create_collection(event)
        assert await self.service.resolve_public_page(event.id, "x" * 43) is None

    async def test_a_prefix_of_the_token_is_not_enough(self):
        event = self._store_event()
        config = await self._create_collection(event)
        assert (
            await self.service.resolve_public_page(event.id, config.upload_token[:-1]) is None
        )

    async def test_an_empty_token(self):
        event = self._store_event()
        await self._create_collection(event)
        assert await self.service.resolve_public_page(event.id, "") is None

    async def test_an_unknown_event(self):
        event = self._store_event()
        config = await self._create_collection(event)
        assert await self.service.resolve_public_page(uuid4(), config.upload_token) is None

    async def test_an_event_without_a_collection(self):
        event = self._store_event()
        assert await self.service.resolve_public_page(event.id, "t" * 43) is None

    @pytest.mark.parametrize("token", ["ö" * 43, "🙂" * 43, "tökenmitümlaut"])
    async def test_a_non_ascii_token_is_a_rejection_not_a_crash(self, token):
        """`compare_digest` raises TypeError on a non-ASCII string, and this is
        the one path where a raise is a disclosure: a 500 on an event that has a
        collection next to a 404 on one that does not lets a prober enumerate
        which events collect photos. Spec 023 learned this the hard way; here the
        `isascii()` guard is the first line of the comparison — so nothing may
        escape this call, not even a TypeError.
        """
        event = self._store_event()
        await self._create_collection(event)

        try:
            resolved = await self.service.resolve_public_page(event.id, token)
        except Exception as exc:  # noqa: BLE001 - the raise itself is the bug
            pytest.fail(f"the gate raised {type(exc).__name__} instead of refusing: {exc}")

        assert resolved is None

    async def test_the_comparison_is_constant_time(self):
        """`compare_digest`, not `==`: the habit costs nothing and the token is
        the only thing between a stranger and a write permission."""
        import app.services.event_photo_service as module

        calls: list[tuple[str, str]] = []
        real = module.secrets.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        event = self._store_event()
        config = await self._create_collection(event)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(module.secrets, "compare_digest", spy)
            await self.service.resolve_public_page(event.id, config.upload_token)

        assert calls == [(config.upload_token, config.upload_token)]

    async def test_a_non_ascii_token_never_reaches_the_comparison(self):
        import app.services.event_photo_service as module

        calls: list[tuple[str, str]] = []
        real = module.secrets.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        event = self._store_event()
        await self._create_collection(event)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(module.secrets, "compare_digest", spy)
            assert await self.service.resolve_public_page(event.id, "ä" * 43) is None

        assert calls == []

    async def test_rotation_invalidates_the_printed_slip(self):
        event = self._store_event()
        config = await self._create_collection(event)
        rotated = await self.service.rotate_token(event.id)

        assert await self.service.resolve_public_page(event.id, config.upload_token) is None
        assert (
            await self.service.resolve_public_page(event.id, rotated.upload_token) is not None
        )

    async def test_a_deleted_collection_is_gone(self):
        event = self._store_event()
        config = await self._create_collection(event)
        await self.service.delete_collection(event.id)
        assert await self.service.resolve_public_page(event.id, config.upload_token) is None

    async def test_the_gate_does_not_fold_in_the_window(self):
        """Deliberate: a closed collection still has to render „der Upload ist
        zu, schreib an …" instead of leaving a guest with a slip and a 404. The
        409 is the router's job, off `upload_window_open`."""
        event = self._store_event()
        config = await self._create_collection(event, upload_open=False, closes_at=NOW)
        resolved = await self.service.resolve_public_page(event.id, config.upload_token)
        assert resolved is not None
        assert self.service.upload_window_open(resolved, event) is False


# --- upload policy -----------------------------------------------------------


class TestUploadPolicy(PhotoBase):
    async def test_the_policy_carries_the_size_limit_type_and_exact_key(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        for variant, expected_key, ceiling in (
            (upload.full, full_key(event.id, upload.photo_id), MAX_UPLOAD_BYTES_FULL),
            (upload.thumb, thumb_key(event.id, upload.photo_id), MAX_UPLOAD_BYTES_THUMB),
        ):
            conditions = _policy(variant.fields)["conditions"]
            # One byte to the ceiling: a leaked signature cannot be used to park
            # a film in the bucket, and a `thumb` slot cannot quietly be filled
            # with a second full-size image.
            assert ["content-length-range", 1, ceiling] in conditions
            # Where „keine Videos" is actually enforced — in the policy, not in
            # the file picker.
            assert {"Content-Type": "image/jpeg"} in conditions
            # Exact key, not a prefix: a permission to write this one object and
            # nothing else in the bucket.
            assert {"key": expected_key} in conditions
            assert {"bucket": BUCKET} in conditions
            assert variant.fields["key"] == expected_key
            assert variant.fields["Content-Type"] == "image/jpeg"
            assert variant.fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
            assert "x-amz-signature" in variant.fields

    async def test_the_two_ceilings_are_six_megabytes_and_four_hundred_kilobytes(self):
        assert MAX_UPLOAD_BYTES_FULL == 6 * 1024 * 1024
        assert MAX_UPLOAD_BYTES_THUMB == 400 * 1024

    async def test_the_upload_url_is_the_regional_endpoint(self):
        """boto3's default `bucket.s3.amazonaws.com` answers 307 to the regional
        host for any bucket outside us-east-1, and a browser will not replay a
        cross-origin multipart POST across that redirect — the upload dies with
        an opaque CORS/network error while curl follows it happily. This is the
        production failure of spec 023, kept from repeating."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        for variant in (upload.full, upload.thumb):
            assert variant.url == f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"

    async def test_the_view_urls_are_regional_too(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)

        urls = self.service.presign_view_urls(
            event.id,
            await self.service.list_photos(event.id),
        )
        for pair in urls.values():
            for url in pair.values():
                assert url.startswith(f"https://{BUCKET}.s3.{REGION}.amazonaws.com/")

    async def test_the_signature_expires_after_fifteen_minutes(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        expiration = datetime.fromisoformat(
            _policy(upload.full.fields)["expiration"].replace("Z", "+00:00"),
        )
        remaining = expiration - datetime.now(timezone.utc)
        assert URL_TTL_SECONDS == 900
        assert timedelta(seconds=URL_TTL_SECONDS - 60) < remaining <= timedelta(
            seconds=URL_TTL_SECONDS,
        )

    async def test_the_row_exists_before_the_upload_happens(self):
        """A failed presign may leave a prunable row; it may never leave an
        object nothing points at."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]

        photo = await self.service.get_photo(event.id, upload.photo_id)
        assert photo is not None
        assert photo.state == EventPhotoState.PENDING
        assert photo.s3_key_full == full_key(event.id, upload.photo_id)
        assert photo.s3_key_thumb == thumb_key(event.id, upload.photo_id)
        assert self._object_keys() == set()

    async def test_the_two_variants_get_different_signatures(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self.service.create_upload_batch(event.id, 1))[0]
        assert upload.full.fields["key"] != upload.thumb.fields["key"]
        assert upload.full.fields["x-amz-signature"] != upload.thumb.fields["x-amz-signature"]

    async def test_the_uploaders_own_words_land_on_every_row(self):
        event = self._store_event()
        await self._create_collection(event)
        await self.service.create_upload_batch(
            event.id,
            2,
            uploader_name="Katja",
            note="die Bilder vom Lagerfeuer",
        )
        rows = self._photo_items(event.id)
        assert {row["uploader_name"] for row in rows} == {"Katja"}
        assert {row["note"] for row in rows} == {"die Bilder vom Lagerfeuer"}


# --- the caps ----------------------------------------------------------------


class TestCaps(PhotoBase):
    @pytest.mark.parametrize("count", [0, -1, MAX_UPLOAD_BATCH + 1, 1000])
    async def test_a_count_outside_the_range_is_refused(self, count):
        event = self._store_event()
        await self._create_collection(event)

        with pytest.raises(ValueError, match="count_out_of_range"):
            await self.service.create_upload_batch(event.id, count)

        # Arithmetic only: nothing was reserved and no quota was charged.
        assert await self._photo_count(event.id) == 0
        assert self._quota_items(event.id) == []
        assert self._photo_items(event.id) == []

    async def test_the_maximum_batch_is_allowed(self):
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self.service.create_upload_batch(event.id, MAX_UPLOAD_BATCH)
        assert len(uploads) == MAX_UPLOAD_BATCH
        assert MAX_UPLOAD_BATCH == 30

    async def test_uploads_without_a_collection_are_refused(self):
        event = self._store_event()
        with pytest.raises(ValueError, match="page_not_found"):
            await self.service.create_upload_batch(event.id, 1)

    async def test_a_full_collection_answers_instead_of_signing(self):
        event = self._store_event()
        await self._create_collection(event)
        self._set_photo_count(event.id, MAX_PHOTOS)

        with pytest.raises(ValueError, match="collection_full"):
            await self.service.create_upload_batch(event.id, 1)

        assert MAX_PHOTOS == 2000
        assert self._photo_items(event.id) == []
        assert await self._photo_count(event.id) == MAX_PHOTOS
        # The order of the five checks is part of the contract: „diese Sammlung
        # ist voll" comes before the hourly quota, so a guest who keeps tapping
        # a full collection does not also burn the quota of the guests whose
        # photos would still fit if the organiser cleared some out.
        assert self._quota_items(event.id) == []

    async def test_a_batch_that_would_overshoot_the_cap_is_refused_whole(self):
        """Not „the first five fit" — a partly-served batch would leave the page
        reporting successes for photos it has no signature for."""
        event = self._store_event()
        await self._create_collection(event)
        self._set_photo_count(event.id, MAX_PHOTOS - 5)

        with pytest.raises(ValueError, match="collection_full"):
            await self.service.create_upload_batch(event.id, 10)
        assert self._photo_items(event.id) == []

    async def test_the_reserved_value_decides_not_the_one_read_before(self):
        """Two concurrent batches both pass the read-based pre-check; the `ADD`
        is what makes only one of them fit. Simulated with a stale read, which is
        exactly what the loser of that race has.
        """
        event = self._store_event()
        await self._create_collection(event)
        self._set_photo_count(event.id, MAX_PHOTOS - 5)

        stale = (await self.service.get_config(event.id)).model_copy(
            update={"photo_count": MAX_PHOTOS - 10},
        )

        async def stale_read(_event_id):
            return stale

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "get_config", stale_read)
            with pytest.raises(ValueError, match="collection_full"):
                await self.service.create_upload_batch(event.id, 10)

        # Released again, so a collection at the cap does not stay locked at
        # 2010 by the callers it turned away.
        assert await self._photo_count(event.id) == MAX_PHOTOS - 5
        assert self._photo_items(event.id) == []

    async def test_the_hourly_quota_refuses_and_reopens_next_hour(self):
        """The quota row is seeded rather than earned: 300 minted permissions is
        ten full batches of DynamoDB writes, and what is under test is the
        conditional `ADD`, not the arithmetic of getting there.
        """
        event = self._store_event()
        await self._create_collection(event)
        hour = NOW.replace(minute=0, second=0, microsecond=0)
        self.events_table.put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_PHOTO_QUOTA_PREFIX}{hour:%Y%m%d%H}",
                "minted": HOURLY_MINT_CEILING,
            },
        )

        with pytest.raises(ValueError, match="rate_limited"):
            await self.service.create_upload_batch(event.id, 1, now=hour + timedelta(minutes=5))

        # Nothing was signed and nothing was reserved for the refused caller.
        assert self._photo_items(event.id) == []
        assert await self._photo_count(event.id) == 0

        # The next hour is a different row, so the collection is open again —
        # and the row it charges cleans itself up via the table's TTL.
        uploads = await self.service.create_upload_batch(
            event.id, 2, now=hour + timedelta(hours=1),
        )
        assert len(uploads) == 2

    async def test_a_batch_is_only_admitted_when_it_fits_whole(self):
        """The condition is `minted <= ceiling - count`, not `<= ceiling`:
        otherwise one call could overshoot by up to `MAX_UPLOAD_BATCH - 1`."""
        event = self._store_event()
        await self._create_collection(event)
        hour = NOW.replace(minute=0, second=0, microsecond=0)
        sort_key = f"{EVENT_SK_PHOTO_QUOTA_PREFIX}{hour:%Y%m%d%H}"
        self.events_table.put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": sort_key,
                "minted": HOURLY_MINT_CEILING - MAX_UPLOAD_BATCH + 1,
            },
        )

        with pytest.raises(ValueError, match="rate_limited"):
            await self.service.create_upload_batch(
                event.id, MAX_UPLOAD_BATCH, now=hour + timedelta(minutes=1),
            )

        # One less fits exactly, and lands the counter on the ceiling.
        await self.service.create_upload_batch(
            event.id, MAX_UPLOAD_BATCH - 1, now=hour + timedelta(minutes=2),
        )
        row = self.events_table.get_item(
            Key={"pk": f"EVENT#{event.id}", "sk": sort_key},
        )["Item"]
        assert int(row["minted"]) == HOURLY_MINT_CEILING

    def test_the_hourly_ceiling_is_the_number_in_the_spec(self):
        """Every other cap in this feature is pinned to its literal; this one
        was only ever used symbolically, so `300 -> 3000` would ship green — and
        the hourly quota is the layer that decides how much one anonymous caller
        with the printed link can cost us in an hour."""
        assert HOURLY_MINT_CEILING == 300

    async def test_the_quota_row_carries_a_ttl_so_nothing_enumerates_it(self):
        event = self._store_event()
        await self._create_collection(event)
        hour = NOW.replace(minute=0, second=0, microsecond=0)

        await self.service.create_upload_batch(event.id, 3, now=hour + timedelta(minutes=7))

        rows = self._quota_items(event.id)
        assert len(rows) == 1
        assert rows[0]["sk"] == f"{EVENT_SK_PHOTO_QUOTA_PREFIX}{hour:%Y%m%d%H}"
        assert int(rows[0]["minted"]) == 3
        assert int(rows[0]["ttl"]) == int((hour + QUOTA_ROW_TTL).timestamp())

    async def test_the_quota_is_not_refunded_when_the_mint_fails(self):
        """It is a rate limit: a caller that made us do work has spent a unit of
        it whether or not the work completed."""
        event = self._store_event()
        await self._create_collection(event)
        hour = NOW.replace(minute=0, second=0, microsecond=0)

        def refuse(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "no"}},
                "PutItem",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "put_item", refuse)
            with pytest.raises(ClientError):
                await self.service.create_upload_batch(
                    event.id, 4, now=hour + timedelta(minutes=3),
                )

        assert int(self._quota_items(event.id)[0]["minted"]) == 4
        # The reservation, unlike the quota, is given back in full.
        assert await self._photo_count(event.id) == 0
        assert self._photo_items(event.id) == []


class TestABatchOutlivingItsCollection(PhotoBase):
    """A reservation proves the collection existed when the counter was bumped,
    not that it still exists when the last signature is minted — and a row
    written after a concurrent `delete_collection` dropped the config row is
    invisible to every sweep, because they all enumerate through `_scan_configs`.
    """

    async def test_a_batch_whose_collection_vanished_mid_mint_is_taken_back(self):
        event = self._store_event()
        await self._create_collection(event)
        real_presign = self.service._presign_upload
        seen = {"n": 0}

        def presign_then_delete(bucket, key, max_bytes):
            seen["n"] += 1
            if seen["n"] == 1:
                # Another admin's DELETE (or the sweep) lands here.
                self.events_table.delete_item(
                    Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_PHOTO_CONFIG},
                )
            return real_presign(bucket, key, max_bytes)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "_presign_upload", presign_then_delete)
            with pytest.raises(ValueError, match="page_not_found"):
                await self.service.create_upload_batch(event.id, 3)

        # Nothing was uploaded against those signatures — they never left the
        # process — so taking the rows back is safe, and leaving them would leave
        # objects nothing can ever find again.
        assert self._photo_items(event.id) == []

    async def test_a_collection_that_is_still_there_mints_as_before(self):
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self.service.create_upload_batch(event.id, 3)
        assert len(uploads) == 3
        assert len(self._photo_items(event.id)) == 3


# --- the reservation counter -------------------------------------------------


class TestPhotoCount(PhotoBase):
    async def test_it_rises_when_permissions_are_minted(self):
        """Not when photos arrive — in-flight uploads have to count against the
        cap, or the mint path would have to count rows."""
        event = self._store_event()
        await self._create_collection(event)

        await self.service.create_upload_batch(event.id, 4)
        assert await self._photo_count(event.id) == 4

        await self.service.create_upload_batch(event.id, 2)
        assert await self._photo_count(event.id) == 6

    async def test_confirming_does_not_move_it(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 3)
        assert await self._photo_count(event.id) == 3

    async def test_it_falls_when_a_photo_is_deleted(self):
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self._upload(event, 3)

        photos = await self.service.list_photos(event.id)
        removed = await self.service.delete_photos(
            event.id,
            [p for p in photos if p.photo_id == uploads[0].photo_id],
        )

        assert removed == 1
        assert await self._photo_count(event.id) == 2

    async def test_it_falls_when_the_pending_sweep_cleans_up(self):
        """The reason the sweep has to run at all: without it a collection whose
        guests kept retrying over a bad link would report itself full at a few
        hundred actual photos."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        stale = await self._upload(event, 2, confirm=False)
        for upload in stale:
            self._age_photo(event, upload.photo_id, PENDING_TTL + timedelta(hours=1))
        assert await self._photo_count(event.id) == 3

        assert await self.service.prune_pending(event.id) == 2
        assert await self._photo_count(event.id) == 1

    async def test_it_never_goes_negative(self):
        """An underflow would let a collection grow past `MAX_PHOTOS` forever,
        which is worse than a counter that is wrong by one. (A negative value
        would also fail `EventPhotoConfig` validation on the way back out, so
        this reading is itself part of the assertion.)"""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)
        self._set_photo_count(event.id, 1)

        photos = await self.service.list_photos(event.id)
        assert await self.service.delete_photos(event.id, photos) == 2

        assert await self._photo_count(event.id) == 1
        assert self._photo_items(event.id) == []

    async def test_deleting_the_collection_takes_the_counter_with_it(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        await self.service.delete_collection(event.id)

        assert self._config_item(event.id) is None
        assert await self.service.get_config(event.id) is None


# --- the photo state machine -------------------------------------------------


class TestPhotoStates(PhotoBase):
    async def test_pending_rows_stay_out_of_the_default_listing(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2, confirm=False)

        assert await self.service.list_photos(event.id) == []
        assert len(await self.service.list_photos(event.id, include_pending=True)) == 2

    async def test_confirm_flips_to_ready_with_dimensions(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        confirmed = await self.service.confirm_photos(
            event.id,
            [
                EventPhotoConfirm(
                    photo_id=upload.photo_id, width=2560, height=1440, bytes=980_000,
                ),
            ],
            event,
        )

        assert [p.state for p in confirmed] == [EventPhotoState.READY]
        assert (confirmed[0].width, confirmed[0].height) == (2560, 1440)
        assert confirmed[0].bytes == 980_000
        assert len(await self.service.list_photos(event.id)) == 1

    async def test_confirm_cannot_star_a_photo_or_move_its_keys(self):
        """The endpoint any link holder may call sets dimensions, bytes and the
        hint — nothing else. The model forbids the fields; this is the assertion
        that the write matches."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        confirmed = (
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=upload.photo_id, width=100, height=100, bytes=100,
                    ),
                ],
                event,
            )
        )[0]

        assert confirmed.starred is False
        assert confirmed.s3_key_full == full_key(event.id, upload.photo_id)
        assert confirmed.s3_key_thumb == thumb_key(event.id, upload.photo_id)
        assert confirmed.state == EventPhotoState.READY
        assert confirmed.edited_at is None

    async def test_a_starred_photo_stays_starred_through_a_replayed_confirm(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        await self.service.update_photo(event.id, upload.photo_id, starred=True)

        entry = EventPhotoConfirm(photo_id=upload.photo_id, width=10, height=10, bytes=10)
        again = (await self.service.confirm_photos(event.id, [entry], event))[0]

        assert again.starred is True

    async def test_confirm_is_idempotent(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]
        entry = EventPhotoConfirm(photo_id=upload.photo_id, width=800, height=600, bytes=50_000)

        first = await self.service.confirm_photos(event.id, [entry], event)
        second = await self.service.confirm_photos(event.id, [entry], event)

        assert first[0].model_dump() == second[0].model_dump()
        assert len(await self.service.list_photos(event.id)) == 1

    async def test_confirming_an_unknown_photo_id_is_a_miss(self):
        event = self._store_event()
        await self._create_collection(event)

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.confirm_photos(
                event.id,
                [EventPhotoConfirm(photo_id=uuid4(), width=10, height=10, bytes=10)],
                event,
            )

    async def test_confirming_another_events_photo_id_is_a_miss(self):
        """Rows are keyed by event, so a borrowed id is simply not there — no
        authorisation check that could be forgotten."""
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_collection(mine)
        await self._create_collection(theirs)
        foreign = (await self._upload(theirs, 1, confirm=False))[0]

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.confirm_photos(
                mine.id,
                [EventPhotoConfirm(photo_id=foreign.photo_id, width=10, height=10, bytes=10)],
                mine,
            )

        assert (
            await self.service.get_photo(theirs.id, foreign.photo_id)
        ).state == EventPhotoState.PENDING

    async def test_a_partial_batch_keeps_what_it_confirmed(self):
        """„Ein Stapel scheitert nie als Ganzes" is the most important property
        of the page on a festival connection: one vanished row must not make a
        guest re-upload thirty photos we already have."""
        event = self._store_event()
        await self._create_collection(event)
        first, third = await self._upload(event, 2, confirm=False)
        missing = uuid4()

        confirmed = await self.service.confirm_photos(
            event.id,
            [
                EventPhotoConfirm(photo_id=first.photo_id, width=10, height=10, bytes=10),
                EventPhotoConfirm(photo_id=missing, width=10, height=10, bytes=10),
                EventPhotoConfirm(photo_id=third.photo_id, width=10, height=10, bytes=10),
            ],
            event,
        )

        assert [p.photo_id for p in confirmed] == [first.photo_id, third.photo_id]
        assert {p.photo_id for p in await self.service.list_photos(event.id)} == {
            first.photo_id,
            third.photo_id,
        }

    async def test_a_replayed_confirm_cannot_resurrect_a_swept_row(self):
        """An unconditional update would recreate the row happily — with its
        objects gone and the counter never charged for it."""
        event = self._store_event()
        await self._create_collection(event)
        stale = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL * 2)
        await self.service.prune_pending(event.id)

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.confirm_photos(
                event.id,
                [EventPhotoConfirm(photo_id=stale.photo_id, width=10, height=10, bytes=10)],
                event,
            )
        assert self._photo_items(event.id) == []

    async def test_a_replayed_confirm_cannot_reset_a_pixelated_photo(self):
        """The dimensions of the pixelated version must not be overwritten with
        those of the original it replaced."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        await self.service.mark_edited(event.id, upload.photo_id, 1200, 800, 400_000)

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=upload.photo_id, width=2560, height=1707, bytes=1_200_000,
                    ),
                ],
                event,
            )

        photo = await self.service.get_photo(event.id, upload.photo_id)
        assert (photo.width, photo.height, photo.bytes) == (1200, 800, 400_000)

    async def test_a_refusal_on_the_first_row_is_still_raised(self):
        """Nothing has flipped yet, so a systemic refusal is the honest answer —
        „unbekanntes Foto" would send the guest looking for the wrong problem."""
        event = self._store_event()
        await self._create_collection(event)
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
                        EventPhotoConfirm(
                            photo_id=upload.photo_id, width=10, height=10, bytes=10,
                        ),
                    ],
                    event,
                )

    async def test_the_capture_hint_is_stored_when_it_is_plausible(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]
        moment = event.start_at + timedelta(hours=6)

        confirmed = (
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=upload.photo_id,
                        width=10,
                        height=10,
                        bytes=10,
                        captured_at_hint=moment,
                    ),
                ],
                event,
            )
        )[0]

        assert confirmed.captured_at_hint == moment

    @pytest.mark.parametrize("offset_days", [1, 30])
    async def test_a_hint_in_the_future_is_dropped_not_stored(self, offset_days):
        """Dropped rather than stored, so nothing downstream has to re-judge it
        and `uploaded_at` takes over."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        confirmed = (
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=upload.photo_id,
                        width=10,
                        height=10,
                        bytes=10,
                        captured_at_hint=NOW + timedelta(days=offset_days),
                    ),
                ],
                event,
            )
        )[0]

        assert confirmed.captured_at_hint is None
        assert "captured_at_hint" not in self._photo_items(event.id)[0]

    async def test_a_hint_a_week_before_the_event_is_dropped(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]

        confirmed = (
            await self.service.confirm_photos(
                event.id,
                [
                    EventPhotoConfirm(
                        photo_id=upload.photo_id,
                        width=10,
                        height=10,
                        bytes=10,
                        captured_at_hint=event.start_at - timedelta(days=7),
                    ),
                ],
                event,
            )
        )[0]

        assert confirmed.captured_at_hint is None

    async def test_an_implausible_hint_replaces_a_stored_one(self):
        """The REMOVE half of the confirm expression: a re-upload from a phone
        whose clock was fixed in between must not leave the old hint behind."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, confirm=False))[0]
        good = EventPhotoConfirm(
            photo_id=upload.photo_id,
            width=10,
            height=10,
            bytes=10,
            captured_at_hint=event.start_at + timedelta(hours=1),
        )
        await self.service.confirm_photos(event.id, [good], event)

        bad = EventPhotoConfirm(
            photo_id=upload.photo_id,
            width=10,
            height=10,
            bytes=10,
            captured_at_hint=NOW + timedelta(days=2),
        )
        again = (await self.service.confirm_photos(event.id, [bad], event))[0]

        assert again.captured_at_hint is None


class TestSorting(PhotoBase):
    async def test_the_collection_is_sorted_by_the_capture_hint(self):
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self._upload(event, 3, confirm=False)
        # Minted in one order, taken in another — which is the normal case: a
        # phone uploads whatever the picker hands over first.
        hints = [
            event.start_at + timedelta(hours=9),
            event.start_at + timedelta(hours=1),
            event.start_at + timedelta(hours=5),
        ]
        await self.service.confirm_photos(
            event.id,
            [
                EventPhotoConfirm(
                    photo_id=u.photo_id, width=10, height=10, bytes=10, captured_at_hint=h,
                )
                for u, h in zip(uploads, hints, strict=True)
            ],
            event,
        )

        photos = await self.service.list_photos(event.id, event=event)
        assert [p.photo_id for p in photos] == [
            uploads[1].photo_id,
            uploads[2].photo_id,
            uploads[0].photo_id,
        ]

    async def test_photos_without_a_hint_fall_back_to_the_upload_time(self):
        event = self._store_event()
        await self._create_collection(event)
        first = (await self._upload(event, 1))[0]
        second = (await self._upload(event, 1))[0]
        self._age_photo(event, second.photo_id, -timedelta(minutes=5))

        photos = await self.service.list_photos(event.id, event=event)
        assert [p.photo_id for p in photos] == [first.photo_id, second.photo_id]

    async def test_a_stored_hint_is_trusted_without_the_event(self):
        """The delete paths do not care about order and do not have the event;
        the hint already passed the check at confirm time."""
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self._upload(event, 2, confirm=False)
        await self.service.confirm_photos(
            event.id,
            [
                EventPhotoConfirm(
                    photo_id=uploads[0].photo_id,
                    width=10,
                    height=10,
                    bytes=10,
                    captured_at_hint=event.start_at + timedelta(hours=8),
                ),
                EventPhotoConfirm(
                    photo_id=uploads[1].photo_id,
                    width=10,
                    height=10,
                    bytes=10,
                    captured_at_hint=event.start_at + timedelta(hours=2),
                ),
            ],
            event,
        )

        photos = await self.service.list_photos(event.id)
        assert [p.photo_id for p in photos] == [uploads[1].photo_id, uploads[0].photo_id]


class TestListingIsPaginated(PhotoBase):
    """A `Query` response is capped at 1 MB, and a truncated list is the worst
    possible input for the callers below: `delete_collection` would drop the
    config row over rows it never saw, and the sweep would take the remainder for
    unreachable leftovers."""

    async def test_a_second_query_page_is_followed(self):
        event = self._store_event()
        await self._create_collection(event)
        uploads = await self._upload(event, 4)

        real_query = self.events_table.query
        calls: list[dict] = []

        def paged_query(**kwargs):
            calls.append(kwargs)
            response = real_query(
                **{k: v for k, v in kwargs.items() if k != "ExclusiveStartKey"},
            )
            items = response.get("Items", [])
            if "ExclusiveStartKey" not in kwargs:
                # What DynamoDB returns when the 1 MB page limit hits: a partial
                # page and a cursor.
                return {"Items": items[:2], "LastEvaluatedKey": {"pk": "x", "sk": "y"}}
            return {"Items": items[2:]}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", paged_query)
            photos = await self.service.list_photos(event.id, event=event)

        assert len(calls) == 2
        assert "ExclusiveStartKey" in calls[1]
        assert {p.photo_id for p in photos} == {u.photo_id for u in uploads}

    async def test_a_failed_query_raises_instead_of_reporting_an_empty_collection(self):
        """„No photos" and „no answer" are indistinguishable to the caller, and
        one of those callers decides on that basis whether the config row may be
        dropped."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        def breaking_query(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "no"}},
                "Query",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", breaking_query)
            with pytest.raises(ClientError):
                await self.service.list_photos(event.id)


# --- organiser edits ---------------------------------------------------------


class TestUpdatePhoto(PhotoBase):
    async def test_starring_leaves_the_note_alone(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, note="Katja mit dem Hund"))[0]

        starred = await self.service.update_photo(event.id, upload.photo_id, starred=True)

        assert starred.starred is True
        assert starred.note == "Katja mit dem Hund"

    async def test_a_blank_note_clears_it(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1, note="Tippfehler"))[0]

        cleared = await self.service.update_photo(event.id, upload.photo_id, note="   ")

        assert cleared.note is None
        assert "note" not in self._photo_items(event.id)[0]

    async def test_a_patch_with_nothing_in_it_still_404s_a_foreign_id(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]

        unchanged = await self.service.update_photo(event.id, upload.photo_id)
        assert unchanged.photo_id == upload.photo_id

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.update_photo(event.id, uuid4())

    async def test_updating_another_events_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_collection(mine)
        await self._create_collection(theirs)
        foreign = (await self._upload(theirs, 1))[0]

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.update_photo(mine.id, foreign.photo_id, starred=True)

    async def test_the_face_check_is_its_own_flag(self):
        """„Angesehen, nichts zu tun" must be distinguishable from „noch nicht
        angesehen" — that is the only question that matters when working through
        600 photos over several sittings, and `edited_at` cannot answer it
        because most photos need no pixelation at all."""
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]

        checked = await self.service.update_photo(event.id, upload.photo_id, faces_checked=True)

        assert checked.faces_checked is True
        assert checked.edited_at is None

    async def test_starring_does_not_clear_the_face_check(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        await self.service.update_photo(event.id, upload.photo_id, faces_checked=True)

        starred = await self.service.update_photo(event.id, upload.photo_id, starred=True)

        assert starred.starred is True
        assert starred.faces_checked is True

    async def test_the_check_survives_a_reread(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        await self.service.update_photo(event.id, upload.photo_id, faces_checked=True)

        assert self._photo_items(event.id)[0]["faces_checked"] is True
        assert (await self.service.get_photo(event.id, upload.photo_id)).faces_checked is True


class TestPixelating(PhotoBase):
    """„Unkenntlich machen" is endgültig by design: the pixelated version goes
    onto the same keys in an unversioned bucket, so nothing keeps the original."""

    async def test_the_edit_uploads_target_the_same_keys(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        # Past the uploader's own signature — see
        # `test_an_edit_is_refused_while_the_uploaders_signature_is_alive`.
        self._age_photo(event, upload.photo_id, timedelta(seconds=URL_TTL_SECONDS + 1))

        edit = await self.service.create_edit_uploads(event.id, upload.photo_id)

        assert edit.photo_id == upload.photo_id
        assert edit.full.fields["key"] == full_key(event.id, upload.photo_id)
        assert edit.thumb.fields["key"] == thumb_key(event.id, upload.photo_id)
        # Both variants, because a thumbnail with an un-pixelated face would
        # make the whole exercise pointless.
        assert ["content-length-range", 1, MAX_UPLOAD_BYTES_FULL] in _policy(
            edit.full.fields,
        )["conditions"]
        assert ["content-length-range", 1, MAX_UPLOAD_BYTES_THUMB] in _policy(
            edit.thumb.fields,
        )["conditions"]

    async def test_the_edit_costs_no_row_and_no_reservation(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        self._age_photo(event, upload.photo_id, timedelta(seconds=URL_TTL_SECONDS + 1))

        await self.service.create_edit_uploads(event.id, upload.photo_id)

        assert len(self._photo_items(event.id)) == 1
        assert await self._photo_count(event.id) == 1

    async def test_edit_uploads_for_an_unknown_photo(self):
        event = self._store_event()
        await self._create_collection(event)
        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.create_edit_uploads(event.id, uuid4())

    async def test_edit_uploads_for_another_events_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_collection(mine)
        await self._create_collection(theirs)
        foreign = (await self._upload(theirs, 1))[0]

        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.create_edit_uploads(mine.id, foreign.photo_id)

    async def test_an_edit_is_refused_while_the_uploaders_signature_is_alive(self):
        """Regression: a presigned POST is not single-use.

        The guest's upload permission is signed for exactly these two keys and
        stays valid for `URL_TTL_SECONDS`, and the pixelate handshake writes
        the same two keys. Minting the edit POSTs inside that window means the
        guest's browser (or anyone who kept the form) can put the un-pixelated
        original back afterwards, while `edited_at` goes on claiming the face
        is gone — and the bucket is unversioned, so nothing survives to notice
        it with. The window has to run out first.
        """
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]

        with pytest.raises(ValueError, match="upload_too_recent"):
            await self.service.create_edit_uploads(event.id, upload.photo_id)

        # One second short is still inside it.
        self._age_photo(event, upload.photo_id, timedelta(seconds=URL_TTL_SECONDS - 1))
        with pytest.raises(ValueError, match="upload_too_recent"):
            await self.service.create_edit_uploads(event.id, upload.photo_id)

        # One second past it, and the edit is minted.
        self._age_photo(event, upload.photo_id, timedelta(seconds=URL_TTL_SECONDS + 1))
        edit = await self.service.create_edit_uploads(event.id, upload.photo_id)
        assert edit.full.fields["key"] == full_key(event.id, upload.photo_id)

    async def test_mark_edited_stamps_the_row_and_the_new_dimensions(self):
        event = self._store_event()
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]

        edited = await self.service.mark_edited(event.id, upload.photo_id, 2000, 1333, 700_000)

        assert edited.edited_at is not None
        assert (edited.width, edited.height, edited.bytes) == (2000, 1333, 700_000)
        # The keys did not move — that is the point of the whole path.
        assert edited.s3_key_full == full_key(event.id, upload.photo_id)
        assert edited.s3_key_thumb == thumb_key(event.id, upload.photo_id)
        # Somebody who drew rectangles on this photo has looked at it, so the
        # check mark comes along and the „ungeprüft" working list shrinks by one
        # without a second request.
        assert edited.faces_checked is True

    async def test_mark_edited_on_an_unknown_photo(self):
        event = self._store_event()
        await self._create_collection(event)
        with pytest.raises(ValueError, match="photo_not_found"):
            await self.service.mark_edited(event.id, uuid4(), 10, 10, 10)


# --- view and download URLs (admin only) -------------------------------------


class TestViewUrls(PhotoBase):
    async def test_every_photo_gets_both_urls(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)
        photos = await self.service.list_photos(event.id)

        urls = self.service.presign_view_urls(event.id, photos)

        assert set(urls) == {str(p.photo_id) for p in photos}
        for photo in photos:
            entry = urls[str(photo.photo_id)]
            assert photo.s3_key_thumb in unquote(entry["thumb_url"])
            assert photo.s3_key_full in unquote(entry["full_url"])
            assert "X-Amz-Signature" in entry["full_url"]
            assert f"X-Amz-Expires={URL_TTL_SECONDS}" in entry["full_url"]
            # Three, not two: the lightbox's „Herunterladen" is the `attachment`
            # signature (spec 024 §Adminansicht) and it refreshes on the same
            # clock as the other two.
            assert photo.s3_key_full in unquote(entry["download_url"])
            assert f"X-Amz-Expires={URL_TTL_SECONDS}" in entry["download_url"]

    async def test_the_response_headers_are_overridden_not_trusted(self):
        """Whatever type the uploader managed to store, the browser is told
        `image/jpeg` and `inline` — which, with S3 being a different origin from
        the app, is what makes „HTML under an image key" a dead end."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        photos = await self.service.list_photos(event.id)

        entry = self.service.presign_view_urls(event.id, photos)[str(photos[0].photo_id)]
        for name in ("thumb_url", "full_url"):
            decoded = unquote(entry[name])
            assert "response-content-type=image/jpeg" in decoded
            assert "response-content-disposition=inline" in decoded

        # The third URL is the same object with `attachment` — that is the whole
        # difference between it and `full_url`, and the reason it is signed
        # separately (the disposition is part of the signature).
        download = unquote(entry["download_url"])
        assert "response-content-type=image/jpeg" in download
        assert "attachment" in download
        assert "inline" not in download

    async def test_no_photos_no_urls(self):
        event = self._store_event()
        assert self.service.presign_view_urls(event.id, []) == {}

    async def test_the_download_url_is_an_attachment_with_a_sortable_name(self):
        """The manifest is fed to `xargs -n1 -P4 curl -sOJ`, and without the
        disposition every one of 300 photos would land as `full.jpg`."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        photo = (await self.service.list_photos(event.id))[0]

        url = self.service.presign_download(event.id, photo, index=7)

        decoded = unquote(url)
        assert f'attachment; filename="0007_{str(photo.photo_id)[:8]}.jpg"' in decoded
        assert photo.s3_key_full in decoded
        assert f"X-Amz-Expires={MANIFEST_TTL_SECONDS}" in url
        assert MANIFEST_TTL_SECONDS == 3600


# --- deletion ----------------------------------------------------------------


class TestDeletion(PhotoBase):
    async def test_deleting_photos_takes_both_objects(self):
        event = self._store_event()
        await self._create_collection(event)
        keep, drop = await self._upload(event, 2)

        photos = await self.service.list_photos(event.id)
        removed = await self.service.delete_photos(
            event.id,
            [p for p in photos if p.photo_id == drop.photo_id],
        )

        assert removed == 1
        assert await self.service.get_photo(event.id, drop.photo_id) is None
        assert self._object_keys() == {
            full_key(event.id, keep.photo_id),
            thumb_key(event.id, keep.photo_id),
        }

    async def test_deleting_the_collection_takes_rows_objects_and_config(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 3)
        await self._upload(event, 1, confirm=False)

        result = await self.service.delete_collection(event.id)

        assert result == {"photos": 4, "completed": True}
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        # The PENDING row's objects were never uploaded; S3 reports a missing key
        # as a successful delete, which is what makes this idempotent.
        assert self._object_keys() == set()

    async def test_deleting_twice_is_idempotent(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        first = await self.service.delete_collection(event.id)
        second = await self.service.delete_collection(event.id)

        assert first == {"photos": 2, "completed": True}
        assert second == {"photos": 0, "completed": True}

    async def test_deleting_a_collection_that_never_existed(self):
        event = self._store_event()
        assert await self.service.delete_collection(event.id) == {
            "photos": 0,
            "completed": True,
        }

    async def test_another_events_collection_is_left_alone(self):
        mine = self._store_event()
        theirs = self._store_event()
        await self._create_collection(mine)
        await self._create_collection(theirs)
        await self._upload(mine, 1)
        keep = (await self._upload(theirs, 1))[0]

        await self.service.delete_collection(mine.id)

        assert self._config_item(theirs.id) is not None
        assert len(self._photo_items(theirs.id)) == 1
        assert self._object_keys() == {
            full_key(theirs.id, keep.photo_id),
            thumb_key(theirs.id, keep.photo_id),
        }

    async def test_a_hit_deadline_reports_incomplete_and_keeps_the_config_row(self):
        """The config row has to survive, or the sweep can never find the
        leftovers again — every sweep enumerates through `_scan_configs`."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        result = await self.service.delete_collection(
            event.id,
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert result == {"photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2

        # And a second, unhurried pass finishes the job.
        assert (await self.service.delete_collection(event.id))["completed"] is True
        assert self._config_item(event.id) is None

    async def test_an_unreadable_work_list_deletes_nothing(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        def breaking_query(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "InternalServerError", "Message": "no"}},
                "Query",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "query", breaking_query)
            result = await self.service.delete_collection(event.id)

        assert result == {"photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4

    async def test_leftover_rows_keep_the_config_row_standing(self):
        """The confirming read: „nothing left" can also describe a query that
        never saw the rows, and a photo row orphaned under a deleted config row
        is unreachable forever."""
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)

        async def blind(*_args, **_kwargs):
            return []

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "list_photos", blind)
            result = await self.service.delete_collection(event.id)

        assert result["completed"] is False
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2

    async def test_a_failing_config_delete_is_reported(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        real_delete = self.events_table.delete_item

        def refuse_the_config(Key, **kwargs):  # noqa: N803 - boto3's own casing
            if Key["sk"] == EVENT_SK_PHOTO_CONFIG:
                raise ClientError(
                    {"Error": {"Code": "InternalServerError", "Message": "no"}},
                    "DeleteItem",
                )
            return real_delete(Key=Key, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "delete_item", refuse_the_config)
            result = await self.service.delete_collection(event.id)

        assert result["completed"] is False
        assert self._config_item(event.id) is not None


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


class TestS3RefusesToDelete(PhotoBase):
    """A photo object that outlives its row is unreachable: nothing knows it
    exists any more, so no admin action, no sweep and no anonymisation pass can
    ever remove it — only the bucket's 400-day lifecycle rule. Every delete path
    therefore keeps its row unless S3 has confirmed the objects are gone."""

    async def test_the_rows_and_the_config_survive_a_refused_delete(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()

        result = await self.service.delete_collection(event.id)

        assert result == {"photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4
        assert await self._photo_count(event.id) == 2

    async def test_a_batch_level_client_error_counts_as_a_refusal(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        self.service._s3 = _ThrowingS3()

        result = await self.service.delete_collection(event.id)

        assert result["completed"] is False
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 1

    async def test_the_next_pass_finishes_the_job(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()
        assert (await self.service.delete_collection(event.id))["completed"] is False

        # S3 is back, and the collection is still findable — so the retry works.
        self.service._s3 = None
        result = await self.service.delete_collection(event.id)

        assert result == {"photos": 2, "completed": True}
        assert self._config_item(event.id) is None
        assert self._object_keys() == set()

    async def test_pruning_keeps_a_row_whose_objects_would_not_go(self):
        event = self._store_event()
        await self._create_collection(event)
        stale = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL + timedelta(hours=1))
        self.service._s3 = _RefusingS3()

        assert await self.service.prune_pending(event.id) == 0
        assert len(self._photo_items(event.id)) == 1
        # The reservation stays charged with the row it belongs to.
        assert await self._photo_count(event.id) == 1

    async def test_the_sweep_names_the_collection_it_could_not_delete(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        summary = await self.service.expire_collections()

        assert summary["collections_deleted"] == 0
        assert summary["completed"] is False
        assert summary["unfinished"] == [str(event.id)]
        assert self._config_item(event.id) is not None


class TestWithoutABucket(PhotoBase):
    """Local dev has no photo bucket: writes are refused, reads degrade."""

    bucket = None

    async def test_minting_uploads_is_refused(self):
        event = self._store_event()
        await self._create_collection(event)

        with pytest.raises(ValueError, match="bucket_not_configured"):
            await self.service.create_upload_batch(event.id, 1)

        # Nothing was reserved and no quota was charged for an upload that
        # cannot happen — the bucket check runs before both.
        assert await self._photo_count(event.id) == 0
        assert self._quota_items(event.id) == []

    async def test_the_count_is_validated_before_the_bucket(self):
        event = self._store_event()
        await self._create_collection(event)
        with pytest.raises(ValueError, match="count_out_of_range"):
            await self.service.create_upload_batch(event.id, 0)

    async def test_edit_uploads_are_refused_too(self):
        event = self._store_event()
        await self._create_collection(event)
        photo = EventPhoto(
            event_id=event.id,
            state=EventPhotoState.READY,
            s3_key_full=full_key(event.id, uuid4()),
            s3_key_thumb=thumb_key(event.id, uuid4()),
        )
        self.events_table.put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo.photo_id}",
                "photo_id": str(photo.photo_id),
                "event_id": str(event.id),
                "state": "READY",
                "s3_key_full": photo.s3_key_full,
                "s3_key_thumb": photo.s3_key_thumb,
                # Old enough that the uploader's presigned POST has expired,
                # so this really tests the bucket check and not the edit
                # lockout in front of it.
                "uploaded_at": (
                    photo.uploaded_at - timedelta(seconds=URL_TTL_SECONDS + 1)
                ).isoformat(),
            },
        )

        with pytest.raises(ValueError, match="bucket_not_configured"):
            await self.service.create_edit_uploads(event.id, photo.photo_id)

        # And the read paths degrade to a placeholder instead of a crash.
        assert self.service.presign_view_urls(event.id, [photo]) == {
            str(photo.photo_id): {
                "thumb_url": None,
                "full_url": None,
                "download_url": None,
            },
        }
        assert self.service.presign_download(event.id, photo, index=1) is None

    async def test_deleting_still_removes_the_rows(self):
        event = self._store_event()
        await self._create_collection(event)
        assert (await self.service.delete_collection(event.id))["completed"] is True
        assert self._config_item(event.id) is None


# --- the PENDING prune -------------------------------------------------------


class TestPrunePending(PhotoBase):
    def test_the_pending_ttl_is_the_window_in_the_spec(self):
        """`hours=24`, not `days=24`: used symbolically everywhere else, so the
        typo that turns „ein abgebrochener Upload" into „drei Wochen Müll mit
        Objekten dahinter" would not fail a single test."""
        assert PENDING_TTL == timedelta(hours=24)

    async def test_only_pending_rows_older_than_the_ttl_go(self):
        event = self._store_event()
        await self._create_collection(event)
        old_ready = (await self._upload(event, 1))[0]
        old_pending = (await self._upload(event, 1, confirm=False))[0]
        young_pending = (await self._upload(event, 1, confirm=False))[0]

        self._age_photo(event, old_ready.photo_id, PENDING_TTL * 3)
        self._age_photo(event, old_pending.photo_id, PENDING_TTL + timedelta(minutes=1))

        assert await self.service.prune_pending(event.id) == 1

        left = {
            p.photo_id for p in await self.service.list_photos(event.id, include_pending=True)
        }
        assert left == {old_ready.photo_id, young_pending.photo_id}
        # A confirmed photo is never a leftover, however old it is.
        assert full_key(event.id, old_ready.photo_id) in self._object_keys()

    async def test_the_objects_of_an_aborted_upload_go_too(self):
        """Usually there are none — but a browser that uploaded `full` and then
        died before `thumb` leaves exactly one, and nothing else would find it."""
        event = self._store_event()
        await self._create_collection(event)
        stale = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL * 2)

        assert await self.service.prune_pending(event.id) == 1
        assert self._object_keys() == set()

    async def test_pruning_without_an_event_id_walks_every_collection(self):
        first = self._store_event()
        second = self._store_event()
        await self._create_collection(first)
        await self._create_collection(second)
        for event in (first, second):
            for upload in await self._upload(event, 1, confirm=False):
                self._age_photo(event, upload.photo_id, PENDING_TTL * 2)

        assert await self.service.prune_pending() == 2
        assert self._photo_items(first.id) == []
        assert self._photo_items(second.id) == []

    async def test_pruning_stops_at_its_deadline(self):
        event = self._store_event()
        await self._create_collection(event)
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

    async def test_pruning_a_collection_with_nothing_to_prune(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1)
        assert await self.service.prune_pending(event.id) == 0


# --- quota rows --------------------------------------------------------------


class TestQuotaRowPrune(PhotoBase):
    """Belt to the table's TTL, not a replacement: DynamoDB deletes an expired
    item „typically within 48 hours", and these rows sit in the same partition as
    the collection they belong to."""

    async def test_a_row_whose_hour_is_long_over_goes(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(
            event, 1, confirm=False, now=NOW - QUOTA_ROW_TTL - timedelta(hours=1),
        )
        assert len(self._quota_items(event.id)) == 1

        assert self.service.prune_quota_rows() == 1
        assert self._quota_items(event.id) == []

    async def test_the_current_hour_is_never_taken(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(event, 1, confirm=False)

        assert self.service.prune_quota_rows() == 0
        assert len(self._quota_items(event.id)) == 1

    async def test_a_row_with_an_unreadable_hour_is_skipped_not_fatal(self):
        """The hour comes out of the sort key rather than the `ttl` attribute, so
        a row written in an older shape is still collectable — and one written in
        no recognisable shape must not stop the pass."""
        event = self._store_event()
        await self._create_collection(event)
        self.events_table.put_item(
            Item={
                "pk": f"EVENT#{event.id}",
                "sk": f"{EVENT_SK_PHOTO_QUOTA_PREFIX}nicht-eine-stunde",
                "minted": 5,
            },
        )
        await self._upload(
            event, 1, confirm=False, now=NOW - QUOTA_ROW_TTL - timedelta(hours=2),
        )

        assert self.service.prune_quota_rows() == 1
        assert len(self._quota_items(event.id)) == 1

    async def test_pruning_stops_at_its_deadline(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(
            event, 1, confirm=False, now=NOW - QUOTA_ROW_TTL - timedelta(hours=1),
        )

        assert (
            self.service.prune_quota_rows(
                deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            == 0
        )
        assert len(self._quota_items(event.id)) == 1


# --- the daily sweep ---------------------------------------------------------


class TestExpirySweep(PhotoBase):
    async def test_a_collection_inside_its_window_survives(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=10),
            end_at=NOW - timedelta(days=9),
        )
        await self._create_collection(event)
        await self._upload(event, 2)

        summary = await self.service.expire_collections()

        assert summary["collections_checked"] == 1
        assert summary["collections_deleted"] == 0
        assert summary["completed"] is True
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4

    async def test_a_collection_past_its_window_is_deleted_with_its_objects(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        await self._upload(event, 3)

        summary = await self.service.expire_collections()

        assert summary["collections_deleted"] == 1
        assert summary["deleted_photos"] == 3
        assert summary["unfinished"] == []
        assert summary["completed"] is True
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_the_override_beats_the_setting_in_both_directions(self):
        # 100 days after the event: the 90-day default would expire it.
        long_lived = self._store_event(
            start_at=NOW - timedelta(days=101),
            end_at=NOW - timedelta(days=100),
        )
        await self._create_collection(long_lived, retention_days=365)

        # 10 days after the event: the default would keep it.
        short_lived = self._store_event(
            start_at=NOW - timedelta(days=11),
            end_at=NOW - timedelta(days=10),
        )
        await self._create_collection(short_lived, retention_days=7)

        summary = await self.service.expire_collections()

        assert summary["collections_checked"] == 2
        assert summary["collections_deleted"] == 1
        assert self._config_item(long_lived.id) is not None
        assert self._config_item(short_lived.id) is None

    async def test_retention_of_a_cancelled_event_runs_from_the_cancellation(self):
        long_dead = self._store_event(
            status=EventStatus.CANCELLED,
            cancelled_at=NOW - timedelta(days=100),
            start_at=NOW + timedelta(days=30),
            end_at=NOW + timedelta(days=31),
            registration_deadline=NOW + timedelta(days=20),
        )
        await self._create_collection(long_dead)

        just_cancelled = self._store_event(
            status=EventStatus.CANCELLED,
            cancelled_at=NOW - timedelta(days=1),
            start_at=NOW - timedelta(days=300),
            end_at=NOW - timedelta(days=299),
        )
        await self._create_collection(just_cancelled)

        await self.service.expire_collections()

        assert self._config_item(long_dead.id) is None
        assert self._config_item(just_cancelled.id) is not None

    async def test_a_collection_whose_event_does_not_resolve_is_kept(self):
        """„The event lookup came back empty" is not „the event is gone".

        `get_event_by_id` is a scan that also answers None when the read failed,
        so deleting on that signal would destroy a live collection mid-window
        over a throttled scan — and nothing brings guests' photos back.
        """
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        upload = (await self._upload(event, 1))[0]
        self.events_table.delete_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        )

        summary = await self.service.expire_collections()

        assert summary["collections_deleted"] == 0
        assert summary["failed"] == []
        assert self._config_item(event.id) is not None
        assert self._object_keys() == {
            full_key(event.id, upload.photo_id),
            thumb_key(event.id, upload.photo_id),
        }

    async def test_an_anonymised_event_lives_out_its_window(self):
        """Anonymisation deletes the collection it finds, but it is not an expiry
        trigger — a collection put up *after* an anonymisation pass is exactly
        the „schickt doch noch eure Fotos" case the spec keeps open."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event, put_up_late=True)
        self.events_table.update_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
            UpdateExpression="SET anonymized_at = :t",
            ExpressionAttributeValues={":t": NOW.isoformat()},
        )

        assert (await self.service.expire_collections())["collections_deleted"] == 0
        assert self._config_item(event.id) is not None

    async def test_the_sweep_prunes_aborted_uploads_in_the_collections_it_keeps(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=2),
            end_at=NOW - timedelta(days=1),
        )
        await self._create_collection(event)
        ready = (await self._upload(event, 1))[0]
        stale = (await self._upload(event, 1, confirm=False))[0]
        fresh = (await self._upload(event, 1, confirm=False))[0]
        self._age_photo(event, stale.photo_id, PENDING_TTL + timedelta(hours=1))

        summary = await self.service.expire_collections()

        assert summary["pending_pruned"] == 1
        remaining = {
            p.photo_id for p in await self.service.list_photos(event.id, include_pending=True)
        }
        assert remaining == {ready.photo_id, fresh.photo_id}
        assert full_key(event.id, stale.photo_id) not in self._object_keys()
        assert await self._photo_count(event.id) == 2

    async def test_the_sweep_mops_up_quota_rows(self):
        event = self._store_event()
        await self._create_collection(event)
        await self._upload(
            event, 1, confirm=False, now=NOW - QUOTA_ROW_TTL - timedelta(hours=1),
        )

        summary = await self.service.expire_collections()

        assert summary["quota_rows_pruned"] == 1
        assert self._quota_items(event.id) == []

    async def test_the_sweep_accepts_an_explicit_now(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=10),
            end_at=NOW - timedelta(days=9),
        )
        await self._create_collection(event)

        assert (await self.service.expire_collections(now=NOW))["collections_deleted"] == 0
        assert (
            await self.service.expire_collections(now=NOW + timedelta(days=100))
        )["collections_deleted"] == 1

    async def test_a_hit_deadline_stops_and_keeps_what_is_left(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        await self._upload(event, 2)

        summary = await self.service.expire_collections(
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert summary["completed"] is False
        assert summary["collections_deleted"] == 0
        assert self._config_item(event.id) is not None

    async def test_an_empty_table_sweeps_cleanly(self):
        summary = await self.service.expire_collections()
        assert {key: summary[key] for key in SWEEP_KEYS} == {
            "collections_checked": 0,
            "collections_deleted": 0,
            "deleted_photos": 0,
            "pending_pruned": 0,
            "quota_rows_pruned": 0,
            "completed": True,
            "unfinished": [],
            "failed": [],
        }

    async def test_a_failed_scan_is_not_an_empty_table(self):
        """„Nothing to do" and „could not look" must not be the same log line: a
        permanently broken sweep would otherwise report `completed: True` while
        every collection past its window kept guests' faces in the bucket."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        await self._upload(event, 1)

        def breaking_scan(**_kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "no"}},
                "Scan",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.events_table, "scan", breaking_scan)
            summary = await self.service.expire_collections()

        assert summary["completed"] is False
        assert summary["collections_checked"] == 0
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 1

    async def test_an_unreadable_config_row_is_admitted(self):
        event = self._store_event()
        await self._create_collection(event)
        self.events_table.update_item(
            Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_PHOTO_CONFIG},
            UpdateExpression="REMOVE upload_token",
        )

        summary = await self.service.expire_collections()

        assert summary["completed"] is False
        assert summary["collections_checked"] == 0

    async def test_one_bad_collection_does_not_save_the_others(self):
        """A permanent fault must not block every collection behind it in scan
        order — „the sweep stops at the same collection every night" is precisely
        the stiller Ausfall the 400-day lifecycle rule is only a backstop for."""
        broken = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        healthy = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(broken)
        await self._create_collection(healthy)
        upload = (await self._upload(broken, 1))[0]
        await self._upload(healthy, 2)

        # A state no enum member matches — `_item_to_photo` raises ValueError on
        # it, out of `list_photos`, out of `delete_collection`.
        self.events_table.update_item(
            Key={
                "pk": f"EVENT#{broken.id}",
                "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{upload.photo_id}",
            },
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":s": "WEIRD"},
        )

        summary = await self.service.expire_collections()

        assert summary["failed"] == [str(broken.id)]
        assert summary["completed"] is False
        assert summary["collections_deleted"] == 1
        assert self._config_item(healthy.id) is None
        assert self._photo_items(healthy.id) == []
        assert self._config_item(broken.id) is not None


# --- concurrency -------------------------------------------------------------


class TestConcurrentBatches(PhotoBase):
    async def test_two_batches_at_once_both_land_and_both_count(self):
        event = self._store_event()
        await self._create_collection(event)

        first, second = await asyncio.gather(
            self.service.create_upload_batch(event.id, 5),
            self.service.create_upload_batch(event.id, 5),
        )

        ids = {u.photo_id for u in first} | {u.photo_id for u in second}
        assert len(ids) == 10
        assert await self._photo_count(event.id) == 10
        assert len(self._photo_items(event.id)) == 10


# --- anonymisation (spec 022 x spec 024) --------------------------------------


class TestAnonymizationDeletesTheCollection(PhotoBase):
    """Spec 024 § Verhältnis zu Spec 022: a face cannot be pseudonymised.

    Every other row an anonymisation pass touches keeps its shape and loses its
    names. The photo collection is one of the two exceptions (the other is spec
    023's Fundsachen page): it goes entirely — config row, photo rows, objects —
    because there is no pseudonym for a picture of somebody.

    The second half of the rule matters just as much: anonymisation is not a
    lock. `anonymized_at` is neither a 404 reason nor an expiry trigger here, so
    „schickt uns doch noch eure Fotos" three months later opens a fresh
    collection that lives by its own window.
    """

    @pytest.fixture(autouse=True)
    def setup_anonymization(self, setup_env):
        self.anonymization = AnonymizationService()
        self.anonymization._events_table = self.tables["events_table"]
        self.anonymization._registrations_table = self.tables["registrations_table"]
        self.anonymization._messages_table = self.tables["messages_table"]
        # Injected rather than left to the singleton, so the collection's rows
        # land in the same moto table and the same moto bucket as everything
        # else in this file.
        self.anonymization._event_photos = self.service

    async def test_the_collection_is_deleted_outright_not_pseudonymised(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        config = await self._create_collection(event, retention_days=365)
        await self._upload(event, 2, uploader_name="Katja", note="am Steg")

        result = await self.anonymization.anonymize_event(event)

        assert result.completed is True
        assert result.event_photos == 2
        assert result.event_photos_failed is False
        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()
        # `uploader_name` and `note` are personal data too, and they leave with
        # the rows rather than being rewritten.
        assert await self.service.resolve_public_page(event.id, config.upload_token) is None

    async def test_a_refused_object_delete_leaves_the_event_unstamped(self):
        """An object that outlives its row is a guest's face nothing can find
        again, so „S3 refused" has to hold the whole pass open."""
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event, retention_days=365)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        result = await self.anonymization.anonymize_event(event)

        assert result.completed is False
        assert result.event_photos_failed is True
        assert result.anonymized_at is None
        assert self._config_item(event.id) is not None
        assert len(self._object_keys()) == 2

    async def test_an_event_without_a_collection_is_unaffected(self):
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        result = await self.anonymization.anonymize_event(event)
        assert result.completed is True
        assert result.event_photos == 0
        assert result.event_photos_failed is False

    async def test_a_new_collection_after_anonymisation_works_and_survives(self):
        """The spec's own wording: „danach ist jeder Schreibweg wieder offen und
        die neue Sammlung überlebt den Sweep in der Nacht darauf."

        Both halves are asserted, because they fail for different reasons. A
        write path closed by `anonymized_at` would be a gate check nobody asked
        for; a new collection swept the same night would be the event date used
        as the only retention anchor — the bug the „later of event end and
        collection creation" rule exists to prevent.
        """
        event = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(event)
        await self._upload(event, 1)
        await self.anonymization.anonymize_event(event)

        stamped = await self.event_service.get_event(event.org_id, event.id)
        assert stamped.is_anonymized is True

        # Every write path, in the order a real organiser and guest use them.
        config = await self._create_collection(event, put_up_late=True)
        assert (
            await self.service.resolve_public_page(event.id, config.upload_token)
        ) is not None
        uploads = await self._upload(event, 2)
        assert len(uploads) == 2
        assert len(self._photo_items(event.id)) == 2
        rotated = await self.service.rotate_token(event.id)
        assert rotated.upload_token != config.upload_token

        # And tonight's sweep leaves it alone: retention counts from the later
        # of event end and creation, and the creation was a moment ago.
        summary = await self.service.expire_collections()
        assert summary["collections_deleted"] == 0
        assert self._config_item(event.id) is not None


# --- deleting the event ------------------------------------------------------


class TestEventDeleteTakesTheCollection(PhotoBase):
    """Deleting an event has to take its photo collection along.

    The event is the only handle anything has on the collection: the admin API
    404s once the ORG#/EVENT# row is gone, and `expire_collections` deliberately
    skips a collection whose event does not resolve (a lookup failure must not
    read as „expired"). An event deleted while its objects are still in the
    bucket therefore leaves photographs of guests' faces there until the
    400-day lifecycle rule, with nothing in the system able to find them again.
    Same contract, same reasoning and same 503 as spec 023's Fundsachen page —
    a second bucket, so a second check.
    """

    async def test_the_collection_goes_with_a_single_event(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_collection(event)
        await self._upload(event, 2)

        assert await self.event_service.delete_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_the_collection_goes_with_a_festival(self):
        event = self._store_event(
            event_type=EventType.FESTIVAL,
            status=EventStatus.CANCELLED,
            cancelled_at=NOW,
        )
        await self._create_collection(event)
        await self._upload(event, 2)

        assert await self.event_service.delete_festival_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._photo_items(event.id) == []
        assert self._object_keys() == set()

    async def test_an_event_without_a_collection_deletes_as_before(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        assert await self.event_service.delete_event(event.org_id, event.id) is True

    async def test_another_events_collection_is_left_alone(self):
        doomed = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        neighbour = self._store_event()
        await self._create_collection(doomed)
        await self._create_collection(neighbour)
        keep = (await self._upload(neighbour, 1))[0]

        await self.event_service.delete_event(doomed.org_id, doomed.id)

        assert self._config_item(neighbour.id) is not None
        assert self._object_keys() == {
            full_key(neighbour.id, keep.photo_id),
            thumb_key(neighbour.id, keep.photo_id),
        }

    async def test_a_single_event_survives_a_refused_object_delete(self):
        """One transient per-key AccessDenied has to fail the event delete
        rather than be logged and walked past — the objects would be
        unreachable a millisecond later."""
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_collection(event)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()

        with pytest.raises(ValueError, match="photos_not_deleted"):
            await self.event_service.delete_event(event.org_id, event.id)

        assert await self.event_service.get_event(event.org_id, event.id) is not None
        assert self._config_item(event.id) is not None
        assert len(self._photo_items(event.id)) == 2
        assert len(self._object_keys()) == 4

    async def test_a_festival_survives_a_refused_object_delete(self):
        event = self._store_event(
            event_type=EventType.FESTIVAL,
            status=EventStatus.CANCELLED,
            cancelled_at=NOW,
        )
        await self._create_collection(event)
        await self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        with pytest.raises(ValueError, match="photos_not_deleted"):
            await self.event_service.delete_festival_event(event.org_id, event.id)

        assert await self.event_service.get_event(event.org_id, event.id) is not None
        assert self._config_item(event.id) is not None

    async def test_the_retry_goes_through_once_s3_is_back(self):
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        await self._create_collection(event)
        await self._upload(event, 2)
        self.service._s3 = _RefusingS3()
        with pytest.raises(ValueError, match="photos_not_deleted"):
            await self.event_service.delete_event(event.org_id, event.id)

        self.service._s3 = None
        assert await self.event_service.delete_event(event.org_id, event.id) is True

        assert self._config_item(event.id) is None
        assert self._object_keys() == set()


# --- the daily worker task ---------------------------------------------------


class TestWorkerTask(PhotoBase):
    """`expire_event_photos` is one service call and a rename of its keys."""

    @pytest.fixture(autouse=True)
    def use_the_singleton(self, setup_env, monkeypatch):
        import app.services.event_photo_service as module

        monkeypatch.setattr(module, "_event_photo_service", self.service)

    async def test_the_task_reports_what_the_sweep_did(self):
        from app.workers.handler import expire_event_photos

        expired = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        await self._create_collection(expired)
        await self._upload(expired, 2)

        kept = self._store_event()
        await self._create_collection(kept)
        stale = (await self._upload(kept, 1, confirm=False))[0]
        self._age_photo(kept, stale.photo_id, PENDING_TTL * 2)

        result = await expire_event_photos()

        assert {key: result[key] for key in TASK_KEYS} == {
            "task": "expire_event_photos",
            "status": "completed",
            "collections_checked": 2,
            "collections_deleted": 1,
            "photos_deleted": 2,
            "pending_pruned": 1,
            # Charged by both mints, and both hours' rows are still inside their
            # own TTL — the prune only removes what the table's TTL missed.
            "quota_rows_pruned": 0,
            "collections_unfinished": [],
            "collections_failed": [],
            "swept_completely": True,
        }
        assert self._config_item(expired.id) is None
        assert self._config_item(kept.id) is not None
        # The reservation the aborted upload was holding is back — that counter
        # is what makes a festival's retry storm look like a full collection.
        assert await self._photo_count(kept.id) == 0

    async def test_the_task_result_is_not_polluted_by_its_own_log_line(self, caplog):
        """The summary doubles as the `extra` of its own log record, and a
        handler is free to add to that dict. Asserted so the contract above
        stays a contract."""
        import logging

        from app.services.logging import request_id_var
        from app.workers.handler import expire_event_photos

        token = request_id_var.set("abc12345")
        try:
            with caplog.at_level(logging.INFO):
                result = await expire_event_photos()
        finally:
            request_id_var.reset(token)

        assert set(result) == set(TASK_KEYS)

    async def test_a_failing_sweep_is_reported_not_raised(self):
        """The collections are still there tomorrow, and the bucket's 400-day
        lifecycle rule is the backstop — nothing here is worth an alarming
        exit."""
        from app.workers.handler import expire_event_photos

        async def exploding(*_args, **_kwargs):
            raise RuntimeError("DynamoDB unreachable")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "expire_collections", exploding)
            result = await expire_event_photos()

        assert result["status"] == "failed"
        assert "DynamoDB unreachable" in result["error"]

    async def test_the_dispatch_key_is_the_payload_the_rule_fires(self):
        """`funke-{env}-photos-expiry` sends `{"task": "expire_event_photos"}`.

        A rule carries exactly one payload and the handler looks the name up in
        a dict, so a typo on either side is a nightly „Unknown task" nobody
        reads. Pinned here because the two live in different repositories'
        worth of file.
        """
        from app.workers.handler import expire_event_photos, handler

        # `handler` calls `asyncio.run`, which refuses to run inside this
        # test's own loop — off-thread it gets the loop-free context Lambda
        # gives it, so the dispatch is exercised instead of the error path.
        result = await asyncio.to_thread(handler, {"task": "expire_event_photos"}, None)

        assert result["task"] == "expire_event_photos"
        assert result["status"] == "completed"
        assert expire_event_photos.__name__ == "expire_event_photos"
