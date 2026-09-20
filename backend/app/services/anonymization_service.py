"""Anonymisation of a finished event's personal data (spec 022).

Replaces the old „delete everything after 90 days" sweep. Where that threw
away the numbers along with the names, this rewrites every personal field in
place and leaves the rows standing, so headcounts, tier splits, check-in
totals and overnight demand stay queryable forever while nothing in the table
points back at a human.

What gets rewritten
-------------------
============================  ==========================================
Row                           Personal fields
============================  ==========================================
``REG#`` (registrations)      name, email, phone, notes, group_members,
                              group_member_emails, invite_label,
                              registration_token
``SCAN#`` (registrations)     person_name
``INVITE#`` (events)          label, email, invite_token
``MSG#`` (messages)           subject, body, body_html, inline_images,
                              recipient_email, list_unsubscribe
``EVENT#`` (events)           registration_link_token, gate_token,
                              ticket_secret
============================  ==========================================

Deliberately kept, because none of it identifies anybody and all of it is
what the surviving rows are FOR: group_size, status, tier, attendance_slots,
member_slots, tent/camper counts, the overnight approval flags, every
timestamp, the invite's batch_label and use counts, and each message's
type/direction/status.

Pseudonyms, not redactions
--------------------------
A person becomes ``Gast a3f2c1`` — a short digest of their
``(registration_id, person_index)`` pair. Two properties matter:

1. It is **deterministic without a lookup table**. The ``SCAN#`` rows store
   only a name, but their sk already carries ``registration_id`` and
   ``person_index``, so the gate log can be re-pseudonymised to exactly the
   same string as the registration without joining the two tables — and a
   re-run can never invent a second name for the same person.
2. It is **not reversible**. The digest is taken over ids that already sit in
   the row in clear, never over the name or address, so knowing the scheme
   buys an attacker nothing they did not already have.

Two words on purpose: `FestivalAttendancePatch` rejects single-word names, so
a one-word pseudonym would make an anonymised registration un-patchable.

Addresses die two different deaths
----------------------------------
``Registration.email`` is a plain ``str`` and becomes
``anonym-a3f2c1@invalid`` — the RFC 2606 reserved TLD, which is unroutable by
definition. ``group_member_emails`` is typed ``EmailStr``, and pydantic's
validator *rejects* reserved TLDs, so those entries cannot hold the same
marker and are dropped to ``None`` instead. Both outcomes are equally dead;
only the contact address keeps a visible shape, so an admin looking at an old
row can tell „anonymised" apart from „never had an address".

Tokens are rotated, not cleared
-------------------------------
``registration_token`` and ``invite_token`` back GSIs and must stay present,
so they are replaced with fresh random values rather than removed. Every
manage-, ticket- and invite-link already in somebody's inbox stops resolving,
which is the point. ``ticket_secret`` goes entirely, so no QR from this event
can ever validate again.

Photos are deleted, not pseudonymised
-------------------------------------
Two features hang photo rows off the same ``EVENT#`` partition, and neither is
pseudonymisable. There is no stand-in for a photo: what identifies the person
in it is the person in it.

Spec 023's lost & found page (``LNF#CONFIG`` plus one ``LNF#PHOTO#`` row per
photo) holds photos of other people's belongings, captioned things like „Handy
von Lena, am Bühnenrand". A page for an event whose addresses are all gone
would also have nobody left to answer the mails it invites, so the whole page
goes — config row, photo rows, S3 objects.

Spec 024's event photo collection (``PHOTOS#CONFIG``, one ``PHOTOS#ITEM#`` row
per photo, plus the hourly ``PHOTOS#QUOTA#`` rows) is guests' photos of each
other, and the ``uploader_name`` and free-text ``note`` on each row are
personal data in their own right. Same treatment, and the collection was never
meant to outlive the event anyway: spec 024 calls it a transfer point rather
than an archive, and its own sweep would have removed it in any case.

Deleting either one leaves it **re-creatable**, deliberately. A late „schickt
uns doch noch eure Fotos"-Runde is exactly the case spec 024 expects, so
``anonymized_at`` gates nothing on either feature: a new page or collection on
an anonymised event is an ordinary one, and only its own retention window ends
it.

Both run last, after every rewrite, because they are the only steps here that
destroy anything: everything above them can be repeated verbatim, so a pass
that dies halfway loses nothing. And they are the steps allowed to fall short
without failing the event — a bucket that cannot be reached leaves objects
behind that nothing can mint a URL for any more, and each bucket's own 400-day
lifecycle rule collects them.

Big events run in passes
------------------------
Every row needs its own ``update_item`` — there is no bulk partial-update in
DynamoDB — so a festival with thousands of guests, gate scans and sent mails
is thousands of round-trips. Three things keep that inside a 29-second API
Gateway window instead of returning a 504:

1. **Streamed, projected reads.** Pages are handled one at a time and only the
   handful of attributes the rewrite needs is fetched. A ``MSG#`` row carries
   the QR PNGs in ``inline_images``; buffering every one of those was enough to
   push the 512 MB API Lambda into an OOM on its own.
2. **Concurrent writes.** ``WRITE_CONCURRENCY`` updates are in flight at once.
3. **A deadline.** Callers pass one; when it runs out the pass stops mid-event,
   returns ``completed=False`` and leaves ``anonymized_at`` unset.

An unfinished event is picked up by simply calling again — the API's caller
loops, the daily sweep gets it tomorrow. A resumed pass re-reads the rows it
already did (cheap, and the projection keeps it cheap) and skips them: the
pseudonyms are deterministic, so „this row already holds exactly the string I
was about to write" is a reliable done-marker that needs no cursor and no
bookkeeping row. That also makes a resumed pass leave rotated tokens alone
instead of rotating them a second time.
"""

