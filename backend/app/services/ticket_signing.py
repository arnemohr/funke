"""Stateless HMAC-signed check-in ticket util (spec 019 §P3).

QR codes handed to guests encode a small signed payload rather than a
lookup key, so verification never needs a database round-trip and works
immediately for every existing registration (no `person_tokens` field, no
backfill migration).

Format: ``FUNKE1.<payload_b64>.<mac_b64>``

- ``payload_b64`` is the URL-safe, unpadded base64 encoding of
  ``json.dumps({"r": ..., "p": ..., "n": ..., "s": ..., "o": ...},
  separators=(",", ":"), ensure_ascii=False)`` — compact, UTF-8-safe JSON
  (umlauts etc. are emitted literally, not escaped).
- ``mac_b64`` is the URL-safe, unpadded base64 encoding of the first 16
  bytes of ``hmac.new(secret.encode(), payload_b64.encode(),
  hashlib.sha256).digest()``.

**Critical: the MAC is computed over the ASCII bytes of the b64url
``payload_b64`` segment itself — NOT over the raw JSON bytes.** The
scanner's offline JS verifier (T311) must replicate this exact rule
(sign the base64 string, not the pre-encoded payload) or every ticket
will fail to verify client-side.

Payload keys:
- ``r``: registration id (str)
- ``p``: person index — ``0`` = the registration contact, ``1..`` =
  ``group_members[p - 1]``
- ``n``: the person's name at signing time (used for the index-stability
  / "stale ticket" check, spec.md:289)
- ``s``: attendance slot keys (``[]`` if none) — informational only, never
  enforced at the gate (Ä13)
- ``o``: ``overnight_approved`` at signing time (Ä17) — serves the
  OFFLINE card only; the online scan always renders the *current*
  registration's overnight status, not this snapshot.
"""

import base64
import hashlib
import hmac
import io
import json
from dataclasses import dataclass
from uuid import UUID

import qrcode

TICKET_PREFIX = "FUNKE1"


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """URL-safe base64 decode, restoring the padding stripped at encode time."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign_ticket(
    secret: str,
    registration_id: UUID | str,
    person_index: int,
    name: str,
    attendance_slots: list[str] | None,
    overnight_approved: bool = False,
) -> str:
    """Sign a check-in ticket for one person on a registration.

    Args:
        secret: The event's `ticket_secret`.
        registration_id: The registration id.
        person_index: 0 = contact, 1.. = group_members[p-1].
        name: The person's current name (for stale-ticket detection).
        attendance_slots: The registration's attendance slot keys (or None).
        overnight_approved: The registration's overnight approval flag (Ä17).

    Returns:
        The `FUNKE1.<payload_b64>.<mac_b64>` ticket code.
    """
    payload = {
        "r": str(registration_id),
        "p": person_index,
        "n": name,
        "s": attendance_slots or [],
        "o": overnight_approved,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = _b64url_encode(payload_json.encode("utf-8"))

    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()[:16]
    mac_b64 = _b64url_encode(mac)

    return f"{TICKET_PREFIX}.{payload_b64}.{mac_b64}"


def verify_ticket(secret: str, code: str) -> dict | None:
    """Verify a ticket code and return its payload, or None on any failure.

    Args:
        secret: The event's `ticket_secret` to verify against.
        code: The ticket code to verify.

    Returns:
        The decoded payload dict on success, None on any failure (malformed
        code, wrong prefix, bad base64, bad signature).
    """
    try:
        parts = code.split(".")
        if len(parts) != 3:
            return None

        prefix, payload_b64, mac_b64 = parts
        if prefix != TICKET_PREFIX:
            return None

        expected_mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()[:16]
        actual_mac = _b64url_decode(mac_b64)

        if not hmac.compare_digest(expected_mac, actual_mac):
            return None

        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return None

        return payload

    except Exception:
        return None


def person_page_token(registration_token: str, person_index: int) -> str:
    """Derive a read-only capability token for one person's ticket page (spec 020).

    Companions who supplied an address are mailed a link to their own ticket
    page. They must NOT get the group's `registration_token` — that one can
    edit slots, rename people and cancel the entire registration.

    Derived from the **registration token**, deliberately NOT from
    `event.ticket_secret`: the ticket secret is handed to every gate client by
    the scanner boot call (spec 019 Risk #6), so a person token derived from it
    would be forgeable by anyone holding a gate link. HMAC is one-way, so a
    leaked person token reveals nothing about the group token and grants no
    write capability anywhere.

    Stateless — nothing is stored, it works for every pre-existing
    registration, and it stays stable across slot and name edits (unlike the
    ticket code itself, which re-signs on every change).
    """
    mac = hmac.new(
        registration_token.encode("utf-8"),
        f"P{person_index}".encode("ascii"),
        hashlib.sha256,
    ).digest()[:16]
    return _b64url_encode(mac)


def verify_person_page_token(
    registration_token: str,
    person_index: int,
    token: str,
) -> bool:
    """Constant-time check of a `person_page_token`."""
    if not token:
        return False
    expected = person_page_token(registration_token, person_index)
    return hmac.compare_digest(expected, token)


@dataclass(frozen=True)
class SignedTicket:
    """One person's freshly-signed check-in ticket."""

    person_index: int
    name: str
    code: str


def build_person_tickets(
    secret: str,
    registration_id: UUID | str,
    contact_name: str,
    group_members: list[str | None] | None,
    attendance_slots: list[str] | None,
    overnight_approved: bool = False,
) -> list[SignedTicket]:
    """Build freshly-signed per-person tickets for a registration.

    Person 0 = `contact_name` (the registrant); person `i+1` = each non-`None`
    entry of `group_members`. `None` tombstone entries (removed members) are
    skipped, but later members keep their original index — indices are never
    reindexed. Shared by the manage-page QR display and the confirmation
    email so both encode identical payloads.
    """
    tickets = [
        SignedTicket(
            person_index=0,
            name=contact_name,
            code=sign_ticket(
                secret, registration_id, 0, contact_name, attendance_slots, overnight_approved,
            ),
        ),
    ]
    for i, member_name in enumerate(group_members or []):
        if member_name is None:
            continue
        tickets.append(
            SignedTicket(
                person_index=i + 1,
                name=member_name,
                code=sign_ticket(
                    secret, registration_id, i + 1, member_name,
                    attendance_slots, overnight_approved,
                ),
            ),
        )
    return tickets


def generate_qr_png(code: str, *, box_size: int = 8, border: int = 2) -> bytes:
    """Render a ticket code as a PNG QR code image, ready for email embedding."""
    img = qrcode.make(code, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
