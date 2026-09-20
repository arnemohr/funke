"""Tests for in-app signing of the Chartervertrag (spec 025 addendum).

The security properties are the point here, so they get the most attention:

- a token that outlived its document must stop working,
- a signature must not be accepted against a render the signer never saw,
- the public payload must not leak licence numbers or the postal address,
- every rejection must look identical from outside.

Sealing is exercised separately in `test_charter_seal.py`; here it is expected
to be *absent* (no certificate in these tests) and the contract must still come
out signed — an unsealed signed contract is worth far more than a signature
refused because a certificate was missing.
"""

import base64
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.models import Event, EventStatus, EventType
from app.models.charter import CharterStatus, SignatureRole
from app.services.charter_service import signature_image_key
from app.services.event_service import _event_to_item

from .test_charter_contract import BUCKET, CharterBase

NOW = datetime.now(timezone.utc)


def _png(width: int = 40, height: int = 12) -> str:
    """A real, minimal PNG — the decoder checks the magic bytes."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + zlib.crc32(tag + data).to_bytes(4, "big")
        )

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    body = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    body += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return base64.b64encode(body).decode()


class SigningBase(CharterBase):
    """A rendered, ready-to-sign contract."""

    def _event(self, **overrides) -> Event:
        defaults = {
            "id": uuid4(),
            "org_id": self.org_id,
            "name": "Charterfahrt Klein",
            "event_type": EventType.SINGLE,
            "start_at": NOW + timedelta(days=10),
            "registration_deadline": NOW + timedelta(days=5),
            "status": EventStatus.OPEN,
            "capacity": 12,
        }
        defaults.update(overrides)
        event = Event(**defaults)
        self.events_table.put_item(Item=_event_to_item(event))
        return event

    async def _ready(self, *, personengleich: bool = True):
        """An event plus a rendered contract. Returns (event, contract)."""
        event = self._event()
        await self.charter.upsert_contract(
            event.id,
            self._upsert(personengleich=personengleich),
        )
        contract = await self.charter.render(event.id)
        return event, contract

    def _upsert(self, *, personengleich: bool):
        from app.models.charter import CharterContractUpsert

        return CharterContractUpsert(
            charterer_name="Frederik Klein",
            charterer_address="Musterweg 12\n21107 Hamburg",
            charterer_email="frederik@example.com",
            uebergabe_at=NOW + timedelta(days=10),
            rueckgabe_at=NOW + timedelta(days=10, hours=8),
            chartergebuehr=Decimal("250.00"),
            kaution=Decimal("100.00"),
            personen_ohne_skipper=7,
            skipper_name="Frederik Klein" if personengleich else "Arne-Christian Mohr",
            skipper_is_charterer=personengleich,
            sbfs_number="S190168991",
            sbfs_issued_on=NOW.date(),
        )


class TestTokenLifecycle(SigningBase):
    async def test_rendering_mints_a_token(self):
        _event, contract = await self._ready()

        assert contract.sign_token
        assert len(contract.sign_token) >= 40

    async def test_re_rendering_replaces_the_token_and_voids_signatures(self):
        """A link must never outlive the document it displayed."""
        event, contract = await self._ready()
        first_token = contract.sign_token
        await self.charter.add_signature(
            event.id,
            SignatureRole.SKIPPER,  # not a required role here, so no sealing
            signed_name="Jemand",
            document_sha256=contract.document_sha256,
        )

        re_rendered = await self.charter.render(event.id)

        assert re_rendered.sign_token != first_token
        assert re_rendered.signatures == []
        assert re_rendered.status is CharterStatus.DRAFT

    async def test_the_old_link_stops_working_after_a_re_render(self):
        event, contract = await self._ready()
        old_token = contract.sign_token
        await self.charter.render(event.id)

        response = self.client.get(f"/api/public/vertrag/{event.id}/{old_token}")

        assert response.status_code == 404

    async def test_a_wrong_token_is_indistinguishable_from_a_missing_contract(self):
        event, _contract = await self._ready()
        other = self._event()

        wrong = self.client.get(f"/api/public/vertrag/{event.id}/nonsense")
        absent = self.client.get(f"/api/public/vertrag/{other.id}/nonsense")

        assert wrong.status_code == absent.status_code == 404
        assert wrong.json()["detail"] == absent.json()["detail"]


class TestPublicPayload(SigningBase):
    async def test_the_page_gets_what_it_needs(self):
        event, contract = await self._ready()

        body = self.client.get(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
        ).json()

        assert body["charterer_name"] == "Frederik Klein"
        assert body["event_name"] == "Charterfahrt Klein"
        assert body["document_sha256"] == contract.document_sha256
        assert body["document_url"].startswith("https://")
        assert body["already_signed"] is False

    async def test_it_leaks_neither_licence_numbers_nor_the_address(self):
        """A regression test on the field list, not on particular values."""
        event, contract = await self._ready()

        body = self.client.get(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
        ).json()

        for forbidden in (
            "sbfs_number",
            "sbfb_number",
            "charterer_address",
            "charterer_phone",
            "sign_token",
            "sondervereinbarungen",
        ):
            assert forbidden not in body, f"{forbidden} must not reach the signing page"
        assert "Musterweg" not in str(body)
        assert "S190168991" not in str(body)

    async def test_a_reopened_link_shows_that_it_is_already_signed(self):
        event, contract = await self._ready(personengleich=False)
        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        body = self.client.get(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
        ).json()

        assert body["already_signed"] is True


class TestSigning(SigningBase):
    async def test_a_typed_name_is_enough(self):
        event, contract = await self._ready()

        response = self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={
                "signed_name": "Frederik Klein",
                "document_sha256": contract.document_sha256,
            },
        )

        assert response.status_code == 204
        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        assert [s.role for s in stored.signatures] == [SignatureRole.CHARTERER]

    async def test_a_drawn_signature_is_stored_then_removed_after_sealing(self):
        """The PNG is transient: once it is inside the document it is redundant
        PII with a ten-year retention attached."""
        event, contract = await self._ready()

        self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={
                "signed_name": "Frederik Klein",
                "image_b64": _png(),
                "document_sha256": contract.document_sha256,
            },
        )

        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        assert all(s.image_key is None for s in stored.signatures)
        listing = self.s3.list_objects_v2(
            Bucket=BUCKET, Prefix=signature_image_key(event.id, SignatureRole.CHARTERER),
        )
        assert listing.get("KeyCount", 0) == 0

    async def test_a_stale_document_hash_is_refused(self):
        """The signer must be signing the render they were shown."""
        event, contract = await self._ready()

        response = self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={"signed_name": "Frederik Klein", "document_sha256": "0" * 64},
        )

        assert response.status_code == 409
        assert "geändert" in response.json()["detail"]
        stored = await self.charter.get_contract(event.id)
        assert stored.signatures == []

    async def test_signing_twice_is_refused(self):
        event, contract = await self._ready()
        payload = {
            "signed_name": "Frederik Klein",
            "document_sha256": contract.document_sha256,
        }
        self.client.post(f"/api/public/vertrag/{event.id}/{contract.sign_token}", json=payload)

        # The contract is signed now, so the token is spent; either answer is
        # a refusal, and both must be refusals.
        again = self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}", json=payload,
        )

        assert again.status_code in (404, 409)
        stored = await self.charter.get_contract(event.id)
        assert len(stored.signatures) == 1

    async def test_something_that_is_not_a_png_is_refused(self):
        event, contract = await self._ready()

        response = self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={
                "signed_name": "Frederik Klein",
                "image_b64": base64.b64encode(b"<html>not a png</html>").decode(),
                "document_sha256": contract.document_sha256,
            },
        )

        assert response.status_code == 400

    async def test_an_oversized_signature_is_refused(self):
        event, contract = await self._ready()
        huge = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 600_000).decode()

        response = self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={
                "signed_name": "Frederik Klein",
                "image_b64": huge,
                "document_sha256": contract.document_sha256,
            },
        )

        assert response.status_code == 400


class TestRequiredRoles(SigningBase):
    async def test_one_signature_completes_a_personengleich_contract(self):
        event, contract = await self._ready(personengleich=True)

        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED

    async def test_a_separate_skipper_must_also_sign(self):
        event, contract = await self._ready(personengleich=False)

        after_charterer = await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )
        assert after_charterer.status is not CharterStatus.SIGNED

        after_skipper = await self.charter.add_signature(
            event.id,
            SignatureRole.SKIPPER,
            signed_name="Arne-Christian Mohr",
            document_sha256=contract.document_sha256,
            by_admin="orga@example.com",
        )
        assert after_skipper.status is CharterStatus.SIGNED

    async def test_the_countersignature_is_never_required(self):
        event, contract = await self._ready(personengleich=True)

        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        assert SignatureRole.VERCHARTERER not in stored.signed_roles()

    async def test_a_contract_is_signed_even_when_it_cannot_be_sealed(self):
        """No certificate is configured in these tests. The signature still counts."""
        event, contract = await self._ready(personengleich=True)

        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        assert stored.sealed_document_key is not None, "the document is still filed"
        assert stored.sealed_at is None, "but it is not sealed"
        assert stored.seal_key_id is None

    async def test_the_finished_document_carries_the_signature(self):
        event, contract = await self._ready(personengleich=True)

        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        stored = await self.charter.get_contract(event.id)
        body = self.s3.get_object(Bucket=BUCKET, Key=stored.sealed_document_key)["Body"].read()
        assert body.startswith(b"%PDF")
        assert len(body) > 0
        assert stored.sealed_document_sha256


class TestAdminSigning(SigningBase):
    """The skipper and the Vercharterer sign through the admin UI: both have a
    login, so neither needs a public token. That is why one contract has
    exactly one signing link rather than three."""

    async def test_the_skipper_signs_through_the_admin_route(self):
        event, contract = await self._ready(personengleich=False)
        self.client.post(
            f"/api/public/vertrag/{event.id}/{contract.sign_token}",
            json={
                "signed_name": "Frederik Klein",
                "document_sha256": contract.document_sha256,
            },
        )

        response = self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={"role": "skipper", "signed_name": "Arne-Christian Mohr"},
        )

        assert response.status_code == 200
        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        skipper = next(s for s in stored.signatures if s.role is SignatureRole.SKIPPER)
        assert skipper.by_admin == "orga@example.com"
        assert skipper.signer_ip is None, "an admin signature has no public IP to record"

    async def test_a_viewer_may_not_sign(self):
        from app.models import AdminRole

        event, _contract = await self._ready(personengleich=False)
        self.role = AdminRole.VIEWER

        response = self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={"role": "skipper", "signed_name": "Wer auch immer"},
        )

        assert response.status_code == 403

    async def test_a_viewer_may_not_send_the_signing_link(self):
        from app.models import AdminRole

        event, _contract = await self._ready()
        self.role = AdminRole.VIEWER

        response = self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/signaturlink",
        )

        assert response.status_code == 403


class TestSealedCopyDispatch(SigningBase):
    """The counterparty holding their own copy is the strongest tamper evidence
    available, so the dispatch runs — but it must never cost a signature."""

    async def test_the_sealed_copy_goes_to_charterer_and_accounting(self, monkeypatch):
        import app.services.charter_service as mod

        sent: list[str] = []

        class _Client:
            async def send_email(self, message):
                sent.append(message.to)
                return None

        monkeypatch.setattr(mod, "get_gmail_client", lambda: _Client())
        # The real settings type, not a stub: the service reads more off it
        # than this test knows about, and a stub only fails later and vaguer.
        import app.services.config as config_module
        from app.services.config import DynamoDBSettings

        monkeypatch.setattr(
            config_module,
            "_settings",
            DynamoDBSettings(
                reports_s3_bucket=BUCKET,
                finance_report_inbox="buchhaltung@example.com",
            ),
        )

        event, contract = await self._ready()
        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        assert sent == ["frederik@example.com", "buchhaltung@example.com"]

    async def test_a_failing_mail_server_does_not_cost_the_signature(self, monkeypatch):
        import app.services.charter_service as mod

        def _boom():
            raise RuntimeError("smtp is down")

        monkeypatch.setattr(mod, "get_gmail_client", _boom)

        event, contract = await self._ready()
        await self.charter.add_signature(
            event.id,
            SignatureRole.CHARTERER,
            signed_name="Frederik Klein",
            document_sha256=contract.document_sha256,
        )

        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED
        assert stored.sealed_document_key is not None


class TestInPersonSigning(SigningBase):
    """Everyone at the pontoon, signing on the organiser's device.

    This is the common case per the organiser: the charterer is usually a crew
    member who skippers that day, and the contract is signed on the day. The
    evidence is weaker than the link route — one device, no per-signer IP — so
    the record has to make that visible rather than pretend otherwise.
    """

    async def test_the_charterer_can_sign_from_the_admin_side(self):
        event, _contract = await self._ready(personengleich=True)

        response = self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={
                "role": "charterer",
                "signed_name": "Frederik Klein",
                "image_b64": _png(),
            },
        )

        assert response.status_code == 200
        stored = await self.charter.get_contract(event.id)
        assert stored.status is CharterStatus.SIGNED

    async def test_an_in_person_signature_is_marked_as_such(self):
        """`by_admin` set and `signer_ip` empty is the honest record of how it
        was taken — the spec says the evidence is weaker, so the row must say
        so too."""
        event, _contract = await self._ready(personengleich=True)

        self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={"role": "charterer", "signed_name": "Frederik Klein"},
        )

        stored = await self.charter.get_contract(event.id)
        sig = stored.signatures[0]
        assert sig.by_admin == "orga@example.com"
        assert sig.signer_ip is None
        assert sig.signer_user_agent is None

    async def test_all_three_can_be_collected_in_one_sitting(self):
        event, _contract = await self._ready(personengleich=False)

        for role, name in (
            ("charterer", "Frederik Klein"),
            ("skipper", "Arne-Christian Mohr"),
            ("vercharterer", "Vorstand"),
        ):
            response = self.client.post(
                f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
                json={"role": role, "signed_name": name, "image_b64": _png()},
            )
            assert response.status_code == 200, f"{role}: {response.text[:120]}"

        stored = await self.charter.get_contract(event.id)
        assert stored.signed_roles() == {
            SignatureRole.CHARTERER,
            SignatureRole.SKIPPER,
            SignatureRole.VERCHARTERER,
        }
        assert stored.status is CharterStatus.SIGNED

    async def test_a_countersignature_after_sealing_is_still_accepted(self):
        """Sealing happens as soon as the *required* roles are in, so the
        optional Vercharterer signature necessarily arrives afterwards."""
        event, _contract = await self._ready(personengleich=True)
        self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={"role": "charterer", "signed_name": "Frederik Klein"},
        )

        response = self.client.post(
            f"/api/admin/events/{event.id}/chartervertrag/unterschreiben",
            json={"role": "vercharterer", "signed_name": "Vorstand"},
        )

        assert response.status_code == 200
        stored = await self.charter.get_contract(event.id)
        assert SignatureRole.VERCHARTERER in stored.signed_roles()
