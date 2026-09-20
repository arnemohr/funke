"""Charter contract domain models (spec 025 — Chartervertrag).

One singleton row per event, co-located under the event's partition as
``EVENT#{event_id} / CHARTER`` — same shape as ``FAHRBERICHT``, ``LNF#CONFIG``
and ``PHOTOS#CONFIG``. A replacement contract is a new render of the same row,
never a second row.

The contract is filled in over several visits, so the draft row is legitimately
partial. Fields the spec's Datenmodell lists as non-optional are therefore typed
non-optional only where an empty value exists (``str`` → ``""``); where none
does (``datetime``, ``Decimal``, ``int``) they are ``| None``, so the render
step can tell „not filled in yet" from „deliberately zero" and name the missing
fields in German. The mandatory set is enforced at render time in the service,
not by this module — the same division of labour as
``LostAndFoundConfig``/``upsert_config``.

Serialisation to and from DynamoDB items lives in ``charter_service``, matching
the sibling specs; nothing in here knows about the table.

Immutable updates via ``model_copy(update={...})`` only.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# The money shape of the whole codebase — one `ExpenseLine`, not a second one
# invented here. Deliberately the Fahrbericht class, not the identically named
# one in `report.py`.
from .fahrbericht import ExpenseLine

# Written onto the item by the service; kept here so the model and the row
# agree on one spelling.
CHARTER_ENTITY_TYPE = "charter_contract"

CHARTERER_NAME_MAX_LENGTH = 200
# Multi-line — the first postal address in the domain, and four lines of a
# German address plus a company line fit comfortably in 400.
CHARTERER_ADDRESS_MAX_LENGTH = 400
SONDERVEREINBARUNGEN_MAX_LENGTH = 500
PHONE_MAX_LENGTH = 50
LICENCE_NUMBER_MAX_LENGTH = 50
# A day on a raft with a skipper; the boat does not hold more.
MAX_PERSONEN_OHNE_SKIPPER = 12

# Bookkeeping retention: 31 December of the handover year plus ten years. One
# flat period instead of separate six- and ten-year tax/commercial classes — a
# four-page PDF costs nothing, a misclassification does.
RETENTION_YEARS = 10
# The handover is stored in UTC but happens in Berlin, so the *year* that
# starts the retention clock has to be read in local time — a handover just
# after midnight on 1 January is otherwise filed under the previous year.
BERLIN_TZ = ZoneInfo("Europe/Berlin")


class CharterStatus(str, Enum):
    """Lifecycle of the contract row.

    ``DRAFT`` covers everything up to and including the first render — a PDF
    that exists but was never handed over is still a draft. ``SENT`` is set by
    the direct dispatch to the charterer, ``SIGNED`` by the confirmed upload of
    the scan. Lower-case values, unlike the other enums in this package: these
    strings are spelled out in spec 025 and appear in the admin UI's chip.
    """

    DRAFT = "draft"
    SENT = "sent"
    SIGNED = "signed"


class SignatureRole(str, Enum):
    """Who a signature belongs to.

    The Schiffsführer block only exists when the skipper is somebody other than
    the charterer; the Vercharterer block is always optional.
    """

    CHARTERER = "charterer"
    SKIPPER = "skipper"
    VERCHARTERER = "vercharterer"


class CharterSignature(BaseModel):
    """One signature, embedded in the contract row.

    There are at most three, so a separate partition would be ceremony. The
    fields beyond the name are what gives a simple electronic signature its
    evidential weight — above all `document_sha256`, which pins *which* render
    the person was actually shown.
    """

    model_config = ConfigDict(from_attributes=True)

    role: SignatureRole
    signed_name: str = Field(..., min_length=1, max_length=CHARTERER_NAME_MAX_LENGTH)
    # PNG of the drawn signature. Absent when the signer only typed a name —
    # deliberately allowed, because a finger-drawn scrawl on a phone is not
    # always possible and a typed name is the same eIDAS level anyway.
    image_key: str | None = None
    signed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    document_sha256: str = Field(..., max_length=64)
    signer_ip: str | None = Field(None, max_length=64)
    signer_user_agent: str | None = Field(None, max_length=200)
    # Set when an authenticated human signed in the admin UI rather than
    # through the public link.
    by_admin: str | None = None


class CharterContract(BaseModel):
    """The ``CHARTER`` row — the whole contract, draft or signed."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    status: CharterStatus = CharterStatus.DRAFT
    # Which set of clauses produced the PDF, e.g. "2026-01". Comes out of
    # `charter_template`, so it is unset until the first render — a reader in
    # 2033 needs to know which wording they are holding.
    template_version: str | None = Field(None, max_length=50)
    # 0 until the first render; every render mints a new n and a new object.
    document_version: int = Field(default=0, ge=0)

    # --- Charterer -------------------------------------------------------
    # Denormalised on purpose: spec 022's anonymisation pseudonymises the
    # `REG#` row, and the contract must not be hollowed out by that.
    charterer_name: str = Field(default="", max_length=CHARTERER_NAME_MAX_LENGTH)
    charterer_address: str = Field(default="", max_length=CHARTERER_ADDRESS_MAX_LENGTH)
    # Only needed to send the PDF; a contract handed over at the jetty has none.
    charterer_email: EmailStr | None = None
    charterer_phone: str | None = Field(None, max_length=PHONE_MAX_LENGTH)
    sondervereinbarungen: str | None = Field(None, max_length=SONDERVEREINBARUNGEN_MAX_LENGTH)

    # --- Charter period --------------------------------------------------
    # Both are entered by hand. `rueckgabe_at` is deliberately *not* derived
    # from `Event.end_at`: that is `None` on a SINGLE event and means something
    # else anyway.
    uebergabe_at: datetime | None = None
    rueckgabe_at: datetime | None = None

    # --- Money -----------------------------------------------------------
    chartergebuehr: Decimal | None = Field(None, ge=0)
    sonderleistungen: list[ExpenseLine] = Field(default_factory=list)
    kaution: Decimal | None = Field(None, ge=0)
    # Written by the renderer so the row keeps the number the PDF prints; the
    # API recomputes it live for the form. See `compute_gesamtbetrag`.
    gesamtbetrag: Decimal | None = Field(None, ge=0)

    # --- Crew ------------------------------------------------------------
    personen_ohne_skipper: int | None = Field(None, ge=0, le=MAX_PERSONEN_OHNE_SKIPPER)
    skipper_name: str = Field(default="", max_length=CHARTERER_NAME_MAX_LENGTH)
    # The normal case: the charterer is a crew member and skippers their own
    # charter. Decides two signature blocks versus three at render time — a
    # property of the produced document, not a state machine.
    skipper_is_charterer: bool = True
    sbfs_number: str | None = Field(None, max_length=LICENCE_NUMBER_MAX_LENGTH)
    sbfs_issued_on: date | None = None
    sbfb_number: str | None = Field(None, max_length=LICENCE_NUMBER_MAX_LENGTH)
    sbfb_issued_on: date | None = None

    # --- Rendered document ------------------------------------------------
    # `contracts/{event_id}/v{n}.pdf` — never overwritten.
    document_key: str | None = None
    document_sha256: str | None = Field(None, max_length=64)
    rendered_at: datetime | None = None

    # --- Dispatch ---------------------------------------------------------
    sent_at: datetime | None = None
    sent_to: str | None = None

    # --- Signature --------------------------------------------------------
    # What the people wrote on the paper …
    signed_on: date | None = None
    # … and when Funke found out about it. The two differ whenever the scan is
    # uploaded after the trip, which is the common case.
    signed_recorded_at: datetime | None = None
    signed_by_admin: str | None = None
    # `contracts/{event_id}/v{n}-signiert.pdf`
    signed_document_key: str | None = None
    signed_document_sha256: str | None = Field(None, max_length=64)
    signed_document_bytes: int | None = Field(None, ge=0)

    # --- Countersignature (optional, never blocking) -----------------------
    # The Vercharterer's line may stay blank and may be filled in years later;
    # `status = signed` does not depend on it.
    countersigned_on: date | None = None
    countersigned_by: str | None = None

    # --- Fahrbericht override ----------------------------------------------
    # Stamped when someone submits the trip report without a signed contract.
    # Nothing is waved through silently — the contract page says so afterwards.
    fahrbericht_override_by: str | None = None
    fahrbericht_override_at: datetime | None = None

    # Grows when a signature is discarded. Nothing is ever deleted from S3, so
    # this list is the record of what used to be the signed document.
    superseded_signed_keys: list[str] = Field(default_factory=list)
    # Computed at render, not at save — while the contract is a draft the
    # handover date may still move. See `compute_retention_until`.
    retention_until: date | None = None

    # --- In-app signing (spec 025 addendum) ---
    # Minted at render, destroyed at the next render. A link that outlived the
    # document it showed would be worse than no link.
    sign_token: str | None = None
    signatures: list[CharterSignature] = Field(default_factory=list)

    # --- Seal ---
    sealed_document_key: str | None = None
    sealed_document_sha256: str | None = Field(None, max_length=64)
    sealed_at: datetime | None = None
    # Which key sealed it, so a reader in 2036 can tell.
    seal_key_id: str | None = None
    # False means PAdES B-B: sealed, but with no third-party time attestation
    # because the timestamp authority was unreachable.
    seal_timestamped: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_gesamtbetrag(self) -> Decimal:
        """Charter fee plus the sum of the extras.

        The deposit is deliberately **not** part of it: it is refundable, so
        adding it would state a total the charterer never owes.
        """
        total = self.chartergebuehr or Decimal("0")
        for line in self.sonderleistungen:
            total += line.amount
        return total

    def compute_retention_until(self) -> date | None:
        """31 December of the handover year plus ten years, or ``None`` while
        the handover date is still unset."""
        if self.uebergabe_at is None:
            return None
        handover_year = self.uebergabe_at.astimezone(BERLIN_TZ).year
        return date(handover_year + RETENTION_YEARS, 12, 31)

    def required_roles(self) -> set[SignatureRole]:
        """Signatures needed before the contract counts as signed.

        The Vercharterer is never in here: countersigning is optional and may
        be added years later, so waiting for it would block the handover on a
        board member's availability.
        """
        roles = {SignatureRole.CHARTERER}
        if not self.skipper_is_charterer:
            roles.add(SignatureRole.SKIPPER)
        return roles

    def signed_roles(self) -> set[SignatureRole]:
        return {sig.role for sig in self.signatures}

    def has_all_required_signatures(self) -> bool:
        return self.required_roles().issubset(self.signed_roles())

    @property
    def is_editable(self) -> bool:
        """A signed contract is frozen — the bytes are the agreement. Fixing
        one goes through „Unterschrift verwerfen" first. Surfaced to the page
        as `can_edit` on the response."""
        return self.status is not CharterStatus.SIGNED


