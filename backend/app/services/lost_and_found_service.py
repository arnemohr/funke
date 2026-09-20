"""Lost & found page service (spec 023 — Fundsachen).

Rows live in the events table next to the invites: ``pk=EVENT#{event_id}``
with ``sk=LNF#CONFIG`` for the page and ``sk=LNF#PHOTO#{photo_id}`` per photo.
There is no GSI — the public URL carries the ``event_id``, so the config row is
fetched with a plain ``GetItem`` and the supplied token compared against the
stored one with ``secrets.compare_digest``.

Three things in here are load-bearing and easy to break:

**Numbers are handed out, never handed back.** The number under a photo is
what a guest quotes in a mail, so it has to mean the same thing three days
later. `create_upload_batch` takes a contiguous block with a single atomic
``ADD next_number :n`` on the config row, and nothing anywhere decrements that
counter — deleting photo 14 leaves 14 empty forever. Two concurrent batches
therefore cannot overlap: each gets its own block, whatever order they land in.

**The Lambda never sees an image byte.** It mints presigned POSTs for the
browser to upload against and presigned GETs for the page to read from. That
is not an optimisation: API Gateway caps a request and a response at 10 MB and
kills the invocation after 29 s, which 50 phone photos would blow through in
both directions.

**Objects go before rows.** Every delete path removes the S3 objects first and
the DynamoDB row second. An orphan row is a cosmetic bug that a re-run fixes;
an orphan object is unrecoverable, because once the row is gone nothing in the
system knows the object exists — only the bucket's 400-day lifecycle rule
would eventually catch it.

Errors are raised as ``ValueError`` with machine-readable lowercase strings
(``page_not_found``, ``photo_not_found``, ``contact_required``,
``bucket_not_configured``, ``count_out_of_range``); the routers turn those into
an HTTP status plus German detail.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ..models import Event, EventStatus
from ..models.lost_and_found import (
    LostAndFoundConfig,
    LostAndFoundConfigUpdate,
    LostAndFoundPhoto,
    LostAndFoundPhotoConfirm,
    LostAndFoundPhotoState,
    LostAndFoundUpload,
    PresignedPost,
)
from .config import (
    EVENT_SK_LNF_CONFIG,
    EVENT_SK_LNF_PHOTO_PREFIX,
    get_events_table,
    get_settings,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)

# Lifetime of every presigned URL this service mints, upload and view alike.
# The public page refreshes its URLs a minute before this runs out, so the
# number is also part of the public response (`url_ttl_seconds`).
URL_TTL_SECONDS = 900

# Hard ceiling in the upload policy. The browser downscales to 1600 px at
# quality 0.82 first, which lands well under this — the limit exists to stop a
# leaked signature from being used to park a film in the bucket.
MAX_UPLOAD_BYTES = 3 * 1024 * 1024

# Photos per upload batch. One batch is one round-trip, and 50 covers „the
# whole box" while keeping the response small enough to be uninteresting.
MAX_UPLOAD_BATCH = 50

UPLOAD_CONTENT_TYPE = "image/jpeg"

# `delete_objects` takes at most 1000 keys per call.
_S3_DELETE_BATCH = 1000

# An upload that has not been confirmed within this window is an abandoned
# one — the tab was closed, the WLAN died, the file would not decode.
PENDING_TTL = timedelta(hours=24)


def _generate_page_token() -> str:
    """43 URL-safe characters — the entire access control of the public page."""
    return secrets.token_urlsafe(32)


def _as_utc(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC — a naive/aware compare raises TypeError,
    and that would kill the sweep silently."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def event_finished_at(event: Event) -> datetime:
    """When this event actually ended, for retention purposes.

    Same rule as the anonymisation sweep's `_event_finished_at` (spec 022): a
    cancellation ends the event the moment it is called off, not on the date it
    would have run. Kept here as an importable helper so both sweeps count from
    the same instant instead of drifting apart.
    """
    candidate = None
    if event.status == EventStatus.CANCELLED:
        candidate = event.cancelled_at
    if candidate is None:
        candidate = event.end_at or event.start_at
    return _as_utc(candidate)


def effective_retention_days(config: LostAndFoundConfig) -> int:
    """The page's own retention, or the environment default when unset."""
    if config.retention_days is not None:
        return config.retention_days
    return get_settings().lost_and_found_retention_days


def page_expires_at(event: Event, config: LostAndFoundConfig) -> datetime:
    """When the page (and its photos) will be deleted.

    Counted from the event's end, or from the page's own creation when that is
    later. The event end is the natural anchor — the box fills up as the event
    ends — but a page may legitimately be put up long afterwards, including on
    an event whose guest data is already anonymised. Anchoring such a page on
    the event would make it expire before anyone could open the link, so the
    later of the two instants wins and the retention window always spans the
    full `retention_days` from the moment the page exists.
    """
    anchor = max(event_finished_at(event), _as_utc(config.created_at))
    return anchor + timedelta(days=effective_retention_days(config))


def is_page_expired(
    event: Event,
    config: LostAndFoundConfig,
    now: datetime | None = None,
) -> bool:
    """Whether the page is past its window and due for deletion."""
    return (now or datetime.now(timezone.utc)) >= page_expires_at(event, config)


def public_page_url(event_id: UUID, page_token: str) -> str:
    """The link that gets handed out — the only URL meant to be shared."""
    return f"{get_settings().base_url.rstrip('/')}/lostfound/{event_id}/{page_token}"


def display_key(event_id: UUID, photo_id: UUID) -> str:
    """S3 key of the gallery-sized variant."""
    return f"lostfound/{event_id}/{photo_id}/display.jpg"


def thumb_key(event_id: UUID, photo_id: UUID) -> str:
    """S3 key of the grid-sized variant."""
    return f"lostfound/{event_id}/{photo_id}/thumb.jpg"


