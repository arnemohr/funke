"""Event photo collection service (spec 024 — Eventfotos).

Rows live in the events table next to the invites and the lost & found page:
``pk=EVENT#{event_id}`` with ``sk=PHOTOS#CONFIG`` for the collection, one
``sk=PHOTOS#ITEM#{photo_id}`` per photo and an hourly
``sk=PHOTOS#QUOTA#{YYYYMMDDHH}`` counter. There is no GSI — the public URL
carries the ``event_id``, so the config row is fetched with a plain ``GetItem``
and the supplied token compared against the stored one with
``secrets.compare_digest``.

This is the mirror image of spec 023, and the difference is the whole point:

**The public direction is writing, not reading.** Anyone holding the link may
put objects in our bucket. Nothing in here ever hands a guest a key, a URL or
a ``photo_id`` of somebody else's photo — the one-way street is an invariant,
not a default — and the five caps that make the write permission survivable
(the window, the policy, the per-batch and per-collection ceilings, the hourly
quota, the emergency brake) all live in this module. `create_upload_batch` is
the security-relevant function of the feature; everything else is bookkeeping
around it.

**``photo_count`` is a reservation counter, not a statistic.** It goes up when
an upload permission is minted (``ADD photo_count :n``) and down on every row
that is removed, including the sweep of aborted uploads. That is what makes
in-flight uploads count against ``MAX_PHOTOS`` without the mint path ever
counting rows — and why the public page shows the number as „ca.".

**Objects go before rows.** Every delete path removes the S3 objects first and
the DynamoDB row second. An orphan row is a cosmetic bug a re-run fixes; an
orphan object is unrecoverable, because once the row is gone nothing in the
system knows the object exists — only the bucket's 400-day lifecycle rule
would eventually catch it.

**The Lambda never sees an image byte.** It mints presigned POSTs the browser
uploads against and presigned GETs the admin view reads from. API Gateway caps
a request and a response at 10 MB and kills the invocation after 29 s, which a
single phone photo batch would blow through in both directions — and a backend
without an image parser is a backend a prepared JPEG cannot be aimed at.

`event_finished_at` and `_as_utc` are imported from the lost & found service on
purpose (spec 024 §"Verhältnis zu Spec 023"): both sweeps have to count from
the same second rather than drift apart over two copies of the same rule.

Errors are raised as ``ValueError`` with machine-readable lowercase strings
(``page_not_found``, ``photo_not_found``, ``contact_required``,
``bucket_not_configured``, ``count_out_of_range``, ``collection_full``,
``rate_limited``); the routers turn those into an HTTP status plus German
detail.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ..models import Event
from ..models.event_photos import (
    EventPhoto,
    EventPhotoConfig,
    EventPhotoConfigUpdate,
    EventPhotoConfirm,
    EventPhotoState,
    EventPhotoUpload,
    PresignedPost,
)
from .config import (
    EVENT_SK_PHOTO_CONFIG,
    EVENT_SK_PHOTO_ITEM_PREFIX,
    EVENT_SK_PHOTO_QUOTA_PREFIX,
    get_events_table,
    get_settings,
)
from .logging import get_logger
from .lost_and_found_service import _as_utc, event_finished_at

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)

# Lifetime of every presigned URL this service mints for a browser to use
# straight away — the upload POSTs and the admin view's GETs. The admin view
# refreshes its URLs shortly before this runs out, so the number is part of the
# admin response as well.
URL_TTL_SECONDS = 900

# Hard ceilings in the upload policies. The browser downscales to 2560 px at
# quality 0.85 (`full`) and 400 px at 0.7 (`thumb`) first, which lands well
# under both — the limits exist so a leaked signature cannot be used to park a
# film in the bucket, and so a `thumb` slot cannot quietly be filled with a
# second full-size image.
MAX_UPLOAD_BYTES_FULL = 6 * 1024 * 1024
MAX_UPLOAD_BYTES_THUMB = 400 * 1024

# Photos per batch. One batch is two round-trips no matter how big it is, and
# 30 is „the good ones from one evening" without making a single anonymous call
# expensive.
MAX_UPLOAD_BATCH = 30

# Photos per collection, counted in reservations. This is the number that makes
# „one Query, sort in memory, no GSI" a sound design: 2000 rows of ~300 bytes
# fit in a single query page. Past it the mint path answers „diese Sammlung ist
# voll" instead of handing out signatures.
MAX_PHOTOS = 2000

# Upload permissions one collection may be granted per clock hour. Enforced
# with a single conditional `ADD minted :n` on the hourly quota row — one row,
# one round-trip — and only ever *after* the token compared equal, so it is no
# oracle for whether a collection exists.
HOURLY_MINT_CEILING = 300

# Nailed down in the policy, not just in the UI: a phone video is 200 MB, the
# browser cannot transcode it, and a collection of them would be unaffordable
# in one go.
UPLOAD_CONTENT_TYPE = "image/jpeg"

# Default for `closes_at` on first save, counted from the end of the event.
# Together with `upload_open` this is the strongest abuse control the feature
# has, because it limits the write permission to the weeks in which it has a
# purpose: a printed slip photographed a year later opens nothing.
DEFAULT_UPLOAD_WINDOW_DAYS = 21

# An upload that has not been confirmed within this window is an abandoned
# one — the tab was closed, the WLAN died, the file would not decode.
PENDING_TTL = timedelta(hours=24)

# Validity of the download manifest's URLs. Deliberately not longer: a
# presigned URL does not outlive the Lambda's temporary credentials it was
# signed with, and regenerating the list costs nothing.
MANIFEST_TTL_SECONDS = 3600

# `delete_objects` takes at most 1000 keys per call.
_S3_DELETE_BATCH = 1000

# DynamoDB `ttl` on a quota row: three hours past the start of its own hour, so
# the row is worthless long before it disappears and the table cleans up after
# itself. `prune_quota_rows` only exists for the case where TTL deletion lags,
# which it is explicitly allowed to do by up to 48 h.
QUOTA_ROW_TTL = timedelta(hours=3)


def _generate_upload_token() -> str:
    """43 URL-safe characters — the entire access control of the upload page."""
    return secrets.token_urlsafe(32)


def hash_uploader_ip(ip: str | None) -> str | None:
    """``HMAC-SHA256(pepper, ip)``, truncated to 16 hex characters.

    Exists for exactly one question (spec 024 §Missbrauch): are these 400
    photos from 30 people or from one? Hashed, because answering that needs no
    stored address; peppered, because a bare hash over the IPv4 space is
    reversible in seconds on a laptop.

    Returns None when ``PHOTO_IP_PEPPER`` is unset — for a privacy field the
    safe default is storing nothing, not „unpeppered if need be". The pepper is
    never rotated per row, so the value also dies with the row.
    """
    if not ip:
        return None
    pepper = get_settings().photo_ip_pepper
    if not pepper:
        return None
    return hmac.new(pepper.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


def effective_retention_days(config: EventPhotoConfig) -> int:
    """The collection's own retention, or the environment default when unset."""
    if config.retention_days is not None:
        return config.retention_days
    return get_settings().event_photo_retention_days


def collection_expires_at(event: Event, config: EventPhotoConfig) -> datetime:
    """When the collection (config, rows and objects) will be deleted.

    Counted from the event's end, or from the collection's own creation when
    that is later — the same rule and the same helper as spec 023, for the same
    reason: a collection put up weeks after the event, or after the event's
    guest data was anonymised, would otherwise expire in the night after it was
    created and be gone before the first guest opened the link.
    """
    anchor = max(event_finished_at(event), _as_utc(config.created_at))
    return anchor + timedelta(days=effective_retention_days(config))


def is_collection_expired(
    event: Event,
    config: EventPhotoConfig,
    now: datetime | None = None,
) -> bool:
    """Whether the collection is past its retention window."""
    return (now or datetime.now(timezone.utc)) >= collection_expires_at(event, config)