class CharterContractUpsert(BaseModel):
    """Body of the ``PUT`` — the fields the organiser types.

    Full-document upsert, not a patch: every field is optional so a half-filled
    draft saves, and an omitted field is stored as empty rather than left over
    from the previous save. Everything the server owns (status, versions, keys,
    hashes, signature and countersignature) is absent by construction.
    """

    model_config = ConfigDict(extra="forbid")

    charterer_name: str = Field(default="", max_length=CHARTERER_NAME_MAX_LENGTH)
    charterer_address: str = Field(default="", max_length=CHARTERER_ADDRESS_MAX_LENGTH)
    charterer_email: EmailStr | None = None
    charterer_phone: str | None = Field(None, max_length=PHONE_MAX_LENGTH)
    sondervereinbarungen: str | None = Field(None, max_length=SONDERVEREINBARUNGEN_MAX_LENGTH)

    uebergabe_at: datetime | None = None
    rueckgabe_at: datetime | None = None

    chartergebuehr: Decimal | None = Field(None, ge=0)
    sonderleistungen: list[ExpenseLine] = Field(default_factory=list)
    kaution: Decimal | None = Field(None, ge=0)

    personen_ohne_skipper: int | None = Field(None, ge=0, le=MAX_PERSONEN_OHNE_SKIPPER)
    skipper_name: str = Field(default="", max_length=CHARTERER_NAME_MAX_LENGTH)
    skipper_is_charterer: bool = True
    sbfs_number: str | None = Field(None, max_length=LICENCE_NUMBER_MAX_LENGTH)
    sbfs_issued_on: date | None = None
    sbfb_number: str | None = Field(None, max_length=LICENCE_NUMBER_MAX_LENGTH)
    sbfb_issued_on: date | None = None