import hashlib
import secrets
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import Event, EventStatus, MessageStatus
from .config import (
    CHECKIN_SK_PREFIX,
    EVENT_SK_INVITE_PREFIX,
    get_events_table,
    get_messages_table,
    get_registrations_table,
)
from .event_photo_service import get_event_photo_service
from .logging import get_logger
from .lost_and_found_service import get_lost_and_found_service

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from .event_photo_service import EventPhotoService
    from .lost_and_found_service import LostAndFoundService

logger = get_logger(__name__)

REGISTRATION_SK_PREFIX = "REG#"
MESSAGE_SK_PREFIX = "MSG#"

# Only a finished event may be anonymised. Everything else still needs the
# addresses to do its job — an OPEN event has to mail people back.
ANONYMIZABLE_STATUSES = frozenset({EventStatus.COMPLETED, EventStatus.CANCELLED})

# RFC 2606 reserved TLD: guaranteed never to resolve, and rejected outright by
# pydantic's EmailStr — so nothing in this codebase can accidentally send there.
ANON_EMAIL_DOMAIN = "invalid"

_DIGEST_LENGTH = 6

# Every row this service touches lives under one `EVENT#` partition key, and a
# single DynamoDB partition tops out near 1000 write units per second. More
# writers than this buys throttling and botocore retries, not throughput.
WRITE_CONCURRENCY = 12

# Rows written between two deadline checks. Small enough that a pass overruns
# its budget by a fraction of a second, large enough to keep the pool busy.
_WRITE_CHUNK = 60

# Marker left in a scrubbed message's subject. Doubles as the done-check on a
# resumed pass, so it must stay in sync with `_anonymize_messages`.
ANON_SUBJECT = "[anonymisiert]"

# Shared 409 detail for every admin action that would need a real address.
# After anonymisation there is nothing left to send to — the guard exists so
# the admin gets told that, instead of watching a send report of "0 sent,
# 47 failed" and wondering what broke.
ANONYMIZED_BLOCK_DETAIL = (
    "Die Daten dieses Events wurden anonymisiert — es können keine E-Mails "
    "mehr verschickt werden."
)