def default_closes_at(event: Event, now: datetime | None = None) -> datetime:
    """Default automatic close: three weeks from the event, or from today.

    Anchored on the *later* of event end and now, exactly like
    `collection_expires_at` anchors on the later of event end and creation, and
    for the same reason. With the event as the only anchor, a collection put up
    more than `DEFAULT_UPLOAD_WINDOW_DAYS` after it is born closed: the form
    tells the organiser „leer lassen — dann setzen wir 21 Tage nach dem Event",
    the save succeeds, and `upload_window_open` answers False on a collection
    created five seconds ago. That kills precisely the case spec 024
    §Verhältnis zu Spec 022 names as the point of being able to re-create a
    collection — the late „schickt uns doch noch eure Fotos" round after an
    event's guest data was anonymised at 90 days, which is always past the 21.

    An organiser who wants a shorter window sets `closes_at` themselves; this
    is only the default for „I did not touch this".
    """
    moment = now or datetime.now(timezone.utc)
    return max(event_finished_at(event), moment) + timedelta(days=DEFAULT_UPLOAD_WINDOW_DAYS)


def public_upload_url(event_id: UUID, upload_token: str) -> str:
    """The link that gets printed and handed out.

    German path on purpose: this one ends up on a slip of paper at the exit and
    is read by guests. The API paths stay English like all the others.
    """
    return f"{get_settings().base_url.rstrip('/')}/fotos/{event_id}/{upload_token}"


def full_key(event_id: UUID, photo_id: UUID) -> str:
    """S3 key of the large variant.

    `full`, not `original`: it is *not* the camera original (the browser
    downscales to 2560 px and the canvas detour strips the EXIF), and a name
    claiming otherwise would lead someone to a wrong assumption later.
    """
    return f"eventphotos/{event_id}/{photo_id}/full.jpg"


def thumb_key(event_id: UUID, photo_id: UUID) -> str:
    """S3 key of the grid-sized variant."""
    return f"eventphotos/{event_id}/{photo_id}/thumb.jpg"


def plausible_capture_time(
    hint: datetime | None,
    event: Event,
    now: datetime | None = None,
) -> datetime | None:
    """The capture hint if it can be believed, otherwise None.

    `file.lastModified` is all that is left of the capture time once the canvas
    downscale has stripped the EXIF (spec 024 §Skalieren im Browser). On a
    phone that is the moment the photo was taken; on a file forwarded through
    three chat apps it is the moment that copy was saved, and on a badly set
    device it is 1980 or next year. Hence a *hint*: it is used for sorting when
    it lands in a window the event could plausibly have happened in, and
    dropped otherwise so `uploaded_at` takes over.

    A day of slack before `start_at` covers the travel-day photos everybody
    considers part of the event, and time zones.
    """
    if hint is None:
        return None
    moment = _as_utc(hint)
    reference = now or datetime.now(timezone.utc)
    if moment > reference:
        return None
    if moment < _as_utc(event.start_at) - timedelta(days=1):
        return None
    return moment


def _sort_key(photo: EventPhoto, event: Event | None) -> tuple[datetime, datetime]:
    """Chronological order of the collection: capture time where believable.

    `uploaded_at` is the tie-breaker as well as the fallback, so the order is
    total and stable — two photos with the same `lastModified` (a burst, or a
    batch of forwarded files that share a save time) keep the order they were
    minted in instead of shuffling on every request. That works only because
    `create_upload_batch` stamps its rows a microsecond apart rather than
    sharing one timestamp; with one timestamp per batch this tie-breaker would
    be a no-op and the order would fall back to the random UUID in the sort key.

    Without an event to check the hint against, a stored hint is trusted: it
    already passed `plausible_capture_time` at confirm time. Callers that have
    the event pass it, which re-checks against an event date edited since.
    """
    uploaded = _as_utc(photo.uploaded_at)
    if event is None:
        hint = _as_utc(photo.captured_at_hint) if photo.captured_at_hint else None
    else:
        hint = plausible_capture_time(photo.captured_at_hint, event)
    return (hint or uploaded, uploaded)


def _config_to_item(config: EventPhotoConfig) -> dict:
    """Convert a config model to a DynamoDB item."""
    item: dict = {
        "pk": f"EVENT#{config.event_id}",
        "sk": EVENT_SK_PHOTO_CONFIG,
        "event_id": str(config.event_id),
        "upload_token": config.upload_token,
        "upload_open": config.upload_open,
        "photo_count": config.photo_count,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
        "entity_type": "EventPhotoConfig",
    }

    # Optional, but at least one of the two is always present — `upsert_config`
    # is where that invariant is enforced.
    if config.contact_email is not None:
        item["contact_email"] = str(config.contact_email)
    if config.contact_telegram_url is not None:
        item["contact_telegram_url"] = config.contact_telegram_url

    if config.contact_name:
        item["contact_name"] = config.contact_name

    if config.intro_text:
        item["intro_text"] = config.intro_text

    if config.closes_at is not None:
        item["closes_at"] = config.closes_at.isoformat()

    if config.retention_days is not None:
        item["retention_days"] = config.retention_days

    return item