class CharterContractResponse(CharterContract):
    """Detail response — the row plus what only the API can supply.

    ``gesamtbetrag`` is recomputed here on every read rather than echoed from
    the row, so the form shows the total of what is currently typed in; the
    stored value stays the one the last PDF printed.
    """

    gesamtbetrag: Decimal = Decimal("0")
    # Short-lived presigns, both `None` until the respective object exists.
    download_url: str | None = None
    signed_download_url: str | None = None
    can_edit: bool = True

    @classmethod
    def from_contract(
        cls,
        contract: CharterContract,
        *,
        download_url: str | None = None,
        signed_download_url: str | None = None,
    ) -> "CharterContractResponse":
        """Build the response off a row. Not the usual `**model_dump()` splat:
        `gesamtbetrag` lives on both models and would arrive twice."""
        return cls(
            **contract.model_dump(exclude={"gesamtbetrag"}),
            gesamtbetrag=contract.compute_gesamtbetrag(),
            download_url=download_url,
            signed_download_url=signed_download_url,
            can_edit=contract.is_editable,
        )


class CharterContractSummary(BaseModel):
    """The block ``GET /api/admin/events/{id}`` carries along, so the contract
    section and the „noch nicht unterschrieben" banner render without a second
    request."""

    status: CharterStatus
    uebergabe_at: datetime | None = None
    signed_on: date | None = None