def _config_to_item(config: LostAndFoundConfig) -> dict:
    """Convert a config model to a DynamoDB item."""
    item = {
        "pk": f"EVENT#{config.event_id}",
        "sk": EVENT_SK_LNF_CONFIG,
        "event_id": str(config.event_id),
        "page_token": config.page_token,
        "published": config.published,
        "next_number": config.next_number,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
        "entity_type": "LostAndFoundConfig",
    }

    # Optional, but at least one of the two is always present — `upsert_config`
    # is where that invariant is enforced.
    if config.coordinator_email is not None:
        item["coordinator_email"] = str(config.coordinator_email)
    if config.coordinator_telegram_url is not None:
        item["coordinator_telegram_url"] = config.coordinator_telegram_url

    if config.coordinator_name:
        item["coordinator_name"] = config.coordinator_name

    if config.intro_text:
        item["intro_text"] = config.intro_text

    if config.retention_days is not None:
        item["retention_days"] = config.retention_days

    return item


def _item_to_config(item: dict) -> LostAndFoundConfig:
    """Convert a DynamoDB item to a config model."""
    return LostAndFoundConfig(
        event_id=UUID(item["event_id"]),
        page_token=item["page_token"],
        coordinator_email=item.get("coordinator_email"),
        coordinator_telegram_url=item.get("coordinator_telegram_url"),
        coordinator_name=item.get("coordinator_name"),
        intro_text=item.get("intro_text"),
        published=bool(item.get("published", False)),
        retention_days=(
            int(item["retention_days"]) if item.get("retention_days") is not None else None
        ),
        next_number=int(item.get("next_number", 0)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def _photo_to_item(photo: LostAndFoundPhoto) -> dict:
    """Convert a photo model to a DynamoDB item."""
    item = {
        "pk": f"EVENT#{photo.event_id}",
        "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo.photo_id}",
        "photo_id": str(photo.photo_id),
        "event_id": str(photo.event_id),
        "number": photo.number,
        "state": photo.state.value,
        "s3_key_display": photo.s3_key_display,
        "s3_key_thumb": photo.s3_key_thumb,
        "uploaded_at": photo.uploaded_at.isoformat(),
        "entity_type": "LostAndFoundPhoto",
    }

    if photo.caption:
        item["caption"] = photo.caption

    if photo.width is not None:
        item["width"] = photo.width

    if photo.height is not None:
        item["height"] = photo.height

    return item


def _item_to_photo(item: dict) -> LostAndFoundPhoto:
    """Convert a DynamoDB item to a photo model."""
    return LostAndFoundPhoto(
        photo_id=UUID(item["photo_id"]),
        event_id=UUID(item["event_id"]),
        number=int(item["number"]),
        caption=item.get("caption"),
        state=LostAndFoundPhotoState(item.get("state", LostAndFoundPhotoState.PENDING.value)),
        s3_key_display=item["s3_key_display"],
        s3_key_thumb=item["s3_key_thumb"],
        width=int(item["width"]) if item.get("width") is not None else None,
        height=int(item["height"]) if item.get("height") is not None else None,
        uploaded_at=datetime.fromisoformat(item["uploaded_at"]),
    )


class LostAndFoundService:
    """Service for the per-event lost & found page and its photos."""

    def __init__(self):
        self._table = None
        self._s3 = None

    @property
    def table(self) -> "Table":
        """The events table (lazy) — the page rows are co-located there."""
        if self._table is None:
            self._table = get_events_table()
        return self._table

    @property
    def s3(self):
        """S3 client (lazy).

        SigV4 is pinned explicitly: eu-central-1 accepts nothing else, and a
        presigned URL signed the old way fails at request time rather than at
        signing time, which is a miserable thing to debug.
        """
        if self._s3 is None:
            region = get_settings().aws_region
            self._s3 = boto3.client(
                "s3",
                region_name=region,
                # Pinned to the REGIONAL endpoint, not boto3's default global
                # one. A presigned POST against `bucket.s3.amazonaws.com` for a
                # bucket outside us-east-1 answers 307 to the regional host, and
                # a browser will not replay a cross-origin multipart POST across
                # that redirect — the upload dies with an opaque CORS/network
                # error while curl follows it happily. Virtual addressing keeps
                # the bucket in the host name, which is what the signature and
                # the CORS rule are both scoped to.
                endpoint_url=f"https://s3.{region}.amazonaws.com",
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": "virtual"},
                ),
            )
        return self._s3

    @property
    def bucket(self) -> str | None:
        """Configured photo bucket, or None in a local environment."""
        return get_settings().lost_and_found_s3_bucket

    def _require_bucket(self) -> str:
        bucket = self.bucket
        if not bucket:
            raise ValueError("bucket_not_configured")
        return bucket

    # -- config ---------------------------------------------------------------

    async def get_config(self, event_id: UUID) -> LostAndFoundConfig | None:
        """Read the page configuration, or None when no page exists yet."""
        try:
            response = self.table.get_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
            )
            item = response.get("Item")
            return _item_to_config(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get lost & found config",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return None

    async def upsert_config(
        self,
        event_id: UUID,
        patch: LostAndFoundConfigUpdate,
    ) -> LostAndFoundConfig:
        """Create the page on first save, patch it afterwards.

        Raises:
            ValueError: ``contact_required`` when the first save has neither a
                mail address nor a Telegram link, or when a later save would
                clear the last one that is left.
        """
        updates = patch.model_dump(exclude_unset=True)
        existing = await self.get_config(event_id)

        if existing is None:
            email = updates.get("coordinator_email")
            telegram = updates.get("coordinator_telegram_url")
            if not email and not telegram:
                raise ValueError("contact_required")

            now = datetime.now(timezone.utc)
            config = LostAndFoundConfig(
                event_id=event_id,
                page_token=_generate_page_token(),
                coordinator_email=email,
                coordinator_telegram_url=telegram,
                coordinator_name=updates.get("coordinator_name"),
                intro_text=updates.get("intro_text"),
                published=bool(updates.get("published", False)),
                retention_days=updates.get("retention_days"),
                created_at=now,
                updated_at=now,
            )
            try:
                self.table.put_item(
                    Item=_config_to_item(config),
                    ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
                )
                logger.info(
                    "Lost & found page created",
                    extra={"event_id": str(event_id)},
                )
                return config

            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    logger.error(
                        "Failed to create lost & found config",
                        extra={"error": str(e), "event_id": str(event_id)},
                    )
                    raise
                # A concurrent first save won the race. Falling through to the
                # patch path keeps ITS token (and any numbers already drawn
                # against it) instead of overwriting the row and invalidating a
                # link that may already have been copied.

        # Either contact may be cleared, but not the last one standing: work out
        # what the row would look like afterwards rather than looking at this
        # payload alone, so „clear the mail" is fine on a page that has Telegram
        # and refused on a page that has nothing else.
        # `existing` is None on the fall-through from a lost create race, where
        # the winner's row is the truth — re-read it rather than guessing.
        current = existing or await self.get_config(event_id)
        remaining_email = (
            updates.get("coordinator_email")
            if "coordinator_email" in updates
            else (current.coordinator_email if current else None)
        )
        remaining_telegram = (
            updates.get("coordinator_telegram_url")
            if "coordinator_telegram_url" in updates
            else (current.coordinator_telegram_url if current else None)
        )
        if not remaining_email and not remaining_telegram:
            raise ValueError("contact_required")

        return await self._patch_config(event_id, updates)

    async def _patch_config(self, event_id: UUID, updates: dict) -> LostAndFoundConfig:
        """Targeted SET/REMOVE on the config row.

        Never a full ``put_item``: the row also carries ``next_number``, and
        writing back a value read a moment ago would hand the next batch
        numbers that an in-flight batch is already using.
        """
        set_parts = ["#updated_at = :updated_at"]
        remove_parts: list[str] = []
        names = {"#updated_at": "updated_at"}
        values: dict[str, object] = {":updated_at": datetime.now(timezone.utc).isoformat()}

        for field, value in updates.items():
            # `EmailStr` is not a `str` subclass Dynamo will take, so it is
            # cast — but only when there is something to cast. Clearing it is a
            # REMOVE below, and `str(None)` would store the literal "None",
            # which then fails validation on the way back out.
            if field == "coordinator_email" and value is not None:
                value = str(value)

            names[f"#{field}"] = field
            if value is None:
                # `_config_to_item` omits unset optionals — mirror that shape
                # so „cleared" and „never set" read identically.
                remove_parts.append(f"#{field}")
                continue

            values[f":{field}"] = value
            set_parts.append(f"#{field} = :{field}")

        expression = "SET " + ", ".join(set_parts)
        if remove_parts:
            expression += " REMOVE " + ", ".join(remove_parts)

        try:
            response = self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
                UpdateExpression=expression,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="ALL_NEW",
            )
            return _item_to_config(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("page_not_found") from e
            logger.error(
                "Failed to update lost & found config",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    async def rotate_token(self, event_id: UUID) -> LostAndFoundConfig:
        """Mint a fresh page token, invalidating every link already sent.

        The emergency brake for a link that ended up in a Facebook group. The
        photos and their numbers are untouched.

        Raises:
            ValueError: ``page_not_found``.
        """
        try:
            response = self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
                UpdateExpression="SET page_token = :token, updated_at = :now",
                ExpressionAttributeValues={
                    ":token": _generate_page_token(),
                    ":now": datetime.now(timezone.utc).isoformat(),
                },
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="ALL_NEW",
            )
            logger.info(
                "Lost & found page token rotated",
                extra={"event_id": str(event_id)},
            )
            return _item_to_config(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("page_not_found") from e
            logger.error(
                "Failed to rotate lost & found token",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    # -- photos ---------------------------------------------------------------

    async def list_photos(
        self,
        event_id: UUID,
        include_pending: bool = False,
    ) -> list[LostAndFoundPhoto]:
        """Photos of one page, ascending by number.

        Ascending by number is also upload order, and it is what the number
        badges make the reader expect. PENDING rows stay out unless the admin
        view explicitly asks for them.

        Raises:
            ClientError: the query failed. Deliberately not an empty list: the
                readers of this cannot tell „no photos" from „no answer", and
                both would render the empty-state copy for a page with forty
                photos — the public one telling a guest who was sent to look up
                number 14 that there is nothing here, the admin one inviting a
                re-upload that draws a second set of numbers for the same box.
        """
        try:
            query_kwargs = {
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with(EVENT_SK_LNF_PHOTO_PREFIX),
            }

            response = self.table.query(**query_kwargs)
            items = response.get("Items", [])

            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            photos = [_item_to_photo(item) for item in items]
            if not include_pending:
                photos = [p for p in photos if p.state == LostAndFoundPhotoState.READY]
            photos.sort(key=lambda p: p.number)
            return photos

        except ClientError as e:
            logger.error(
                "Failed to list lost & found photos",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    async def get_photo(self, event_id: UUID, photo_id: UUID) -> LostAndFoundPhoto | None:
        """Read one photo row, or None when it does not exist."""
        try:
            response = self.table.get_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo_id}",
                },
            )
            item = response.get("Item")
            return _item_to_photo(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get lost & found photo",
                extra={"error": str(e), "photo_id": str(photo_id)},
            )
            return None

    async def create_upload_batch(self, event_id: UUID, count: int) -> list[LostAndFoundUpload]:
        """Reserve ``count`` numbers and mint upload permissions for them.

        The numbers come from a single atomic ``ADD next_number :count`` on the
        config row. Whatever the returned high-water mark is, the block below
        it belongs to this caller alone — two concurrent batches get disjoint
        blocks in whichever order DynamoDB applies them, which is the only
        property that matters. `next_number` starts at 0, so the first photo of
        a page is number 1.

        Raises:
            ValueError: ``count_out_of_range``, ``page_not_found``,
                ``bucket_not_configured``.
        """
        if count < 1 or count > MAX_UPLOAD_BATCH:
            raise ValueError("count_out_of_range")

        bucket = self._require_bucket()

        try:
            response = self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
                UpdateExpression="ADD next_number :count",
                ExpressionAttributeValues={":count": count},
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("page_not_found") from e
            logger.error(
                "Failed to reserve lost & found numbers",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

        high_water = int(response["Attributes"]["next_number"])
        numbers = range(high_water - count + 1, high_water + 1)

        uploads: list[LostAndFoundUpload] = []
        for number in numbers:
            photo_id = uuid4()
            photo = LostAndFoundPhoto(
                photo_id=photo_id,
                event_id=event_id,
                number=number,
                state=LostAndFoundPhotoState.PENDING,
                s3_key_display=display_key(event_id, photo_id),
                s3_key_thumb=thumb_key(event_id, photo_id),
            )

            # Row first, signature second. If the presign fails, a PENDING row
            # with nothing behind it is swept in 24 h; the other order can put
            # an object in the bucket that no row points at, and nothing but
            # the lifecycle rule would ever find it.
            self.table.put_item(Item=_photo_to_item(photo))

            uploads.append(
                LostAndFoundUpload(
                    photo_id=photo_id,
                    number=number,
                    display=self._presign_upload(bucket, photo.s3_key_display),
                    thumb=self._presign_upload(bucket, photo.s3_key_thumb),
                ),
            )

        # The reservation above proved the config row existed when the block was
        # drawn — not that it still exists now. Minting 50 signatures takes
        # hundreds of milliseconds, and a concurrent `delete_page` (another
        # admin, the sweep, an anonymisation pass) can drop the page inside that
        # window: `delete_page` lists the rows it knows about, removes them,
        # checks once that none are left and then deletes the config row. Rows
        # written after that check are orphans nothing can reach — both sweeps
        # enumerate pages through `_scan_configs` — and they would collide on
        # `number` with a page created later for the same event. Nothing has been
        # uploaded against these signatures yet (they have not left this
        # process), so the rows can simply be taken back.
        if not self._config_row_exists(event_id):
            self._rollback_upload_rows(event_id, uploads)
            raise ValueError("page_not_found")

        logger.info(
            "Lost & found upload batch minted",
            extra={
                "event_id": str(event_id),
                "count": count,
                "first_number": numbers[0],
                "last_number": numbers[-1],
            },
        )
        return uploads

    def _config_row_exists(self, event_id: UUID) -> bool:
        """Whether the page's config row is (still) there.

        A failed read answers True, exactly like `_has_photo_rows`: the caller
        uses this to decide whether to take freshly written rows back, and
        „gone" is the guess that destroys a live batch over a throttled read.
        """
        try:
            response = self.table.get_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
                ProjectionExpression="sk",
                ConsistentRead=True,
            )
        except ClientError as e:
            logger.error(
                "Could not confirm the lost & found config row still exists",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return True
        return response.get("Item") is not None

    def _rollback_upload_rows(self, event_id: UUID, uploads: list[LostAndFoundUpload]) -> None:
        """Remove rows of a batch whose page disappeared mid-mint.

        Safe in a way no other row deletion is: these signatures never reached a
        browser, so there is nothing in the bucket behind them. The keys are
        swept anyway — one call, and the alternative is an object no row points
        at — but a refusal only costs a log line here.
        """
        keys: list[str] = []
        for upload in uploads:
            keys.append(thumb_key(event_id, upload.photo_id))
            keys.append(display_key(event_id, upload.photo_id))
        self._delete_objects(keys)

        for upload in uploads:
            try:
                self.table.delete_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{upload.photo_id}",
                    },
                )
            except ClientError as e:
                logger.error(
                    "Could not take back a lost & found row whose page vanished",
                    extra={"error": str(e), "photo_id": str(upload.photo_id)},
                )

        logger.warning(
            "Lost & found upload batch rolled back — the page was deleted while it was minted",
            extra={"event_id": str(event_id), "count": len(uploads)},
        )

    def _presign_upload(self, bucket: str, key: str) -> PresignedPost:
        """One presigned POST for exactly one key.

        POST rather than PUT because only the POST policy can carry conditions:
        a presigned PUT is an unconditional write permission with no size or
        type limit. The key is fixed by the signature (an exact-match
        condition, not a prefix), the type is nailed to JPEG, and the body has
        to be between one byte and `MAX_UPLOAD_BYTES`.
        """
        try:
            presigned = self.s3.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": UPLOAD_CONTENT_TYPE},
                Conditions=[
                    {"Content-Type": UPLOAD_CONTENT_TYPE},
                    ["content-length-range", 1, MAX_UPLOAD_BYTES],
                ],
                ExpiresIn=URL_TTL_SECONDS,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign lost & found upload",
                extra={"error": str(e), "key": key},
            )
            raise

        return PresignedPost(
            url=presigned["url"],
            fields={k: str(v) for k, v in presigned["fields"].items()},
        )

    async def confirm_photos(
        self,
        event_id: UUID,
        items: list[LostAndFoundPhotoConfirm],
    ) -> tuple[list[LostAndFoundPhoto], list[UUID]]:
        """Flip the rows whose uploads made it through to READY.

        Idempotent per row: confirming a row twice just rewrites the same
        values.

        Reports instead of aborting. Each row is its own `update_item`, so by
        the time entry 30 turns out to be gone — a concurrent `delete_photo`,
        or `prune_pending` reaping a row whose upload took longer than 24 h —
        entries 1..29 are already READY and public. Telling the caller „the
        batch failed" then makes it re-upload photos that are live under
        numbers a guest may already have been given, which is the one thing
        numbers exist to prevent.

        Returns:
            ``(confirmed, not_confirmed)`` — the rows as they now stand, and
            the ids that did not flip. The caller decides what a shortfall
            means; the router answers 404 only when nothing at all was
            confirmed.

        Raises:
            ClientError: a non-conditional failure on the *first* row, where
                nothing is public yet and a systemic refusal (throttling, a
                narrowed policy) is the honest answer rather than „unknown
                photo".
        """
        confirmed: list[LostAndFoundPhoto] = []
        not_confirmed: list[UUID] = []

        for entry in items:
            set_parts = [
                "#state = :state",
                "#width = :width",
                "#height = :height",
            ]
            names = {"#state": "state", "#width": "width", "#height": "height"}
            values: dict[str, object] = {
                ":state": LostAndFoundPhotoState.READY.value,
                ":width": entry.width,
                ":height": entry.height,
            }
            remove_parts: list[str] = []

            caption = entry.caption.strip() if entry.caption else None
            names["#caption"] = "caption"
            if caption:
                values[":caption"] = caption
                set_parts.append("#caption = :caption")
            else:
                remove_parts.append("#caption")

            expression = "SET " + ", ".join(set_parts)
            if remove_parts:
                expression += " REMOVE " + ", ".join(remove_parts)

            try:
                response = self.table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{entry.photo_id}",
                    },
                    UpdateExpression=expression,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                    ConditionExpression="attribute_exists(sk)",
                    ReturnValues="ALL_NEW",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    not_confirmed.append(entry.photo_id)
                    continue
                logger.error(
                    "Failed to confirm lost & found photo",
                    extra={"error": str(e), "photo_id": str(entry.photo_id)},
                )
                if not confirmed:
                    raise
                not_confirmed.append(entry.photo_id)
                continue

            confirmed.append(_item_to_photo(response["Attributes"]))

        logger.info(
            "Lost & found photos confirmed",
            extra={
                "event_id": str(event_id),
                "count": len(confirmed),
                "not_confirmed": len(not_confirmed),
            },
        )
        return confirmed, not_confirmed

    async def update_caption(
        self,
        event_id: UUID,
        photo_id: UUID,
        caption: str | None,
    ) -> LostAndFoundPhoto:
        """Set or clear one photo's caption.

        Raises:
            ValueError: ``photo_not_found``.
        """
        cleaned = caption.strip() if caption else None

        if cleaned:
            expression = "SET #caption = :caption"
            values: dict[str, object] | None = {":caption": cleaned}
        else:
            expression = "REMOVE #caption"
            values = None

        kwargs = {
            "Key": {
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo_id}",
            },
            "UpdateExpression": expression,
            "ExpressionAttributeNames": {"#caption": "caption"},
            "ConditionExpression": "attribute_exists(sk)",
            "ReturnValues": "ALL_NEW",
        }
        if values:
            kwargs["ExpressionAttributeValues"] = values

        try:
            response = self.table.update_item(**kwargs)
            return _item_to_photo(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("photo_not_found") from e
            logger.error(
                "Failed to update lost & found caption",
                extra={"error": str(e), "photo_id": str(photo_id)},
            )
            raise

    async def delete_photo(self, event_id: UUID, photo_id: UUID) -> None:
        """Delete one photo, its two objects, and nothing else.

        The number it held stays burnt: `next_number` is never decremented, so
        the gap is permanent and no future photo inherits an old mail thread.

        Raises:
            ValueError: ``photo_not_found``, or ``objects_not_deleted`` when S3
                refused — the row then stays, because it is the only thing that
                still points at the two objects.
        """
        photo = await self.get_photo(event_id, photo_id)
        if photo is None:
            raise ValueError("photo_not_found")

        if not self._delete_objects([photo.s3_key_thumb, photo.s3_key_display]):
            raise ValueError("objects_not_deleted")

        self.table.delete_item(
            Key={
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo_id}",
            },
        )
        logger.info(
            "Lost & found photo deleted",
            extra={"event_id": str(event_id), "photo_id": str(photo_id)},
        )

    # -- viewing --------------------------------------------------------------

    def presign_view_urls(
        self,
        event_id: UUID,
        photos: list[LostAndFoundPhoto],
    ) -> dict[str, dict[str, str | None]]:
        """Short-lived GET URLs per photo, keyed by ``str(photo_id)``.

        Every photo gets an entry so callers can index without guarding; the
        two values are ``None`` when no bucket is configured (local dev) or
        when signing failed. The response type is nailed to ``image/jpeg`` and
        ``inline`` so a browser renders the object instead of offering to save
        a file named after a UUID.
        """
        urls: dict[str, dict[str, str | None]] = {}
        bucket = self.bucket

        for photo in photos:
            entry: dict[str, str | None] = {"thumb_url": None, "display_url": None}
            if bucket:
                entry["thumb_url"] = self._presign_view(bucket, photo.s3_key_thumb)
                entry["display_url"] = self._presign_view(bucket, photo.s3_key_display)
            urls[str(photo.photo_id)] = entry

        return urls

    def _presign_view(self, bucket: str, key: str) -> str | None:
        """One presigned GET, or None when signing failed.

        A single unsignable key must not take the whole page down with it — a
        gallery with one broken tile still does its job.
        """
        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentType": UPLOAD_CONTENT_TYPE,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=URL_TTL_SECONDS,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign lost & found view URL",
                extra={"error": str(e), "key": key},
            )
            return None

    async def resolve_public_page(
        self,
        event_id: UUID,
        page_token: str,
    ) -> tuple[LostAndFoundConfig, list[LostAndFoundPhoto]] | None:
        """The public page's single gate — None on every rejection.

        Never distinguishes between „wrong token", „no such event", „not
        published yet", „expired" and „anonymised": all five are None, and the
        router turns None into a flat 404. A 403 anywhere in here would confirm
        that the page exists.

        A failed *read* is not a rejection and does not get the 404 treatment —
        see `resolve_public_page_with_event`.
        """
        resolved = await self.resolve_public_page_with_event(event_id, page_token)
        if resolved is None:
            return None
        config, photos, _event = resolved
        return config, photos

    async def resolve_public_page_with_event(
        self,
        event_id: UUID,
        page_token: str,
    ) -> tuple[LostAndFoundConfig, list[LostAndFoundPhoto], Event] | None:
        """`resolve_public_page` plus the Event it already had to load.

        The public response needs the event's name and date, and looking the
        event up costs a table scan — so the gate hands over what it fetched
        rather than making the router pay for it twice.

        Raises:
            ClientError: the photo query failed. Answering „no photos" for a
                page with forty of them tells a guest who was sent to look up
                number 14 to give up; the router turns this into a 503, which
                only ever happens *after* the token matched and therefore
                confirms nothing to a prober.
        """
        from .event_service import get_event_service

        config = await self.get_config(event_id)
        if config is None:
            return None

        # `compare_digest` raises TypeError on a non-ASCII string, and this is
        # the one route where raising is a disclosure: a 500 on an event that
        # has a page next to a 404 on one that does not lets a prober enumerate
        # which events have Fundsachen. A real token is url-safe base64.
        if not page_token.isascii():
            return None

        # Constant-time: a timing side channel on a 43-character token is
        # theoretical, but the comparison is free and the habit is not.
        if not secrets.compare_digest(config.page_token, page_token):
            return None

        if not config.published:
            return None

        event = await get_event_service().get_event_by_id(event_id)
        if event is None:
            return None

        if is_page_expired(event, config):
            return None

        photos = await self.list_photos(event_id)
        return config, photos, event

    # -- deletion -------------------------------------------------------------

    def _delete_objects(self, keys: list[str]) -> bool:
        """Delete up to `_S3_DELETE_BATCH` keys; report whether they are gone.

        S3 reports a missing key as a successful delete, which is what makes
        the whole delete path idempotent — a PENDING row whose upload never
        happened cleans up exactly like a real one.

        Everything else is a failure the caller must not paper over. `Quiet`
        mode returns *only* the failures, so a per-key `AccessDenied`,
        `InternalError` or `SlowDown` shows up in `Errors` while the call
        itself succeeds. Both that and a whole-batch `ClientError` answer
        False, and every caller then keeps the row: a row without its objects
        is a retry, an object without its row is unreachable forever.

        Without a bucket (local dev) there is nothing to delete and nothing to
        fail — the rows still have to go.
        """
        bucket = self.bucket
        if not bucket or not keys:
            return True

        try:
            response = self.s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
            )
        except ClientError as e:
            logger.error(
                "Failed to delete lost & found objects",
                extra={"error": str(e), "keys": len(keys)},
            )
            return False

        errors = response.get("Errors") or []
        if errors:
            logger.error(
                "S3 refused to delete lost & found objects — keeping their rows",
                extra={
                    "keys": len(keys),
                    "failed": len(errors),
                    "first_key": errors[0].get("Key"),
                    "first_code": errors[0].get("Code"),
                },
            )
            return False

        return True

    def _has_photo_rows(self, event_id: UUID) -> bool:
        """Whether any photo row is still under the event's partition.

        A failed query answers True: the caller uses this to decide whether it
        may drop the config row, and guessing "empty" there is the one guess
        that cannot be taken back.
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with(EVENT_SK_LNF_PHOTO_PREFIX),
                Limit=1,
            )
        except ClientError as e:
            logger.error(
                "Failed to confirm lost & found photo rows are gone",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return True
        return bool(response.get("Items"))

    async def delete_page(self, event_id: UUID, deadline: datetime | None = None) -> dict:
        """Delete the page: every object, every photo row, then the config row.

        Idempotent — a second call on an already-deleted page reports zero
        deleted photos and ``completed: True``.

        Args:
            event_id: the event whose page goes away.
            deadline: wall-clock at which to stop for now. When it hits, the
                result carries ``completed: False``, the config row is left
                standing (so the page is still findable by the sweep), and the
                caller has to call again — same contract as a spec 022
                anonymisation pass. An S3 delete that S3 refused reports the
                same way, for the same reason.

        Returns:
            ``{"deleted_photos": int, "completed": bool}``.
        """
        try:
            photos = await self.list_photos(event_id, include_pending=True)
        except ClientError:
            # The work list is unreadable, so nothing may go — least of all the
            # config row, which is the sweep's only handle on this page. Same
            # answer as a refused S3 delete: come back and call again.
            logger.error(
                "Lost & found page delete could not read its work list",
                extra={"event_id": str(event_id)},
            )
            return {"deleted_photos": 0, "completed": False}

        deleted = 0
        completed = True

        # Both variants of a photo travel together, so the S3 batch is filled
        # with pairs and the rows are removed only after their objects are gone.
        for start in range(0, len(photos), _S3_DELETE_BATCH // 2):
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                completed = False
                break

            chunk = photos[start : start + _S3_DELETE_BATCH // 2]
            keys: list[str] = []
            for photo in chunk:
                keys.extend([photo.s3_key_thumb, photo.s3_key_display])

            if not self._delete_objects(keys):
                # The rows of this chunk stay, and so does the config row —
                # they are the only handle anything has on those objects. The
                # caller sees `completed: False` and comes back.
                completed = False
                continue

            for photo in chunk:
                self.table.delete_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo.photo_id}",
                    },
                )
                deleted += 1

        # The work list came from a read that logs and returns [] when its
        # query fails, so "nothing left to delete" also describes a query that
        # never saw the photos. Confirm before dropping the config row: it is
        # the only handle the sweep has on a page, and a photo row orphaned
        # under a deleted config row is unreachable forever.
        if completed and self._has_photo_rows(event_id):
            completed = False

        if completed:
            self.table.delete_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
            )

        logger.info(
            "Lost & found page deleted",
            extra={
                "event_id": str(event_id),
                "deleted_photos": deleted,
                "completed": completed,
            },
        )
        return {"deleted_photos": deleted, "completed": completed}

    # -- sweeps ---------------------------------------------------------------

    def _scan_configs(self) -> tuple[list[LostAndFoundConfig], bool]:
        """Every page in the table, plus whether that list is complete.

        A scan filtered down to one exact sk. There is no index for this and
        there does not need to be: pages are per-event and few, and this runs
        once a day in the worker.

        The flag exists because the alternative is a lie that reads exactly like
        good news. A throttled scan, a narrowed IAM policy or a table-name
        mismatch used to return an empty list, which the sweep then reported as
        „nothing to do, completed" — a permanently broken sweep and an idle one
        are the same log line, while every page past its retention window stays
        up until the bucket's 400-day rule. It is also the interlock for the
        orphan hunt below: a partial list of pages would make live photos look
        like orphans.

        Returns:
            ``(configs, complete)``. ``complete`` is False when the scan itself
            failed or a row could not be parsed.
        """
        configs: list[LostAndFoundConfig] = []
        complete = True
        scan_kwargs = {
            "FilterExpression": "sk = :sk",
            "ExpressionAttributeValues": {":sk": EVENT_SK_LNF_CONFIG},
        }

        items: list[dict] = []
        try:
            response = self.table.scan(**scan_kwargs)
            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.scan(**scan_kwargs)
                items.extend(response.get("Items", []))

        except ClientError as e:
            logger.error(
                "Failed to scan lost & found configs",
                extra={"error": str(e)},
            )
            return [], False

        for item in items:
            try:
                configs.append(_item_to_config(item))
            except (KeyError, ValueError) as e:
                # One malformed row must not stop the sweep from expiring the
                # others; it will still be here tomorrow to be noticed. Reported
                # through the flag so `pages_checked` never claims to have looked
                # at something it could not read.
                complete = False
                logger.error(
                    "Skipping unreadable lost & found config",
                    extra={"error": str(e), "pk": item.get("pk")},
                )

        return configs, complete

    def _scan_orphan_photos(self, known_pages: set[UUID]) -> tuple[list[LostAndFoundPhoto], bool]:
        """Photo rows under an event that has no config row any more.

        Nothing else can see these: `expire_pages` and `prune_pending(None)`
        both enumerate pages through `_scan_configs`, and the admin GET answers
        `configured: false` for an event without a config row. Left alone they
        live until the bucket's 400-day rule, and they collide on ``number``
        with a page created later for the same event — a listing with two
        „Nummer 9" is the one thing the counter exists to prevent.

        Three separate guards, because deleting a row that only *looks*
        orphaned destroys a live photo:

        - the page list has to be **complete** (`_scan_configs`' second return
          value) — against a truncated one every photo looks orphaned;
        - a row younger than `PENDING_TTL` is never a candidate. The page list
          was taken before the loop above, so a page created *during* the sweep
          is legitimately absent from it, and its first upload batch is minutes
          old at most;
        - and every candidate's event is asked once more, with a consistent
          read, whether it really has no config row.

        Returns:
            ``(orphans, complete)`` — a failed or unparseable row only shrinks
            the list, it never invents an orphan, so acting on a partial result
            is safe.
        """
        orphans: list[LostAndFoundPhoto] = []
        complete = True
        cutoff = datetime.now(timezone.utc) - PENDING_TTL
        scan_kwargs = {
            "FilterExpression": "begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {":prefix": EVENT_SK_LNF_PHOTO_PREFIX},
        }

        items: list[dict] = []
        try:
            response = self.table.scan(**scan_kwargs)
            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.scan(**scan_kwargs)
                items.extend(response.get("Items", []))
        except ClientError as e:
            logger.error(
                "Failed to scan for orphaned lost & found photos",
                extra={"error": str(e)},
            )
            complete = False

        for item in items:
            try:
                photo = _item_to_photo(item)
            except (KeyError, ValueError) as e:
                complete = False
                logger.error(
                    "Skipping unreadable lost & found photo row",
                    extra={"error": str(e), "sk": item.get("sk")},
                )
                continue
            if photo.event_id in known_pages or photo.uploaded_at >= cutoff:
                continue
            orphans.append(photo)

        # One confirming read per event, not per row. `_config_row_exists`
        # answers True when the read itself failed, so a throttled check keeps
        # the rows — the sweep runs again tomorrow.
        checked: dict[UUID, bool] = {}
        confirmed: list[LostAndFoundPhoto] = []
        for photo in orphans:
            if photo.event_id not in checked:
                checked[photo.event_id] = self._config_row_exists(photo.event_id)
            if checked[photo.event_id]:
                # Not a shortfall: a page created between the two scans is a
                # correct exclusion, so `complete` stays as it was.
                logger.info(
                    "A page exists after all for what looked like an orphaned photo — left alone",
                    extra={"event_id": str(photo.event_id)},
                )
                continue
            confirmed.append(photo)
        orphans = confirmed

        if orphans:
            logger.warning(
                "Found lost & found photo rows without a page",
                extra={"count": len(orphans)},
            )
        return orphans, complete

    async def expire_pages(
        self,
        now: datetime | None = None,
        deadline: datetime | None = None,
    ) -> dict:
        """Delete every page past its retention window, prune the rest.

        A page on an anonymised event goes too, as a safety net: spec 022
        deletes it directly, but a page created after the anonymisation (or one
        missed by a truncated pass) must not survive.

        A page whose event does not resolve is left alone and logged. „No
        event" is not a reliable statement here: `get_event_by_id` is a scan,
        and it also answers None when the read itself failed. Deleting on that
        signal would destroy a live page mid-window over a throttled scan, and
        nothing brings the photos back. Events that are deleted properly take
        their page with them (`delete_event`, `delete_festival_event`), so a
        page in this state means somebody removed the event row by hand.

        Every page is swept inside its own ``try`` — one page that throws must
        not cost every page behind it in scan order its turn, the same isolation
        `anonymize_expired_data` gives each event.

        Returns:
            ``{"pages_checked", "pages_deleted", "deleted_photos",
            "pending_pruned", "orphan_photos_deleted", "completed",
            "unfinished", "failed"}`` — ``unfinished`` lists the event ids whose
            deletion ran out of time, ``failed`` those whose sweep raised.
        """
        from .event_service import get_event_service

        moment = now or datetime.now(timezone.utc)
        event_service = get_event_service()

        pages_deleted = 0
        deleted_photos = 0
        pending_pruned = 0
        unfinished: list[str] = []
        failed: list[str] = []

        configs, scan_complete = self._scan_configs()
        completed = scan_complete
        out_of_time = False

        for config in configs:
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                completed = False
                out_of_time = True
                break

            try:
                event = await event_service.get_event_by_id(config.event_id)
                if event is None:
                    logger.warning(
                        "Lost & found page whose event did not resolve — skipped, not deleted",
                        extra={"event_id": str(config.event_id)},
                    )
                    continue

                expired = is_page_expired(event, config, moment)

                if not expired:
                    pending_pruned += await self.prune_pending(
                        config.event_id, deadline=deadline,
                    )
                    continue

                result = await self.delete_page(config.event_id, deadline=deadline)

            except Exception as e:
                # One bad page must not stop the sweep. Everything in here is
                # retried tomorrow, and a page that keeps failing has to be
                # visible in the summary rather than silently blocking every
                # page behind it in scan order — an unparseable photo row is a
                # permanent fault, and „the sweep stops at the same page every
                # night" is precisely the stiller Ausfall the 400-day lifecycle
                # rule is only supposed to be a backstop for.
                failed.append(str(config.event_id))
                completed = False
                logger.error(
                    "Sweeping a lost & found page failed — continuing with the rest",
                    extra={"event_id": str(config.event_id), "error": str(e)},
                )
                continue

            deleted_photos += result["deleted_photos"]
            if result["completed"]:
                pages_deleted += 1
            else:
                completed = False
                unfinished.append(str(config.event_id))

        # Rows whose page is gone are invisible to everything above, so they get
        # their own pass — but only from a complete page list, and only with time
        # left, because deleting a row that merely looks like an orphan destroys
        # a live photo.
        orphan_photos_deleted = 0
        if scan_complete and not out_of_time:
            orphans, orphans_complete = self._scan_orphan_photos(
                {config.event_id for config in configs},
            )
            if not orphans_complete:
                completed = False
            if orphans:
                orphan_photos_deleted = self._prune_rows(orphans, deadline=deadline)
                if orphan_photos_deleted < len(orphans):
                    completed = False

        summary = {
            "pages_checked": len(configs),
            "pages_deleted": pages_deleted,
            "deleted_photos": deleted_photos,
            "pending_pruned": pending_pruned,
            "orphan_photos_deleted": orphan_photos_deleted,
            "completed": completed,
            "unfinished": unfinished,
            "failed": failed,
        }
        logger.info("Lost & found expiry sweep finished", extra=summary)
        return summary

    async def prune_pending(
        self,
        event_id: UUID | None = None,
        deadline: datetime | None = None,
    ) -> int:
        """Drop PENDING photo rows older than 24 h, with their objects.

        These are aborted uploads: the tab was closed, the upload timed out.
        Their objects usually do not exist at all, which the delete path
        tolerates. The numbers they drew stay burnt — they may already be
        printed on nothing, but reusing one is the only outcome that could
        confuse a guest.

        Args:
            event_id: one page, or every page when None.
            deadline: wall-clock at which to stop. What is left is found again
                by the next run; the point is a clean stop with a reported
                summary rather than an invocation killed mid-write.

        Returns:
            How many rows were removed.
        """
        cutoff = datetime.now(timezone.utc) - PENDING_TTL

        if event_id is not None:
            photos = [
                p
                for p in await self.list_photos(event_id, include_pending=True)
                if p.state == LostAndFoundPhotoState.PENDING and p.uploaded_at < cutoff
            ]
            return self._prune_rows(photos, deadline=deadline)

        pruned = 0
        configs, _complete = self._scan_configs()
        for config in configs:
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break
            pruned += await self.prune_pending(config.event_id, deadline=deadline)
        return pruned

    def _prune_rows(
        self,
        photos: list[LostAndFoundPhoto],
        deadline: datetime | None = None,
    ) -> int:
        """Objects first, then rows — see the module docstring.

        Batched like `delete_page`: one `delete_objects` per chunk instead of
        one per row, because a page whose upload was retried over a bad festival
        link can hold hundreds of PENDING rows, and two round-trips each is what
        used to run this past the sweep's reserved time budget. A chunk whose
        objects S3 would not delete keeps its rows for the next sweep — they are
        what makes those objects findable at all.
        """
        pruned = 0

        for start in range(0, len(photos), _S3_DELETE_BATCH // 2):
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break

            chunk = photos[start : start + _S3_DELETE_BATCH // 2]
            keys: list[str] = []
            for photo in chunk:
                keys.extend([photo.s3_key_thumb, photo.s3_key_display])

            if not self._delete_objects(keys):
                continue

            for photo in chunk:
                self.table.delete_item(
                    Key={
                        "pk": f"EVENT#{photo.event_id}",
                        "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo.photo_id}",
                    },
                )
                pruned += 1

        if pruned:
            logger.info(
                "Pruned abandoned lost & found uploads",
                extra={"count": pruned},
            )
        return pruned


# Singleton instance
_lost_and_found_service: LostAndFoundService | None = None


def get_lost_and_found_service() -> LostAndFoundService:
    """Get or create LostAndFoundService instance."""
    global _lost_and_found_service
    if _lost_and_found_service is None:
        _lost_and_found_service = LostAndFoundService()
    return _lost_and_found_service
