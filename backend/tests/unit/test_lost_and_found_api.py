"""Tests for the Fundsachen endpoints (spec 023) — the nine routes.

The admin side is checked through the role guards and the org boundary: a
viewer reads and never writes, and an event ID from another organisation is
never found, whatever the caller's role.

The public side is checked for the one property the spec insists on: *every*
rejection is the same 404 with the same sentence. `test_no_rejection_is_an
_oracle` asserts that as a set comparison rather than case by case, because the
failure mode is a future branch growing its own, more helpful, answer.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import app.services.config as config_module
import app.services.event_service as event_service_module
import app.services.lost_and_found_service as lnf_module
from app.main import app
from app.models import Event, EventStatus, EventType
from app.models.admin import AdminRole
from app.services.auth import TokenPayload, verify_token
from app.services.config import (
    EVENT_SK_LNF_CONFIG,
    EVENT_SK_LNF_PHOTO_PREFIX,
    DynamoDBSettings,
)
from app.services.event_service import EventService, _event_to_item
from app.services.lost_and_found_service import (
    MAX_UPLOAD_BATCH,
    URL_TTL_SECONDS,
    LostAndFoundService,
    display_key,
    thumb_key,
)

BUCKET = "funke-test-lostfound"
BASE_URL = "https://fest.example.com"
NOW = datetime.now(timezone.utc)

# The single answer to every public rejection.
NOT_FOUND_BODY = {"detail": "Diese Seite gibt es nicht (mehr)."}


class ApiBase:
    """A TestClient whose org and role can be swapped mid-test."""

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

        self.s3 = boto3.client("s3", region_name="eu-central-1")
        self.s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-central-1"},
        )

        self.service = LostAndFoundService()
        self.service._table = self.events_table
        monkeypatch.setattr(lnf_module, "_lost_and_found_service", self.service)

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

    def _admin(self, event: Event, suffix: str = "") -> str:
        return f"/api/admin/events/{event.id}/lostfound{suffix}"

    def _public(self, event_id, token: str) -> str:
        return f"/api/public/lostfound/{event_id}/{token}"

    def _create_page(self, event: Event, **patch) -> dict:
        body = {"coordinator_email": "fundsachen@example.com"}
        body.update(patch)
        response = self.client.put(self._admin(event), json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def _upload(self, event: Event, count: int, *, confirm: bool = True) -> list[dict]:
        response = self.client.post(self._admin(event, "/uploads"), json={"count": count})
        assert response.status_code == 200, response.text
        uploads = response.json()["uploads"]

        for upload in uploads:
            for key in (
                display_key(event.id, upload["photo_id"]),
                thumb_key(event.id, upload["photo_id"]),
            ):
                self.s3.put_object(Bucket=BUCKET, Key=key, Body=b"jpeg-bytes")

        if confirm:
            confirmed = self.client.post(
                self._admin(event, "/photos/confirm"),
                json={
                    "photos": [
                        {"photo_id": u["photo_id"], "width": 1600, "height": 1200} for u in uploads
                    ],
                },
            )
            assert confirmed.status_code == 200, confirmed.text
        return uploads

    def _config_item(self, event_id) -> dict | None:
        return self.events_table.get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_LNF_CONFIG},
        ).get("Item")

    def _photo_item(self, event_id, photo_id) -> dict | None:
        return self.events_table.get_item(
            Key={
                "pk": f"EVENT#{event_id}",
                "sk": f"{EVENT_SK_LNF_PHOTO_PREFIX}{photo_id}",
            },
        ).get("Item")


# --- authorisation -----------------------------------------------------------


class TestAuthorisation(ApiBase):
    def test_without_a_token_nothing_is_reachable(self):
        event = self._store_event()
        app.dependency_overrides.clear()
        response = TestClient(app).get(self._admin(event))
        assert response.status_code == 401

    def test_a_viewer_may_read(self):
        event = self._store_event()
        self._create_page(event)
        self.role = AdminRole.VIEWER
        assert self.client.get(self._admin(event)).status_code == 200

    def test_a_viewer_may_not_write(self):
        event = self._store_event()
        page = self._create_page(event)
        upload = self._upload(event, 1)[0]
        self.role = AdminRole.VIEWER

        writes = [
            self.client.put(self._admin(event), json={"published": True}),
            self.client.delete(self._admin(event)),
            self.client.post(self._admin(event, "/rotate-token")),
            self.client.post(self._admin(event, "/uploads"), json={"count": 1}),
            self.client.post(
                self._admin(event, "/photos/confirm"),
                json={"photos": [{"photo_id": upload["photo_id"], "width": 8, "height": 8}]},
            ),
            self.client.patch(
                self._admin(event, f"/photos/{upload['photo_id']}"),
                json={"caption": "x"},
            ),
            self.client.delete(self._admin(event, f"/photos/{upload['photo_id']}")),
        ]
        assert [r.status_code for r in writes] == [403] * 7
        # Nothing changed behind the refusals.
        assert self._config_item(event.id)["page_token"] == page["page_token"]

    @pytest.mark.parametrize("role", [AdminRole.OWNER, AdminRole.ADMIN])
    def test_owners_and_admins_may_write(self, role):
        event = self._store_event()
        self.role = role
        response = self.client.put(
            self._admin(event),
            json={"coordinator_email": "fund@example.com"},
        )
        assert response.status_code == 200

    def test_another_organisation_cannot_touch_the_page(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        upload = self._upload(event, 1)[0]

        self.org_id = uuid4()  # a different org's admin, same event id
        attempts = [
            self.client.get(self._admin(event)),
            self.client.put(self._admin(event), json={"published": False}),
            self.client.delete(self._admin(event)),
            self.client.post(self._admin(event, "/rotate-token")),
            self.client.post(self._admin(event, "/uploads"), json={"count": 1}),
            self.client.post(
                self._admin(event, "/photos/confirm"),
                json={"photos": [{"photo_id": upload["photo_id"], "width": 8, "height": 8}]},
            ),
            self.client.patch(
                self._admin(event, f"/photos/{upload['photo_id']}"),
                json={"caption": "x"},
            ),
            self.client.delete(self._admin(event, f"/photos/{upload['photo_id']}")),
        ]
        assert [r.status_code for r in attempts] == [404] * 8
        assert self._config_item(event.id)["page_token"] == page["page_token"]
        assert self._photo_item(event.id, upload["photo_id"]) is not None


# --- configuration -----------------------------------------------------------


class TestAdminConfig(ApiBase):
    def test_an_event_without_a_page_answers_with_an_empty_form(self):
        event = self._store_event()
        response = self.client.get(self._admin(event))

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "configured": False,
            "page_token": None,
            "public_url": None,
            "coordinator_name": None,
            "coordinator_email": None,
            "coordinator_telegram_url": None,
            "intro_text": None,
            "published": False,
            # Pre-filled from the environment so the form always has a number.
            "retention_days": 90,
            "expires_at": None,
            "photos": [],
        }

    def test_an_unknown_event_is_not_found(self):
        assert self.client.get(f"/api/admin/events/{uuid4()}/lostfound").status_code == 404

    def test_the_first_save_creates_the_page(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event),
            json={
                "coordinator_email": "fundsachen@example.com",
                "coordinator_name": "Aline",
                "intro_text": "Die Kiste steht im Büro.",
                "published": False,
                "retention_days": None,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert len(body["page_token"]) == 43
        assert body["public_url"] == (f"{BASE_URL}/lostfound/{event.id}/{body['page_token']}")
        assert body["coordinator_name"] == "Aline"
        assert body["published"] is False
        assert body["retention_days"] == 90
        assert body["expires_at"] is not None
        assert body["photos"] == []

    def test_the_first_save_needs_some_way_to_reach_a_human(self):
        event = self._store_event()
        response = self.client.put(self._admin(event), json={"published": True})

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Bitte gib an, wie sich Gäste melden können — eine E-Mail-Adresse "
            "oder einen Telegram-Link."
        )
        assert self._config_item(event.id) is None

    def test_a_telegram_link_alone_is_enough(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event),
            json={"coordinator_telegram_url": "t.me/fundsachen", "published": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["coordinator_email"] is None
        assert body["coordinator_telegram_url"] == "https://t.me/fundsachen"

    @pytest.mark.parametrize(
        "value",
        [
            "javascript:alert(1)",
            "https://evil.example.com/t.me/fundsachen",
            "data:text/html,<script>x</script>",
            "https://t.me/",
            "@ab",
        ],
    )
    def test_a_non_telegram_link_is_refused(self, value):
        """The value is rendered as an `href` on a public page, so anything that
        is not a t.me URL has to die at the edge."""
        event = self._store_event()
        response = self.client.put(
            self._admin(event),
            json={"coordinator_email": "fund@example.com", "coordinator_telegram_url": value},
        )

        assert response.status_code == 422
        assert self._config_item(event.id) is None

    def test_an_unknown_field_is_refused(self):
        event = self._store_event()
        response = self.client.put(
            self._admin(event),
            json={"coordinator_email": "fund@example.com", "publish": True},
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"coordinator_email": "kein-email"},
            {"coordinator_email": "fund@example.com", "retention_days": 6},
            {"coordinator_email": "fund@example.com", "retention_days": 366},
            {"coordinator_email": "fund@example.com", "coordinator_name": "x" * 201},
            {"coordinator_email": "fund@example.com", "intro_text": "x" * 2001},
        ],
    )
    def test_invalid_bodies_are_refused(self, body):
        event = self._store_event()
        assert self.client.put(self._admin(event), json=body).status_code == 422

    def test_publishing_keeps_the_token_and_the_rest_of_the_form(self):
        event = self._store_event()
        created = self._create_page(event, coordinator_name="Aline")

        updated = self.client.put(self._admin(event), json={"published": True}).json()
        assert updated["published"] is True
        assert updated["page_token"] == created["page_token"]
        assert updated["coordinator_name"] == "Aline"

    def test_retention_override_is_echoed_and_can_be_cleared(self):
        event = self._store_event()
        self._create_page(event)

        overridden = self.client.put(self._admin(event), json={"retention_days": 14}).json()
        assert overridden["retention_days"] == 14

        cleared = self.client.put(self._admin(event), json={"retention_days": None}).json()
        assert cleared["retention_days"] == 90

    def test_rotating_the_token_returns_the_new_page(self):
        event = self._store_event()
        created = self._create_page(event, published=True)

        rotated = self.client.post(self._admin(event, "/rotate-token"))
        assert rotated.status_code == 200
        body = rotated.json()
        assert body["page_token"] != created["page_token"]
        assert body["public_url"].endswith(body["page_token"])

        assert (
            self.client.get(
                self._public(event.id, created["page_token"]),
            ).status_code
            == 404
        )
        assert (
            self.client.get(
                self._public(event.id, body["page_token"]),
            ).status_code
            == 200
        )

    def test_rotating_without_a_page(self):
        event = self._store_event()
        response = self.client.post(self._admin(event, "/rotate-token"))
        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Für dieses Event gibt es noch keine Fundsachen-Seite."
        )

    def test_deleting_the_page_reports_what_went_and_is_idempotent(self):
        event = self._store_event()
        self._create_page(event, published=True)
        self._upload(event, 2)

        first = self.client.delete(self._admin(event))
        assert first.status_code == 200
        assert first.json() == {"deleted_photos": 2, "completed": True}

        second = self.client.delete(self._admin(event))
        assert second.json() == {"deleted_photos": 0, "completed": True}
        assert self.client.get(self._admin(event)).json()["configured"] is False


# --- uploads and photos ------------------------------------------------------


class TestAdminPhotos(ApiBase):
    def test_minting_uploads_returns_a_presigned_post_per_variant(self):
        event = self._store_event()
        self._create_page(event)

        response = self.client.post(self._admin(event, "/uploads"), json={"count": 3})
        assert response.status_code == 200
        uploads = response.json()["uploads"]

        assert [u["number"] for u in uploads] == [1, 2, 3]
        for upload in uploads:
            for variant, key in (
                ("display", display_key(event.id, upload["photo_id"])),
                ("thumb", thumb_key(event.id, upload["photo_id"])),
            ):
                assert upload[variant]["fields"]["key"] == key
                assert upload[variant]["fields"]["Content-Type"] == "image/jpeg"
                assert "policy" in upload[variant]["fields"]
                assert upload[variant]["url"]

    @pytest.mark.parametrize("count", [0, -1, MAX_UPLOAD_BATCH + 1])
    def test_a_batch_size_outside_the_range_is_refused(self, count):
        event = self._store_event()
        self._create_page(event)
        response = self.client.post(self._admin(event, "/uploads"), json={"count": count})
        assert response.status_code == 422

    def test_minting_uploads_without_a_page(self):
        event = self._store_event()
        response = self.client.post(self._admin(event, "/uploads"), json={"count": 1})
        assert response.status_code == 404

    def test_pending_uploads_are_visible_to_the_admin_but_not_the_public(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        pending = self._upload(event, 1, confirm=False)[0]

        admin_photos = self.client.get(self._admin(event)).json()["photos"]
        assert [p["state"] for p in admin_photos] == ["PENDING"]
        assert admin_photos[0]["number"] == pending["number"]
        assert admin_photos[0]["width"] is None

        public = self.client.get(self._public(event.id, page["page_token"]))
        assert public.json()["photos"] == []

    def test_confirming_flips_the_rows_to_ready(self):
        event = self._store_event()
        self._create_page(event)
        uploads = self._upload(event, 2, confirm=False)

        response = self.client.post(
            self._admin(event, "/photos/confirm"),
            json={
                "photos": [
                    {
                        "photo_id": uploads[0]["photo_id"],
                        "width": 1600,
                        "height": 1200,
                        "caption": "Blaue Jacke",
                    },
                    {"photo_id": uploads[1]["photo_id"], "width": 400, "height": 400},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["confirmed"] == 2
        assert [p["state"] for p in body["photos"]] == ["READY", "READY"]
        assert body["photos"][0]["caption"] == "Blaue Jacke"
        assert body["photos"][0]["thumb_url"]
        assert body["photos"][1]["caption"] is None

    def test_confirming_an_unknown_photo(self):
        event = self._store_event()
        self._create_page(event)
        response = self.client.post(
            self._admin(event, "/photos/confirm"),
            json={"photos": [{"photo_id": str(uuid4()), "width": 8, "height": 8}]},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Dieses Foto gibt es nicht (mehr)."

    def test_confirming_a_photo_from_another_event(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_page(mine)
        self._create_page(theirs)
        foreign = self._upload(theirs, 1, confirm=False)[0]

        response = self.client.post(
            self._admin(mine, "/photos/confirm"),
            json={"photos": [{"photo_id": foreign["photo_id"], "width": 8, "height": 8}]},
        )
        assert response.status_code == 404
        assert self._photo_item(theirs.id, foreign["photo_id"])["state"] == "PENDING"

    def test_captions_can_be_set_and_cleared(self):
        event = self._store_event()
        self._create_page(event)
        upload = self._upload(event, 1)[0]
        path = self._admin(event, f"/photos/{upload['photo_id']}")

        set_response = self.client.patch(path, json={"caption": "Autoschlüssel"})
        assert set_response.status_code == 200
        assert set_response.json()["caption"] == "Autoschlüssel"
        assert set_response.json()["number"] == upload["number"]

        cleared = self.client.patch(path, json={"caption": None})
        assert cleared.json()["caption"] is None

    def test_an_overlong_caption_is_refused(self):
        event = self._store_event()
        self._create_page(event)
        upload = self._upload(event, 1)[0]

        response = self.client.patch(
            self._admin(event, f"/photos/{upload['photo_id']}"),
            json={"caption": "x" * 201},
        )
        assert response.status_code == 422

    def test_captioning_an_unknown_or_foreign_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_page(mine)
        self._create_page(theirs)
        foreign = self._upload(theirs, 1)[0]

        assert (
            self.client.patch(
                self._admin(mine, f"/photos/{uuid4()}"),
                json={"caption": "x"},
            ).status_code
            == 404
        )
        assert (
            self.client.patch(
                self._admin(mine, f"/photos/{foreign['photo_id']}"),
                json={"caption": "x"},
            ).status_code
            == 404
        )

    def test_deleting_a_photo(self):
        event = self._store_event()
        self._create_page(event)
        uploads = self._upload(event, 2)

        response = self.client.delete(self._admin(event, f"/photos/{uploads[0]['photo_id']}"))
        assert response.status_code == 204
        assert self._photo_item(event.id, uploads[0]["photo_id"]) is None

        remaining = self.client.get(self._admin(event)).json()["photos"]
        assert [p["number"] for p in remaining] == [uploads[1]["number"]]

    def test_deleting_an_unknown_or_foreign_photo(self):
        mine = self._store_event()
        theirs = self._store_event()
        self._create_page(mine)
        self._create_page(theirs)
        foreign = self._upload(theirs, 1)[0]

        assert (
            self.client.delete(
                self._admin(mine, f"/photos/{uuid4()}"),
            ).status_code
            == 404
        )
        assert (
            self.client.delete(
                self._admin(mine, f"/photos/{foreign['photo_id']}"),
            ).status_code
            == 404
        )
        assert self._photo_item(theirs.id, foreign["photo_id"]) is not None

    def test_the_admin_grid_carries_signed_urls_and_dimensions(self):
        event = self._store_event()
        self._create_page(event)
        self._upload(event, 1)

        photo = self.client.get(self._admin(event)).json()["photos"][0]
        assert photo["width"] == 1600
        assert photo["height"] == 1200
        assert "X-Amz-Signature" in photo["display_url"]
        assert "X-Amz-Signature" in photo["thumb_url"]


class TestAnonymisedEvents(ApiBase):
    """Anonymisation deletes the page that exists at the time, but it does not
    close the feature: a Fundsachen box is often only sorted out long after the
    guest data is gone, so every write path stays open afterwards and the
    retention window then runs from the page's own creation."""

    def _anonymise(self, event: Event) -> None:
        self.events_table.update_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
            UpdateExpression="SET anonymized_at = :t",
            ExpressionAttributeValues={":t": NOW.isoformat()},
        )

    def test_every_write_path_accepts_an_anonymised_event(self):
        event = self._store_event()
        self._create_page(event)
        upload = self._upload(event, 1, confirm=False)[0]
        self._anonymise(event)

        writes = [
            self.client.put(
                self._admin(event),
                json={"coordinator_email": "fundsachen@example.com"},
            ),
            self.client.post(self._admin(event, "/uploads"), json={"count": 3}),
            self.client.post(
                self._admin(event, "/photos/confirm"),
                json={
                    "photos": [{"photo_id": upload["photo_id"], "width": 800, "height": 600}],
                },
            ),
            # A caption is the most personal thing on the page — „Handy von
            # Lena, am Bühnenrand" is the example the spec itself names.
            self.client.patch(
                self._admin(event, f"/photos/{upload['photo_id']}"),
                json={"caption": "Handy von Lena, am Bühnenrand"},
            ),
        ]

        assert [r.status_code for r in writes] == [200, 200, 200, 200]
        # And the writes actually landed.
        row = self._photo_item(event.id, upload["photo_id"])
        assert row["state"] == "READY"
        assert row["caption"] == "Handy von Lena, am Bühnenrand"

    def test_a_page_on_an_anonymised_event_can_still_be_read_and_deleted(self):
        event = self._store_event()
        self._create_page(event)
        self._upload(event, 1)
        self._anonymise(event)

        assert self.client.get(self._admin(event)).status_code == 200
        assert self.client.delete(self._admin(event)).status_code == 200
        assert self._config_item(event.id) is None


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


