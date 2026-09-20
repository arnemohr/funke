"""Tests for the Eventfotos endpoints (spec 024) — the fourteen routes.

Structured around the one property this feature lives or dies by: it is a
**one-way street**. Guests write, guests read nothing. The admin side is
therefore checked the way spec 023's is — role guards and the org boundary —
while the public side gets two extra kinds of scrutiny that 023 does not need:

* `TestTheOneWayStreet` asserts the invariant against the response *schema*
  rather than a sample body, so a field added to the public model years from
  now fails the build instead of quietly opening a reading path.
* `TestPublicGate` asserts as a set comparison that every rejection at or
  before the token comparison is the same 404 with the same sentence — the
  failure mode being a future branch that grows its own, more helpful, answer.

The admin half then covers what only an HTTP test can see: that the presigned
GETs carry their response-header overrides, that the literal segments under
`/photos/` are not swallowed by `/photos/{photo_id}`, and that a refused S3
delete comes back as something the organiser can act on.
"""

from datetime import date, datetime, timedelta, timezone
from typing import get_args
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.services.config as config_module
import app.services.event_photo_service as photo_module
import app.services.event_service as event_service_module
from app.api.admin.event_photos import _MAX_BULK_DELETE
from app.api.public.event_photos import EventPhotoUploadPageResponse
from app.main import app
from app.models import Event, EventStatus, EventType
from app.models.admin import AdminRole
from app.models.event_photos import RETENTION_DAYS_MAX, RETENTION_DAYS_MIN
from app.services.auth import TokenPayload, verify_token
from app.services.config import (
    EVENT_SK_PHOTO_CONFIG,
    EVENT_SK_PHOTO_ITEM_PREFIX,
    EVENT_SK_PHOTO_QUOTA_PREFIX,
    DynamoDBSettings,
)
from app.services.event_photo_service import (
    HOURLY_MINT_CEILING,
    MANIFEST_TTL_SECONDS,
    MAX_PHOTOS,
    MAX_UPLOAD_BATCH,
    URL_TTL_SECONDS,
    EventPhotoService,
    full_key,
    thumb_key,
)
from app.services.event_service import EventService, _event_to_item

BUCKET = "funke-test-eventphotos"
BASE_URL = "https://fest.example.com"
PEPPER = "pfeffer-aus-der-umgebung"
NOW = datetime.now(timezone.utc)

# The single answer to every public rejection at or before the token check.
NOT_FOUND_BODY = {"detail": "Diese Seite gibt es nicht (mehr)."}
CLOSED_DETAIL = "Der Upload für dieses Event ist geschlossen."


class ApiBase:
    """A TestClient whose org, role and environment can be swapped mid-test."""

    bucket: str | None = BUCKET
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

        self.s3 = boto3.client("s3", region_name="eu-central-1")
        self.s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-central-1"},
        )

        self.service = EventPhotoService()
        self.service._table = self.events_table
        monkeypatch.setattr(photo_module, "_event_photo_service", self.service)

        event_service = EventService()
        event_service._table = self.events_table
        monkeypatch.setattr(event_service_module, "_event_service", event_service)

        self.org_id = uuid4()
        self.role = AdminRole.ADMIN

        def _identity() -> TokenPayload:
            return TokenPayload(
                sub="auth0|tester",
                email="orga@example.com",
                org_id=str(self.org_id),
                role=self.role,
            )

        app.dependency_overrides[verify_token] = _identity
        self.client = TestClient(app)
        yield
        app.dependency_overrides.clear()

    # -- factories ------------------------------------------------------------

    def _store_event(self, **overrides) -> Event:
        defaults = dict(
            id=uuid4(),
            org_id=self.org_id,
            name="Sommerfahrt Müggelsee",
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

    def _admin(self, event: Event, suffix: str = "") -> str:
        return f"/api/admin/events/{event.id}/photos{suffix}"

    def _public(self, event_id, token: str, suffix: str = "") -> str:
        return f"/api/public/photos/{event_id}/{token}{suffix}"

    def _create_collection(self, event: Event, **patch) -> dict:
        """First save — which is what mints the token, so it needs a contact."""
        body = {"contact_email": "fotos@example.com"}
        body.update(patch)
        response = self.client.put(self._admin(event, "/config"), json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def _upload(
        self,
        event: Event,
        token: str,
        count: int,
        *,
        confirm: bool = True,
        headers: dict | None = None,
        **body,
    ) -> list[dict]:
        """Walk one batch through the public path: mint, put the objects, confirm.

        The objects really land in moto, because a delete that reports „gone"
        for a key that was never there proves nothing about the delete.
        """
        response = self.client.post(
            self._public(event.id, token, "/uploads"),
            json={"count": count, **body},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        uploads = response.json()["uploads"]

        for upload in uploads:
            photo_id = UUID(upload["photo_id"])
            for key in (full_key(event.id, photo_id), thumb_key(event.id, photo_id)):
                self.s3.put_object(Bucket=BUCKET, Key=key, Body=b"jpeg-bytes")

        if confirm:
            confirmed = self.client.post(
                self._public(event.id, token, "/confirm"),
                json=[
                    {
                        "photo_id": u["photo_id"],
                        "width": 2560,
                        "height": 1920,
                        "bytes": 900_000,
                    }
                    for u in uploads
                ],
            )
            assert confirmed.status_code == 200, confirmed.text
        return uploads

    def _config_item(self, event_id) -> dict | None:
        return self.events_table.get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_PHOTO_CONFIG},
        ).get("Item")

    def _photo_item(self, event_id, photo_id) -> dict | None:
        return self.events_table.get_item(
            Key={
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_PHOTO_ITEM_PREFIX}{photo_id}",
            },
        ).get("Item")

    def _age_photo(self, event: Event, photo_id, age: timedelta) -> None:
        """Backdate a row's `uploaded_at`.

        Needed by every test that goes through „Unkenntlich machen": the edit
        handshake is refused while the uploader's own presigned POST is still
        valid for the same two keys (see the service), and `uploaded_at` is the
        moment that signature was minted.
        """
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

    def _stale_upload(self, event: Event, token: str) -> dict:
        """One confirmed photo whose upload permission has already expired."""
        upload = self._upload(event, token, 1)[0]
        self._age_photo(event, upload["photo_id"], timedelta(seconds=URL_TTL_SECONDS + 1))
        return upload

    def _exhaust_the_hourly_quota(self, event: Event) -> None:
        """Park the hourly counter on its ceiling.

        Both the current hour and the next one, so a test that starts at
        :59:59.9 and mints at :00:00.1 cannot flake on the boundary.
        """
        moment = datetime.now(timezone.utc)
        for offset in (0, 1):
            hour = (moment + timedelta(hours=offset)).strftime("%Y%m%d%H")
            self.events_table.put_item(
                Item={
                    "pk": f"EVENT#{event.id}",
                    "sk": f"{EVENT_SK_PHOTO_QUOTA_PREFIX}{hour}",
                    "minted": HOURLY_MINT_CEILING,
                },
            )


# --- the one-way street ------------------------------------------------------

# Substrings that would betray a reading path if they ever showed up in a
# public field name.
_FORBIDDEN_SUBSTRINGS = ("url", "key", "photo_id", "s3")

# The two field names that legitimately contain one of those substrings, pinned
# as an exhaustive set so a *third* one cannot be added without a failing test.
# Neither can carry an image: `contact_telegram_url` is the `https://t.me/…`
# href the page must show (it is validated at the model edge), and
# `url_ttl_seconds` is an integer the page uses to schedule its own reloads.
_ALLOWED_NAMES = {"contact_telegram_url", "url_ttl_seconds"}


