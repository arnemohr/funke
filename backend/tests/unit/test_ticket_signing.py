"""Tests for the stateless HMAC ticket signing/verification util (spec 019 §T304)."""

from uuid import uuid4

from app.services.ticket_signing import (
    build_person_tickets,
    generate_qr_png,
    sign_ticket,
    verify_ticket,
)

SECRET_A = "a-secret-for-event-a-1234567890"
SECRET_B = "a-different-secret-for-event-b-"


class TestRoundTrip:
    """Sign -> verify returns the exact payload."""

    def test_round_trip_basic(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Max Mustermann", ["fr-abend", "sa-tag"], overnight_approved=False)
        payload = verify_ticket(SECRET_A, code)

        assert payload == {
            "r": str(rid),
            "p": 0,
            "n": "Max Mustermann",
            "s": ["fr-abend", "sa-tag"],
            "o": False,
        }

    def test_round_trip_umlaut_name(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 1, "Jörg Müller", ["sa-tag"])
        payload = verify_ticket(SECRET_A, code)

        assert payload is not None
        assert payload["n"] == "Jörg Müller"
        assert payload["r"] == str(rid)
        assert payload["p"] == 1

    def test_round_trip_empty_slots_none(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Anna Meier", None)
        payload = verify_ticket(SECRET_A, code)

        assert payload is not None
        assert payload["s"] == []

    def test_round_trip_empty_slots_list(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Anna Meier", [])
        payload = verify_ticket(SECRET_A, code)

        assert payload is not None
        assert payload["s"] == []

    def test_round_trip_overnight_true(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Ben Otto", ["fr-abend"], overnight_approved=True)
        payload = verify_ticket(SECRET_A, code)

        assert payload is not None
        assert payload["o"] is True

    def test_round_trip_overnight_false(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Ben Otto", ["fr-abend"], overnight_approved=False)
        payload = verify_ticket(SECRET_A, code)

        assert payload is not None
        assert payload["o"] is False


class TestTamperAndWrongSecret:
    def test_tampered_payload_segment(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Max Mustermann", ["fr-abend"])
        prefix, payload_b64, mac_b64 = code.split(".")

        # Flip a single character in the payload segment.
        flipped_char = "A" if payload_b64[0] != "A" else "B"
        tampered_payload = flipped_char + payload_b64[1:]
        tampered_code = f"{prefix}.{tampered_payload}.{mac_b64}"

        assert verify_ticket(SECRET_A, tampered_code) is None

    def test_wrong_secret(self):
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Max Mustermann", ["fr-abend"])

        assert verify_ticket("completely-wrong-secret-value-x", code) is None

    def test_foreign_event_secret_does_not_verify(self):
        """A ticket signed with event A's secret must not verify under event B's."""
        rid = uuid4()
        code = sign_ticket(SECRET_A, rid, 0, "Max Mustermann", ["fr-abend"])

        assert verify_ticket(SECRET_B, code) is None
        # Sanity: it does verify under its own secret.
        assert verify_ticket(SECRET_A, code) is not None


class TestGarbageInputs:
    def test_empty_string(self):
        assert verify_ticket(SECRET_A, "") is None

    def test_prefix_only(self):
        assert verify_ticket(SECRET_A, "FUNKE1") is None

    def test_wrong_prefix(self):
        assert verify_ticket(SECRET_A, "FUNKE2.x.y") is None

    def test_non_base64_segments(self):
        assert verify_ticket(SECRET_A, "FUNKE1.not-valid-b64!!!.also-not-valid!!!") is None

    def test_too_many_segments(self):
        assert verify_ticket(SECRET_A, "FUNKE1.a.b.c") is None

    def test_too_few_segments(self):
        assert verify_ticket(SECRET_A, "FUNKE1.a") is None


class TestBuildPersonTickets:
    """T312: shared per-person ticket builder used by both the manage-page
    QR display and the confirmation email's inline QR images."""

    def test_contact_only_no_group_members(self):
        rid = uuid4()
        tickets = build_person_tickets(SECRET_A, rid, "Anna Meier", None, ["fr"])

        assert len(tickets) == 1
        assert tickets[0].person_index == 0
        assert tickets[0].name == "Anna Meier"
        assert verify_ticket(SECRET_A, tickets[0].code)["n"] == "Anna Meier"

    def test_contact_plus_group_members_indexed_from_one(self):
        rid = uuid4()
        tickets = build_person_tickets(
            SECRET_A, rid, "Anna Meier", ["Bob Fisch", "Carla Muschel"], ["fr"],
        )

        assert [t.person_index for t in tickets] == [0, 1, 2]
        assert [t.name for t in tickets] == ["Anna Meier", "Bob Fisch", "Carla Muschel"]

    def test_none_tombstone_skipped_but_index_preserved(self):
        rid = uuid4()
        tickets = build_person_tickets(
            SECRET_A, rid, "Anna Meier", ["Bob Fisch", None, "Carla Muschel"], ["fr"],
        )

        # Tombstoned member (index 1) is skipped, but Carla keeps index 2 —
        # indices are never reindexed after a removal.
        assert [t.person_index for t in tickets] == [0, 1, 3]
        assert [t.name for t in tickets] == ["Anna Meier", "Bob Fisch", "Carla Muschel"]

    def test_each_code_verifies_under_the_same_secret(self):
        rid = uuid4()
        tickets = build_person_tickets(
            SECRET_A, rid, "Anna Meier", ["Bob Fisch"], ["fr", "sa"], overnight_approved=True,
        )

        for ticket in tickets:
            payload = verify_ticket(SECRET_A, ticket.code)
            assert payload is not None
            assert payload["r"] == str(rid)
            assert payload["p"] == ticket.person_index
            assert payload["o"] is True


class TestGenerateQrPng:
    """T312: PNG QR image generation for embedding in the confirmation email."""

    def test_returns_valid_png_bytes(self):
        png = generate_qr_png("FUNKE1.abc.def")

        assert png.startswith(b"\x89PNG\r\n\x1a\n")  # PNG magic number

    def test_different_codes_yield_different_images(self):
        png_a = generate_qr_png("FUNKE1.aaa.bbb")
        png_b = generate_qr_png("FUNKE1.ccc.ddd")

        assert png_a != png_b