def person_pseudonym(registration_id: str, person_index: int) -> str:
    """Stable display name for one person of one registration.

    Derived from ids that are already in the row in clear, so it leaks nothing
    and needs no lookup table — see the module docstring.
    """
    digest = hashlib.sha256(f"{registration_id}:{person_index}".encode()).hexdigest()
    return f"Gast {digest[:_DIGEST_LENGTH]}"


def person_pseudonym_email(registration_id: str, person_index: int) -> str:
    """Unroutable stand-in address matching `person_pseudonym`'s digest."""
    digest = hashlib.sha256(f"{registration_id}:{person_index}".encode()).hexdigest()
    return f"anonym-{digest[:_DIGEST_LENGTH]}@{ANON_EMAIL_DOMAIN}"


def invite_pseudonym(invite_id: str) -> str:
    """Stable stand-in for an invite label, which is usually a person's name."""
    digest = hashlib.sha256(f"invite:{invite_id}".encode()).hexdigest()
    return f"Kontingent {digest[:_DIGEST_LENGTH]}"


@dataclass
class AnonymizationResult:
    """What one `anonymize_event` call actually touched.

    `completed` is the one field a caller must not ignore: on `False` the event
    still holds personal data and the call has to be repeated. The counters are
    per pass, so summing them across the passes of one event gives the total.
    """

    event_id: str
    event_name: str
    anonymized_at: datetime | None = None
    already_anonymized: bool = False
    completed: bool = True
    registrations: int = 0
    scans: int = 0
    invites: int = 0
    messages: int = 0
    lost_and_found_photos: int = 0
    lost_and_found_failed: bool = False
    event_photos: int = 0
    event_photos_failed: bool = False

    @property
    def rows_touched(self) -> int:
        return (
            self.registrations
            + self.scans
            + self.invites
            + self.messages
            + self.lost_and_found_photos
            + self.event_photos
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["anonymized_at"] = (
            self.anonymized_at.isoformat() if self.anonymized_at else None
        )
        data["rows_touched"] = self.rows_touched
        return data


@dataclass
class _Update:
    """One pending `update_item`: the key, the SET map and the REMOVE list."""

    key: dict
    updates: dict = field(default_factory=dict)
    removes: list[str] = field(default_factory=list)


class _Pass:
    """The mutable state of one `anonymize_event` call.

    Holds the write pool and the deadline, and remembers whether the deadline
    cut the pass short — `truncated` is what turns into `completed=False`.
    """

    def __init__(self, pool: ThreadPoolExecutor, deadline: datetime | None):
        self.pool = pool
        self.deadline = deadline
        self.truncated = False

    def stop(self) -> bool:
        """True once the budget is gone, latching `truncated` on the way there.

        Latched rather than recomputed so that every loop above it unwinds on
        the same answer — a pass that decided to stop must not resume because
        the next check happened to land a microsecond earlier.
        """
        if (
            not self.truncated
            and self.deadline is not None
            and datetime.now(timezone.utc) >= self.deadline
        ):
            self.truncated = True
        return self.truncated


def _iter_pages(
    table: "Table",
    pk: str,
    sk_prefix: str,
    attributes: list[str],
) -> Iterator[list[dict]]:
    """Yield one query page at a time for rows under `pk` matching `sk_prefix`.

    Projected, not whole items: on a big event the un-projected read was both
    the slowest part of the pass and the memory ceiling (`MSG#` rows carry
    base64 QR images). Attribute names are aliased throughout — `name`,
    `status` and `body` are all DynamoDB reserved words.

    Yielded per page rather than accumulated so the caller can write as it
    reads and stop when its deadline runs out.
    """
    names = {f"#p{i}": attr for i, attr in enumerate(attributes)}
    query_kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
        "ProjectionExpression": ", ".join(names),
        "ExpressionAttributeNames": names,
    }

    while True:
        response = table.query(**query_kwargs)
        items = response.get("Items", [])
        if items:
            yield items
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return
        query_kwargs["ExclusiveStartKey"] = last_key