def _nested_models(annotation) -> list[type[BaseModel]]:
    """Every pydantic model reachable from one annotation, unions included."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        found.extend(_nested_models(arg))
    return found


def _schema_field_names(model: type[BaseModel]) -> set[str]:
    """All field names of a model and of everything nested inside it."""
    names: set[str] = set()
    seen: set[type[BaseModel]] = set()
    stack = [model]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            names.add(name)
            stack.extend(_nested_models(field.annotation))
    return names


def _body_keys(payload) -> set[str]:
    """Every key in a JSON body, at any depth."""
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(key)
            keys |= _body_keys(value)
    elif isinstance(payload, list):
        for entry in payload:
            keys |= _body_keys(entry)
    return keys


def _suspicious(names) -> set[str]:
    return {
        name
        for name in names
        if any(part in name.lower() for part in _FORBIDDEN_SUBSTRINGS)
    } - _ALLOWED_NAMES


class TestTheOneWayStreet(ApiBase):
    """Spec 024 §Die Einbahnstraße, as a schema test.

    „Die öffentliche Antwort enthält kein Feld, das eine Bild-URL, einen
    S3-Key oder eine `photo_id` tragen kann." A sample-body assertion would
    only catch a field somebody remembered to populate; this catches the field
    itself, on the day it is declared, which is the day the mistake is cheap.
    """

    def test_the_public_response_schema_cannot_carry_a_read_path(self):
        names = _schema_field_names(EventPhotoUploadPageResponse)
        assert _suspicious(names) == set(), (
            "A field on the public upload-page response now looks like it can "
            "carry an image URL, an S3 key or a photo_id. That is the one "
            "invariant of spec 024 — guests upload and see nothing. If the new "
            "field genuinely cannot carry one, add it to _ALLOWED_NAMES with a "
            "reason."
        )
        # And the allowlist itself has to stay true: both names must still be
        # on the model, or the exemption has outlived its field.
        assert _ALLOWED_NAMES <= names

    def test_the_actual_public_body_carries_no_read_path_either(self):
        """The schema test is the guard; this is the proof it describes reality."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 2)

        body = self.client.get(self._public(event.id, collection["upload_token"])).json()

        assert _suspicious(_body_keys(body)) == set()
        # No value smells of S3 either — a presigned GET, a key or a filename
        # would all be a reading path smuggled through a differently named
        # field.
        rendered = str(body)
        for fragment in ("eventphotos/", "X-Amz-", ".jpg", BUCKET):
            assert fragment not in rendered

    def test_the_confirm_response_is_a_count_and_nothing_else(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 2, confirm=False)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[
                {"photo_id": u["photo_id"], "width": 100, "height": 80, "bytes": 4000}
                for u in uploads
            ],
        )

        assert response.status_code == 200
        assert response.json() == {"confirmed": 2}

    def test_the_page_answers_a_count_but_no_inventory(self):
        event = self._store_event()
        collection = self._create_collection(
            event,
            contact_name="Aline",
            intro_text="Alles vom Steg, bitte.",
        )
        self._upload(event, collection["upload_token"], 3)

        body = self.client.get(self._public(event.id, collection["upload_token"])).json()

        assert body["event_name"] == event.name
        assert body["event_date"] == event.start_at.date().isoformat()
        assert body["intro_text"] == "Alles vom Steg, bitte."
        assert body["contact_name"] == "Aline"
        assert body["contact_email"] == "fotos@example.com"
        assert body["upload_open"] is True
        assert body["retention_days"] == 90
        assert body["photo_count"] == 3
        assert body["max_files_per_batch"] == MAX_UPLOAD_BATCH
        assert body["url_ttl_seconds"] == URL_TTL_SECONDS
        # Pinned as a set: the aggregate total is the *only* thing this
        # response is allowed to say about content.
        assert set(body) == {
            "event_name",
            "event_date",
            "intro_text",
            "upload_open",
            "closes_at",
            "retention_days",
            "contact_name",
            "contact_email",
            "contact_telegram_url",
            "photo_count",
            "max_files_per_batch",
            "max_bytes",
            "url_ttl_seconds",
        }


# --- the public gate ---------------------------------------------------------


class TestPublicGate(ApiBase):
    def test_no_rejection_is_an_oracle(self):
        """Wrong token, unknown event, no collection and a rotated-away token
        must be indistinguishable — same status, same body. Anything else
        confirms which events collect photos."""
        live = self._store_event()
        live_collection = self._create_collection(live)

        bare = self._store_event()  # an event that never got a collection

        rotated = self._store_event()
        stale = self._create_collection(rotated)
        self.client.post(self._admin(rotated, "/rotate-token"))

        deleted = self._store_event()
        deleted_collection = self._create_collection(deleted)
        assert self.client.delete(self._admin(deleted)).status_code == 200

        rejections = {
            "wrong token": self._public(live.id, "x" * 43),
            "short token": self._public(live.id, "x"),
            "token prefix": self._public(live.id, live_collection["upload_token"][:-1]),
            "unknown event": self._public(uuid4(), live_collection["upload_token"]),
            "no collection": self._public(bare.id, live_collection["upload_token"]),
            "rotated away": self._public(rotated.id, stale["upload_token"]),
            "deleted": self._public(deleted.id, deleted_collection["upload_token"]),
        }

        answers = {
            label: (r.status_code, r.json())
            for label, path in rejections.items()
            for r in [self.client.get(path)]
        }
        assert answers == dict.fromkeys(rejections, (404, NOT_FOUND_BODY))
        # The page that should work still works, so the sweep above is not
        # passing by breaking everything.
        assert (
            self.client.get(
                self._public(live.id, live_collection["upload_token"]),
            ).status_code
            == 200
        )

    def test_a_non_ascii_token_is_a_flat_404_not_a_500(self):
        """`compare_digest` raises TypeError on non-ASCII, and a 500 next to a
        404 is exactly the oracle the flat rejection exists to prevent. Spec
        023 learned this the hard way; here the ASCII check comes first."""
        event = self._store_event()
        self._create_collection(event)

        client = TestClient(app, raise_server_exceptions=False)
        for suffix, call in (
            ("", lambda p: client.get(p)),
            ("/uploads", lambda p: client.post(p, json={"count": 1})),
            ("/confirm", lambda p: client.post(p, json=[])),
        ):
            response = call(self._public(event.id, "ö" * 43, suffix))
            assert (response.status_code, response.json()) == (404, NOT_FOUND_BODY), suffix

    def test_the_public_page_needs_no_token_header(self):
        event = self._store_event()
        collection = self._create_collection(event)
        app.dependency_overrides.clear()

        anonymous = TestClient(app)
        assert (
            anonymous.get(self._public(event.id, collection["upload_token"])).status_code == 200
        )

    def test_a_syntactically_invalid_event_id_is_a_validation_error(self):
        """Documented deviation, same as spec 023: the path param is typed
        `UUID`, so garbage in that segment never reaches the gate."""
        assert self.client.get("/api/public/photos/nicht-uuid/abc").status_code == 422


# --- public uploads ----------------------------------------------------------