def _item_to_config(item: dict) -> EventPhotoConfig:
    """Convert a DynamoDB item to a config model."""
    closes_at = item.get("closes_at")
    return EventPhotoConfig(
        event_id=UUID(item["event_id"]),
        upload_token=item["upload_token"],
        contact_email=item.get("contact_email"),
        contact_telegram_url=item.get("contact_telegram_url"),
        contact_name=item.get("contact_name"),
        intro_text=item.get("intro_text"),
        # Missing means „not shut" — the row is only ever written by this
        # service, and a row without the attribute predates nothing, but the
        # default that keeps an unreadable flag from closing a live collection
        # is the open one.
        upload_open=bool(item.get("upload_open", True)),
        closes_at=datetime.fromisoformat(closes_at) if closes_at else None,
        retention_days=(
            int(item["retention_days"]) if item.get("retention_days") is not None else None
        ),
        photo_count=int(item.get("photo_count", 0)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def _photo_to_item(photo: EventPhoto) -> dict:
    """Convert a photo model to a DynamoDB item.

    Unset optionals are omitted rather than stored as None, exactly like spec
    023: „never set" and „cleared" then read identically, and the patch paths
    below use REMOVE to get back to this shape.
    """
    item: dict = {
        "pk": f"EVENT#{photo.event_id}",
        "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo.photo_id}",
        "photo_id": str(photo.photo_id),
        "event_id": str(photo.event_id),
        "state": photo.state.value,
        "s3_key_full": photo.s3_key_full,
        "s3_key_thumb": photo.s3_key_thumb,
        "uploaded_at": photo.uploaded_at.isoformat(),
        "starred": photo.starred,
        "faces_checked": photo.faces_checked,
        "entity_type": "EventPhoto",
    }

    if photo.width is not None:
        item["width"] = photo.width

    if photo.height is not None:
        item["height"] = photo.height

    if photo.bytes is not None:
        item["bytes"] = photo.bytes

    if photo.uploader_name:
        item["uploader_name"] = photo.uploader_name

    if photo.note:
        item["note"] = photo.note

    if photo.captured_at_hint is not None:
        item["captured_at_hint"] = photo.captured_at_hint.isoformat()

    if photo.edited_at is not None:
        item["edited_at"] = photo.edited_at.isoformat()

    if photo.uploader_ip_hash:
        item["uploader_ip_hash"] = photo.uploader_ip_hash

    return item


def _item_to_photo(item: dict) -> EventPhoto:
    """Convert a DynamoDB item to a photo model."""
    captured = item.get("captured_at_hint")
    edited = item.get("edited_at")
    return EventPhoto(
        photo_id=UUID(item["photo_id"]),
        event_id=UUID(item["event_id"]),
        state=EventPhotoState(item.get("state", EventPhotoState.PENDING.value)),
        s3_key_full=item["s3_key_full"],
        s3_key_thumb=item["s3_key_thumb"],
        width=int(item["width"]) if item.get("width") is not None else None,
        height=int(item["height"]) if item.get("height") is not None else None,
        bytes=int(item["bytes"]) if item.get("bytes") is not None else None,
        uploader_name=item.get("uploader_name"),
        note=item.get("note"),
        captured_at_hint=datetime.fromisoformat(captured) if captured else None,
        uploaded_at=datetime.fromisoformat(item["uploaded_at"]),
        starred=bool(item.get("starred", False)),
        faces_checked=bool(item.get("faces_checked", False)),
        edited_at=datetime.fromisoformat(edited) if edited else None,
        uploader_ip_hash=item.get("uploader_ip_hash"),
    )


class EventPhotoService:
    """Service for the per-event photo collection and its upload page."""

    def __init__(self):
        self._table = None
        self._s3 = None

    @property
    def table(self) -> "Table":
        """The events table (lazy) — the collection rows are co-located there."""
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
        """Configured event photo bucket, or None in a local environment.

        Its own bucket, never the lost & found one: opposite access direction,
        different retention, different blast radius. A write permission handed
        to anybody with a link must not live next to the Fundsachen photos.
        """
        return get_settings().event_photo_s3_bucket

    def _require_bucket(self) -> str:
        bucket = self.bucket
        if not bucket:
            raise ValueError("bucket_not_configured")
        return bucket

    # -- config ---------------------------------------------------------------

    async def get_config(self, event_id: UUID) -> EventPhotoConfig | None:
        """Read the collection configuration, or None when none exists yet.

        `None` means exactly one thing — there is no collection — and a failed
        read is **not** that. Spec 023's counterpart swallows the `ClientError`
        and answers None; here that would be actively harmful, because None is
        what the public gate turns into the flat „Diese Seite gibt es nicht
        (mehr)". A throttled `GetItem` would tell a guest halfway through a
        forty-photo batch that the page no longer exists — a dead end the
        upload page treats as permanent and offers no retry for — and it would
        make the routers' 503 branches unreachable code. So this raises, and
        every caller decides whether „unreadable" is a 503 or a stop.

        Raises:
            ClientError: the read failed. Never confused with „no collection".
        """
        try:
            response = self.table.get_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
            )
        except ClientError as e:
            logger.error(
                "Failed to get event photo config",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

        item = response.get("Item")
        return _item_to_config(item) if item else None

    async def upsert_config(
        self,
        event_id: UUID,
        patch: EventPhotoConfigUpdate,
        event: Event,
    ) -> EventPhotoConfig:
        """Create the collection on first save, patch it afterwards.

        The first save is what mints the token, so a half-finished collection
        is never reachable: without a contact there is no first save, and
        without a first save there is no valid token.

        `closes_at` is defaulted to `default_closes_at(event)` only when the
        caller did not mention the field at all. An explicit ``None`` is an
        organiser deciding the collection should not close by itself, which is
        a different statement from „I did not touch this".

        Args:
            event_id: the event this collection belongs to.
            patch: the fields the organiser submitted.
            event: passed in rather than looked up, so this service never
                depends on `event_service` (which in turn deletes collections
                — the import would be circular and the dependency pointless:
                every caller already holds the event it just authorised
                against).

        Raises:
            ValueError: ``contact_required`` when the first save has neither a
                mail address nor a Telegram link, or when a later save would
                clear the last one that is left. ``page_not_found`` when the
                row disappeared under a patch.
        """
        updates = patch.model_dump(exclude_unset=True)
        existing = await self.get_config(event_id)

        if existing is None:
            email = updates.get("contact_email")
            telegram = updates.get("contact_telegram_url")
            if not email and not telegram:
                raise ValueError("contact_required")

            now = datetime.now(timezone.utc)
            config = EventPhotoConfig(
                event_id=event_id,
                upload_token=_generate_upload_token(),
                contact_email=email,
                contact_telegram_url=telegram,
                contact_name=updates.get("contact_name"),
                intro_text=updates.get("intro_text"),
                upload_open=bool(updates.get("upload_open", True)),
                closes_at=(
                    updates["closes_at"] if "closes_at" in updates else default_closes_at(event)
                ),
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
                    "Event photo collection created",
                    extra={"event_id": str(event_id)},
                )
                return config

            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    logger.error(
                        "Failed to create event photo config",
                        extra={"error": str(e), "event_id": str(event_id)},
                    )
                    raise
                # A concurrent first save won the race. Falling through to the
                # patch path keeps ITS token instead of overwriting the row and
                # invalidating a link that may already have been printed — and
                # it keeps ITS `photo_count`, which an in-flight batch may
                # already be holding reservations against.

        # Either contact may be cleared, but not the last one standing: work out
        # what the row would look like afterwards rather than looking at this
        # payload alone, so „clear the mail" is fine on a collection that has
        # Telegram and refused on one that has nothing else.
        # `existing` is None on the fall-through from a lost create race, where
        # the winner's row is the truth — re-read it rather than guessing, and
        # it can legitimately still be None if that winner's row was deleted in
        # between, so nothing here dereferences it unguarded.
        current = existing or await self.get_config(event_id)
        remaining_email = (
            updates.get("contact_email")
            if "contact_email" in updates
            else (current.contact_email if current else None)
        )
        remaining_telegram = (
            updates.get("contact_telegram_url")
            if "contact_telegram_url" in updates
            else (current.contact_telegram_url if current else None)
        )
        if not remaining_email and not remaining_telegram:
            raise ValueError("contact_required")

        return await self._patch_config(event_id, updates)

    async def _patch_config(self, event_id: UUID, updates: dict) -> EventPhotoConfig:
        """Targeted SET/REMOVE on the config row.

        Never a full ``put_item``: the row also carries ``photo_count`` and
        ``upload_token``, and writing back values read a moment ago would hand
        an in-flight batch's reservations away and could resurrect a rotated
        token.
        """
        set_parts = ["#updated_at = :updated_at"]
        remove_parts: list[str] = []
        names = {"#updated_at": "updated_at"}
        values: dict[str, object] = {":updated_at": datetime.now(timezone.utc).isoformat()}

        for field, raw in updates.items():
            value = raw
            # `EmailStr` is not a `str` subclass Dynamo will take, so it is
            # cast — but only when there is something to cast. Clearing it is a
            # REMOVE below, and `str(None)` would store the literal "None",
            # which then fails validation on the way back out.
            if field == "contact_email" and value is not None:
                value = str(value)
            # Same story for a datetime: DynamoDB has no date type, and every
            # timestamp in this table is an ISO string.
            elif isinstance(value, datetime):
                value = value.isoformat()

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
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
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
                "Failed to update event photo config",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    async def rotate_token(self, event_id: UUID) -> EventPhotoConfig:
        """Mint a fresh upload token, devaluing every slip already printed.

        The emergency brake for a link that ended up in a Facebook group. The
        photos are untouched — this closes the door, it does not empty the
        room.

        Raises:
            ValueError: ``page_not_found``.
        """
        try:
            response = self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
                UpdateExpression="SET upload_token = :token, updated_at = :now",
                ExpressionAttributeValues={
                    ":token": _generate_upload_token(),
                    ":now": datetime.now(timezone.utc).isoformat(),
                },
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="ALL_NEW",
            )
            logger.info(
                "Event photo upload token rotated",
                extra={"event_id": str(event_id)},
            )
            return _item_to_config(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("page_not_found") from e
            logger.error(
                "Failed to rotate event photo token",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    # -- photos ---------------------------------------------------------------

    async def list_photos(
        self,
        event_id: UUID,
        include_pending: bool = False,
        event: Event | None = None,
    ) -> list[EventPhoto]:
        """Photos of one collection, chronologically ascending.

        One `Query` with `begins_with(sk, 'PHOTOS#ITEM#')`, **paged to the
        end**, then sorted in memory. The paging is not optional: the query
        response is capped at 1 MB, a full collection is around 600 kB of rows
        plus whatever the notes add, and a silently truncated list is the worst
        possible input for the callers below — `delete_collection` would drop
        the config row over rows it never saw, and the sweep would take the
        remainder for orphans.

        Args:
            event_id: the collection to read.
            include_pending: PENDING rows stay out unless the admin view or a
                delete path explicitly asks for them.
            event: when given, capture hints are re-checked against it (see
                `_sort_key`).

        Raises:
            ClientError: the query failed. Deliberately not an empty list —
                „no photos" and „no answer" are indistinguishable to the
                callers, and one of them decides on that basis whether the
                collection may be dropped.
        """
        try:
            query_kwargs = {
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with(EVENT_SK_PHOTO_ITEM_PREFIX),
            }

            response = self.table.query(**query_kwargs)
            items = response.get("Items", [])

            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            photos = [_item_to_photo(item) for item in items]
            if not include_pending:
                photos = [p for p in photos if p.state == EventPhotoState.READY]
            photos.sort(key=lambda p: _sort_key(p, event))
            return photos

        except ClientError as e:
            logger.error(
                "Failed to list event photos",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    async def get_photo(self, event_id: UUID, photo_id: UUID) -> EventPhoto | None:
        """Read one photo row, or None when it does not exist.

        The key is composed from `event_id`, which is what makes a `photo_id`
        from another event a plain miss rather than an authorisation check that
        could be forgotten.
        """
        try:
            response = self.table.get_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo_id}",
                },
            )
            item = response.get("Item")
            return _item_to_photo(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get event photo",
                extra={"error": str(e), "photo_id": str(photo_id)},
            )
            return None

    async def create_upload_batch(
        self,
        event_id: UUID,
        count: int,
        uploader_name: str | None = None,
        note: str | None = None,
        ip_hash: str | None = None,
        now: datetime | None = None,
    ) -> list[EventPhotoUpload]:
        """Mint upload permissions for ``count`` photos.

        The one place in this feature where an anonymous caller makes us spend
        something, so the checks run in a deliberate order — cheapest and least
        revealing first, and every one of them a distinct error string the
        public router maps to its own status:

        1. ``count_out_of_range`` — arithmetic only, no read.
        2. ``page_not_found`` — no collection here (the caller already compared
           the token, so this is a race, not a probe).
        3. ``bucket_not_configured`` — local environment, nothing to sign
           against.
        4. ``collection_full`` — the reservation counter says `MAX_PHOTOS` is
           reached.
        5. ``rate_limited`` — the hourly quota for this collection is used up.

        The quota is charged before the rows are written and is *not* refunded
        on a later failure: it is a rate limit, and a caller that makes us do
        work has spent a unit of it whether or not the work completed.

        Rows are written PENDING and signatures minted per photo. Anything that
        fails partway takes the whole batch back — rows and reservation — rather
        than leaving a caller with three usable signatures and a counter that
        thinks it handed out thirty.

        Returns:
            One `EventPhotoUpload` per photo, each with two presigned POSTs.
        """
        if count < 1 or count > MAX_UPLOAD_BATCH:
            raise ValueError("count_out_of_range")

        config = await self.get_config(event_id)
        if config is None:
            raise ValueError("page_not_found")

        bucket = self._require_bucket()

        # Read-based pre-check so a full collection gets a clean answer without
        # touching the counter. The authoritative check is on the reserved
        # value below — two concurrent batches can both pass this one.
        if config.photo_count + count > MAX_PHOTOS:
            raise ValueError("collection_full")

        moment = _as_utc(now or datetime.now(timezone.utc))
        self._consume_quota(event_id, count, moment)
        self._reserve_photo_count(event_id, count)

        written: list[EventPhoto] = []
        uploads: list[EventPhotoUpload] = []
        try:
            for index in range(count):
                photo_id = uuid4()
                photo = EventPhoto(
                    photo_id=photo_id,
                    event_id=event_id,
                    state=EventPhotoState.PENDING,
                    s3_key_full=full_key(event_id, photo_id),
                    s3_key_thumb=thumb_key(event_id, photo_id),
                    uploader_name=uploader_name,
                    note=note,
                    # One microsecond apart, in mint order — which is the order
                    # the guest's browser picked the files in. Stamping the same
                    # `moment` on all thirty would make `_sort_key`'s tie-breaker
                    # a no-op and leave the grid ordered by the random UUID in
                    # the sort key: stable across reloads, but arbitrary. That
                    # bites exactly the batch the tie-breaker exists for — files
                    # whose `captured_at_hint` is missing or implausible, i.e.
                    # forwarded photos, the ones already hardest to place.
                    uploaded_at=moment + timedelta(microseconds=index),
                    uploader_ip_hash=ip_hash,
                )

                # Row first, signature second. If the presign fails, a PENDING
                # row with nothing behind it is swept in 24 h; the other order
                # can put an object in the bucket that no row points at, and
                # nothing but the lifecycle rule would ever find it.
                self.table.put_item(Item=_photo_to_item(photo))
                written.append(photo)

                uploads.append(
                    EventPhotoUpload(
                        photo_id=photo_id,
                        full=self._presign_upload(
                            bucket, photo.s3_key_full, MAX_UPLOAD_BYTES_FULL,
                        ),
                        thumb=self._presign_upload(
                            bucket, photo.s3_key_thumb, MAX_UPLOAD_BYTES_THUMB,
                        ),
                    ),
                )
        except ClientError:
            self._rollback_upload_rows(event_id, written, release=count)
            raise

        # The reservation proved the config row existed when the counter was
        # bumped — not that it still exists now. Minting 30 signatures takes
        # hundreds of milliseconds, and a concurrent `delete_collection`
        # (another admin, the sweep, an anonymisation pass) can drop the
        # collection inside that window: it removes the rows it knows about,
        # checks once that none are left and then deletes the config row. Rows
        # written after that check are orphans nothing can reach — every sweep
        # enumerates collections through `_scan_configs`. Nothing has been
        # uploaded against these signatures yet (they have not left this
        # process), so the rows can simply be taken back.
        if not self._config_row_exists(event_id):
            self._rollback_upload_rows(event_id, written, release=count)
            raise ValueError("page_not_found")

        logger.info(
            "Event photo upload batch minted",
            extra={"event_id": str(event_id), "count": count},
        )
        return uploads

    def _consume_quota(self, event_id: UUID, count: int, now: datetime) -> None:
        """Charge ``count`` against this collection's quota for the current hour.

        One conditional `ADD` on one row: no read, no second round-trip, and
        two concurrent batches cannot both squeeze past the ceiling because the
        condition is evaluated against the stored value at apply time. The
        ceiling is `HOURLY_MINT_CEILING - count` rather than the constant
        itself, so a batch is only admitted when it fits *whole* — otherwise a
        single call could overshoot by up to `MAX_UPLOAD_BATCH - 1`.

        The row carries the table's `ttl` attribute and disappears on its own a
        couple of hours after its hour is over, which is why nothing ever has
        to enumerate these rows on the write path.

        Raises:
            ValueError: ``rate_limited``.
        """
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        sort_key = f"{EVENT_SK_PHOTO_QUOTA_PREFIX}{hour_start:%Y%m%d%H}"

        try:
            self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": sort_key},
                UpdateExpression="ADD #minted :count SET #ttl = :ttl",
                ConditionExpression=(
                    "attribute_not_exists(#minted) OR #minted <= :ceiling"
                ),
                ExpressionAttributeNames={"#minted": "minted", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":count": count,
                    ":ttl": int((hour_start + QUOTA_ROW_TTL).timestamp()),
                    ":ceiling": HOURLY_MINT_CEILING - count,
                },
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "Event photo hourly mint quota exhausted",
                    extra={"event_id": str(event_id), "hour": sort_key},
                )
                raise ValueError("rate_limited") from e
            logger.error(
                "Failed to charge the event photo mint quota",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

    def _reserve_photo_count(self, event_id: UUID, count: int) -> int:
        """Reserve ``count`` slots in the collection, atomically.

        `ADD photo_count :count` returns the new value, and that value — not
        the one read a moment earlier — decides whether the collection is full.
        A batch that overshot is released again before the refusal, so a
        collection that sits at `MAX_PHOTOS` does not stay locked at 2030 by
        callers that were turned away.

        Raises:
            ValueError: ``page_not_found``, ``collection_full``.
        """
        try:
            response = self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
                UpdateExpression="ADD photo_count :count",
                ExpressionAttributeValues={":count": count},
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("page_not_found") from e
            logger.error(
                "Failed to reserve event photo slots",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise

        reserved = int(response["Attributes"]["photo_count"])
        if reserved > MAX_PHOTOS:
            self._release_photo_count(event_id, count)
            raise ValueError("collection_full")
        return reserved

    def _release_photo_count(self, event_id: UUID, count: int) -> None:
        """Give ``count`` reserved slots back.

        Guarded so the counter cannot go negative: an underflow here would let
        a collection grow past `MAX_PHOTOS` forever, and „the counter is wrong
        by three" is a cosmetic fault next to that. A refusal is logged and
        swallowed — every caller of this is already handling a failure and must
        not have a second one thrown on top of it.
        """
        try:
            self.table.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
                UpdateExpression="ADD photo_count :delta",
                ExpressionAttributeValues={":delta": -count, ":count": count},
                ConditionExpression="attribute_exists(sk) AND photo_count >= :count",
            )
        except ClientError as e:
            logger.error(
                "Could not release reserved event photo slots",
                extra={"error": str(e), "event_id": str(event_id), "count": count},
            )

    def _config_row_exists(self, event_id: UUID) -> bool:
        """Whether the collection's config row is (still) there.

        A failed read answers True, exactly like `_has_photo_rows`: the caller
        uses this to decide whether to take freshly written rows back, and
        „gone" is the guess that destroys a live batch over a throttled read.
        """
        try:
            response = self.table.get_item(
                Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
                ProjectionExpression="sk",
                ConsistentRead=True,
            )
        except ClientError as e:
            logger.error(
                "Could not confirm the event photo config row still exists",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return True
        return response.get("Item") is not None

    def _rollback_upload_rows(
        self,
        event_id: UUID,
        photos: list[EventPhoto],
        release: int,
    ) -> None:
        """Take back a batch that could not be finished.

        Safe in a way no other row deletion is: these signatures never reached
        a browser, so there is nothing in the bucket behind them. The keys are
        swept anyway — one call, and the alternative is an object no row points
        at — but a refusal only costs a log line here.

        The reservation is released in full (`release`, not `len(photos)`): the
        counter was charged for the whole batch, and the rows that were never
        written are exactly the ones nothing will ever clean up for it.
        """
        keys: list[str] = []
        for photo in photos:
            keys.append(photo.s3_key_thumb)
            keys.append(photo.s3_key_full)
        self._delete_objects(keys)

        for photo in photos:
            try:
                self.table.delete_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo.photo_id}",
                    },
                )
            except ClientError as e:
                logger.error(
                    "Could not take back an event photo row from a failed batch",
                    extra={"error": str(e), "photo_id": str(photo.photo_id)},
                )

        self._release_photo_count(event_id, release)

        logger.warning(
            "Event photo upload batch rolled back",
            extra={"event_id": str(event_id), "rows": len(photos), "released": release},
        )

    def _presign_upload(self, bucket: str, key: str, max_bytes: int) -> PresignedPost:
        """One presigned POST for exactly one key.

        POST rather than PUT because only the POST policy can carry conditions:
        a presigned PUT is an unconditional write permission with no size or
        type limit, and this one is handed to anybody holding a printed link.
        The key is fixed by the signature (an exact-match condition, not a
        prefix), the type is nailed to JPEG — which is also where „no videos"
        is actually enforced — and the body has to be between one byte and
        `max_bytes`.

        `Content-Type` appears twice on purpose: in `Fields` so the browser
        sends the value the policy will be checked against, and in `Conditions`
        so a caller that swaps it out fails the signature instead of storing
        HTML under an image key.
        """
        try:
            presigned = self.s3.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": UPLOAD_CONTENT_TYPE},
                Conditions=[
                    {"Content-Type": UPLOAD_CONTENT_TYPE},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=URL_TTL_SECONDS,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign event photo upload",
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
        confirmations: list[EventPhotoConfirm],
        event: Event,
    ) -> list[EventPhoto]:
        """Flip the rows whose uploads made it through to READY.

        The only path from PENDING to READY, and the only write an anonymous
        caller may perform on an existing row. It sets pixel dimensions, byte
        size and the capture hint, and nothing else: not `state` to anything
        but READY, not `starred`, not a key. The row is addressed under
        ``EVENT#{event_id}``, so a `photo_id` from another event simply is not
        there.

        Reports instead of aborting, like spec 023's confirm and for the same
        reason: each row is its own `update_item`, so by the time entry 30
        turns out to be gone — swept after 24 h, deleted by an organiser
        mid-upload — entries 1..29 are already READY. Telling a guest on a
        festival connection „der Stapel ist fehlgeschlagen" would make them
        re-upload thirty photos we already have. A batch never fails as a
        whole.

        The condition allows PENDING and READY (a replayed confirm from a stale
        tab rewrites the same values) but refuses a row that has already been
        edited: a pixelated photo's dimensions must not be reset to those of
        the original it replaced.

        Returns:
            The rows that flipped, in call order. Shorter than the input when
            some ids were unknown, empty when none of them existed.

        Raises:
            ValueError: ``photo_not_found`` when not a single row could be
                confirmed — the router turns that into the 404 a wholly
                foreign `photo_id` deserves, while a partly-good batch reports
                what it managed.
        """
        confirmed: list[EventPhoto] = []
        skipped: list[UUID] = []

        for entry in confirmations:
            hint = plausible_capture_time(entry.captured_at_hint, event)

            set_parts = [
                "#state = :state",
                "#width = :width",
                "#height = :height",
                "#bytes = :bytes",
            ]
            remove_parts: list[str] = []
            names = {
                "#state": "state",
                "#width": "width",
                "#height": "height",
                "#bytes": "bytes",
                "#captured_at_hint": "captured_at_hint",
            }
            values: dict[str, object] = {
                ":state": EventPhotoState.READY.value,
                ":width": entry.width,
                ":height": entry.height,
                ":bytes": entry.bytes,
                ":pending": EventPhotoState.PENDING.value,
                ":ready": EventPhotoState.READY.value,
            }

            if hint is not None:
                values[":captured_at_hint"] = hint.isoformat()
                set_parts.append("#captured_at_hint = :captured_at_hint")
            else:
                # An implausible hint is dropped rather than stored, so nothing
                # downstream has to re-judge it and `uploaded_at` takes over.
                remove_parts.append("#captured_at_hint")

            expression = "SET " + ", ".join(set_parts)
            if remove_parts:
                expression += " REMOVE " + ", ".join(remove_parts)

            try:
                response = self.table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{entry.photo_id}",
                    },
                    UpdateExpression=expression,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                    # `attribute_exists(pk)` is what stops a replayed confirm
                    # from resurrecting a row the sweep already removed: an
                    # unconditional update would happily recreate it, with the
                    # objects gone and the counter never charged for it.
                    ConditionExpression=(
                        "attribute_exists(pk) "
                        "AND (#state = :pending OR #state = :ready) "
                        "AND attribute_not_exists(edited_at)"
                    ),
                    ReturnValues="ALL_NEW",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    skipped.append(entry.photo_id)
                    continue
                logger.error(
                    "Failed to confirm event photo",
                    extra={"error": str(e), "photo_id": str(entry.photo_id)},
                )
                if not confirmed:
                    # Nothing is stored yet, and a systemic refusal (throttling,
                    # a narrowed policy) is the honest answer rather than
                    # „unbekanntes Foto".
                    raise
                skipped.append(entry.photo_id)
                continue

            confirmed.append(_item_to_photo(response["Attributes"]))

        logger.info(
            "Event photos confirmed",
            extra={
                "event_id": str(event_id),
                "count": len(confirmed),
                "skipped": len(skipped),
            },
        )

        if not confirmed:
            raise ValueError("photo_not_found")
        return confirmed

    async def update_photo(
        self,
        event_id: UUID,
        photo_id: UUID,
        starred: bool | None = None,
        note: str | None = None,
        faces_checked: bool | None = None,
    ) -> EventPhoto:
        """Organiser edits on one photo row: the star, the note, the check mark.

        ``None`` means „leave alone" for both — the admin PATCH is partial, and
        a `starred` toggle must not wipe the uploader's note. An empty or
        blank `note` is the way to clear one, which is the only thing the
        organiser realistically wants to do with somebody else's words.

        Raises:
            ValueError: ``photo_not_found``.
        """
        if starred is None and note is None and faces_checked is None:
            # Nothing to write; still answer with the row so the caller gets
            # its 404 for a foreign id instead of a silent 200.
            photo = await self.get_photo(event_id, photo_id)
            if photo is None:
                raise ValueError("photo_not_found")
            return photo

        set_parts: list[str] = []
        remove_parts: list[str] = []
        names: dict[str, str] = {}
        values: dict[str, object] = {}

        if starred is not None:
            names["#starred"] = "starred"
            values[":starred"] = starred
            set_parts.append("#starred = :starred")

        if faces_checked is not None:
            names["#faces_checked"] = "faces_checked"
            values[":faces_checked"] = faces_checked
            set_parts.append("#faces_checked = :faces_checked")

        if note is not None:
            names["#note"] = "note"
            cleaned = note.strip()
            if cleaned:
                values[":note"] = cleaned
                set_parts.append("#note = :note")
            else:
                remove_parts.append("#note")

        expression = ""
        if set_parts:
            expression = "SET " + ", ".join(set_parts)
        if remove_parts:
            expression += (" " if expression else "") + "REMOVE " + ", ".join(remove_parts)

        kwargs: dict = {
            "Key": {
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo_id}",
            },
            "UpdateExpression": expression,
            "ExpressionAttributeNames": names,
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
                "Failed to update event photo",
                extra={"error": str(e), "photo_id": str(photo_id)},
            )
            raise

    async def create_edit_uploads(
        self,
        event_id: UUID,
        photo_id: UUID,
        now: datetime | None = None,
    ) -> EventPhotoUpload:
        """Two fresh presigned POSTs onto the photo's **existing** keys.

        This is the write half of „Unkenntlich machen": the browser pulls the
        `full` variant onto a canvas, pixelates the regions the organiser drew
        and puts the result back over the same two keys. Both variants, because
        a thumbnail with an un-pixelated face would make the whole exercise
        pointless — and the same keys, because the bucket is unversioned and
        the point is that the original stops existing.

        No new row and no reservation: the photo already exists and already
        counts. A `photo_id` from another event is not found here, because the
        row is looked up under this event's partition.

        **Refused while the uploader's own signature is still alive.** The
        guest's presigned POST was minted for these exact two keys and stays
        valid for `URL_TTL_SECONDS`; a presigned POST is not single-use. So a
        photo pixelated inside that window can be overwritten with the
        un-pixelated original by re-sending the very form the guest's browser
        still holds — and `edited_at` would go on saying the face is gone,
        which is the one lie this feature cannot afford (the bucket is
        unversioned, so nothing survives to compare against). `uploaded_at` is
        the mint moment, so it is exactly the clock that has to run out first.
        Fifteen minutes is a wait; an anonymisation that silently did not
        happen is not.

        Raises:
            ValueError: ``photo_not_found``, ``upload_too_recent``,
                ``bucket_not_configured``.
        """
        photo = await self.get_photo(event_id, photo_id)
        if photo is None:
            raise ValueError("photo_not_found")

        moment = now or datetime.now(timezone.utc)
        if _as_utc(photo.uploaded_at) + timedelta(seconds=URL_TTL_SECONDS) > moment:
            raise ValueError("upload_too_recent")

        bucket = self._require_bucket()

        return EventPhotoUpload(
            photo_id=photo.photo_id,
            full=self._presign_upload(bucket, photo.s3_key_full, MAX_UPLOAD_BYTES_FULL),
            thumb=self._presign_upload(bucket, photo.s3_key_thumb, MAX_UPLOAD_BYTES_THUMB),
        )

    async def mark_edited(
        self,
        event_id: UUID,
        photo_id: UUID,
        width: int,
        height: int,
        bytes_: int,
    ) -> EventPhoto:
        """Record that the pixelated version replaced the original.

        Called after the two edit POSTs succeeded. `edited_at` is what the
        admin grid marks the tile with, and it is also what keeps a replayed
        `confirm` from writing the pre-edit dimensions back (see
        `confirm_photos`).

        Raises:
            ValueError: ``photo_not_found``.
        """
        try:
            response = self.table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo_id}",
                },
                # `faces_checked` comes along for free: somebody who drew
                # rectangles on this photo has, by definition, looked at it.
                UpdateExpression=(
                    "SET #edited_at = :edited_at, #width = :width, "
                    "#height = :height, #bytes = :bytes, "
                    "#faces_checked = :faces_checked"
                ),
                ExpressionAttributeNames={
                    "#edited_at": "edited_at",
                    "#width": "width",
                    "#height": "height",
                    "#bytes": "bytes",
                    "#faces_checked": "faces_checked",
                },
                ExpressionAttributeValues={
                    ":edited_at": datetime.now(timezone.utc).isoformat(),
                    ":width": width,
                    ":height": height,
                    ":bytes": bytes_,
                    ":faces_checked": True,
                },
                ConditionExpression="attribute_exists(sk)",
                ReturnValues="ALL_NEW",
            )
            logger.info(
                "Event photo edited in place",
                extra={"event_id": str(event_id), "photo_id": str(photo_id)},
            )
            return _item_to_photo(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError("photo_not_found") from e
            logger.error(
                "Failed to mark event photo as edited",
                extra={"error": str(e), "photo_id": str(photo_id)},
            )
            raise

    # -- viewing (admin only) -------------------------------------------------

    def presign_view_urls(
        self,
        event_id: UUID,
        photos: list[EventPhoto],
    ) -> dict[str, dict[str, str | None]]:
        """Short-lived GET URLs per photo, keyed by ``str(photo_id)``.

        Only ever reachable through an admin route — these URLs are the reading
        direction the public side does not have. Every photo gets an entry so
        callers can index without guarding; the values are ``None`` when no
        bucket is configured (local dev) or when signing failed.

        Three URLs, not two, because `Content-Disposition` is part of what gets
        signed: `full_url` is the same object as `download_url` but `inline`,
        which is what the lightbox needs, while the lightbox's „Herunterladen"
        needs `attachment`. That is the mechanism spec 024 §Adminansicht names,
        and its virtue is that it involves no CORS at all — `attachment` is
        honoured on a plain cross-origin `<a href>`, whereas `<a download>` is
        ignored cross-origin and the `fetch`-into-a-Blob workaround silently
        stops working the day the bucket's CORS rule and the frontend's origin
        drift apart. Signing is local HMAC work, so a third URL per tile costs
        no round-trip.
        """
        urls: dict[str, dict[str, str | None]] = {}
        bucket = self.bucket

        for photo in photos:
            entry: dict[str, str | None] = {
                "thumb_url": None,
                "full_url": None,
                "download_url": None,
            }
            if bucket:
                entry["thumb_url"] = self._presign_view(bucket, photo.s3_key_thumb)
                entry["full_url"] = self._presign_view(bucket, photo.s3_key_full)
                entry["download_url"] = self.presign_download(
                    event_id,
                    photo,
                    index=None,
                    ttl=URL_TTL_SECONDS,
                )
            urls[str(photo.photo_id)] = entry

        return urls

    def _presign_view(self, bucket: str, key: str) -> str | None:
        """One presigned GET, or None when signing failed.

        A single unsignable key must not take the whole grid down with it — a
        page with one broken tile still does its job, and the admin view has an
        `onerror` handler for exactly this.

        The response headers are overridden, not trusted: whatever content type
        the uploader managed to store, the browser is told ``image/jpeg`` and
        ``inline``. Together with the S3 origin being a different origin from
        the app, that is what makes „HTML uploaded under an image key" a dead
        end rather than a scripting hole.
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
                "Failed to presign event photo view URL",
                extra={"error": str(e), "key": key},
            )
            return None

    def presign_download(
        self,
        event_id: UUID,
        photo: EventPhoto,
        index: int | None,
        ttl: int = MANIFEST_TTL_SECONDS,
    ) -> str | None:
        """The `full` variant as a file: `attachment` plus a filename.

        Serves both the download manifest and the lightbox's „Herunterladen",
        because both want the same thing — a URL a browser saves rather than
        renders. `attachment` is what makes that work cross-origin without any
        CORS rule; `<a download>` alone is ignored on a foreign origin.

        `attachment` plus a filename, because the manifest is fed to
        ``xargs -n1 -P4 curl -sOJ``: `curl -J` takes the name from the
        disposition header, and without it every one of 300 photos would be
        saved as `full.jpg`. The zero-padded index keeps the chronological
        order visible in a file listing, and the `photo_id` prefix keeps two
        photos with the same index from overwriting each other. ``index=None``
        is the single download, where there is no list to keep in order and
        `foto-1f4c9ab3.jpg` is the more honest name.

        Both spellings are built from the id's hex digits and a fixed format,
        so nothing an uploader typed can reach the header — a filename is the
        one place in this feature where a stray quote or newline would be an
        injection into a response header.

        Returns None without a bucket or when signing failed — the manifest
        skips the line instead of failing the download, and the grid drops one
        button rather than one tile.
        """
        bucket = self.bucket
        if not bucket:
            return None

        short = str(photo.photo_id)[:8]
        filename = f"foto-{short}.jpg" if index is None else f"{index:04d}_{short}.jpg"
        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": photo.s3_key_full,
                    "ResponseContentType": UPLOAD_CONTENT_TYPE,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                },
                ExpiresIn=ttl,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign event photo download URL",
                extra={"error": str(e), "event_id": str(event_id), "key": photo.s3_key_full},
            )
            return None

    # -- the public gate ------------------------------------------------------

    async def resolve_public_page(
        self,
        event_id: UUID,
        upload_token: str,
    ) -> EventPhotoConfig | None:
        """The upload page's gate — None on every rejection.

        Never distinguishes between „wrong token" and „no such collection":
        both are None and the router turns None into a flat 404. Anything else
        would confirm that a collection exists for this event.

        It deliberately does **not** fold the upload window into the gate. A
        closed collection still has to render its „der Upload ist zu, schreib
        an …" page, so the window state goes back to the caller (see
        `upload_window_open`) instead of becoming a 404 that leaves a guest
        with a printed slip and no explanation.
        """
        config = await self.get_config(event_id)
        if config is None:
            return None

        # `compare_digest` raises TypeError on a non-ASCII string, and this is
        # the one route where raising is a disclosure: a 500 on an event that
        # has a collection next to a 404 on one that does not lets a prober
        # enumerate which events collect photos. A real token is url-safe
        # base64, so this rejects nothing legitimate. Spec 023 learned this the
        # hard way; here it is the first line of the comparison.
        if not upload_token.isascii():
            return None

        # Constant-time: a timing side channel on a 43-character token is
        # theoretical, but the comparison is free and the habit is not.
        if not secrets.compare_digest(config.upload_token, upload_token):
            return None

        return config

    async def resolve_public_page_with_event(
        self,
        event_id: UUID,
        upload_token: str,
    ) -> tuple[EventPhotoConfig, Event] | None:
        """`resolve_public_page` plus the Event it needs anyway.

        The public response carries the event's name and date, and the window
        check needs its end — so the gate hands over what it fetched rather
        than making the router look the event up a second time. A collection
        whose event cannot be resolved is None: without the event there is no
        way to tell whether the window is still open, and „no answer" must not
        become „upload away".
        """
        from .event_service import get_event_service

        config = await self.resolve_public_page(event_id, upload_token)
        if config is None:
            return None

        event = await get_event_service().get_event_by_id(event_id)
        if event is None:
            return None

        return config, event

    def upload_window_open(
        self,
        config: EventPhotoConfig,
        event: Event,
        now: datetime | None = None,
    ) -> bool:
        """Whether new photos may be handed in right now.

        Three conditions, descending in finality: the organiser's switch, the
        automatic close, and the retention window — a collection whose photos
        are due for deletion tonight must not accept more of them.
        """
        moment = now or datetime.now(timezone.utc)

        if not config.upload_open:
            return False
        if config.closes_at is not None and moment >= _as_utc(config.closes_at):
            return False
        return not is_collection_expired(event, config, moment)

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
                "Failed to delete event photo objects",
                extra={"error": str(e), "keys": len(keys)},
            )
            return False

        errors = response.get("Errors") or []
        if errors:
            logger.error(
                "S3 refused to delete event photo objects — keeping their rows",
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
        may drop the config row, and guessing „empty" there is the one guess
        that cannot be taken back.
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with(EVENT_SK_PHOTO_ITEM_PREFIX),
                Limit=1,
            )
        except ClientError as e:
            logger.error(
                "Failed to confirm event photo rows are gone",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return True
        return bool(response.get("Items"))

    async def delete_photos(
        self,
        event_id: UUID,
        photos: list[EventPhoto],
        deadline: datetime | None = None,
    ) -> int:
        """Delete the given photos: objects first, then rows, then the counter.

        Serves the single delete, the bulk delete, the PENDING prune and the
        full collection delete, because all four want the same three steps in
        the same order.

        Batched: one `delete_objects` per chunk instead of two calls per photo,
        because a collection whose upload was retried over a bad festival link
        can hold hundreds of rows and per-row round-trips are what runs a
        sweep past its time budget. A chunk whose objects S3 refuses to delete
        keeps its rows for the next attempt — they are what makes those objects
        findable at all.

        `photo_count` is decremented by the number of rows actually removed,
        once per chunk rather than once per row: the effect on the counter is
        identical and it is one write instead of a thousand.

        Returns:
            How many rows were removed. A result below ``len(photos)`` means
            something is left over — S3 refused, or the deadline hit — and the
            caller has to come back.
        """
        removed = 0

        # Both variants of a photo travel together, so the S3 batch is filled
        # with pairs.
        for start in range(0, len(photos), _S3_DELETE_BATCH // 2):
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break

            chunk = photos[start : start + _S3_DELETE_BATCH // 2]
            keys: list[str] = []
            for photo in chunk:
                keys.extend([photo.s3_key_thumb, photo.s3_key_full])

            if not self._delete_objects(keys):
                continue

            in_chunk = 0
            for photo in chunk:
                try:
                    self.table.delete_item(
                        Key={
                            "pk": f"EVENT#{event_id}",
                            "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo.photo_id}",
                        },
                    )
                except ClientError as e:
                    # The objects of this chunk are already gone, so the row is
                    # worthless — but it is also harmless, and the next pass
                    # deletes it. Counting it as removed would decrement the
                    # counter for a row that is still there.
                    logger.error(
                        "Failed to delete an event photo row",
                        extra={"error": str(e), "photo_id": str(photo.photo_id)},
                    )
                    continue
                in_chunk += 1

            if in_chunk:
                self._release_photo_count(event_id, in_chunk)
            removed += in_chunk

        if removed:
            logger.info(
                "Event photos deleted",
                extra={"event_id": str(event_id), "count": removed},
            )
        return removed

    async def delete_collection(self, event_id: UUID, deadline: datetime | None = None) -> dict:
        """Delete the collection: every object, every row, then the config row.

        Idempotent — a second call on an already-deleted collection reports
        zero photos and ``completed: True``.

        Args:
            event_id: the event whose collection goes away.
            deadline: wall-clock at which to stop for now. When it hits, the
                result carries ``completed: False``, the config row is left
                standing (so the collection is still findable by the sweep),
                and the caller has to call again — the same contract as a spec
                022 anonymisation pass and spec 023's `delete_page`. An S3
                delete that S3 refused reports the same way, for the same
                reason.

        Returns:
            ``{"photos": int, "completed": bool}``.
        """
        try:
            photos = await self.list_photos(event_id, include_pending=True)
        except ClientError:
            # The work list is unreadable, so nothing may go — least of all the
            # config row, which is the sweep's only handle on this collection.
            # Same answer as a refused S3 delete: come back and call again.
            logger.error(
                "Event photo collection delete could not read its work list",
                extra={"event_id": str(event_id)},
            )
            return {"photos": 0, "completed": False}

        deleted = await self.delete_photos(event_id, photos, deadline=deadline)
        completed = deleted == len(photos)

        # Even a complete-looking pass gets one confirming read: „nothing left"
        # can also describe a query that never saw the rows, and a photo row
        # orphaned under a deleted config row is unreachable forever — every
        # sweep enumerates collections through `_scan_configs`.
        if completed and self._has_photo_rows(event_id):
            completed = False

        if completed:
            try:
                self.table.delete_item(
                    Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
                )
            except ClientError as e:
                logger.error(
                    "Failed to delete the event photo config row",
                    extra={"error": str(e), "event_id": str(event_id)},
                )
                completed = False

        logger.info(
            "Event photo collection deleted",
            extra={
                "event_id": str(event_id),
                "photos": deleted,
                "completed": completed,
            },
        )
        return {"photos": deleted, "completed": completed}

    # -- sweeps ---------------------------------------------------------------

    def _scan_configs(self) -> tuple[list[EventPhotoConfig], bool]:
        """Every collection in the table, plus whether that list is complete.

        A scan filtered down to one exact sk. There is no index for this and
        there does not need to be: collections are per-event and few, and this
        runs once a day in the worker.

        The flag exists because the alternative is a lie that reads exactly
        like good news. A throttled scan, a narrowed IAM policy or a table-name
        mismatch returns an empty list, which the sweep would report as
        „nothing to do, completed" — a permanently broken sweep and an idle one
        would be the same log line, while every collection past its window kept
        guests' faces in the bucket until the 400-day lifecycle rule.

        Returns:
            ``(configs, complete)``. ``complete`` is False when the scan itself
            failed or a row could not be parsed.
        """
        configs: list[EventPhotoConfig] = []
        complete = True
        scan_kwargs = {
            "FilterExpression": "sk = :sk",
            "ExpressionAttributeValues": {":sk": EVENT_SK_PHOTO_CONFIG},
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
                "Failed to scan event photo configs",
                extra={"error": str(e)},
            )
            return [], False

        for item in items:
            try:
                configs.append(_item_to_config(item))
            except (KeyError, ValueError) as e:
                # One malformed row must not stop the sweep from expiring the
                # others; it will still be here tomorrow to be noticed.
                # Reported through the flag so the summary never claims to have
                # looked at something it could not read.
                complete = False
                logger.error(
                    "Skipping unreadable event photo config",
                    extra={"error": str(e), "pk": item.get("pk")},
                )

        return configs, complete

    async def expire_collections(
        self,
        now: datetime | None = None,
        deadline: datetime | None = None,
    ) -> dict:
        """The daily sweep: expired collections out, aborted uploads out.

        Three duties, in the order of how much they can cost if skipped:
        delete every collection past its retention window, prune PENDING rows
        older than 24 h in the ones that stay, and mop up quota rows the
        table's TTL has not got around to.

        A collection whose event does not resolve is left alone and logged.
        „No event" is not a reliable statement here: `get_event_by_id` is a
        scan, and it also answers None when the read itself failed. Deleting on
        that signal would destroy a live collection mid-window over a throttled
        scan, and nothing brings guests' photos back. Events that are deleted
        properly take their collection with them, so a collection in this state
        means somebody removed the event row by hand.

        Every collection is swept inside its own ``try`` — one that throws must
        not cost every collection behind it in scan order its turn, the same
        isolation the anonymisation sweep gives each event.

        Returns:
            ``{"collections_checked", "collections_deleted", "deleted_photos",
            "pending_pruned", "quota_rows_pruned", "completed", "unfinished",
            "failed"}`` — ``unfinished`` lists the event ids whose deletion ran
            out of time, ``failed`` those whose sweep raised.
        """
        from .event_service import get_event_service

        moment = now or datetime.now(timezone.utc)
        event_service = get_event_service()

        collections_deleted = 0
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
                        "Event photo collection whose event did not resolve — skipped",
                        extra={"event_id": str(config.event_id)},
                    )
                    continue

                if not is_collection_expired(event, config, moment):
                    pending_pruned += await self.prune_pending(
                        config.event_id, deadline=deadline,
                    )
                    continue

                result = await self.delete_collection(config.event_id, deadline=deadline)

            except Exception as e:
                # One bad collection must not stop the sweep. Everything in
                # here is retried tomorrow, and one that keeps failing has to
                # be visible in the summary rather than silently blocking every
                # collection behind it in scan order — „the sweep stops at the
                # same collection every night" is precisely the stiller Ausfall
                # the 400-day lifecycle rule is only meant to be a backstop
                # for.
                failed.append(str(config.event_id))
                completed = False
                logger.error(
                    "Sweeping an event photo collection failed — continuing with the rest",
                    extra={"event_id": str(config.event_id), "error": str(e)},
                )
                continue

            deleted_photos += result["photos"]
            if result["completed"]:
                collections_deleted += 1
            else:
                completed = False
                unfinished.append(str(config.event_id))

        # Quota rows are keyed by hour, not by collection, so they are their own
        # pass — and a cheap one, only worth doing when there is time left.
        quota_rows_pruned = 0
        if not out_of_time:
            quota_rows_pruned = self.prune_quota_rows(deadline=deadline)

        summary = {
            "collections_checked": len(configs),
            "collections_deleted": collections_deleted,
            "deleted_photos": deleted_photos,
            "pending_pruned": pending_pruned,
            "quota_rows_pruned": quota_rows_pruned,
            "completed": completed,
            "unfinished": unfinished,
            "failed": failed,
        }
        logger.info("Event photo expiry sweep finished", extra=summary)
        return summary

    async def prune_pending(
        self,
        event_id: UUID | None = None,
        deadline: datetime | None = None,
    ) -> int:
        """Drop PENDING photo rows older than 24 h, with their objects.

        These are aborted uploads: the tab was closed, the connection died, the
        file would not decode. Their objects usually do not exist at all, which
        the delete path tolerates — and the reservations they hold are the
        reason this has to run: without it a collection whose guests kept
        retrying over a bad link would report itself full at a few hundred
        actual photos.

        Args:
            event_id: one collection, or every collection when None.
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
                if p.state == EventPhotoState.PENDING and _as_utc(p.uploaded_at) < cutoff
            ]
            return await self.delete_photos(event_id, photos, deadline=deadline)

        pruned = 0
        configs, _complete = self._scan_configs()
        for config in configs:
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break
            pruned += await self.prune_pending(config.event_id, deadline=deadline)
        return pruned

    def prune_quota_rows(self, deadline: datetime | None = None) -> int:
        """Remove hourly quota rows whose hour is long over.

        Belt to the table's TTL, not a replacement for it: DynamoDB deletes an
        expired item „typically within 48 hours", and on a table that is mostly
        idle it can be slower than that. These rows are tiny, but they sit in
        the same partition as the collection they belong to and show up in
        every `Query` a careless future reader writes without a `begins_with`.

        The hour comes out of the sort key rather than the `ttl` attribute, so
        a row written without one (a partial write, an older shape) is still
        collectable.

        Returns:
            How many rows were removed.
        """
        now = datetime.now(timezone.utc)
        scan_kwargs = {
            "FilterExpression": "begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {":prefix": EVENT_SK_PHOTO_QUOTA_PREFIX},
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
                "Failed to scan event photo quota rows",
                extra={"error": str(e)},
            )
            return 0

        pruned = 0
        for item in items:
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break

            stamp = str(item.get("sk", ""))[len(EVENT_SK_PHOTO_QUOTA_PREFIX) :]
            try:
                hour_start = datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            except ValueError:
                logger.error(
                    "Skipping an event photo quota row with an unreadable hour",
                    extra={"pk": item.get("pk"), "sk": item.get("sk")},
                )
                continue

            # Same window the `ttl` attribute carries, so this never removes a
            # row the current hour could still be charging against.
            if hour_start + QUOTA_ROW_TTL > now:
                continue

            try:
                self.table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            except ClientError as e:
                logger.error(
                    "Failed to delete an event photo quota row",
                    extra={"error": str(e), "sk": item.get("sk")},
                )
                continue
            pruned += 1

        if pruned:
            logger.info("Pruned event photo quota rows", extra={"count": pruned})
        return pruned


# Singleton instance
_event_photo_service: EventPhotoService | None = None


def get_event_photo_service() -> EventPhotoService:
    """Get or create EventPhotoService instance."""
    global _event_photo_service
    if _event_photo_service is None:
        _event_photo_service = EventPhotoService()
    return _event_photo_service