def _fresh_token() -> str:
    """A replacement token that is obviously a replacement when you see it."""
    return f"anon-{secrets.token_urlsafe(16)}"


class AnonymizationService:
    """Rewrites a finished event's personal data into stable pseudonyms."""

    def __init__(self):
        self._events_table = None
        self._registrations_table = None
        self._messages_table = None
        self._lost_and_found = None
        self._event_photos = None

    @property
    def events_table(self) -> "Table":
        if self._events_table is None:
            self._events_table = get_events_table()
        return self._events_table

    @property
    def registrations_table(self) -> "Table":
        if self._registrations_table is None:
            self._registrations_table = get_registrations_table()
        return self._registrations_table

    @property
    def messages_table(self) -> "Table":
        if self._messages_table is None:
            self._messages_table = get_messages_table()
        return self._messages_table

    @property
    def lost_and_found(self) -> "LostAndFoundService":
        if self._lost_and_found is None:
            self._lost_and_found = get_lost_and_found_service()
        return self._lost_and_found

    @property
    def event_photos(self) -> "EventPhotoService":
        if self._event_photos is None:
            self._event_photos = get_event_photo_service()
        return self._event_photos

    # -- row rewriters --------------------------------------------------------

    def _anonymize_registrations(self, event_pk: str, run: _Pass) -> int:
        """Rewrite every `REG#` row's personal fields in place."""
        count = 0

        for page in _iter_pages(
            self.registrations_table,
            event_pk,
            REGISTRATION_SK_PREFIX,
            ["pk", "sk", "id", "name", "group_members"],
        ):
            if run.stop():
                break

            pending: list[_Update] = []
            for item in page:
                reg_id = item.get("id") or item["sk"].removeprefix(REGISTRATION_SK_PREFIX)
                pseudonym = person_pseudonym(reg_id, 0)
                if item.get("name") == pseudonym:
                    # An earlier pass already did this row. Skipping also means
                    # its token is not rotated twice.
                    continue

                # Tombstones (`None` entries) must survive as tombstones: QR
                # `person_index` is positional, so collapsing them would silently
                # re-number everybody who came after a removed companion.
                members = item.get("group_members")
                if members is not None:
                    members = [
                        None if m is None else person_pseudonym(reg_id, i + 1)
                        for i, m in enumerate(members)
                    ]

                updates = {
                    "name": pseudonym,
                    "email": person_pseudonym_email(reg_id, 0),
                    # Rotated, not removed — it is a GSI key. Kills the manage link.
                    "registration_token": _fresh_token(),
                }
                if members is not None:
                    updates["group_members"] = members

                # `tier` stays (it is a category, not a person); the label usually
                # IS a person's name, so it goes.
                pending.append(
                    _Update(
                        key={"pk": item["pk"], "sk": item["sk"]},
                        updates=updates,
                        removes=["phone", "notes", "group_member_emails", "invite_label"],
                    ),
                )

            count += self._write(self.registrations_table, pending, run)

        return count

    def _anonymize_scans(self, event_pk: str, run: _Pass) -> int:
        """Rewrite the gate log's `person_name` to the same pseudonym the
        registration now carries.

        The sk is `SCAN#{ts}#{registration_id}#{person_index}`, so the pair the
        pseudonym is derived from is right there — no join, and no way for the
        two tables to end up disagreeing about who „Gast a3f2c1" is.
        """
        count = 0

        for page in _iter_pages(
            self.registrations_table,
            event_pk,
            CHECKIN_SK_PREFIX,
            ["pk", "sk", "person_name"],
        ):
            if run.stop():
                break

            pending: list[_Update] = []
            for item in page:
                key = {"pk": item["pk"], "sk": item["sk"]}
                parts = item["sk"].split("#")
                # ["SCAN", iso_ts, registration_id, person_index]
                if len(parts) < 4:
                    # Malformed sk — drop the name rather than leave it standing.
                    if "person_name" in item:
                        pending.append(_Update(key=key, removes=["person_name"]))
                    continue

                try:
                    person_index = int(parts[3])
                except ValueError:
                    person_index = 0

                pseudonym = person_pseudonym(parts[2], person_index)
                if item.get("person_name") == pseudonym:
                    continue

                pending.append(_Update(key=key, updates={"person_name": pseudonym}))

            count += self._write(self.registrations_table, pending, run)

        return count

    def _anonymize_invites(self, event_pk: str, now: datetime, run: _Pass) -> int:
        """Rewrite every `INVITE#` row and revoke it.

        `batch_label` is deliberately kept: it is a grouping the organiser
        invented („Werft 2026"), not something collected from a guest, and it
        is the only thing that keeps the surviving use-counts interpretable.
        """
        count = 0

        for page in _iter_pages(
            self.events_table,
            event_pk,
            EVENT_SK_INVITE_PREFIX,
            ["pk", "sk", "id", "label", "revoked_at"],
        ):
            if run.stop():
                break

            pending: list[_Update] = []
            for item in page:
                invite_id = item.get("id") or item["sk"].removeprefix(EVENT_SK_INVITE_PREFIX)
                pseudonym = invite_pseudonym(invite_id)
                if item.get("label") == pseudonym:
                    continue

                updates = {
                    "label": pseudonym,
                    # GSI key — rotated so the invite URL stops resolving.
                    "invite_token": _fresh_token(),
                }
                # Belt and braces: a rotated token already kills the link, but an
                # explicit revocation makes the row read as dead to every guard.
                if not item.get("revoked_at"):
                    updates["revoked_at"] = now.isoformat()

                pending.append(
                    _Update(
                        key={"pk": item["pk"], "sk": item["sk"]},
                        updates=updates,
                        removes=["email"],
                    ),
                )

            count += self._write(self.events_table, pending, run)

        return count

    def _anonymize_messages(self, event_pk: str, run: _Pass) -> int:
        """Strip every `MSG#` row's content and neutralise unsent ones.

        The body carries names, addresses and tokenised links, and
        `inline_images` carries the QR PNGs, so all of it goes. Type, direction,
        status and timestamps stay: „an F5 went out to this registration on the
        14th" is the send audit trail, and it names nobody.

        Anything not already SENT is forced to FAILED with a maxed retry count.
        A scrubbed message must never reach the wire — `process_email_queue`
        only picks up QUEUED, and `retry_failed_emails` needs both a
        `recipient_email` (removed here) and `retry_count < 3`.

        The projection here matters more than anywhere else: `inline_images`
        holds base64 QR PNGs, so reading whole rows to decide what to strip was
        by itself enough to OOM the 512 MB API Lambda on a large festival.
        """
        count = 0

        for page in _iter_pages(
            self.messages_table,
            event_pk,
            MESSAGE_SK_PREFIX,
            ["pk", "sk", "subject", "status"],
        ):
            if run.stop():
                break

            pending: list[_Update] = []
            for item in page:
                if item.get("subject") == ANON_SUBJECT:
                    continue

                updates = {
                    "subject": ANON_SUBJECT,
                    "body": "",
                }
                if item.get("status") != MessageStatus.SENT.value:
                    updates["status"] = MessageStatus.FAILED.value
                    updates["error_code"] = "anonymized"
                    updates["retry_count"] = 99

                pending.append(
                    _Update(
                        key={"pk": item["pk"], "sk": item["sk"]},
                        updates=updates,
                        removes=[
                            "body_html",
                            "inline_images",
                            "recipient_email",
                            "list_unsubscribe",
                        ],
                    ),
                )

            count += self._write(self.messages_table, pending, run)

        return count

    # -- the deletions --------------------------------------------------------

    async def _delete_lost_and_found(self, event_id: UUID, run: _Pass) -> tuple[int, bool]:
        """Delete the event's Fundsachen page outright (spec 023).

        Returns the number of photo rows removed and whether the page outlived
        the attempt. A page that survives is reported rather than raised: the
        remaining rewrites are done and correct, and re-running the sweep is the
        recovery path for everything here anyway.

        Two different kinds of shortfall, deliberately handled differently:

        - The deadline ran out mid-page. `delete_page` then leaves the config
          row standing, so the pass reports `completed=False`, the event keeps
          its `anonymized_at` unset, and the next pass resumes the deletion.
        - Something threw. The config row survives every raising path (it is
          removed last), so spec 023's daily `expire_lost_and_found` sweep finds
          the page again — it deletes pages on anonymised events for exactly
          this reason. The event may therefore be stamped despite the failure,
          which is the point: an unreachable bucket must not hold a whole
          event's pseudonymisation hostage.
        """
        try:
            result = await self.lost_and_found.delete_page(event_id, deadline=run.deadline)
        except Exception as e:
            logger.error(
                "Deleting the lost & found page failed — the expiry sweep will retry it",
                extra={"event_id": str(event_id), "error": str(e)},
            )
            return 0, True

        if not result["completed"]:
            # Same latch the rewrite steps use, reached from the callee's own
            # deadline check rather than `run.stop()`.
            run.truncated = True
            return result["deleted_photos"], True

        # `delete_page` builds its work list from a read that logs and returns
        # an empty list when it fails, so "completed" on its own also describes
        # a query that never saw the photos. One confirming read turns that into
        # a retry instead of photo rows orphaned under a deleted config row,
        # which nothing would ever find again.
        try:
            leftover = await self.lost_and_found.list_photos(event_id, include_pending=True)
        except ClientError as e:
            # A read that failed says nothing about what is left, so it counts as
            # „something is left" — the same way `_has_photo_rows` answers True.
            logger.error(
                "Could not confirm the lost & found page is empty — retrying next pass",
                extra={"event_id": str(event_id), "error": str(e)},
            )
            run.truncated = True
            return result["deleted_photos"], True

        if leftover:
            logger.error(
                "Lost & found photos survived the delete — retrying next pass",
                extra={"event_id": str(event_id), "remaining": len(leftover)},
            )
            run.truncated = True
            return result["deleted_photos"], True

        return result["deleted_photos"], False

    async def _delete_event_photos(self, event_id: UUID, run: _Pass) -> tuple[int, bool]:
        """Delete the event's photo collection outright (spec 024).

        Returns the number of photo rows removed and whether the collection
        outlived the attempt. Same contract as `_delete_lost_and_found` and for
        the same reason: the rewrites above are done and correct, and calling
        again is the recovery path for everything in this service anyway.

        Deletion rather than pseudonymisation — see the module docstring — and
        nothing here marks the collection as off limits afterwards.
        `anonymized_at` is not a 404 reason for spec 024, so a fresh collection
        can be opened on this event tomorrow and lives by its own window.

        The two kinds of shortfall are as different as they are over there:

        - The deadline ran out mid-collection, or S3 refused a delete batch.
          `delete_collection` leaves the config row standing in both cases, so
          the pass reports `completed=False`, the event keeps `anonymized_at`
          unset, and the next pass resumes the deletion.
        - Something threw. The config row survives every raising path (it goes
          last), so spec 024's daily `expire_event_photos` sweep picks the
          collection up once its window is over. The event may therefore be
          stamped despite the failure, which is the point: an unreachable
          bucket must not hold a whole event's pseudonymisation hostage.
        """
        try:
            result = await self.event_photos.delete_collection(event_id, deadline=run.deadline)
        except Exception as e:
            logger.error(
                "Deleting the event photo collection failed — the expiry sweep will retry it",
                extra={"event_id": str(event_id), "error": str(e)},
            )
            return 0, True

        if not result["completed"]:
            # Same latch the rewrite steps use, reached from the callee's own
            # deadline and S3 checks rather than from `run.stop()`.
            run.truncated = True
            return result["photos"], True

        # `delete_collection` probes for surviving rows itself, which makes this
        # read the outer guarantee rather than the only one: whatever that
        # method grows into, an `AnonymizationResult` must never claim a
        # collection is gone while rows sit under the partition, because a photo
        # row orphaned under a deleted config row is unreachable forever — every
        # spec 024 sweep enumerates collections through their config rows. One
        # Query against a collection that should now be empty, so it costs a
        # page of nothing.
        try:
            leftover = await self.event_photos.list_photos(event_id, include_pending=True)
        except ClientError as e:
            # A read that failed says nothing about what is left, so it counts as
            # „something is left" — the same way the service's own probe answers.
            logger.error(
                "Could not confirm the event photo collection is empty — retrying next pass",
                extra={"event_id": str(event_id), "error": str(e)},
            )
            run.truncated = True
            return result["photos"], True

        if leftover:
            logger.error(
                "Event photos survived the delete — retrying next pass",
                extra={"event_id": str(event_id), "remaining": len(leftover)},
            )
            run.truncated = True
            return result["photos"], True

        return result["photos"], False

    # -- writing --------------------------------------------------------------

    def _write(self, table: "Table", pending: list[_Update], run: _Pass) -> int:
        """Apply `pending` concurrently, in deadline-checked chunks.

        Returns how many rows were actually written — a pass that runs out of
        time stops between chunks and reports the truth, so the caller can add
        this pass's number to the previous one's.

        The `Table` handle is shared across the pool's threads. That is the one
        boto3 object here that gets touched concurrently: the botocore client
        underneath it is thread-safe, and the resource layer on top only adds
        stateless (de)serialisation. Creating a resource per thread instead
        would cost more in model loading than the writes save.

        A failed write raises out of `pool.map` and aborts the whole pass.
        Rows already written stay written, `anonymized_at` stays unset, and the
        retry re-reads and skips them — which is exactly the resume path.
        """
        written = 0

        for start in range(0, len(pending), _WRITE_CHUNK):
            if run.stop():
                break
            chunk = pending[start : start + _WRITE_CHUNK]
            list(run.pool.map(lambda item: self._apply(table, item), chunk))
            written += len(chunk)

        return written

    def _apply(self, table: "Table", item: _Update) -> None:
        """One `update_item` combining SET and REMOVE.

        Attribute names are all aliased — `name`, `status` and `body` are
        DynamoDB reserved words, and this is called with caller-chosen field
        names, so aliasing selectively would be a trap waiting for the next
        field somebody adds.
        """
        set_parts: list[str] = []
        names: dict[str, str] = {}
        values: dict[str, object] = {}

        for i, (attr, value) in enumerate(item.updates.items()):
            names[f"#s{i}"] = attr
            values[f":s{i}"] = value
            set_parts.append(f"#s{i} = :s{i}")

        remove_parts: list[str] = []
        for i, attr in enumerate(item.removes):
            names[f"#r{i}"] = attr
            remove_parts.append(f"#r{i}")

        clauses = []
        if set_parts:
            clauses.append("SET " + ", ".join(set_parts))
        if remove_parts:
            clauses.append("REMOVE " + ", ".join(remove_parts))
        if not clauses:
            return

        kwargs = {
            "Key": item.key,
            "UpdateExpression": " ".join(clauses),
            "ExpressionAttributeNames": names,
        }
        if values:
            kwargs["ExpressionAttributeValues"] = values

        table.update_item(**kwargs)

    # -- entry point ----------------------------------------------------------

    async def anonymize_event(
        self,
        event: Event,
        deadline: datetime | None = None,
    ) -> AnonymizationResult:
        """Pseudonymise every personal field this event owns.

        Order matters. The co-located rows are rewritten, and the lost & found
        page and the event photo collection deleted, BEFORE the `EVENT#` item is
        stamped, so a failure partway through leaves `anonymized_at` unset and
        the whole thing retryable — the alternative would mark an event clean
        while half its addresses were still in the table. Re-runs
        are safe: the pseudonyms are deterministic, and the only non-idempotent
        steps (token rotation) sit behind the `anonymized_at` guard and, within
        an unfinished event, behind the per-row done-check.

        Args:
            event: the event to scrub.
            deadline: wall-clock at which to give up for now. With none, the
                call runs until the event is done — right for a script, wrong
                for anything behind API Gateway's 29-second ceiling. When the
                deadline hits first, the result carries `completed=False` and
                `anonymized_at=None`, and the caller must call again.

        Raises:
            ValueError: the event is not COMPLETED or CANCELLED (German
                detail — routers map this to 409).
        """
        result = AnonymizationResult(event_id=str(event.id), event_name=event.name)

        if event.is_anonymized:
            result.already_anonymized = True
            result.anonymized_at = event.anonymized_at
            return result

        if event.status not in ANONYMIZABLE_STATUSES:
            raise ValueError(
                "Nur abgeschlossene oder abgesagte Events können anonymisiert "
                f"werden (aktueller Status: {event.status.value})",
            )

        now = datetime.now(timezone.utc)
        event_pk = f"EVENT#{event.id}"

        with ThreadPoolExecutor(
            max_workers=WRITE_CONCURRENCY,
            thread_name_prefix="anon",
        ) as pool:
            run = _Pass(pool, deadline)

            # Registrations first: they hold the names and addresses, so a
            # truncated pass has scrubbed the most sensitive rows it could.
            result.registrations = self._anonymize_registrations(event_pk, run)
            if not run.truncated:
                result.scans = self._anonymize_scans(event_pk, run)
            if not run.truncated:
                result.invites = self._anonymize_invites(event_pk, now, run)
            if not run.truncated:
                result.messages = self._anonymize_messages(event_pk, run)

        # Outside the write pool: these two delete rows instead of rewriting
        # them, in `delete_objects` batches that no amount of concurrency here
        # would speed up.
        if not run.truncated:
            (
                result.lost_and_found_photos,
                result.lost_and_found_failed,
            ) = await self._delete_lost_and_found(event.id, run)
        if not run.truncated:
            (
                result.event_photos,
                result.event_photos_failed,
            ) = await self._delete_event_photos(event.id, run)

        if run.truncated:
            result.completed = False
            logger.info(
                "Anonymization pass truncated by its deadline — call again",
                extra={
                    "event_id": str(event.id),
                    "rows_touched": result.rows_touched,
                },
            )
            return result

        # Stamped last, and in the same call that kills the event's own tokens,
        # so „anonymized_at is set" always implies „the links are dead".
        self._apply(
            self.events_table,
            _Update(
                key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
                updates={"anonymized_at": now.isoformat()},
                removes=["registration_link_token", "gate_token", "ticket_secret"],
            ),
        )
        result.anonymized_at = now

        logger.info(
            "Event anonymised",
            extra={
                "event_id": str(event.id),
                "registrations": result.registrations,
                "scans": result.scans,
                "invites": result.invites,
                "messages": result.messages,
                "lost_and_found_photos": result.lost_and_found_photos,
                "lost_and_found_failed": result.lost_and_found_failed,
                "event_photos": result.event_photos,
                "event_photos_failed": result.event_photos_failed,
            },
        )
        return result


_service: AnonymizationService | None = None


def get_anonymization_service() -> AnonymizationService:
    """Get the anonymization service singleton."""
    global _service
    if _service is None:
        _service = AnonymizationService()
    return _service