class TestPublicUploads(ApiBase):
    def test_an_open_collection_mints_a_pair_of_presigned_posts_per_photo(self):
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": 3, "uploader_name": "Katja", "note": "vom Steg"},
        )

        assert response.status_code == 200
        uploads = response.json()["uploads"]
        assert len(uploads) == 3
        for upload in uploads:
            photo_id = UUID(upload["photo_id"])
            for variant, key in (
                ("full", full_key(event.id, photo_id)),
                ("thumb", thumb_key(event.id, photo_id)),
            ):
                assert upload[variant]["fields"]["key"] == key
                assert upload[variant]["fields"]["Content-Type"] == "image/jpeg"
                assert "policy" in upload[variant]["fields"]
                # The regional endpoint: the global one answers 307 for a
                # bucket outside us-east-1 and a browser will not replay a
                # cross-origin multipart POST across a redirect.
                assert "s3.eu-central-1.amazonaws.com" in upload[variant]["url"]

        # The uploader's own words land on every row of their batch.
        row = self._photo_item(event.id, uploads[0]["photo_id"])
        assert (row["uploader_name"], row["note"], row["state"]) == (
            "Katja",
            "vom Steg",
            "PENDING",
        )

    def test_the_switch_closes_the_write_path_but_not_the_page(self):
        event = self._store_event()
        collection = self._create_collection(event, upload_open=False)
        token = collection["upload_token"]

        minted = self.client.post(
            self._public(event.id, token, "/uploads"),
            json={"count": 1},
        )
        assert minted.status_code == 409
        assert minted.json()["detail"] == CLOSED_DETAIL

        # A guest holding a printed slip is told why, with the contact, rather
        # than shown a 404.
        page = self.client.get(self._public(event.id, token))
        assert page.status_code == 200
        assert page.json()["upload_open"] is False
        assert page.json()["contact_email"] == "fotos@example.com"

    def test_a_closes_at_in_the_past_closes_the_write_path(self):
        event = self._store_event()
        collection = self._create_collection(
            event,
            closes_at=(NOW - timedelta(hours=1)).isoformat(),
        )
        token = collection["upload_token"]

        minted = self.client.post(
            self._public(event.id, token, "/uploads"),
            json={"count": 1},
        )
        assert minted.status_code == 409
        assert minted.json()["detail"] == CLOSED_DETAIL

        page = self.client.get(self._public(event.id, token)).json()
        # The stored switch is still on; the *window* is what closed.
        assert page["upload_open"] is False
        assert self._config_item(event.id)["upload_open"] is True

    def test_a_full_collection_answers_instead_of_signing(self):
        event = self._store_event()
        collection = self._create_collection(event)
        self.events_table.update_item(
            Key={"pk": f"EVENT#{event.id}", "sk": EVENT_SK_PHOTO_CONFIG},
            UpdateExpression="SET photo_count = :n",
            ExpressionAttributeValues={":n": MAX_PHOTOS},
        )

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": 1},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Diese Sammlung ist voll — bitte melde dich bei der Orga."
        )

    def test_the_hourly_quota_answers_429(self):
        """After the token matched, so it is not an oracle — and the wording
        says „nochmal", because it is the one refusal that fixes itself."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._exhaust_the_hourly_quota(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": 1},
        )

        assert response.status_code == 429
        assert "zu viele" in response.json()["detail"]
        # Nothing was reserved on the way out.
        assert int(self._config_item(event.id)["photo_count"]) == 0

    def test_an_oversized_batch_is_a_400_with_readable_copy(self):
        """A 422 wall of pydantic JSON is unreadable on a phone, so the cap
        lives in the service and comes back as one German sentence."""
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": MAX_UPLOAD_BATCH + 1},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            f"Bitte lade höchstens {MAX_UPLOAD_BATCH} Fotos auf einmal hoch."
        )

    @pytest.mark.parametrize("count", [0, -1])
    def test_a_nonsensical_batch_size_never_reaches_the_service(self, count):
        event = self._store_event()
        collection = self._create_collection(event)
        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": count},
        )
        assert response.status_code == 422


# --- public confirm ----------------------------------------------------------


class TestPublicConfirm(ApiBase):
    def test_confirming_flips_only_this_events_rows(self):
        mine = self._store_event()
        theirs = self._store_event()
        mine_collection = self._create_collection(mine)
        theirs_collection = self._create_collection(theirs)

        ours = self._upload(mine, mine_collection["upload_token"], 2, confirm=False)
        foreign = self._upload(
            theirs,
            theirs_collection["upload_token"],
            1,
            confirm=False,
        )[0]

        response = self.client.post(
            self._public(mine.id, mine_collection["upload_token"], "/confirm"),
            json=[
                {"photo_id": u["photo_id"], "width": 2560, "height": 1440, "bytes": 800_000}
                for u in ours
            ]
            + [
                # Addressed under EVENT#{mine}, so this row simply is not there.
                {"photo_id": foreign["photo_id"], "width": 8, "height": 8, "bytes": 8},
            ],
        )

        assert response.status_code == 200
        # The count is the whole answer: nothing about *which* entry failed.
        assert response.json() == {"confirmed": 2}
        assert [self._photo_item(mine.id, u["photo_id"])["state"] for u in ours] == [
            "READY",
            "READY",
        ]
        assert self._photo_item(theirs.id, foreign["photo_id"])["state"] == "PENDING"

    def test_a_batch_that_confirmed_nothing_is_a_404(self):
        """Per the service's contract: unknown ids are skipped, and only a
        batch in which nothing flipped is an error."""
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[{"photo_id": str(uuid4()), "width": 8, "height": 8, "bytes": 8}],
        )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Diese Fotos sind nicht angekommen — bitte lade sie noch einmal hoch."
        )

    def test_an_empty_batch_is_a_no_op_not_a_404(self):
        """What a browser sends when every file in the stapel turned out to be
        undecodable (HEIC on Chrome)."""
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[],
        )

        assert (response.status_code, response.json()) == (200, {"confirmed": 0})

    def test_confirm_is_not_window_gated(self):
        """The batch was authorised when it was minted. A collection that
        closed mid-upload would otherwise leave forty rows PENDING with real
        objects behind them, swept away without anybody being told."""
        event = self._store_event()
        collection = self._create_collection(event)
        token = collection["upload_token"]
        uploads = self._upload(event, token, 1, confirm=False)

        self.client.put(self._admin(event, "/config"), json={"upload_open": False})

        response = self.client.post(
            self._public(event.id, token, "/confirm"),
            json=[
                {
                    "photo_id": uploads[0]["photo_id"],
                    "width": 100,
                    "height": 100,
                    "bytes": 500,
                },
            ],
        )

        assert (response.status_code, response.json()) == (200, {"confirmed": 1})

    def test_confirm_cannot_escalate(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1, confirm=False)[0]

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[
                {
                    "photo_id": upload["photo_id"],
                    "width": 10,
                    "height": 10,
                    "bytes": 10,
                    "starred": True,
                },
            ],
        )

        assert response.status_code == 422
        assert self._photo_item(event.id, upload["photo_id"])["starred"] is False

    def test_an_oversized_confirm_array_is_refused_by_the_body_cap(self):
        """An unauthenticated caller must not be able to make us parse a
        four-megabyte array for free."""
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[
                {"photo_id": str(uuid4()), "width": 8, "height": 8, "bytes": 8}
                for _ in range(MAX_UPLOAD_BATCH + 1)
            ],
        )

        assert response.status_code == 422


# --- the uploader's address --------------------------------------------------


class TestUploaderIpHash(ApiBase):
    """`HMAC-SHA256(pepper, ip)`, 16 hex chars, for exactly one question: are
    these 400 photos from 30 people or from one?"""

    def test_the_address_is_stored_as_a_hash(self):
        event = self._store_event()
        collection = self._create_collection(event)

        upload = self._upload(event, collection["upload_token"], 1)[0]

        stored = self._photo_item(event.id, upload["photo_id"])["uploader_ip_hash"]
        assert len(stored) == 16
        assert all(c in "0123456789abcdef" for c in stored)
        # Not the address, in any obvious rendering of it. (That the hash is
        # stable for one address and differs for another is pinned directly on
        # `hash_uploader_ip` in test_event_photos.py — here the point is that
        # the route stores a digest at all.)
        assert "testclient" not in stored

        # And the organiser can actually see it, because a field nobody can
        # read is stored personal data with no purpose (spec 024 §Missbrauch).
        photos = self.client.get(self._admin(event)).json()["photos"]
        assert {p["uploader_ip_hash"] for p in photos} == {stored}

    def test_a_forwarded_header_cannot_choose_the_hash(self):
        """Regression, and the whole point of this field.

        `X-Forwarded-For` is written by every hop *in front* of us — CloudFront
        appends the viewer's address to whatever the client sent, then API
        Gateway appends again. So its first entry is attacker-controlled, and
        reading it would let one header per request make 400 photos from one
        person look like 400 people: the single question `uploader_ip_hash`
        exists to answer, answered wrongly by whoever wants it answered
        wrongly. The address is taken from the request scope instead, which
        Mangum fills from `requestContext.http.sourceIp`.
        """
        event = self._store_event()
        collection = self._create_collection(event)
        token = collection["upload_token"]

        plain = self._upload(event, token, 1)[0]
        forged = self._upload(
            event,
            token,
            1,
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
        )[0]
        differently_forged = self._upload(
            event,
            token,
            1,
            headers={"X-Forwarded-For": "198.51.100.4"},
        )[0]

        digests = {
            self._photo_item(event.id, u["photo_id"])["uploader_ip_hash"]
            for u in (plain, forged, differently_forged)
        }
        # All three came from the same client, and the header did not change
        # that — one digest, not three.
        assert len(digests) == 1


class TestWithoutTheIpPepper(ApiBase):
    """For a privacy field the safe default is storing nothing, not
    „unpeppered if need be" — a bare hash over the IPv4 space is reversible in
    seconds."""

    pepper = None

    def test_no_pepper_means_no_hash_at_all(self):
        event = self._store_event()
        collection = self._create_collection(event)

        upload = self._upload(
            event,
            collection["upload_token"],
            1,
            headers={"X-Forwarded-For": "203.0.113.7"},
        )[0]

        assert "uploader_ip_hash" not in self._photo_item(event.id, upload["photo_id"])
        photo = self.client.get(self._admin(event)).json()["photos"][0]
        assert photo["uploader_ip_hash"] is None


# --- admin authorisation -----------------------------------------------------


class TestAdminAuthorisation(ApiBase):
    def _every_route(self, event: Event, photo_id: str) -> list:
        """One call per admin route, in the order of spec 024 §Endpunkte."""
        return [
            self.client.get(self._admin(event, "/config")),
            self.client.put(
                self._admin(event, "/config"),
                json={"contact_email": "fremd@example.com"},
            ),
            self.client.post(self._admin(event, "/rotate-token")),
            self.client.get(self._admin(event)),
            self.client.patch(self._admin(event, f"/{photo_id}"), json={"starred": True}),
            self.client.delete(self._admin(event, f"/{photo_id}")),
            self.client.post(
                self._admin(event, "/bulk-delete"),
                json={"photo_ids": [photo_id]},
            ),
            self.client.post(self._admin(event, f"/{photo_id}/edit-uploads")),
            self.client.post(
                self._admin(event, f"/{photo_id}/edit-confirm"),
                json={"width": 10, "height": 10, "bytes": 100},
            ),
            self.client.get(self._admin(event, "/download-manifest")),
            self.client.delete(self._admin(event)),
        ]

    def test_without_a_token_nothing_is_reachable(self):
        event = self._store_event()
        app.dependency_overrides.clear()
        assert TestClient(app).get(self._admin(event, "/config")).status_code == 401

    def test_a_viewer_may_read_the_config_and_the_grid(self):
        event = self._store_event()
        self._create_collection(event)
        self._upload(event, self._config_item(event.id)["upload_token"], 1)

        self.role = AdminRole.VIEWER
        assert self.client.get(self._admin(event, "/config")).status_code == 200
        assert self.client.get(self._admin(event)).status_code == 200

    def test_a_viewer_may_not_write_and_may_not_take_the_collection_away(self):
        event = self._store_event()
        collection = self._create_collection(event)
        photo_id = self._upload(event, collection["upload_token"], 1)[0]["photo_id"]

        self.role = AdminRole.VIEWER
        answers = self._every_route(event, photo_id)
        statuses = [r.status_code for r in answers]

        # GET config and GET photos are the viewer's two reads; everything
        # else is a 403 — including the download manifest, which hands the
        # whole collection out as files and is the one action on this page
        # that takes the photos out of our reach.
        assert statuses == [200, 403, 403, 200, 403, 403, 403, 403, 403, 403, 403]
        # Nothing changed behind the refusals.
        assert self._config_item(event.id)["upload_token"] == collection["upload_token"]
        assert self._photo_item(event.id, photo_id) is not None

    @pytest.mark.parametrize("role", [AdminRole.OWNER, AdminRole.ADMIN])
    def test_owners_and_admins_may_write(self, role):
        event = self._store_event()
        self.role = role
        response = self.client.put(
            self._admin(event, "/config"),
            json={"contact_email": "fotos@example.com"},
        )
        assert response.status_code == 200

    def test_another_organisation_finds_nothing(self):
        """`get_event` reads `pk=ORG#{org_id}`, so a foreign event ID never
        resolves — one lookup carries the whole authorisation story."""
        event = self._store_event()
        collection = self._create_collection(event)
        photo_id = self._upload(event, collection["upload_token"], 1)[0]["photo_id"]

        self.org_id = uuid4()  # another org's admin, same event id
        answers = self._every_route(event, photo_id)

        assert [r.status_code for r in answers] == [404] * 11
        assert {r.json()["detail"] for r in answers} == {"Event nicht gefunden"}
        assert self._config_item(event.id)["upload_token"] == collection["upload_token"]
        assert self._photo_item(event.id, photo_id) is not None
        assert self.s3.head_object(
            Bucket=BUCKET,
            Key=full_key(event.id, UUID(photo_id)),
        )["ContentLength"] == len(b"jpeg-bytes")


# --- admin configuration -----------------------------------------------------


class TestAdminConfig(ApiBase):
    def test_an_event_without_a_collection_is_a_404_not_an_empty_form(self):
        """Deliberately unlike spec 023's `configured: false`: there is no
        token, no link and no contact to report yet, and a second response
        shape would be a second branch for the client."""
        event = self._store_event()
        response = self.client.get(self._admin(event, "/config"))

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Für dieses Event gibt es noch keine Fotosammlung."
        )

    def test_the_grid_404s_off_the_same_missing_collection(self):
        event = self._store_event()
        assert self.client.get(self._admin(event)).status_code == 404

    def test_an_unknown_event_is_not_found(self):
        assert (
            self.client.get(f"/api/admin/events/{uuid4()}/photos/config").status_code == 404
        )

    def test_the_first_save_creates_the_collection_and_the_link(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event, "/config"),
            json={
                "contact_email": "fotos@example.com",
                "contact_name": "Aline",
                "intro_text": "Alles vom Steg, bitte.",
                "retention_days": None,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["upload_token"]) == 43
        # The already-assembled string the QR code encodes — the frontend never
        # builds it a second time, so the two cannot drift apart.
        assert body["public_url"] == f"{BASE_URL}/fotos/{event.id}/{body['upload_token']}"
        assert body["upload_open"] is True
        assert body["window_open"] is True
        # Default automatic close: 21 days from the later of event end and now,
        # so a collection created late is never born closed.
        assert date.fromisoformat(body["closes_at"][:10]) == (
            datetime.now(timezone.utc) + timedelta(days=21)
        ).date()
        assert body["retention_days"] == 90
        assert body["photo_count"] == 0
        assert body["limits"]["max_photos"] == MAX_PHOTOS
        assert body["limits"]["default_retention_days"] == 90
        assert body["limits"]["manifest_ttl_seconds"] == MANIFEST_TTL_SECONDS

    def test_the_first_save_needs_a_way_to_reach_a_human(self):
        """On a page where people hand in photos *of other people*, it has to
        say who to ask to get one removed again."""
        event = self._store_event()
        response = self.client.put(self._admin(event, "/config"), json={"upload_open": True})

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Bitte gib an, an wen sich Gäste wenden können — eine E-Mail-Adresse oder "
            "einen Telegram-Link. Ohne Kontakt darf diese Seite nicht online gehen."
        )
        # No config row means no token, so a half-finished collection was never
        # reachable at all.
        assert self._config_item(event.id) is None

    def test_the_last_contact_cannot_be_cleared(self):
        event = self._store_event()
        self._create_collection(event)

        response = self.client.put(self._admin(event, "/config"), json={"contact_email": None})

        assert response.status_code == 400
        assert self._config_item(event.id)["contact_email"] == "fotos@example.com"

    def test_a_telegram_link_alone_is_enough(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event, "/config"),
            json={"contact_telegram_url": "t.me/fotos"},
        )

        assert response.status_code == 200
        assert response.json()["contact_email"] is None
        assert response.json()["contact_telegram_url"] == "https://t.me/fotos"

    @pytest.mark.parametrize(
        "value",
        ["javascript:alert(1)", "https://evil.example.com/t.me/fotos", "https://t.me/"],
    )
    def test_a_non_telegram_link_dies_at_the_edge(self, value):
        """The value becomes an `href` on a public page."""
        event = self._store_event()
        response = self.client.put(
            self._admin(event, "/config"),
            json={"contact_email": "fotos@example.com", "contact_telegram_url": value},
        )
        assert response.status_code == 422
        assert self._config_item(event.id) is None

    def test_an_unknown_field_is_refused(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event, "/config"),
            json={"contact_email": "fotos@example.com", "upload_offen": True},
        )
        assert response.status_code == 422

    def test_the_retention_override_is_echoed_and_can_be_cleared(self):
        event = self._store_event()
        self._create_collection(event)

        overridden = self.client.put(self._admin(event, "/config"), json={"retention_days": 14})
        assert overridden.json()["retention_days"] == 14

        cleared = self.client.put(self._admin(event, "/config"), json={"retention_days": None})
        assert cleared.json()["retention_days"] == 90

    def test_the_retention_override_has_bounds_and_they_are_the_spec_ones(self):
        """7 and 365 were only ever exercised as accepted values, so nothing
        rejected `6` or `366`. The bounds are what keeps the collection an
        Umschlagstelle: below a week it shuts before the guests get to their
        camera roll, above a year it is an archive of other people's faces."""
        event = self._store_event()
        self._create_collection(event)

        assert (RETENTION_DAYS_MIN, RETENTION_DAYS_MAX) == (7, 365)

        for refused in (RETENTION_DAYS_MIN - 1, RETENTION_DAYS_MAX + 1, 0, -1):
            response = self.client.put(
                self._admin(event, "/config"),
                json={"retention_days": refused},
            )
            assert response.status_code == 422, refused

        for accepted in (RETENTION_DAYS_MIN, RETENTION_DAYS_MAX):
            response = self.client.put(
                self._admin(event, "/config"),
                json={"retention_days": accepted},
            )
            assert response.status_code == 200
            assert response.json()["retention_days"] == accepted

    def test_closes_at_never_leaves_without_a_timezone(self):
        """`closes_at` is the only timestamp in either response that a client
        supplied, and `<input type="datetime-local">` posts it naive. Handed
        back naive, a browser reads it as *local* time: the header states a
        close two hours off in CEST, and re-saving the form shifts the stored
        instant by that offset every round trip. Every sibling timestamp is
        offset-aware, so a naive one is also unreadable — the client cannot
        tell which zone it is in."""
        event = self._store_event()
        naive = (NOW + timedelta(days=5)).replace(tzinfo=None, microsecond=0)

        created = self._create_collection(event, closes_at=naive.isoformat())
        page = self.client.get(self._public(event.id, created["upload_token"])).json()

        for label, value in (
            ("admin", created["closes_at"]),
            ("public", page["closes_at"]),
            # The siblings, so the assertion is about a shared property and not
            # about one field somebody remembered.
            ("expires_at", created["expires_at"]),
            ("created_at", created["created_at"]),
        ):
            parsed = datetime.fromisoformat(value)
            assert parsed.tzinfo is not None, f"{label} came back naive: {value}"
        # The instant is the one the service already assumed for it — UTC, not
        # shifted by anybody's offset.
        assert datetime.fromisoformat(created["closes_at"]) == naive.replace(
            tzinfo=timezone.utc,
        )

    def test_rotating_the_token_devalues_every_printed_slip(self):
        event = self._store_event()
        created = self._create_collection(event)

        rotated = self.client.post(self._admin(event, "/rotate-token"))
        assert rotated.status_code == 200
        body = rotated.json()
        assert body["upload_token"] != created["upload_token"]
        assert body["public_url"].endswith(body["upload_token"])
        assert body["public_url"] != created["public_url"]

        assert self.client.get(self._public(event.id, created["upload_token"])).status_code == 404
        assert self.client.get(self._public(event.id, body["upload_token"])).status_code == 200

    def test_rotating_without_a_collection(self):
        event = self._store_event()
        response = self.client.post(self._admin(event, "/rotate-token"))
        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Für dieses Event gibt es noch keine Fotosammlung."
        )