class TestDeletingThePageIsResumable(ApiBase):
    """The page delete has a time budget, so a page with a thousand rows answers
    `completed: false` and is called again — without one the invocation is simply
    killed at the gateway's 29 s and the client gets a 504 it cannot resume
    from."""

    def test_the_delete_pass_carries_a_deadline(self):
        event = self._store_event()
        self._create_page(event)
        seen = {}
        real = self.service.delete_page

        async def recording(event_id, deadline=None):
            seen["deadline"] = deadline
            return await real(event_id, deadline=deadline)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.service, "delete_page", recording)
            response = self.client.delete(self._admin(event))

        assert response.status_code == 200
        assert seen["deadline"] is not None
        assert seen["deadline"] > datetime.now(timezone.utc)

    def test_an_unfinished_pass_is_a_resumable_answer_not_an_error(self):
        event = self._store_event()
        self._create_page(event)
        self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        response = self.client.delete(self._admin(event))

        assert response.status_code == 200
        assert response.json() == {"deleted_photos": 0, "completed": False}
        assert self._config_item(event.id) is not None

    def test_deleting_the_event_is_refused_while_its_page_owns_objects(self):
        """The event is the only way back to the page — it must outlive it."""
        event = self._store_event(status=EventStatus.CANCELLED, cancelled_at=NOW)
        self._create_page(event)
        self._upload(event, 1)
        self.service._s3 = _RefusingS3()

        response = self.client.delete(f"/api/admin/events/{event.id}")

        assert response.status_code == 503
        assert "Fundsachen" in response.json()["detail"]
        assert self.events_table.get_item(
            Key={"pk": f"ORG#{event.org_id}", "sk": f"EVENT#{event.id}"},
        ).get("Item") is not None
        assert self._config_item(event.id) is not None


