"""Tests for the Chartervertrag (spec 025) — everything except the rendering.

Two halves, and the split is deliberate.

The first half drives the ten admin routes through a real `TestClient` against
moto's DynamoDB and S3, because most of what spec 025 promises is a *refusal*:
a signed contract cannot be edited, a festival cannot carry one, a viewer
cannot write, a render will not start on an incomplete form. A refusal is only
worth anything if it comes back as the right status with the right German
sentence, and only the router knows that.

The second half is the coupling to the three neighbours spec 025 reaches into —
the trip report, the anonymisation sweep, and the two delete paths. Those are
tested at the service level, where the promise actually lives.

The one thing not in here is what the PDF looks like; `charter_pdf` owns that.
The renderer does run, though — „a second render produces v2 and does not
overwrite v1" is a claim about two real objects in a bucket.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import app.services.charter_service as charter_module
import app.services.config as config_module
import app.services.event_service as event_service_module
from app.main import app
from app.models import (
    Event,
    EventStatus,
    EventType,
    Registration,
    RegistrationStatus,
)
from app.models.admin import AdminRole
from app.models.charter import CharterContract, CharterStatus
from app.models.fahrbericht import ExpenseLine
from app.services.anonymization_service import AnonymizationService
from app.services.auth import TokenPayload, verify_token
from app.services.charter_service import (
    CharterService,
    _contract_to_item,
    _item_to_contract,
)
from app.services.config import EVENT_SK_CHARTER, DynamoDBSettings
from app.services.event_photo_service import EventPhotoService
from app.services.event_service import CHARTER_NOT_DELETED, EventService, _event_to_item
from app.services.lost_and_found_service import LostAndFoundService
from app.services.registration_service import _item_to_registration, _registration_to_item

# The *reports* bucket, not lostfound and not eventphotos: those two expire
# after 400 days and would quietly delete a ten-year record. The test names it
# out loud so a future rewire is visible in the diff.
BUCKET = "funke-test-reports"

NOW = datetime.now(timezone.utc)


class CharterBase:
    """A TestClient whose role can be swapped mid-test, plus a wired service.

    Every collaborator is constructed here rather than fetched through its
    `get_*_service()` singleton: a singleton caches a `Table` handle from
    whichever moto context happened to create it first, which makes test order
    matter. The router-facing singletons are then monkeypatched to these
    instances so the HTTP path and the direct calls see one and the same row.
    """

    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb, monkeypatch):
        self.tables = mock_dynamodb
        self.events_table = mock_dynamodb["events_table"]

        monkeypatch.setattr(
            config_module,
            "_settings",
            DynamoDBSettings(reports_s3_bucket=BUCKET),
        )

        self.s3 = boto3.client("s3", region_name="eu-central-1")
        self.s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-central-1"},
        )

        self.charter = CharterService()
        self.charter._table = self.events_table
        monkeypatch.setattr(charter_module, "_charter_service", self.charter)

        self.event_service = EventService()
        self.event_service._table = self.events_table
        self.event_service._charter = self.charter
        self.event_service._lost_and_found = self._lnf_service()
        self.event_service._event_photos = self._photo_service()
        monkeypatch.setattr(event_service_module, "_event_service", self.event_service)

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

    def _lnf_service(self) -> LostAndFoundService:
        service = LostAndFoundService()
        service._table = self.events_table
        return service

    def _photo_service(self) -> EventPhotoService:
        service = EventPhotoService()
        service._table = self.events_table
        return service

    # -- factories ------------------------------------------------------------

    def _store_event(self, **overrides) -> Event:
        defaults = dict(
            id=uuid4(),
            org_id=self.org_id,
            name="Charterfahrt Elbe",
            start_at=NOW + timedelta(days=10),
            registration_deadline=NOW + timedelta(days=5),
            status=EventStatus.OPEN,
            capacity=12,
            event_type=EventType.SINGLE,
        )
        defaults.update(overrides)
        event = Event(**defaults)
        self.events_table.put_item(Item=_event_to_item(event))
        return event

    def _store_contract(self, event_id, **overrides) -> CharterContract:
        """Put a contract row straight into the table, bypassing the routes.

        Used where the *starting state* is the point of the test (a signed
        contract inside its retention, say) rather than the path that gets
        there.
        """
        defaults = dict(
            event_id=event_id,
            charterer_name="Frieda Beispiel",
            charterer_address="Musterweg 1\n21107 Hamburg",
            uebergabe_at=NOW - timedelta(days=1),
            rueckgabe_at=NOW,
            chartergebuehr=Decimal("250.00"),
            kaution=Decimal("500.00"),
            personen_ohne_skipper=8,
        )
        defaults.update(overrides)
        contract = CharterContract(**defaults)
        self.events_table.put_item(Item=_contract_to_item(contract))
        return contract

    # -- routes ---------------------------------------------------------------

    def _url(self, event: Event, suffix: str = "") -> str:
        return f"/api/admin/events/{event.id}/chartervertrag{suffix}"

    def _payload(self, **patch) -> dict:
        """A complete, renderable form. Money travels as strings, the way the
        page sends it — a JSON float would arrive with rounding noise."""
        body = {
            "charterer_name": "Frieda Beispiel",
            "charterer_address": "Musterweg 1\n21107 Hamburg",
            "charterer_email": "frieda@example.com",
            "charterer_phone": "+49 40 123456",
            "uebergabe_at": "2026-06-13T09:00:00+00:00",
            "rueckgabe_at": "2026-06-13T17:00:00+00:00",
            "chartergebuehr": "250.00",
            "sonderleistungen": [{"description": "Diesel", "amount": "25.50"}],
            "kaution": "500.00",
            "personen_ohne_skipper": 8,
            "skipper_name": "Frieda Beispiel",
            "skipper_is_charterer": True,
        }
        body.update(patch)
        return body

    def _save(self, event: Event, **patch) -> dict:
        response = self.client.put(self._url(event), json=self._payload(**patch))
        assert response.status_code == 200, response.text
        return response.json()

    def _render(self, event: Event) -> dict:
        response = self.client.post(self._url(event, "/render"))
        assert response.status_code == 200, response.text
        return response.json()

    def _sign(self, event: Event, *, signed_on: str = "2026-06-13") -> dict:
        """The whole signature handshake: presign, upload, confirm."""
        upload = self.client.post(self._url(event, "/upload"), json={})
        assert upload.status_code == 200, upload.text
        key = upload.json()["key"]

        # The browser's direct-to-S3 POST, minus the multipart form: what the
        # confirm cares about is that the object is there and what is in it.
        self.s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=b"scanned-signature-page",
            ContentType="application/pdf",
        )

        confirmed = self.client.post(
            self._url(event, "/signiert"),
            json={"signed_on": signed_on, "alle_parteien_unterschrieben": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        return confirmed.json()

    # -- reading back ---------------------------------------------------------

    def _contract_row(self, event_id) -> CharterContract | None:
        """The stored row, read straight from the table.

        Not `get_contract`, which is a coroutine: most of what these tests
        assert about the row happens in a synchronous HTTP test, and awaiting
        the service there would mean making every one of them async for a
        single `get_item`.
        """
        item = self.events_table.get_item(
            Key={"pk": f"EVENT#{event_id}", "sk": EVENT_SK_CHARTER},
        ).get("Item")
        return _item_to_contract(item) if item else None

    def _object_exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError:
            return False
        return True

    def _keys(self) -> set[str]:
        listing = self.s3.list_objects_v2(Bucket=BUCKET)
        return {obj["Key"] for obj in listing.get("Contents", [])}


# --- the total ---------------------------------------------------------------


class TestGesamtbetrag(CharterBase):
    """Charter fee plus extras, and the deposit deliberately left out of it —
    it is refundable, so including it would state a total nobody owes."""

    def test_the_total_is_fee_plus_extras(self):
        contract = CharterContract(
            event_id=uuid4(),
            chartergebuehr=Decimal("250.00"),
            sonderleistungen=[
                ExpenseLine(description="Diesel", amount=Decimal("25.50")),
                ExpenseLine(description="Endreinigung", amount=Decimal("40.00")),
            ],
            kaution=Decimal("500.00"),
        )
        assert contract.compute_gesamtbetrag() == Decimal("315.50")

    def test_the_deposit_is_not_part_of_the_total(self):
        with_deposit = CharterContract(
            event_id=uuid4(),
            chartergebuehr=Decimal("250.00"),
            kaution=Decimal("500.00"),
        )
        without_deposit = with_deposit.model_copy(update={"kaution": None})
        assert with_deposit.compute_gesamtbetrag() == Decimal("250.00")
        assert without_deposit.compute_gesamtbetrag() == with_deposit.compute_gesamtbetrag()

    def test_a_deposit_alone_totals_nothing(self):
        contract = CharterContract(event_id=uuid4(), kaution=Decimal("500.00"))
        assert contract.compute_gesamtbetrag() == Decimal("0")

    def test_the_api_answers_with_the_live_total(self):
        event = self._store_event()
        body = self._save(event)
        # 250,00 fee + 25,50 diesel; the 500,00 deposit is not in it.
        assert Decimal(str(body["gesamtbetrag"])) == Decimal("275.50")

        body = self._save(
            event,
            sonderleistungen=[
                {"description": "Diesel", "amount": "25.50"},
                {"description": "Endreinigung", "amount": "40.00"},
            ],
        )
        assert Decimal(str(body["gesamtbetrag"])) == Decimal("315.50")


# --- rendering ----------------------------------------------------------------


class TestRender(CharterBase):
    def test_an_incomplete_form_is_refused_with_a_german_field_list(self):
        event = self._store_event()
        created = self.client.put(
            self._url(event),
            json={"charterer_name": "Frieda Beispiel"},
        )
        assert created.status_code == 200, created.text

        response = self.client.post(self._url(event, "/render"))

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail.startswith("Es fehlen noch Angaben: ")
        # German field names, not attribute names — the sentence is printed to
        # the organiser as it stands.
        for missing in (
            "Anschrift des Charterers",
            "Übergabe",
            "Rückgabe",
            "Chartergebühr",
            "Kaution",
            "Personenzahl ohne Skipper",
        ):
            assert missing in detail
        assert "charterer_address" not in detail
        # What is filled in is not named.
        assert "Name des Charterers" not in detail

        # Refused means nothing was produced.
        assert self._keys() == set()
        assert self.client.get(self._url(event)).json()["document_version"] == 0

    def test_a_licence_is_only_demanded_when_the_skipper_is_someone_else(self):
        event = self._store_event()
        self._save(event, skipper_is_charterer=False, skipper_name="Jonas Deich")

        response = self.client.post(self._url(event, "/render"))

        assert response.status_code == 422
        assert "Führerschein (SBFS oder SBFB)" in response.json()["detail"]

    def test_a_second_render_produces_v2_and_leaves_v1_alone(self):
        event = self._store_event()
        self._save(event)

        first = self._render(event)
        assert first["document_version"] == 1
        v1_key = first["document_key"]
        assert v1_key.endswith("/v1.pdf")
        v1_bytes = self.s3.get_object(Bucket=BUCKET, Key=v1_key)["Body"].read()
        assert v1_bytes.startswith(b"%PDF-")

        # The form moves on between the two renders, so the sheets genuinely
        # differ and an overwrite would be detectable rather than a no-op.
        self._save(event, chartergebuehr="300.00")
        second = self._render(event)

        assert second["document_version"] == 2
        v2_key = second["document_key"]
        assert v2_key.endswith("/v2.pdf")
        assert v2_key != v1_key
        assert self._keys() == {v1_key, v2_key}

        # v1 is byte-for-byte what it was: the printed copy somebody is holding
        # is still the document the row described when it was printed.
        assert self.s3.get_object(Bucket=BUCKET, Key=v1_key)["Body"].read() == v1_bytes
        assert first["document_sha256"] != second["document_sha256"]

    def test_the_render_freezes_the_total_and_the_retention_deadline(self):
        event = self._store_event()
        self._save(event)

        rendered = self._render(event)

        assert Decimal(str(rendered["gesamtbetrag"])) == Decimal("275.50")
        # 31 December of the handover year plus ten.
        assert rendered["retention_until"] == "2036-12-31"
        assert rendered["template_version"]


# --- the signature -------------------------------------------------------------


class TestSignature(CharterBase):
    def test_signed_is_reached_without_a_countersignature(self):
        event = self._store_event()
        self._save(event)
        self._render(event)

        signed = self._sign(event)

        assert signed["status"] == CharterStatus.SIGNED.value
        assert signed["signed_on"] == "2026-06-13"
        assert signed["signed_document_key"].endswith("/v1-signiert.pdf")
        assert signed["signed_document_sha256"]
        assert signed["signed_document_bytes"] == len(b"scanned-signature-page")
        # The Vercharterer's line is blank and nothing waited for it.
        assert signed["countersigned_on"] is None
        assert signed["countersigned_by"] is None

    def test_a_later_countersignature_changes_neither_status_nor_hash(self):
        event = self._store_event()
        self._save(event)
        self._render(event)
        signed = self._sign(event)

        response = self.client.post(
            self._url(event, "/gegenzeichnung"),
            json={"countersigned_on": "2026-08-01"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["countersigned_on"] == "2026-08-01"
        assert body["countersigned_by"] == "orga@example.com"
        # The countersignature is a separate fact about a separate line.
        assert body["status"] == signed["status"] == CharterStatus.SIGNED.value
        assert body["signed_document_sha256"] == signed["signed_document_sha256"]
        assert body["signed_document_key"] == signed["signed_document_key"]
        assert body["signed_on"] == signed["signed_on"]
        assert body["document_sha256"] == signed["document_sha256"]

    def test_a_signed_contract_cannot_be_edited(self):
        event = self._store_event()
        self._save(event)
        self._render(event)
        self._sign(event)

        response = self.client.put(self._url(event), json=self._payload(charterer_name="Jemand"))

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Ein unterschriebener Vertrag kann nicht geändert werden. "
            "Zum Korrigieren zuerst die Unterschrift verwerfen."
        )
        # The refusal was not half-applied.
        current = self.client.get(self._url(event)).json()
        assert current["charterer_name"] == "Frieda Beispiel"
        assert current["can_edit"] is False

    def test_confirming_without_an_uploaded_object_is_a_404(self):
        event = self._store_event()
        self._save(event)
        self._render(event)

        # The upload permission is minted but the browser never posted.
        assert self.client.post(self._url(event, "/upload"), json={}).status_code == 200

        response = self.client.post(
            self._url(event, "/signiert"),
            json={"signed_on": "2026-06-13", "alle_parteien_unterschrieben": True},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Die hochgeladene Datei ist nicht angekommen. Bitte den Upload wiederholen."
        )
        assert self.client.get(self._url(event)).json()["status"] == CharterStatus.DRAFT.value

    def test_discarding_a_signature_keeps_the_old_key_and_deletes_nothing(self):
        event = self._store_event()
        self._save(event)
        self._render(event)
        signed = self._sign(event)
        old_key = signed["signed_document_key"]
        keys_before = self._keys()

        response = self.client.post(self._url(event, "/unsign"))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == CharterStatus.DRAFT.value
        assert body["signed_document_key"] is None
        assert body["signed_document_sha256"] is None
        assert body["superseded_signed_keys"] == [old_key]
        assert body["can_edit"] is True

        # Nothing left the bucket — with a signed contract the bytes are the
        # agreement, so the superseded scan stays readable forever.
        assert self._keys() == keys_before
        assert self._object_exists(old_key)

    def test_a_discarded_signature_can_be_replaced_and_both_keys_are_kept(self):
        event = self._store_event()
        self._save(event)
        self._render(event)
        first_key = self._sign(event)["signed_document_key"]
        self.client.post(self._url(event, "/unsign"))

        # Correcting the contract means a new sheet: render v2, sign that.
        self._save(event, chartergebuehr="300.00")
        self._render(event)
        second = self._sign(event, signed_on="2026-06-14")

        assert second["signed_document_key"].endswith("/v2-signiert.pdf")
        assert second["superseded_signed_keys"] == [first_key]
        assert self._object_exists(first_key)


# --- who may do what ----------------------------------------------------------


class TestAuthorisation(CharterBase):
    def test_a_festival_cannot_carry_a_contract(self):
        event = self._store_event(
            event_type=EventType.FESTIVAL,
            end_at=NOW + timedelta(days=12),
        )

        response = self.client.put(self._url(event), json=self._payload())

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Ein Chartervertrag kann nur zu einer Einzelfahrt angelegt werden."
        )
        # PUT is the only route that can create a row, so refusing it here means
        # a festival can never acquire one at all.
        assert self.client.get(self._url(event)).status_code == 404

    def test_a_viewer_may_read_the_contract_and_the_pdf(self):
        event = self._store_event()
        self._save(event)
        self._render(event)

        self.role = AdminRole.VIEWER

        assert self.client.get(self._url(event)).status_code == 200
        pdf = self.client.get(self._url(event, "/pdf"), follow_redirects=False)
        assert pdf.status_code == 302
        assert BUCKET in pdf.headers["location"]

    def test_a_viewer_may_write_nothing(self):
        event = self._store_event()
        before = self._save(event)
        self._render(event)

        self.role = AdminRole.VIEWER

        writes = [
            self.client.put(self._url(event), json=self._payload(charterer_name="Jemand")),
            self.client.post(self._url(event, "/render")),
            self.client.post(self._url(event, "/senden")),
            self.client.post(self._url(event, "/upload"), json={}),
            self.client.post(
                self._url(event, "/signiert"),
                json={"signed_on": "2026-06-13", "alle_parteien_unterschrieben": True},
            ),
            self.client.post(
                self._url(event, "/gegenzeichnung"),
                json={"countersigned_on": "2026-06-13"},
            ),
            self.client.post(self._url(event, "/unsign")),
            self.client.delete(self._url(event)),
        ]
        assert [r.status_code for r in writes] == [403] * 8

        # Nothing moved behind the refusals: still v1, still the same name.
        self.role = AdminRole.ADMIN
        current = self.client.get(self._url(event)).json()
        assert current["charterer_name"] == before["charterer_name"]
        assert current["document_version"] == 1
        assert current["status"] == CharterStatus.DRAFT.value

    @pytest.mark.parametrize("role", [AdminRole.OWNER, AdminRole.ADMIN])
    def test_owners_and_admins_may_write(self, role):
        event = self._store_event()
        self.role = role
        assert self.client.put(self._url(event), json=self._payload()).status_code == 200

    def test_another_organisation_finds_nothing(self):
        event = self._store_event()
        self._save(event)

        self.org_id = uuid4()  # same event id, a different organisation's admin

        assert self.client.get(self._url(event)).status_code == 404
        assert self.client.put(self._url(event), json=self._payload()).status_code == 404
        assert self.client.post(self._url(event, "/render")).status_code == 404


# --- the trip report coupling --------------------------------------------------


class TestFahrberichtCoupling(CharterBase):
    """Spec 025 hangs the reminder on the one habit that follows every trip.

    The trip report's own submission logic is `fahrbericht_service`'s business
    and is stubbed out here — what these tests are about is whether the charter
    row lets the submission run at all, and what it records when it does.
    """

    @pytest.fixture(autouse=True)
    def stub_the_report(self, monkeypatch):
        import app.api.admin.fahrbericht as fahrbericht_module
        from app.models.fahrbericht import FahrberichtResponse, SubmitResult

        self.submissions: list = []

        class _StubService:
            def __init__(self, sink):
                self._sink = sink

            async def submit(self, event_id, *, org_id, submitted_by):
                self._sink.append(event_id)
                return SubmitResult(fahrbericht=FahrberichtResponse(event_id=event_id))

        monkeypatch.setattr(
            fahrbericht_module,
            "get_fahrbericht_service",
            lambda: _StubService(self.submissions),
        )

    def _submit(self, event: Event, body: dict | None = None):
        return self.client.post(
            f"/api/admin/events/{event.id}/fahrbericht/submit",
            json=body,
        )

    def test_a_trip_without_a_contract_is_untouched(self):
        event = self._store_event()

        response = self._submit(event)

        assert response.status_code == 200, response.text
        assert self.submissions == [event.id]

    def test_an_unsigned_contract_blocks_the_submission(self):
        event = self._store_event()
        self._store_contract(event.id)

        response = self._submit(event)

        assert response.status_code == 409
        assert response.json()["detail"] == "chartervertrag_fehlt"
        assert self.submissions == []

    def test_the_override_files_the_report_and_records_who_waived_it(self):
        event = self._store_event()
        self._store_contract(event.id)

        response = self._submit(event, {"ohne_vertrag_abgeben": True})

        assert response.status_code == 200, response.text
        assert self.submissions == [event.id]

        contract = self._contract_row(event.id)
        assert contract.fahrbericht_override_by == "orga@example.com"
        assert contract.fahrbericht_override_at is not None
        # Nothing else moved: the waiver is a note, not a signature.
        assert contract.status is CharterStatus.DRAFT
        assert contract.signed_document_key is None

    def test_a_signed_contract_passes_through_without_a_stamp(self):
        event = self._store_event()
        self._store_contract(
            event.id,
            status=CharterStatus.SIGNED,
            signed_on=date(2026, 6, 13),
            signed_document_key="contracts/x/v1-signiert.pdf",
        )

        response = self._submit(event)

        assert response.status_code == 200, response.text
        assert self.submissions == [event.id]
        assert self._contract_row(event.id).fahrbericht_override_by is None


# --- anonymisation -------------------------------------------------------------


class TestAnonymizationLeavesTheContractAlone(CharterBase):
    """The regression test spec 025 asks for, in so many words.

    `anonymize_event` runs four named scrub passes and no generic prefix sweep,
    so a `CHARTER` row survives it by construction. That is the wanted
    behaviour — a contract is an accounting record, not a guest list — but „by
    construction" is exactly the kind of property somebody removes by adding a
    tidy generic sweep later. Hence a test that fails when they do.
    """

    @pytest.fixture(autouse=True)
    def wire_the_sweep(self):
        self.anonymizer = AnonymizationService()
        self.anonymizer._events_table = self.events_table
        self.anonymizer._registrations_table = self.tables["registrations_table"]
        self.anonymizer._messages_table = self.tables["messages_table"]
        self.anonymizer._lost_and_found = self._lnf_service()
        self.anonymizer._event_photos = self._photo_service()

    async def test_name_address_and_licence_numbers_survive_the_sweep(self):
        event = self._store_event(
            status=EventStatus.COMPLETED,
            start_at=NOW - timedelta(days=200),
            registration_deadline=NOW - timedelta(days=210),
        )
        self._store_contract(
            event.id,
            charterer_name="Frederik Klein",
            charterer_address="Deichstraße 7\n21107 Hamburg",
            charterer_email="frederik@example.com",
            charterer_phone="+49 170 1234567",
            skipper_name="Jonas Deich",
            skipper_is_charterer=False,
            sbfs_number="S190168991",
            sbfs_issued_on=date(2023, 10, 9),
            sbfb_number="B240112233",
            sbfb_issued_on=date(2024, 1, 12),
            status=CharterStatus.SIGNED,
            signed_on=date(2026, 6, 13),
            signed_document_key="contracts/x/v1-signiert.pdf",
        )

        # The same person also registered for the trip. Their `REG#` row is
        # pseudonymised, and the contract's own denormalised copy is what keeps
        # it from being hollowed out.
        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name="Frederik Klein",
            email="frederik@example.com",
            group_size=1,
            status=RegistrationStatus.PARTICIPATING,
            registration_token=f"tok-{uuid4()}",
            registered_at=NOW - timedelta(days=205),
        )
        self.tables["registrations_table"].put_item(Item=_registration_to_item(registration))

        result = await self.anonymizer.anonymize_event(event)
        assert result.completed

        scrubbed = _item_to_registration(
            self.tables["registrations_table"].get_item(
                Key={"pk": f"EVENT#{event.id}", "sk": f"REG#{registration.id}"},
            )["Item"],
        )
        assert scrubbed.name != "Frederik Klein"

        contract = self._contract_row(event.id)
        assert contract is not None
        assert contract.charterer_name == "Frederik Klein"
        assert contract.charterer_address == "Deichstraße 7\n21107 Hamburg"
        assert contract.sbfs_number == "S190168991"
        assert contract.sbfb_number == "B240112233"
        # The rest of the row is untouched too — the point is that the sweep
        # does not see this partition at all, not that it spares three fields.
        assert contract.skipper_name == "Jonas Deich"
        assert str(contract.charterer_email) == "frederik@example.com"
        assert contract.charterer_phone == "+49 170 1234567"
        assert contract.status is CharterStatus.SIGNED


# --- retention -----------------------------------------------------------------


class TestDeletionIsRefusedWithinRetention(CharterBase):
    """Both delete paths, because both leave the contract's partition standing.

    `delete_event` removes exactly one item under `pk=ORG#{org_id}`;
    `delete_festival_event` adds prefix purges for INVITE#/REG#/SCAN#/MSG#.
    Neither touches `EVENT#{id} / CHARTER`, so without the guard the contract
    outlives the event as an orphan carrying a name, a postal address and two
    licence numbers — worse than deleting it, not better.
    """

    def _signed(self, event: Event, *, retention_until: date) -> None:
        self._store_contract(
            event.id,
            status=CharterStatus.SIGNED,
            signed_on=date(2026, 6, 13),
            signed_document_key="contracts/x/v1-signiert.pdf",
            retention_until=retention_until,
        )

    async def test_delete_event_refuses_while_the_deadline_is_ahead(self):
        event = self._store_event(status=EventStatus.CANCELLED)
        self._signed(event, retention_until=date(date.today().year + 10, 12, 31))

        with pytest.raises(ValueError) as raised:
            await self.event_service.delete_event(self.org_id, event.id)

        assert str(raised.value) == CHARTER_NOT_DELETED
        assert await self.event_service.get_event(self.org_id, event.id) is not None
        assert self._contract_row(event.id) is not None

    async def test_delete_festival_event_refuses_too(self):
        event = self._store_event(
            status=EventStatus.CANCELLED,
            event_type=EventType.FESTIVAL,
            end_at=NOW + timedelta(days=12),
        )
        self._signed(event, retention_until=date(date.today().year + 10, 12, 31))

        with pytest.raises(ValueError) as raised:
            await self.event_service.delete_festival_event(self.org_id, event.id)

        assert str(raised.value) == CHARTER_NOT_DELETED
        assert await self.event_service.get_event(self.org_id, event.id) is not None

    async def test_nothing_blocks_once_the_deadline_has_passed(self):
        event = self._store_event(status=EventStatus.CANCELLED)
        self._signed(event, retention_until=date(2020, 12, 31))

        assert await self.event_service.delete_event(self.org_id, event.id) is True

    async def test_an_unsigned_draft_never_blocks(self):
        event = self._store_event(status=EventStatus.CANCELLED)
        self._store_contract(event.id)

        assert await self.event_service.delete_event(self.org_id, event.id) is True

    def test_the_route_names_the_year_the_organiser_has_to_wait_for(self):
        event = self._store_event(status=EventStatus.CANCELLED)
        self._signed(event, retention_until=date(2036, 12, 31))

        response = self.client.delete(f"/api/admin/events/{event.id}")

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Das Event hat einen unterschriebenen Chartervertrag und kann bis 2036 "
            "nicht gelöscht werden."
        )