# --- route order -------------------------------------------------------------


class TestRouteOrder(ApiBase):
    """FastAPI matches in declaration order, so `/photos/{photo_id}` declared
    above `/photos/config` would hand „config" to the parameterised route and
    answer a 422 nobody could explain. These tests pin the order rather than
    the comment that asks for it."""

    def test_a_literal_segment_is_never_parsed_as_a_photo_id(self):
        event = self._store_event()
        collection = self._create_collection(event)
        photo_id = self._upload(event, collection["upload_token"], 1)[0]["photo_id"]

        config = self.client.get(self._admin(event, "/config"))
        assert config.status_code == 200
        assert config.json()["upload_token"] == collection["upload_token"]

        bulk = self.client.post(self._admin(event, "/bulk-delete"), json={"photo_ids": []})
        # A 422 here is the *body* cap (min_length=1), not a failed UUID parse —
        # so it names photo_ids, not a path parameter.
        assert bulk.status_code == 422
        assert "photo_ids" in str(bulk.json())

        manifest = self.client.get(self._admin(event, "/download-manifest"))
        assert manifest.status_code == 200
        assert manifest.headers["content-type"].startswith("text/plain")

        deleted = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [photo_id]},
        )
        assert deleted.status_code == 200

    def test_a_real_photo_id_segment_is_still_parsed_as_a_uuid(self):
        """The contrast that makes the test above meaningful: garbage in the
        `{photo_id}` slot *is* a 422, so a 422 on „config" would have been the
        same failure."""
        event = self._store_event()
        self._create_collection(event)
        assert self.client.patch(
            self._admin(event, "/nicht-uuid"),
            json={"starred": True},
        ).status_code == 422