class TestAFailedReadIsNotAnEmptyGallery(ApiBase):
    """An empty grid presented as fact invites a second upload of the whole box,
    and every re-upload draws fresh numbers — the page then lists each item twice
    and the number a guest already quoted points at one of a pair."""

    def _break_photo_reads(self, mp):
        """Throttle the photo query. Config and event reads are `get_item` and a
        scan, so they still answer — the failure is exactly the one that used to
        come back as „no photos"."""

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

        mp.setattr(self.events_table, "query", query)

    def test_the_admin_grid_fails_instead_of_showing_nothing(self):
        event = self._store_event()
        self._create_page(event)
        self._upload(event, 2)

        with pytest.MonkeyPatch.context() as mp:
            self._break_photo_reads(mp)
            response = self.client.get(self._admin(event))

        assert response.status_code == 503
        assert "neu" in response.json()["detail"]

    def test_the_public_page_says_try_again_not_nothing_here(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        self._upload(event, 2)

        with pytest.MonkeyPatch.context() as mp:
            self._break_photo_reads(mp)
            response = self.client.get(self._public(event.id, page["page_token"]))

        assert response.status_code == 503
        assert response.json() != NOT_FOUND_BODY

    def test_a_wrong_token_is_still_a_flat_404(self):
        """The 503 must stay behind the token check, or it becomes an oracle."""
        event = self._store_event()
        self._create_page(event, published=True)

        with pytest.MonkeyPatch.context() as mp:
            self._break_photo_reads(mp)
            response = self.client.get(self._public(event.id, "x" * 43))

        assert response.status_code == 404
        assert response.json() == NOT_FOUND_BODY


class TestPartialConfirmation(ApiBase):
    """A batch is dozens of rows and each one is its own write. Telling the
    client „the batch failed" for one vanished row makes it re-upload photos that
    are already public under numbers a guest may have been given."""

    def test_a_partial_batch_is_a_200_that_names_the_shortfall(self):
        event = self._store_event()
        self._create_page(event)
        uploads = self._upload(event, 2, confirm=False)
        gone = str(uuid4())

        response = self.client.post(
            self._admin(event, "/photos/confirm"),
            json={
                "photos": [
                    {"photo_id": uploads[0]["photo_id"], "width": 10, "height": 10},
                    {"photo_id": gone, "width": 10, "height": 10},
                    {"photo_id": uploads[1]["photo_id"], "width": 10, "height": 10},
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["confirmed"] == 2
        assert body["not_confirmed"] == [gone]
        assert self._photo_item(event.id, uploads[0]["photo_id"])["state"] == "READY"

    def test_a_batch_that_confirmed_nothing_is_still_a_404(self):
        event = self._store_event()
        self._create_page(event)

        response = self.client.post(
            self._admin(event, "/photos/confirm"),
            json={"photos": [{"photo_id": str(uuid4()), "width": 10, "height": 10}]},
        )

        assert response.status_code == 404


class TestWithoutABucket(ApiBase):
    """Local dev: no bucket, so uploads are refused and reads carry no URLs."""

    bucket = None

    def test_minting_uploads_reports_the_missing_store(self):
        event = self._store_event()
        self._create_page(event)
        response = self.client.post(self._admin(event, "/uploads"), json={"count": 1})

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Der Fundsachen-Speicher ist in dieser Umgebung nicht eingerichtet."
        )

    def test_reads_still_work_with_null_urls(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        assert self.client.get(self._admin(event)).status_code == 200
        assert self.client.get(self._public(event.id, page["page_token"])).status_code == 200


# --- the public page ---------------------------------------------------------


class TestPublicPage(ApiBase):
    def test_the_published_page_renders(self):
        event = self._store_event()
        page = self._create_page(
            event,
            published=True,
            coordinator_name="Aline",
            intro_text="Die Kiste steht im Büro.",
        )
        upload = self._upload(event, 1)[0]
        self.client.patch(
            self._admin(event, f"/photos/{upload['photo_id']}"),
            json={"caption": "Blaue Jacke"},
        )

        response = self.client.get(self._public(event.id, page["page_token"]))
        assert response.status_code == 200
        body = response.json()

        assert body["event_name"] == event.name
        assert body["event_date"] == event.start_at.date().isoformat()
        assert body["coordinator_name"] == "Aline"
        assert body["coordinator_email"] == "fundsachen@example.com"
        assert body["intro_text"] == "Die Kiste steht im Büro."
        assert body["retention_days"] == 90
        assert body["url_ttl_seconds"] == URL_TTL_SECONDS
        # Pinned as a set: the public payload must never start carrying the
        # page_token (it is in the URL the visitor already has, but echoing it
        # into a body that ends up in caches and logs is how tokens leak) or
        # the `published` flag, which is an admin concern.
        assert set(body) == {
            "event_name",
            "event_date",
            "coordinator_name",
            "coordinator_email",
            "coordinator_telegram_url",
            "intro_text",
            "retention_days",
            "url_ttl_seconds",
            "photos",
        }

        photo = body["photos"][0]
        assert photo["number"] == upload["number"]
        assert photo["caption"] == "Blaue Jacke"
        assert photo["width"] == 1600
        # A guest has no use for the id, the keys or the upload time, so they
        # are not in the payload at all.
        assert set(photo) == {
            "number",
            "caption",
            "thumb_url",
            "display_url",
            "width",
            "height",
        }

    def test_a_published_page_without_photos(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        body = self.client.get(self._public(event.id, page["page_token"])).json()
        assert body["photos"] == []

    def test_photos_arrive_in_number_order(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        uploads = self._upload(event, 4)
        self.client.delete(self._admin(event, f"/photos/{uploads[1]['photo_id']}"))

        body = self.client.get(self._public(event.id, page["page_token"])).json()
        # The gap where number 2 was stays a gap — nothing is renumbered.
        assert [p["number"] for p in body["photos"]] == [1, 3, 4]

    def test_no_rejection_is_an_oracle(self):
        """Wrong token, unknown event, unpublished, expired and deleted must be
        indistinguishable — same status, same body."""
        live = self._store_event()
        live_page = self._create_page(live, published=True)

        unpublished = self._store_event()
        unpublished_page = self._create_page(unpublished)

        expired = self._store_event(
            start_at=NOW - timedelta(days=200),
            end_at=NOW - timedelta(days=199),
        )
        expired_page = self._create_page(expired, published=True)
        # Retention runs from the later of event end and page creation, so the
        # page has to be as old as the event to actually be past its window.
        self.events_table.update_item(
            Key={"pk": f"EVENT#{expired.id}", "sk": EVENT_SK_LNF_CONFIG},
            UpdateExpression="SET created_at = :t",
            ExpressionAttributeValues={":t": (NOW - timedelta(days=199)).isoformat()},
        )

        deleted = self._store_event()
        deleted_page = self._create_page(deleted, published=True)
        self.client.delete(self._admin(deleted))

        rotated_event = self._store_event()
        stale_page = self._create_page(rotated_event, published=True)
        self.client.post(self._admin(rotated_event, "/rotate-token"))

        rejections = {
            "wrong token": self._public(live.id, "x" * 43),
            "short token": self._public(live.id, "x"),
            "token prefix": self._public(live.id, live_page["page_token"][:-1]),
            "unknown event": self._public(uuid4(), live_page["page_token"]),
            "unpublished": self._public(unpublished.id, unpublished_page["page_token"]),
            "expired": self._public(expired.id, expired_page["page_token"]),
            "deleted": self._public(deleted.id, deleted_page["page_token"]),
            "rotated away": self._public(rotated_event.id, stale_page["page_token"]),
        }

        answers = {
            label: (r.status_code, r.json())
            for label, path in rejections.items()
            for r in [self.client.get(path)]
        }
        assert answers == dict.fromkeys(rejections, (404, NOT_FOUND_BODY))
        # And the page that should work still works, so the sweep above is not
        # passing by breaking everything.
        assert self.client.get(self._public(live.id, live_page["page_token"])).status_code == 200

    def test_a_syntactically_invalid_event_id_is_a_validation_error(self):
        """Documented deviation: the path param is typed `UUID`, so garbage in
        that segment never reaches the gate — same as `/api/public/tickets`."""
        assert self.client.get("/api/public/lostfound/nicht-uuid/abc").status_code == 422

    def test_the_public_page_needs_no_token_header(self):
        event = self._store_event()
        page = self._create_page(event, published=True)
        app.dependency_overrides.clear()
        anonymous = TestClient(app)
        assert anonymous.get(self._public(event.id, page["page_token"])).status_code == 200

    def test_a_non_ascii_token_is_a_flat_404(self):
        event = self._store_event()
        self._create_page(event, published=True)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(self._public(event.id, "ö" * 43))
        assert (response.status_code, response.json()) == (404, NOT_FOUND_BODY)