class CharterSignedConfirm(BaseModel):
    """„The scan is up, and here is what the paper says."

    ``alle_parteien_unterschrieben`` is the mandatory checkbox — the organiser
    asserting they looked at the sheet. The Vercharterer's countersignature is
    deliberately not asked for here; it never gates ``signed``.
    """

    model_config = ConfigDict(extra="forbid")

    signed_on: date
    alle_parteien_unterschrieben: bool


class CharterCountersign(BaseModel):
    """Filing the Vercharterer's countersignature after the fact — allowed at
    any time, years later included. Who signed comes from the token, not the
    body."""

    model_config = ConfigDict(extra="forbid")

    countersigned_on: date


class CharterUpload(BaseModel):
    """Upload permission for the signed scan: one presigned POST, nailed to
    exactly one key.

    Shaped like `LostAndFoundUpload` but kept local — one file, not a pool, and
    no reason to couple spec 025 to spec 023's models.
    """

    url: str
    fields: dict[str, str]
    key: str


class CharterPublicView(BaseModel):
    """What the charterer sees on the signing page.

    Deliberately narrow. Licence numbers and the postal address are on the
    contract row and are **not** here: the page needs to show what is being
    agreed, not everything the Verein knows. The PDF behind `document_url` is
    the authoritative text — this is orientation around it.
    """

    event_name: str
    charterer_name: str
    skipper_name: str
    skipper_is_charterer: bool
    uebergabe_at: datetime | None
    rueckgabe_at: datetime | None
    chartergebuehr: Decimal | None
    kaution: Decimal | None
    gesamtbetrag: Decimal
    document_url: str
    document_sha256: str
    # Already signed by this role? Lets the page show "done" instead of a form
    # when somebody reopens their link.
    already_signed: bool


class CharterSignRequest(BaseModel):
    """Body of the public signing POST."""

    model_config = ConfigDict(extra="forbid")

    signed_name: str = Field(..., min_length=1, max_length=CHARTERER_NAME_MAX_LENGTH)
    # base64 PNG from the canvas. Optional: a typed name alone is a valid
    # simple electronic signature.
    image_b64: str | None = None
    # The hash of the render the signer was shown. Mismatch means the contract
    # moved under their feet and the signature must not be accepted.
    document_sha256: str = Field(..., max_length=64)


class CharterAdminSignRequest(BaseModel):
    """Body of the admin-side signature (skipper or countersignature)."""

    model_config = ConfigDict(extra="forbid")

    role: SignatureRole
    signed_name: str = Field(..., min_length=1, max_length=CHARTERER_NAME_MAX_LENGTH)
    image_b64: str | None = None