# --- the admin grid ----------------------------------------------------------


class TestAdminGrid(ApiBase):
    def _urls(self, event: Event) -> list[dict]:
        return self.client.get(self._admin(event)).json()["photos"]

    def test_the_view_urls_override_the_response_headers(self):
        """Whatever an uploader managed to store under an image key, the
        browser is told `image/jpeg` and `inline` — which, together with S3
        being a different origin from the app, is what makes „HTML under a
        .jpg" a dead end rather than a scripting hole."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 1)

        photo = self._urls(event)[0]
        for url in (photo["thumb_url"], photo["full_url"]):
            assert "X-Amz-Signature" in url
            # The raw percent-encoded form, as it goes over the wire.
            assert "response-content-type=image%2Fjpeg" in url
            query = parse_qs(urlparse(url).query)
            assert query["response-content-type"] == ["image/jpeg"]
            assert query["response-content-disposition"] == ["inline"]
            assert query["X-Amz-Expires"] == [str(URL_TTL_SECONDS)]

    def test_the_download_url_is_an_attachment_and_needs_no_cors(self):
        """Spec 024 §Adminansicht: „Herunterladen" (presigned GET mit
        `attachment`). The grid used to ship only the `inline` URL and the page
        fetched it into a Blob — which silently stops downloading anything the
        moment the bucket's CORS rule and the frontend's origin drift apart (a
        new domain, a preview host, prod deployed before the domain switch).
        `Content-Disposition: attachment` is honoured on a plain cross-origin
        `<a href>` with no CORS involved at all, which is why the spec picked
        it."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 1)

        photo = self._urls(event)[0]
        url = photo["download_url"]
        assert url and url != photo["full_url"]

        query = parse_qs(urlparse(url).query)
        assert query["response-content-type"] == ["image/jpeg"]
        assert query["response-content-disposition"] == [
            f'attachment; filename="foto-{photo["photo_id"][:8]}.jpg"',
        ]
        # Same clock as the other two, so the page's refresh-before-expiry
        # covers all three.
        assert query["X-Amz-Expires"] == [str(URL_TTL_SECONDS)]

    def test_the_grid_reports_dimensions_and_the_sort_timestamp(self):
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 1)

        body = self.client.get(self._admin(event)).json()
        assert body["total"] == 1
        assert body["pending_count"] == 0
        assert body["url_ttl_seconds"] == URL_TTL_SECONDS

        photo = body["photos"][0]
        assert (photo["width"], photo["height"], photo["bytes"]) == (2560, 1920, 900_000)
        assert photo["state"] == "READY"
        # `taken_at` is computed server-side so the plausibility rule lives in
        # one place; with no hint it falls back to `uploaded_at`.
        assert photo["taken_at"] == photo["uploaded_at"]

    def test_pending_rows_are_a_count_not_broken_tiles(self):
        """Deliberately unlike spec 023's grid: here the uploader is a guest on
        a phone we will never hear from again, so a PENDING row is a tile the
        organiser can do nothing about. The 24 h sweep cleans it up."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 2, confirm=False)

        body = self.client.get(self._admin(event)).json()
        assert body["photos"] == []
        assert (body["total"], body["pending_count"]) == (0, 2)

    def test_the_filters_are_the_three_views_of_the_page(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 3)

        starred = uploads[0]["photo_id"]
        edited = uploads[1]["photo_id"]
        assert self.client.patch(
            self._admin(event, f"/{starred}"),
            json={"starred": True},
        ).status_code == 200
        assert self.client.post(
            self._admin(event, f"/{edited}/edit-confirm"),
            json={"width": 2560, "height": 1920, "bytes": 700_000},
        ).status_code == 200

        def ids(query: str) -> list[str]:
            body = self.client.get(self._admin(event, query)).json()
            return [p["photo_id"] for p in body["photos"]]

        assert len(ids("")) == 3
        assert ids("?filter=starred") == [starred]
        # `unedited` is the narrow question — where was pixelation applied — so
        # the edited photo drops out of it.
        assert edited not in ids("?filter=unedited")
        assert len(ids("?filter=unedited")) == 2

        # `unchecked` is the working list for going through faces, and it is a
        # different list: pixelating implies a look, so `edited` is gone from
        # here too, but so is anything ticked off without a change.
        assert edited not in ids("?filter=unchecked")
        assert self.client.patch(
            self._admin(event, f"/{starred}"),
            json={"faces_checked": True},
        ).status_code == 200
        assert ids("?filter=unchecked") == [uploads[2]["photo_id"]]

    def test_an_unknown_filter_is_refused(self):
        event = self._store_event()
        self._create_collection(event)
        assert self.client.get(self._admin(event, "?filter=alle")).status_code == 422

    def test_offset_and_limit_page_the_response(self):
        """Paging is about the *response*, not the read: 500 photos would be a
        thousand presigned GETs to mint and ship."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 5)

        first = self.client.get(self._admin(event, "?limit=2")).json()
        assert len(first["photos"]) == 2
        assert (first["total"], first["offset"], first["limit"]) == (5, 0, 2)

        last = self.client.get(self._admin(event, "?offset=4&limit=2")).json()
        assert len(last["photos"]) == 1
        assert last["total"] == 5

        # The pages are disjoint and in the same chronological order.
        middle = self.client.get(self._admin(event, "?offset=2&limit=2")).json()
        paged = (
            [p["photo_id"] for p in first["photos"]]
            + [p["photo_id"] for p in middle["photos"]]
            + [p["photo_id"] for p in last["photos"]]
        )
        everything = [
            p["photo_id"] for p in self.client.get(self._admin(event)).json()["photos"]
        ]
        assert paged == everything

    def test_batches_come_back_oldest_first(self):
        """The grid is chronological, and the day headings depend on it.

        Asserted down to the individual photo, across batches *and within* one:
        `create_upload_batch` stamps its rows a microsecond apart in mint order,
        so `_sort_key`'s `uploaded_at` tie-breaker resolves a batch whose files
        carry no usable `captured_at_hint` into the order the guest picked them
        in. Sharing one timestamp across the batch would make that tie-breaker a
        no-op and leave the order to the random UUID in the DynamoDB sort key —
        stable across reloads, but arbitrary, and arbitrary in exactly the case
        the tie-breaker exists for (forwarded files with no capture time).
        """
        event = self._store_event()
        token = self._create_collection(event)["upload_token"]
        first = [u["photo_id"] for u in self._upload(event, token, 2)]
        second = [u["photo_id"] for u in self._upload(event, token, 2)]

        grid = [p["photo_id"] for p in self.client.get(self._admin(event)).json()["photos"]]

        assert grid == first + second
        # And the same request twice gives the same order — a grid that
        # reshuffled on reload would make the day headings jump around.
        assert grid == [
            p["photo_id"] for p in self.client.get(self._admin(event)).json()["photos"]
        ]

    @pytest.mark.parametrize("query", ["?offset=-1", "?limit=0", "?limit=501"])
    def test_nonsensical_paging_is_refused(self, query):
        event = self._store_event()
        self._create_collection(event)
        assert self.client.get(self._admin(event, query)).status_code == 422

    def test_the_note_can_be_edited_and_cleared_without_touching_the_star(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(
            event,
            collection["upload_token"],
            1,
            note="das ist Katja mit dem Hund",
        )[0]
        path = self._admin(event, f"/{upload['photo_id']}")

        starred = self.client.patch(path, json={"starred": True}).json()
        assert starred["starred"] is True
        # A star toggle must not wipe the guest's words.
        assert starred["note"] == "das ist Katja mit dem Hund"

        cleared = self.client.patch(path, json={"note": ""}).json()
        assert cleared["note"] is None
        assert cleared["starred"] is True

    def test_the_face_check_is_patchable_and_reported(self):
        """The grid needs „schon angesehen" as its own bit: most photos need no
        pixelation, so `edited_at` cannot tell „geprüft, nichts zu tun" from
        „noch nicht angesehen"."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]
        path = self._admin(event, f"/{upload['photo_id']}")

        assert self.client.get(self._admin(event)).json()["photos"][0]["faces_checked"] is False

        checked = self.client.patch(path, json={"faces_checked": True}).json()
        assert checked["faces_checked"] is True
        assert checked["edited_at"] is None

        # And it goes back off — a second pair of eyes may disagree.
        unchecked = self.client.patch(path, json={"faces_checked": False}).json()
        assert unchecked["faces_checked"] is False

    def test_pixelating_ticks_the_check_off(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        body = self.client.post(
            self._admin(event, f"/{upload['photo_id']}/edit-confirm"),
            json={"width": 2560, "height": 1920, "bytes": 700_000},
        ).json()

        assert body["edited_at"] is not None
        assert body["faces_checked"] is True

    def test_confirm_cannot_tick_the_check_itself(self):
        """An anonymous uploader must not be able to mark their own photo as
        reviewed — that would empty the organisers' working list from outside."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1, confirm=False)[0]

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/confirm"),
            json=[
                {
                    "photo_id": upload["photo_id"],
                    "width": 2560,
                    "height": 1920,
                    "bytes": 900_000,
                    "faces_checked": True,
                },
            ],
        )
        assert response.status_code == 422

    def test_an_overlong_note_is_refused(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]
        assert self.client.patch(
            self._admin(event, f"/{upload['photo_id']}"),
            json={"note": "x" * 301},
        ).status_code == 422

    def test_the_patch_body_admits_nothing_but_the_star_and_the_note(self):
        """`extra="forbid"`, so an added field is a 422 rather than a silent
        write — the same guard the public confirm has, one role up."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        for body in ({"state": "PENDING"}, {"starred": True, "edited_at": None}):
            response = self.client.patch(
                self._admin(event, f"/{upload['photo_id']}"),
                json=body,
            )
            assert response.status_code == 422, body
        assert self._photo_item(event.id, upload["photo_id"])["state"] == "READY"

    def test_an_empty_patch_leaves_the_row_alone(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1, note="am Steg")[0]

        response = self.client.patch(self._admin(event, f"/{upload['photo_id']}"), json={})

        assert response.status_code == 200
        assert (response.json()["starred"], response.json()["note"]) == (False, "am Steg")

        # And it answers with freshly signed URLs. The pixelate editor depends on
        # exactly this: a presigned GET lives 15 minutes, the grid is regularly
        # open for longer, and an empty PATCH is how the editor mints a new
        # signature and retries instead of telling somebody to reload the page.
        # If this ever stops carrying URLs, that retry silently stops working.
        body = response.json()
        assert body["full_url"] and "X-Amz-Signature" in body["full_url"]
        assert body["thumb_url"] and "X-Amz-Signature" in body["thumb_url"]

    def test_patching_an_unknown_or_foreign_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_collection(mine)
        foreign = self._upload(
            theirs,
            self._create_collection(theirs)["upload_token"],
            1,
        )[0]

        for photo_id in (str(uuid4()), foreign["photo_id"]):
            response = self.client.patch(
                self._admin(mine, f"/{photo_id}"),
                json={"starred": True},
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Dieses Foto gibt es nicht (mehr)."
        assert self._photo_item(theirs.id, foreign["photo_id"])["starred"] is False


# --- Unkenntlich machen ------------------------------------------------------


class TestPixelateHandshake(ApiBase):
    def test_edit_uploads_point_at_the_photos_existing_keys(self):
        """Same keys, unversioned bucket — which is what makes this final. A
        kept original is precisely the image that is supposed to stop existing."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._stale_upload(event, collection["upload_token"])
        photo_id = UUID(upload["photo_id"])

        response = self.client.post(self._admin(event, f"/{photo_id}/edit-uploads"))

        assert response.status_code == 200
        body = response.json()
        assert body["photo_id"] == upload["photo_id"]
        assert body["full"]["fields"]["key"] == full_key(event.id, photo_id)
        assert body["thumb"]["fields"]["key"] == thumb_key(event.id, photo_id)
        # Both variants, because a thumbnail with an un-pixelated face would
        # make the whole exercise pointless.
        assert body["full"]["fields"]["Content-Type"] == "image/jpeg"
        assert body["thumb"]["fields"]["Content-Type"] == "image/jpeg"

    def test_editing_is_refused_while_the_uploaders_signature_lives(self):
        """409, not a silent overwrite: the guest's presigned POST is valid for
        fifteen minutes on exactly these keys and a presigned POST is not
        single-use, so pixelating inside that window can be undone by re-sending
        the form the guest's browser still holds — while `edited_at` keeps
        claiming the face is gone."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        response = self.client.post(self._admin(event, f"/{upload['photo_id']}/edit-uploads"))

        assert response.status_code == 409
        assert "Viertelstunde" in response.json()["detail"]

        # Once the window has passed, the same call works.
        self._age_photo(event, upload["photo_id"], timedelta(seconds=URL_TTL_SECONDS + 1))
        assert (
            self.client.post(
                self._admin(event, f"/{upload['photo_id']}/edit-uploads"),
            ).status_code
            == 200
        )

    def test_edit_uploads_for_an_unknown_or_foreign_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_collection(mine)
        foreign = self._upload(
            theirs,
            self._create_collection(theirs)["upload_token"],
            1,
        )[0]

        for photo_id in (str(uuid4()), foreign["photo_id"]):
            response = self.client.post(self._admin(mine, f"/{photo_id}/edit-uploads"))
            assert response.status_code == 404
            assert response.json()["detail"] == "Dieses Foto gibt es nicht (mehr)."

    def test_edit_confirm_stamps_edited_at_and_the_new_dimensions(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        response = self.client.post(
            self._admin(event, f"/{upload['photo_id']}/edit-confirm"),
            json={"width": 1280, "height": 960, "bytes": 300_000},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["edited_at"] is not None
        assert (body["width"], body["height"], body["bytes"]) == (1280, 960, 300_000)
        assert body["photo_id"] == upload["photo_id"]

        # And it stuck, so the grid marks the tile and the `unedited` filter
        # drops it.
        grid = self.client.get(self._admin(event)).json()["photos"][0]
        assert grid["edited_at"] == body["edited_at"]

    def test_a_replayed_public_confirm_cannot_undo_the_edit(self):
        """`edited_at` is also what stops a stale tab from writing the pre-edit
        dimensions back over a photo that has since been pixelated."""
        event = self._store_event()
        collection = self._create_collection(event)
        token = collection["upload_token"]
        upload = self._upload(event, token, 1)[0]

        self.client.post(
            self._admin(event, f"/{upload['photo_id']}/edit-confirm"),
            json={"width": 1280, "height": 960, "bytes": 300_000},
        )

        replay = self.client.post(
            self._public(event.id, token, "/confirm"),
            json=[
                {
                    "photo_id": upload["photo_id"],
                    "width": 2560,
                    "height": 1920,
                    "bytes": 900_000,
                },
            ],
        )

        # Nothing flipped, so it is the „not arrived" 404 — and the row kept
        # the pixelated dimensions.
        assert replay.status_code == 404
        row = self._photo_item(event.id, upload["photo_id"])
        assert int(row["width"]) == 1280

    def test_edit_confirm_for_an_unknown_photo(self):
        event = self._store_event()
        self._create_collection(event)
        assert self.client.post(
            self._admin(event, f"/{uuid4()}/edit-confirm"),
            json={"width": 10, "height": 10, "bytes": 10},
        ).status_code == 404


# --- the download manifest ---------------------------------------------------


class TestDownloadManifest(ApiBase):
    def _lines(self, response) -> tuple[list[str], list[str]]:
        body = response.text.splitlines()
        return (
            [line for line in body if line.startswith("#")],
            [line for line in body if line and not line.startswith("#")],
        )

    def test_one_line_per_photo_plus_the_header_the_organiser_needs(self):
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 3)
        # A PENDING row has no object behind it yet, so it is not a download.
        self._upload(event, collection["upload_token"], 1, confirm=False)

        response = self.client.get(self._admin(event, "/download-manifest"))

        assert response.status_code == 200
        comments, urls = self._lines(response)
        assert len(urls) == 3
        assert comments[0] == f"# 3 Fotos — {event.name}"
        # The expiry note, because the list is free to regenerate and a
        # presigned URL cannot outlive the Lambda's credentials.
        assert "gültig bis" in comments[1]
        assert "neu herunterladen" in comments[2]
        # The one-liner filters the comment lines: bare `xargs` would hand „#"
        # to curl as a URL, once per comment line.
        assert comments[3] == (
            "# grep -v '^#' fotos-sommerfahrt-mueggelsee.txt | xargs -n1 -P4 curl -sOJ"
        )

    def test_the_response_is_an_attachment_with_a_transliterated_filename(self):
        """Content-Disposition's plain form is quoted ASCII, so „Müggelsee"
        loses its umlaut here rather than in the browser's guess."""
        event = self._store_event()
        self._create_collection(event)

        response = self.client.get(self._admin(event, "/download-manifest"))

        assert response.headers["content-disposition"] == (
            'attachment; filename="fotos-sommerfahrt-mueggelsee.txt"'
        )
        assert response.headers["content-type"].startswith("text/plain")

    def test_every_url_is_a_signed_attachment_download_of_the_full_variant(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 2)

        _comments, urls = self._lines(
            self.client.get(self._admin(event, "/download-manifest")),
        )

        signed_keys = set()
        for index, url in enumerate(urls, start=1):
            query = parse_qs(urlparse(url).query)
            assert "X-Amz-Signature" in query
            # An hour, and no longer: a presigned URL does not outlive the
            # temporary credentials it was signed with.
            assert query["X-Amz-Expires"] == [str(MANIFEST_TTL_SECONDS)]
            disposition = query["response-content-disposition"][0]
            # `curl -J` takes the filename from here; without it all 300 photos
            # would be saved as `full.jpg`.
            assert disposition.startswith("attachment; filename=")
            assert f"{index:04d}_" in disposition
            signed_keys.add(urlparse(url).path)

        assert len(signed_keys) == 2
        for upload in uploads:
            key = full_key(event.id, UUID(upload["photo_id"]))
            assert any(path.endswith(key) for path in signed_keys)

    def test_filter_starred_narrows_the_list(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 3)
        self.client.patch(self._admin(event, f"/{uploads[1]['photo_id']}"), json={"starred": True})

        response = self.client.get(self._admin(event, "/download-manifest?filter=starred"))
        comments, urls = self._lines(response)

        assert len(urls) == 1
        assert comments[0] == f"# 1 Fotos — {event.name}"
        assert full_key(event.id, UUID(uploads[1]["photo_id"])) in urls[0]

    def test_the_manifest_of_an_empty_collection_is_just_its_header(self):
        event = self._store_event()
        self._create_collection(event)
        comments, urls = self._lines(self.client.get(self._admin(event, "/download-manifest")))
        assert (len(comments), urls) == (4, [])

    def test_an_unknown_filter_is_refused(self):
        event = self._store_event()
        self._create_collection(event)
        assert self.client.get(
            self._admin(event, "/download-manifest?filter=unedited"),
        ).status_code == 422

    def test_no_collection_no_manifest(self):
        event = self._store_event()
        assert self.client.get(self._admin(event, "/download-manifest")).status_code == 404


# --- deletion ----------------------------------------------------------------


class _RefusingS3:
    """Reports every key of a delete as failed — the shape a per-key
    `AccessDenied`, `SlowDown` or `InternalError` arrives in."""

    def delete_objects(self, Bucket, Delete):  # noqa: N803 - boto3's own casing
        return {
            "Errors": [
                {"Key": entry["Key"], "Code": "InternalError", "Message": "nope"}
                for entry in Delete["Objects"]
            ],
        }


class TestDeletingPhotos(ApiBase):
    def test_deleting_one_photo_takes_its_objects_with_it(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 2)
        gone = UUID(uploads[0]["photo_id"])

        response = self.client.delete(self._admin(event, f"/{gone}"))

        assert response.status_code == 204
        assert self._photo_item(event.id, gone) is None
        assert self.s3.list_objects_v2(
            Bucket=BUCKET,
            Prefix=f"eventphotos/{event.id}/{gone}/",
        ).get("KeyCount", 0) == 0
        # The reservation counter follows the rows down.
        assert int(self._config_item(event.id)["photo_count"]) == 1
        remaining = self.client.get(self._admin(event)).json()["photos"]
        assert [p["photo_id"] for p in remaining] == [uploads[1]["photo_id"]]

    def test_deleting_an_unknown_or_foreign_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_collection(mine)
        foreign = self._upload(
            theirs,
            self._create_collection(theirs)["upload_token"],
            1,
        )[0]

        for photo_id in (str(uuid4()), foreign["photo_id"]):
            assert self.client.delete(self._admin(mine, f"/{photo_id}")).status_code == 404
        assert self._photo_item(theirs.id, foreign["photo_id"]) is not None

    def test_a_refused_object_delete_keeps_the_row_and_says_so(self):
        """The row is what makes the objects findable at all, so it stays — and
        the organiser is told to try again instead of believing a face is gone."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]
        self.service._s3 = _RefusingS3()

        response = self.client.delete(self._admin(event, f"/{upload['photo_id']}"))

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Die Bilddateien konnten nicht gelöscht werden — bitte versuch es noch einmal."
        )
        assert self._photo_item(event.id, upload["photo_id"]) is not None


class TestBulkDelete(ApiBase):
    def test_only_the_named_photos_go(self):
        event = self._store_event()
        collection = self._create_collection(event)
        uploads = self._upload(event, collection["upload_token"], 4)
        doomed = [uploads[0]["photo_id"], uploads[2]["photo_id"]]

        response = self.client.post(self._admin(event, "/bulk-delete"), json={"photo_ids": doomed})

        assert response.status_code == 200
        assert response.json() == {"requested": 2, "deleted": 2, "completed": True}
        # A set, not a list: which photos survive is this test's subject, and
        # the order they come back in belongs to
        # `test_batches_come_back_oldest_first` alone — asserted twice, it is
        # the delete test that breaks when the sort changes.
        survivors = {p["photo_id"] for p in self.client.get(self._admin(event)).json()["photos"]}
        assert survivors == {uploads[1]["photo_id"], uploads[3]["photo_id"]}
        assert int(self._config_item(event.id)["photo_count"]) == 2

    def test_an_unknown_id_is_a_success_not_an_error(self):
        """Failing the whole call over one stale id would mean reloading and
        reselecting three hundred tiles."""
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        first = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [upload["photo_id"], str(uuid4())]},
        )
        assert first.status_code == 200
        assert first.json() == {"requested": 2, "deleted": 1, "completed": True}

        # And a second pass with the same list is a no-op, not a 404.
        second = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [upload["photo_id"], str(uuid4())]},
        )
        assert second.json() == {"requested": 2, "deleted": 0, "completed": True}

    def test_a_foreign_id_in_the_list_is_simply_not_matched(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_collection(mine)
        foreign = self._upload(
            theirs,
            self._create_collection(theirs)["upload_token"],
            1,
        )[0]

        response = self.client.post(
            self._admin(mine, "/bulk-delete"),
            json={"photo_ids": [foreign["photo_id"]]},
        )

        assert response.json() == {"requested": 1, "deleted": 0, "completed": True}
        assert self._photo_item(theirs.id, foreign["photo_id"]) is not None

    def test_duplicate_ids_are_counted_once(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]

        response = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [upload["photo_id"]] * 3},
        )
        assert response.json() == {"requested": 1, "deleted": 1, "completed": True}

    @pytest.mark.parametrize("size", [0, _MAX_BULK_DELETE + 1])
    def test_the_list_is_capped_at_both_ends(self, size):
        event = self._store_event()
        self._create_collection(event)
        response = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [str(uuid4()) for _ in range(size)]},
        )
        assert response.status_code == 422

    def test_the_biggest_allowed_list_is_accepted(self):
        event = self._store_event()
        self._create_collection(event)
        response = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [str(uuid4()) for _ in range(_MAX_BULK_DELETE)]},
        )
        assert response.status_code == 200
        assert response.json()["requested"] == _MAX_BULK_DELETE

    def test_a_refused_object_delete_is_an_unfinished_pass(self):
        event = self._store_event()
        collection = self._create_collection(event)
        upload = self._upload(event, collection["upload_token"], 1)[0]
        self.service._s3 = _RefusingS3()

        response = self.client.post(
            self._admin(event, "/bulk-delete"),
            json={"photo_ids": [upload["photo_id"]]},
        )

        assert response.status_code == 200
        assert response.json() == {"requested": 1, "deleted": 0, "completed": False}
        assert self._photo_item(event.id, upload["photo_id"]) is not None


class TestDeletingTheCollection(ApiBase):
    def test_the_whole_collection_goes_and_a_second_call_is_a_no_op(self):
        event = self._store_event()
        collection = self._create_collection(event)
        token = collection["upload_token"]
        self._upload(event, token, 2)
        self._upload(event, token, 1, confirm=False)

        first = self.client.delete(self._admin(event))
        assert first.status_code == 200
        assert first.json() == {"photos": 3, "completed": True}

        assert self._config_item(event.id) is None
        assert self.s3.list_objects_v2(
            Bucket=BUCKET,
            Prefix=f"eventphotos/{event.id}/",
        ).get("KeyCount", 0) == 0
        # The link dies with the collection.
        assert self.client.get(self._public(event.id, token)).status_code == 404
        assert self.client.get(self._admin(event, "/config")).status_code == 404

        second = self.client.delete(self._admin(event))
        assert second.json() == {"photos": 0, "completed": True}

    def test_a_refused_object_delete_reports_an_unfinished_pass(self):
        """`completed: false` is a resumable answer, not an error — and the
        config row stays, because it is the sweep's only handle on the
        collection. A caller that treats it as success orphans the objects."""
        event = self._store_event()
        collection = self._create_collection(event)
        self._upload(event, collection["upload_token"], 2)
        self.service._s3 = _RefusingS3()

        response = self.client.delete(self._admin(event))

        assert response.status_code == 200
        assert response.json() == {"photos": 0, "completed": False}
        assert self._config_item(event.id) is not None
        assert self.s3.list_objects_v2(
            Bucket=BUCKET,
            Prefix=f"eventphotos/{event.id}/",
        )["KeyCount"] == 4

    def test_a_collection_can_be_built_again_afterwards(self):
        """Spec 024 §Verhältnis zu Spec 022: a late „schickt uns doch noch eure
        Fotos" round is exactly the use case, so nothing about deletion closes
        the feature."""
        event = self._store_event()
        first = self._create_collection(event)
        self._upload(event, first["upload_token"], 1)
        self.client.delete(self._admin(event))

        second = self._create_collection(event)
        assert second["upload_token"] != first["upload_token"]
        assert second["photo_count"] == 0
        assert self.client.get(self._public(event.id, second["upload_token"])).status_code == 200
        self._upload(event, second["upload_token"], 1)
        assert self.client.get(self._admin(event)).json()["total"] == 1


# --- a local environment without a bucket ------------------------------------


class _ThrottledTable:
    """Proxies a real table but throttles `get_item`.

    The only way to reach the „unreadable" branches from the outside, and they
    are the ones with the interesting failure mode: `get_config` used to swallow
    the `ClientError` and answer `None`, which the public gate turns into „Diese
    Seite gibt es nicht (mehr)" — a permanent-looking dead end handed to a guest
    who is thirty photos into a batch, and a set of 503 branches that could
    never fire.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def get_item(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
            "GetItem",
        )


class TestWhenTheCollectionCannotBeRead(ApiBase):
    """A failed read is „try again", never „does not exist"."""

    def test_the_public_page_answers_503_not_404(self):
        event = self._store_event()
        collection = self._create_collection(event)
        token = collection["upload_token"]
        self.service._table = _ThrottledTable(self.events_table)

        for path in (
            self._public(event.id, token),
            self._public(event.id, token, "/uploads"),
            self._public(event.id, token, "/confirm"),
        ):
            response = (
                self.client.get(path)
                if path.endswith(token)
                else self.client.post(path, json={"count": 1} if "uploads" in path else [])
            )
            assert response.status_code == 503, path
            assert response.json()["detail"] == (
                "Das klappt gerade nicht — bitte versuch es in ein paar Minuten nochmal."
            )

    def test_the_admin_config_answers_503_not_404(self):
        """Otherwise the organiser is told „für dieses Event gibt es noch keine
        Fotosammlung" about a live collection, and the obvious next move —
        create one — mints a token that devalues every printed slip."""
        event = self._store_event()
        self._create_collection(event)
        self.service._table = _ThrottledTable(self.events_table)

        response = self.client.get(self._admin(event, "/config"))

        assert response.status_code == 503
        assert "nicht gelesen werden" in response.json()["detail"]


class TestWithoutABucket(ApiBase):
    """Local dev: no bucket, so nothing can be signed. Writes are refused with
    a sentence that says which side is broken; reads keep working with null
    URLs rather than taking the page down."""

    bucket = None

    def test_minting_reports_the_missing_store(self):
        event = self._store_event()
        collection = self._create_collection(event)

        response = self.client.post(
            self._public(event.id, collection["upload_token"], "/uploads"),
            json={"count": 1},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Der Fotospeicher ist gerade nicht erreichbar — bitte später nochmal."
        )

    def test_reads_still_work(self):
        event = self._store_event()
        collection = self._create_collection(event)
        assert self.client.get(self._admin(event, "/config")).status_code == 200
        assert self.client.get(self._admin(event)).json()["photos"] == []
        assert (
            self.client.get(self._public(event.id, collection["upload_token"])).status_code == 200
        )

    def test_the_manifest_degrades_to_its_header(self):
        event = self._store_event()
        self._create_collection(event)
        response = self.client.get(self._admin(event, "/download-manifest"))
        assert response.status_code == 200
        assert all(line.startswith("#") for line in response.text.splitlines())
