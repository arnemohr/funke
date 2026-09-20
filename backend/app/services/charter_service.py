"""Charter contract service (spec 025 — Chartervertrag).

One singleton row per event, ``pk=EVENT#{event_id} / sk=CHARTER``, next to the
Fahrbericht and the Fundsachen config. A replacement contract is a new render of
the same row, never a second row.

Three things in here are load-bearing:

**A render never overwrites.** Every render mints ``document_version + 1`` and
writes ``contracts/{event_id}/v{n}.pdf``. Nothing ever writes the same key
twice, so the PDF somebody printed last week is still exactly where it was.
Spec 025 accepts, explicitly, that two simultaneous renders could hand out the
same ``n`` — the counter is read-then-written, not conditional. In practice one
person touches contracts. As soon as two do, this needs a conditional update.

**A signed contract is frozen.** Once the scan is confirmed the bytes *are* the
agreement, so the row refuses every write except the countersignature until
somebody explicitly discards the signature. Discarding moves the old key into
``superseded_signed_keys`` and deletes nothing from S3 — the reports bucket has
no lifecycle rule for exactly this reason.

**Objects go before rows.** A render puts the PDF and only then writes the key
onto the row. The other order leaves a row pointing at nothing, i.e. a download
button that 404s; this order can at worst leave an unreferenced object in a
bucket that costs nothing and is versioned in prod.

Money is stored as *strings* and parsed back into ``Decimal``, the same shape
``fahrbericht_service`` uses. DynamoDB rejects floats outright, and a string
round-trip keeps the exact cents without depending on the resource layer's
Decimal context.

Errors are raised as ``ValueError`` with the machine-readable identifiers from
spec 025's Fehler table (``vertrag_bereits_unterschrieben``,
``vertrag_nicht_erzeugt``, ``datei_nicht_hochgeladen``, …); the router turns
each into an HTTP status plus the German line. The one exception is
``CharterIncompleteError``, which also carries the list of missing field names
because the 422 has to name them.
"""

import hashlib
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ..models.charter import (
    BERLIN_TZ,
    CHARTER_ENTITY_TYPE,
    RETENTION_YEARS,
    CharterContract,
    CharterContractSummary,
    CharterContractUpsert,
    CharterPublicView,
    CharterSignature,
    CharterSignedConfirm,
    CharterStatus,
    CharterUpload,
    SignatureRole,
)
from ..models.fahrbericht import ExpenseLine
from .charter_pdf import render_charter_pdf
from .charter_template import TEMPLATE_VERSION
from .config import EVENT_PK_PREFIX, EVENT_SK_CHARTER, get_events_table, get_settings
from .email_client import Attachment, EmailMessage, get_gmail_client
from .logging import get_logger

logger = get_logger(__name__)

# Lifetime of every presigned URL this service mints — download and upload
# alike. Long enough to print two copies and walk to the printer, short enough
# that a link pasted into a chat is dead by the time anybody clicks it.
URL_TTL_SECONDS = 900

# The signed scan is one document: a four-page PDF from a scanner or a photo
# from a phone. 15 MB covers both with room to spare and stops a leaked
# signature from being used to park something large in a bucket that has no
# lifecycle rule.
MAX_SIGNED_UPLOAD_BYTES = 15 * 1024 * 1024

# What the browser may upload as the signed contract. Pinned into the presign
# policy, so anything else is rejected by S3 rather than by us.
ALLOWED_SIGNED_CONTENT_TYPES = ("application/pdf", "image/jpeg")

# Prefix inside the existing reports bucket. Not a new bucket, and explicitly
# not `lostfound`/`eventphotos`: both of those expire objects after 400 days
# and would silently delete a record that has to survive ten years.
CONTRACTS_PREFIX = "contracts"

RENDERED_CONTENT_TYPE = "application/pdf"

# Read the uploaded scan in 1 MiB slices rather than into one bytes object —
# 15 MB in a 512 MB Lambda is survivable but pointless.
_HASH_CHUNK_BYTES = 1024 * 1024


class CharterIncompleteError(ValueError):
    """The mandatory set is not complete, and these fields are missing.

    A plain error string is not enough here: spec 025's 422 has to name the
    fields in German, so the list travels with the exception instead of being
    re-derived by the router.
    """

    def __init__(self, fields: list[str]) -> None:
        super().__init__("vertrag_unvollstaendig")
        self.fields = fields


def document_key(event_id: UUID, version: int) -> str:
    """S3 key of the rendered contract at version ``n``."""
    return f"{CONTRACTS_PREFIX}/{event_id}/v{version}.pdf"


def signed_document_key(event_id: UUID, version: int) -> str:
    """S3 key of the signed scan belonging to version ``n``.

    Named after the *rendered* version it belongs to, so a scan can never be
    mistaken for the signature of a different sheet — which is the whole point
    of the provenance line in the PDF's footer.
    """
    return f"{CONTRACTS_PREFIX}/{event_id}/v{version}-signiert.pdf"


def missing_mandatory_fields(contract: CharterContract) -> list[str]:
    """German names of everything the render still needs, in form order.

    The model deliberately types the draft as partial (see
    ``models/charter.py``), so this — not pydantic — is where the mandatory set
    of spec 025 § Ablauf 4 is enforced. Empty rather than zero: a fee of 0,00 €
    is a decision, a fee that was never typed is a gap.
    """
    missing: list[str] = []

    if not contract.charterer_name.strip():
        missing.append("Name des Charterers")
    if not contract.charterer_address.strip():
        missing.append("Anschrift des Charterers")
    if contract.uebergabe_at is None:
        missing.append("Übergabe")
    if contract.rueckgabe_at is None:
        missing.append("Rückgabe")
    if contract.chartergebuehr is None:
        missing.append("Chartergebühr")
    if contract.kaution is None:
        missing.append("Kaution")
    if contract.personen_ohne_skipper is None:
        missing.append("Personenzahl ohne Skipper")

    # With the checkbox set the form mirrors the charterer's name, but a draft
    # saved before the mirror ran has an empty `skipper_name` — the renderer
    # falls back to the charterer there, so accept the same thing here instead
    # of demanding a field the page hides.
    if not contract.skipper_name.strip() and not (
        contract.skipper_is_charterer and contract.charterer_name.strip()
    ):
        missing.append("Schiffsführer")

    # A licence is only demanded when charterer and skipper are different
    # people: in the normal case the skipper is a club member whose licence the
    # club already holds, and the paper original leaves the line blank there.
    if not contract.skipper_is_charterer and not (contract.sbfs_number or contract.sbfb_number):
        missing.append("Führerschein (SBFS oder SBFB)")

    return missing


def _dec_str(value: Decimal | None) -> str | None:
    """Money on the way into the item: a string, never a float."""
    return str(value) if value is not None else None


def _dec(value) -> Decimal | None:
    """Money on the way back out. Tolerates the `Decimal` the resource layer
    hands back for a legacy numeric attribute as well as our own string."""
    return None if value is None else Decimal(str(value))


def _contract_to_item(contract: CharterContract) -> dict:
    """Convert a contract model to a DynamoDB item.

    Unset optionals are omitted rather than stored as ``None``, matching the
    sibling services — „cleared" and „never set" then read identically.
    """
    item: dict = {
        "pk": f"{EVENT_PK_PREFIX}{contract.event_id}",
        "sk": EVENT_SK_CHARTER,
        "entity_type": CHARTER_ENTITY_TYPE,
        "event_id": str(contract.event_id),
        "status": contract.status.value,
        "document_version": contract.document_version,
        "charterer_name": contract.charterer_name,
        "charterer_address": contract.charterer_address,
        "skipper_name": contract.skipper_name,
        "skipper_is_charterer": contract.skipper_is_charterer,
        # `mode="json"` turns the `Decimal` amount into a string, exactly like
        # the Fahrbericht's own expense lines.
        "sonderleistungen": [line.model_dump(mode="json") for line in contract.sonderleistungen],
        "superseded_signed_keys": list(contract.superseded_signed_keys),
        "signatures": [sig.model_dump(mode="json") for sig in contract.signatures],
        "seal_timestamped": contract.seal_timestamped,
        "created_at": contract.created_at.isoformat(),
        "updated_at": contract.updated_at.isoformat(),
    }

    optionals: dict[str, object | None] = {
        "template_version": contract.template_version,
        "charterer_email": str(contract.charterer_email) if contract.charterer_email else None,
        "charterer_phone": contract.charterer_phone,
        "sondervereinbarungen": contract.sondervereinbarungen,
        "uebergabe_at": contract.uebergabe_at.isoformat() if contract.uebergabe_at else None,
        "rueckgabe_at": contract.rueckgabe_at.isoformat() if contract.rueckgabe_at else None,
        "chartergebuehr": _dec_str(contract.chartergebuehr),
        "kaution": _dec_str(contract.kaution),
        "gesamtbetrag": _dec_str(contract.gesamtbetrag),
        "personen_ohne_skipper": contract.personen_ohne_skipper,
        "sbfs_number": contract.sbfs_number,
        "sbfs_issued_on": contract.sbfs_issued_on.isoformat() if contract.sbfs_issued_on else None,
        "sbfb_number": contract.sbfb_number,
        "sbfb_issued_on": contract.sbfb_issued_on.isoformat() if contract.sbfb_issued_on else None,
        "document_key": contract.document_key,
        "document_sha256": contract.document_sha256,
        "rendered_at": contract.rendered_at.isoformat() if contract.rendered_at else None,
        "sent_at": contract.sent_at.isoformat() if contract.sent_at else None,
        "sent_to": contract.sent_to,
        "signed_on": contract.signed_on.isoformat() if contract.signed_on else None,
        "signed_recorded_at": (
            contract.signed_recorded_at.isoformat() if contract.signed_recorded_at else None
        ),
        "signed_by_admin": contract.signed_by_admin,
        "signed_document_key": contract.signed_document_key,
        "signed_document_sha256": contract.signed_document_sha256,
        "signed_document_bytes": contract.signed_document_bytes,
        "countersigned_on": (
            contract.countersigned_on.isoformat() if contract.countersigned_on else None
        ),
        "countersigned_by": contract.countersigned_by,
        "fahrbericht_override_by": contract.fahrbericht_override_by,
        "fahrbericht_override_at": (
            contract.fahrbericht_override_at.isoformat()
            if contract.fahrbericht_override_at
            else None
        ),
        "retention_until": (
            contract.retention_until.isoformat() if contract.retention_until else None
        ),
        "sign_token": contract.sign_token,
        "sealed_document_key": contract.sealed_document_key,
        "sealed_document_sha256": contract.sealed_document_sha256,
        "sealed_at": contract.sealed_at.isoformat() if contract.sealed_at else None,
        "seal_key_id": contract.seal_key_id,
    }
    item.update({key: value for key, value in optionals.items() if value is not None})
    return item


def _dt(value) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value) -> date | None:
    return date.fromisoformat(value) if value else None


def _item_to_contract(item: dict) -> CharterContract:
    """Convert a DynamoDB item to a contract model."""
    return CharterContract(
        event_id=UUID(item["event_id"]),
        status=CharterStatus(item.get("status", CharterStatus.DRAFT.value)),
        template_version=item.get("template_version"),
        document_version=int(item.get("document_version", 0)),
        charterer_name=item.get("charterer_name", ""),
        charterer_address=item.get("charterer_address", ""),
        charterer_email=item.get("charterer_email"),
        charterer_phone=item.get("charterer_phone"),
        sondervereinbarungen=item.get("sondervereinbarungen"),
        uebergabe_at=_dt(item.get("uebergabe_at")),
        rueckgabe_at=_dt(item.get("rueckgabe_at")),
        chartergebuehr=_dec(item.get("chartergebuehr")),
        sonderleistungen=[ExpenseLine(**line) for line in item.get("sonderleistungen") or []],
        kaution=_dec(item.get("kaution")),
        gesamtbetrag=_dec(item.get("gesamtbetrag")),
        personen_ohne_skipper=(
            int(item["personen_ohne_skipper"])
            if item.get("personen_ohne_skipper") is not None
            else None
        ),
        skipper_name=item.get("skipper_name", ""),
        skipper_is_charterer=bool(item.get("skipper_is_charterer", True)),
        sbfs_number=item.get("sbfs_number"),
        sbfs_issued_on=_date(item.get("sbfs_issued_on")),
        sbfb_number=item.get("sbfb_number"),
        sbfb_issued_on=_date(item.get("sbfb_issued_on")),
        document_key=item.get("document_key"),
        document_sha256=item.get("document_sha256"),
        rendered_at=_dt(item.get("rendered_at")),
        sent_at=_dt(item.get("sent_at")),
        sent_to=item.get("sent_to"),
        signed_on=_date(item.get("signed_on")),
        signed_recorded_at=_dt(item.get("signed_recorded_at")),
        signed_by_admin=item.get("signed_by_admin"),
        signed_document_key=item.get("signed_document_key"),
        signed_document_sha256=item.get("signed_document_sha256"),
        signed_document_bytes=(
            int(item["signed_document_bytes"])
            if item.get("signed_document_bytes") is not None
            else None
        ),
        countersigned_on=_date(item.get("countersigned_on")),
        countersigned_by=item.get("countersigned_by"),
        fahrbericht_override_by=item.get("fahrbericht_override_by"),
        fahrbericht_override_at=_dt(item.get("fahrbericht_override_at")),
        superseded_signed_keys=list(item.get("superseded_signed_keys") or []),
        retention_until=_date(item.get("retention_until")),
        sign_token=item.get("sign_token"),
        signatures=[CharterSignature(**sig) for sig in (item.get("signatures") or [])],
        sealed_document_key=item.get("sealed_document_key"),
        sealed_document_sha256=item.get("sealed_document_sha256"),
        sealed_at=_dt(item.get("sealed_at")),
        seal_key_id=item.get("seal_key_id"),
        seal_timestamped=bool(item.get("seal_timestamped", False)),
        created_at=_dt(item["created_at"]) or datetime.now(timezone.utc),
        updated_at=_dt(item["updated_at"]) or datetime.now(timezone.utc),
    )


class CharterService:
    """The charter contract row, its PDFs and its signature."""

    def __init__(self):
        self._table = None
        self._s3 = None

    @property
    def table(self):
        """The events table (lazy) — the contract row is co-located there."""
        if self._table is None:
            self._table = get_events_table()
        return self._table

    @property
    def s3(self):
        """S3 client (lazy).

        Built the way `event_photo_service` builds its: pinned to the regional
        endpoint, SigV4, virtual addressing. `report_service`'s plain
        `boto3.client("s3")` is fine for the server-side put and get in here,
        but the same client also mints the browser's presigned POST — and a
        presigned POST against the global endpoint answers 307 to the regional
        host, which a browser will not replay a cross-origin multipart upload
        across. One client, built for the stricter of the two uses.
        """
        if self._s3 is None:
            region = get_settings().aws_region
            self._s3 = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=f"https://s3.{region}.amazonaws.com",
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": "virtual"},
                ),
            )
        return self._s3

    @property
    def bucket(self) -> str | None:
        """The existing reports bucket, or None in a local environment.

        Deliberately shared with the closing reports: it already has
        BLOCK_ALL, encryption, RETAIN and versioning outside dev, and — the
        part that matters here — **no lifecycle rule**. The photo buckets
        expire after 400 days.
        """
        return get_settings().reports_s3_bucket

    def _require_bucket(self) -> str:
        bucket = self.bucket
        if not bucket:
            raise ValueError("bucket_not_configured")
        return bucket

    # -- the row ---------------------------------------------------------------

    async def get_contract(self, event_id: UUID) -> CharterContract | None:
        """Read the contract row, or None when the event has none.

        A failed read raises rather than answering None: None means „this event
        has no contract", and every caller acts on that — the router 404s, the
        Fahrbericht submission waves itself through, `delete_event` stops
        refusing. None of those may happen because DynamoDB was throttled.
        """
        try:
            response = self.table.get_item(
                Key={"pk": f"{EVENT_PK_PREFIX}{event_id}", "sk": EVENT_SK_CHARTER},
            )
        except ClientError as e:
            logger.error(
                "Failed to read the charter contract",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            raise
        item = response.get("Item")
        return _item_to_contract(item) if item else None

    async def get_summary(self, event_id: UUID) -> CharterContractSummary | None:
        """The little block `GET /api/admin/events/{id}` carries along."""
        contract = await self.get_contract(event_id)
        if contract is None:
            return None
        return CharterContractSummary(
            status=contract.status,
            uebergabe_at=contract.uebergabe_at,
            signed_on=contract.signed_on,
        )

    def _put(self, contract: CharterContract) -> CharterContract:
        """Write the whole row. The contract is a single-writer document — the
        organiser has the form open — so a full put is honest about that,
        unlike a targeted update that would pretend fields merge."""
        self.table.put_item(Item=_contract_to_item(contract))
        return contract

    async def upsert_contract(
        self,
        event_id: UUID,
        payload: CharterContractUpsert,
    ) -> CharterContract:
        """Create the contract on the first save, replace the typed fields
        afterwards. Idempotent, and a half-filled draft is a legitimate save.

        Full-document semantics on purpose: the form posts everything it shows,
        so a cleared field arrives as empty and has to *become* empty. Server
        state (status, versions, keys, hashes, signature) is not in the body
        and is carried over untouched.

        Raises:
            ValueError: ``vertrag_bereits_unterschrieben``.
        """
        existing = await self.get_contract(event_id)
        now = datetime.now(timezone.utc)

        # `model_copy(update=…)` does not validate, so the expense lines are
        # carried over as models rather than as the dicts `model_dump` would
        # produce — a dict in there survives the write and then fails at
        # `line.amount` when the total is computed.
        fields: dict = {
            **payload.model_dump(exclude={"sonderleistungen"}),
            "sonderleistungen": list(payload.sonderleistungen),
        }

        if existing is None:
            return self._put(
                CharterContract(event_id=event_id, created_at=now, updated_at=now, **fields),
            )

        if not existing.is_editable:
            raise ValueError("vertrag_bereits_unterschrieben")

        return self._put(existing.model_copy(update={**fields, "updated_at": now}))

    async def delete_contract(self, event_id: UUID) -> None:
        """Drop the row — only while it is a draft that never produced a PDF.

        Once a PDF exists the row is the only thing that knows the object's key
        and hash, and the object itself is never deleted. Removing the row
        would leave a contract in the bucket that nothing can name.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``,
                ``vertrag_bereits_unterschrieben``, ``vertrag_bereits_erzeugt``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if contract.status is CharterStatus.SIGNED:
            raise ValueError("vertrag_bereits_unterschrieben")
        if contract.document_key or contract.document_version > 0:
            raise ValueError("vertrag_bereits_erzeugt")

        self.table.delete_item(
            Key={"pk": f"{EVENT_PK_PREFIX}{event_id}", "sk": EVENT_SK_CHARTER},
        )
        logger.info("Charter contract deleted", extra={"event_id": str(event_id)})

    # -- rendering -------------------------------------------------------------

    async def render(self, event_id: UUID) -> CharterContract:
        """Check the mandatory set, render the PDF, store it, stamp the row.

        Mints a fresh ``document_version`` every time and never touches an
        existing object. The version is bumped *before* the render because the
        footer prints it — „Dokument v2" has to be on the sheet that is v2.

        A re-render puts the row back to ``draft``: the status describes the
        document that exists now, and the copy the charterer was sent is no
        longer that document. ``sent_at``/``sent_to`` stay as the record that a
        dispatch happened.

        Raises:
            CharterIncompleteError: the mandatory set is not complete.
            ValueError: ``vertrag_nicht_gefunden``,
                ``vertrag_bereits_unterschrieben``, ``bucket_not_configured``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if contract.status is CharterStatus.SIGNED:
            raise ValueError("vertrag_bereits_unterschrieben")

        missing = missing_mandatory_fields(contract)
        if missing:
            raise CharterIncompleteError(missing)

        bucket = self._require_bucket()
        now = datetime.now(timezone.utc)
        version = contract.document_version + 1
        key = document_key(event_id, version)

        candidate = contract.model_copy(
            update={
                "document_version": version,
                "template_version": TEMPLATE_VERSION,
                # The number this PDF prints, frozen onto the row. The API keeps
                # recomputing the live total for the form separately.
                "gesamtbetrag": contract.compute_gesamtbetrag(),
                # Computed here rather than on save: while the contract is a
                # draft the handover date may still move.
                "retention_until": contract.compute_retention_until(),
                "rendered_at": now,
                "document_key": key,
            },
        )

        pdf_bytes = render_charter_pdf(candidate, rendered_at=now)
        digest = hashlib.sha256(pdf_bytes).hexdigest()

        # Object first, row second — see the module docstring. A put that fails
        # leaves the row untouched, so the next attempt reuses the same `n`.
        try:
            self.s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=pdf_bytes,
                ContentType=RENDERED_CONTENT_TYPE,
            )
        except ClientError as e:
            logger.error(
                "Failed to store the rendered charter contract",
                extra={"error": str(e), "event_id": str(event_id), "key": key},
            )
            raise ValueError("dokument_nicht_gespeichert") from e

        stored = self._put(
            candidate.model_copy(
                update={
                    "document_sha256": digest,
                    "status": CharterStatus.DRAFT,
                    # A new render is a new document. Every signature collected
                    # against the old one is void, and the link that showed it
                    # must stop working — a link outliving the text it displayed
                    # would let somebody sign a contract nobody agreed to. This
                    # deliberately inverts the spec-020 precedent, where a
                    # changed event silently re-issued its QR codes.
                    "sign_token": secrets.token_urlsafe(32),
                    "signatures": [],
                    "updated_at": now,
                },
            ),
        )
        logger.info(
            "Charter contract rendered",
            extra={
                "event_id": str(event_id),
                "document_version": version,
                "bytes": len(pdf_bytes),
            },
        )
        return stored

    # -- dispatch --------------------------------------------------------------

    async def send_to_charterer(
        self, event_id: UUID, *, include_sign_link: bool = False,
    ) -> CharterContract:
        """Mail the rendered PDF to the charterer as an attachment.

        The attachment, not a link: this is also the copy on a durable medium
        under § 312f Abs. 2 BGB, and — for an external charterer — the step
        that gets the clauses incorporated at all (§ 305 Abs. 2 BGB). A link
        that expires in fifteen minutes is neither.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``, ``vertrag_nicht_erzeugt``,
                ``keine_charterer_adresse``, ``smtp_nicht_konfiguriert``,
                ``versand_fehlgeschlagen``, ``bucket_not_configured``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.document_key:
            raise ValueError("vertrag_nicht_erzeugt")
        if not contract.charterer_email:
            raise ValueError("keine_charterer_adresse")

        pdf_bytes = self._read_object(contract.document_key)
        recipient = str(contract.charterer_email)
        message = EmailMessage(
            to=recipient,
            subject=_dispatch_subject(contract),
            body_text=_dispatch_body(contract, include_sign_link=include_sign_link),
            attachments=[
                Attachment(
                    filename=_dispatch_filename(contract),
                    content=pdf_bytes,
                    content_type=RENDERED_CONTENT_TYPE,
                ),
            ],
        )

        client = get_gmail_client()
        try:
            result = await client.send_email(message)
        except ValueError as e:
            # `send_email` — not `get_gmail_client` — is what raises when the
            # SMTP credentials are missing. That is a configuration gap, not a
            # failed send, and the page answers it with „lade das PDF herunter
            # und verschick es selbst".
            logger.warning(
                "Charter contract dispatch skipped — SMTP is not configured",
                extra={"event_id": str(event_id)},
            )
            raise ValueError("smtp_nicht_konfiguriert") from e
        except Exception as e:  # noqa: BLE001 — any transport failure reads the same
            logger.exception(
                "Charter contract dispatch failed",
                extra={"event_id": str(event_id)},
            )
            raise ValueError("versand_fehlgeschlagen") from e

        if not result.success:
            logger.error(
                "Charter contract dispatch was refused",
                extra={"event_id": str(event_id), "error": result.error},
            )
            raise ValueError("versand_fehlgeschlagen")

        now = datetime.now(timezone.utc)
        stored = self._put(
            contract.model_copy(
                update={
                    "status": CharterStatus.SENT,
                    "sent_at": now,
                    "sent_to": recipient,
                    "updated_at": now,
                },
            ),
        )
        logger.info(
            "Charter contract sent to the charterer",
            extra={"event_id": str(event_id), "document_version": contract.document_version},
        )
        return stored

    # -- documents -------------------------------------------------------------

    def presign_download(self, key: str, *, filename: str) -> str:
        """A short-lived GET the browser can be redirected to.

        `inline` with a real filename: the organiser prints this at the jetty,
        and a browser offering to save `v2.pdf` from a UUID path is one step
        further from the printer than it needs to be.

        Raises:
            ValueError: ``bucket_not_configured``, ``download_nicht_moeglich``.
        """
        bucket = self._require_bucket()
        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'inline; filename="{filename}"',
                },
                ExpiresIn=URL_TTL_SECONDS,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign a charter contract download",
                extra={"error": str(e), "key": key},
            )
            raise ValueError("download_nicht_moeglich") from e

    def presign_download_or_none(self, key: str | None, *, filename: str) -> str | None:
        """`presign_download` for the detail response, where a missing bucket
        or an unsignable key must not take the whole page down — the form still
        works, only the download button is dead."""
        if not key:
            return None
        try:
            return self.presign_download(key, filename=filename)
        except ValueError:
            return None

    def _read_object(self, key: str) -> bytes:
        """Fetch a stored object whole. Only used for the mail attachment, and
        a contract PDF is a few hundred kilobytes."""
        bucket = self._require_bucket()
        try:
            response = self.s3.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            logger.error(
                "Failed to read a stored charter contract",
                extra={"error": str(e), "key": key},
            )
            raise ValueError("dokument_nicht_lesbar") from e

    # -- the signed scan -------------------------------------------------------

    async def create_signed_upload(self, event_id: UUID, content_type: str) -> CharterUpload:
        """One presigned POST for exactly one key — the signed scan.

        POST rather than PUT because only the POST policy carries conditions: a
        presigned PUT is an unconditional write permission with no size and no
        type limit. boto3 pins the key to an exact match, the content type is
        nailed to what the browser announced, and the body has to be between
        one byte and `MAX_SIGNED_UPLOAD_BYTES`.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``, ``vertrag_nicht_erzeugt``,
                ``dateityp_nicht_erlaubt``, ``bucket_not_configured``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.document_key or contract.document_version < 1:
            raise ValueError("vertrag_nicht_erzeugt")
        if content_type not in ALLOWED_SIGNED_CONTENT_TYPES:
            raise ValueError("dateityp_nicht_erlaubt")

        bucket = self._require_bucket()
        key = signed_document_key(event_id, contract.document_version)

        try:
            presigned = self.s3.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, MAX_SIGNED_UPLOAD_BYTES],
                ],
                ExpiresIn=URL_TTL_SECONDS,
            )
        except ClientError as e:
            logger.error(
                "Failed to presign the signed charter upload",
                extra={"error": str(e), "key": key},
            )
            raise ValueError("upload_nicht_moeglich") from e

        return CharterUpload(
            url=presigned["url"],
            fields={k: str(v) for k, v in presigned["fields"].items()},
            key=key,
        )

    async def confirm_signed(
        self,
        event_id: UUID,
        confirm: CharterSignedConfirm,
        *,
        signed_by: str | None,
    ) -> CharterContract:
        """Record that the scan arrived and the paper is signed.

        Reads the object once to hash it, so ``signed_document_sha256`` is the
        digest of the bytes S3 actually holds rather than of whatever the
        browser said it uploaded.

        ``retention_until`` is recomputed here even though the render already
        set it: a draft may legitimately have moved its handover date after the
        render, and this is the moment the row becomes retention-bound.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``, ``vertrag_nicht_erzeugt``,
                ``bestaetigung_fehlt``, ``datei_nicht_hochgeladen``,
                ``bucket_not_configured``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.document_key or contract.document_version < 1:
            raise ValueError("vertrag_nicht_erzeugt")
        if not confirm.alle_parteien_unterschrieben:
            raise ValueError("bestaetigung_fehlt")

        bucket = self._require_bucket()
        key = signed_document_key(event_id, contract.document_version)

        try:
            self.s3.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            # 404 and 403 both mean „not there" here: the bucket blocks all
            # public access, so a HEAD that is refused is a HEAD on a key that
            # does not exist.
            logger.warning(
                "Charter scan confirmed but the object is not in the bucket",
                extra={"error": str(e), "key": key},
            )
            raise ValueError("datei_nicht_hochgeladen") from e

        digest, size = self._hash_object(key)

        now = datetime.now(timezone.utc)
        stored = self._put(
            contract.model_copy(
                update={
                    "status": CharterStatus.SIGNED,
                    "signed_on": confirm.signed_on,
                    "signed_recorded_at": now,
                    "signed_by_admin": signed_by,
                    "signed_document_key": key,
                    "signed_document_sha256": digest,
                    "signed_document_bytes": size,
                    "retention_until": contract.compute_retention_until()
                    or contract.retention_until,
                    "updated_at": now,
                },
            ),
        )
        logger.info(
            "Charter contract marked as signed",
            extra={
                "event_id": str(event_id),
                "document_version": contract.document_version,
                "bytes": size,
            },
        )
        return stored

    def _hash_object(self, key: str) -> tuple[str, int]:
        """SHA-256 and byte count of a stored object, streamed.

        The count is taken from what was actually read rather than from the
        `Content-Length` header, so the two numbers on the row always describe
        the same bytes.
        """
        bucket = self._require_bucket()
        try:
            response = self.s3.get_object(Bucket=bucket, Key=key)
            digest = hashlib.sha256()
            size = 0
            for chunk in response["Body"].iter_chunks(_HASH_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
        except ClientError as e:
            logger.error(
                "Failed to hash the signed charter contract",
                extra={"error": str(e), "key": key},
            )
            raise ValueError("datei_nicht_hochgeladen") from e
        return digest.hexdigest(), size

    async def countersign(
        self,
        event_id: UUID,
        countersigned_on: date,
        *,
        countersigned_by: str | None,
    ) -> CharterContract:
        """File the Vercharterer's countersignature, whenever it happens.

        Touches nothing else — not the status, not the document, not either
        hash. The countersignature never gated ``signed``, so filing it years
        later must not look like a new event in the contract's life.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")

        stored = self._put(
            contract.model_copy(
                update={
                    "countersigned_on": countersigned_on,
                    "countersigned_by": countersigned_by,
                    "updated_at": datetime.now(timezone.utc),
                },
            ),
        )
        logger.info("Charter contract countersigned", extra={"event_id": str(event_id)})
        return stored

    async def unsign(self, event_id: UUID) -> CharterContract:
        """Discard the signature so the contract can be corrected.

        The old key moves into ``superseded_signed_keys`` and the object stays
        in the bucket. Spec 020's precedent — QR codes healing themselves
        silently on a rename — is deliberately inverted here: with a signed
        contract the bytes *are* the agreement, so nothing about them is ever
        quietly replaced.

        The countersignature is left standing. It is a separate fact about a
        separate line, filed independently and never part of what makes a
        contract signed.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``,
                ``vertrag_nicht_unterschrieben``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if contract.status is not CharterStatus.SIGNED:
            raise ValueError("vertrag_nicht_unterschrieben")

        superseded = list(contract.superseded_signed_keys)
        if contract.signed_document_key and contract.signed_document_key not in superseded:
            superseded.append(contract.signed_document_key)

        stored = self._put(
            contract.model_copy(
                update={
                    "status": CharterStatus.DRAFT,
                    "signed_on": None,
                    "signed_recorded_at": None,
                    "signed_by_admin": None,
                    "signed_document_key": None,
                    "signed_document_sha256": None,
                    "signed_document_bytes": None,
                    "superseded_signed_keys": superseded,
                    "updated_at": datetime.now(timezone.utc),
                },
            ),
        )
        logger.warning(
            "Charter signature discarded",
            extra={"event_id": str(event_id), "superseded": len(superseded)},
        )
        return stored

    # -- couplings -------------------------------------------------------------

    async def blocks_fahrbericht(self, event_id: UUID) -> bool:
        """Whether submitting the trip report should be refused.

        True only when a contract row exists and has no signed scan. No row
        means the trip was not chartered, and the ordinary case must not become
        more expensive because this feature exists.
        """
        contract = await self.get_contract(event_id)
        return contract is not None and not contract.signed_document_key

    async def stamp_fahrbericht_override(
        self,
        event_id: UUID,
        *,
        submitted_by: str | None,
    ) -> None:
        """Record that the trip report was filed without a signed contract.

        Nothing is waved through silently: the contract page says who did this
        and when. A missing row is not an error — the caller checks
        `blocks_fahrbericht` first, and a race that removed the row in between
        just means there was nothing to stamp.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            return

        now = datetime.now(timezone.utc)
        self._put(
            contract.model_copy(
                update={
                    "fahrbericht_override_by": submitted_by,
                    "fahrbericht_override_at": now,
                    "updated_at": now,
                },
            ),
        )
        logger.warning(
            "Trip report filed without a signed charter contract",
            extra={"event_id": str(event_id), "submitted_by": submitted_by or "unknown"},
        )

    async def deletion_block_year(self, event_id: UUID, today: date | None = None) -> int | None:
        """The year until which a signed contract keeps this event undeletable.

        ``None`` when nothing blocks. The year is returned rather than a bare
        boolean because the German refusal names it („… kann bis 2036 nicht
        gelöscht werden").

        Why this has to be checked at all: `delete_event` removes exactly one
        item, under `pk=ORG#{org_id}`. The contract lives under
        `pk=EVENT#{event_id}` and would survive — an orphaned row carrying a
        name, a postal address and two licence numbers, reachable through no
        admin route and bound by no deadline. That is worse than deleting it.
        """
        moment = today or date.today()
        contract = await self.get_contract(event_id)
        if contract is None or contract.status is not CharterStatus.SIGNED:
            return None

        until = contract.retention_until or contract.compute_retention_until()
        if until is None:
            # Signed with no handover date anywhere on the row — impossible
            # through the render path, which demands one. Refuse anyway and
            # count from today: a signed contract with a broken deadline is the
            # one case where guessing „already expired" is unrecoverable.
            until = date(moment.year + RETENTION_YEARS, 12, 31)

        return None if until < moment else until.year

    # --- In-app signing and sealing (spec 025 addendum) --------------------

    async def get_by_sign_token(self, event_id: UUID, token: str) -> CharterContract:
        """Look a contract up by its signing token.

        Any failure answers the same way — `vertrag_nicht_gefunden` — because
        distinguishing "wrong token" from "no contract" would confirm that a
        contract exists for an event id anyone can guess.
        """
        contract = await self.get_contract(event_id)
        if contract is None or not contract.sign_token or not token:
            raise ValueError("vertrag_nicht_gefunden")
        if not secrets.compare_digest(contract.sign_token, token):
            raise ValueError("vertrag_nicht_gefunden")
        return contract

    async def public_view(
        self, event_id: UUID, token: str, *, event_name: str,
    ) -> CharterPublicView:
        """The narrow payload behind the signing link."""
        contract = await self.get_by_sign_token(event_id, token)
        if not contract.document_key or not contract.document_sha256:
            raise ValueError("vertrag_nicht_erzeugt")

        return CharterPublicView(
            event_name=event_name,
            charterer_name=contract.charterer_name,
            skipper_name=contract.skipper_name or contract.charterer_name,
            skipper_is_charterer=contract.skipper_is_charterer,
            uebergabe_at=contract.uebergabe_at,
            rueckgabe_at=contract.rueckgabe_at,
            chartergebuehr=contract.chartergebuehr,
            kaution=contract.kaution,
            gesamtbetrag=contract.compute_gesamtbetrag(),
            document_url=self.presign_download(
                contract.document_key, filename="Chartervertrag.pdf",
            ),
            document_sha256=contract.document_sha256,
            already_signed=SignatureRole.CHARTERER in contract.signed_roles(),
        )

    async def add_signature(
        self,
        event_id: UUID,
        role: SignatureRole,
        *,
        signed_name: str,
        document_sha256: str,
        image_b64: str | None = None,
        signer_ip: str | None = None,
        signer_user_agent: str | None = None,
        by_admin: str | None = None,
    ) -> CharterContract:
        """Record one signature and seal once the required set is complete.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``, ``vertrag_nicht_erzeugt``,
                ``vertrag_wurde_geaendert``, ``bereits_unterschrieben``,
                ``unterschrift_ungueltig``, ``unterschrift_zu_gross``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.document_key or not contract.document_sha256:
            raise ValueError("vertrag_nicht_erzeugt")
        # The signature has to cover the document the person was shown. A
        # mismatch means the contract was re-rendered while they had it open.
        if not secrets.compare_digest(contract.document_sha256, document_sha256 or ""):
            raise ValueError("vertrag_wurde_geaendert")
        if role in contract.signed_roles():
            raise ValueError("bereits_unterschrieben")

        image_key: str | None = None
        if image_b64:
            raw = _decode_signature_image(image_b64)
            image_key = signature_image_key(event_id, role)
            self.s3.put_object(
                Bucket=self._require_bucket(),
                Key=image_key,
                Body=raw,
                ContentType="image/png",
            )

        signature = CharterSignature(
            role=role,
            signed_name=signed_name.strip(),
            image_key=image_key,
            document_sha256=document_sha256,
            signer_ip=signer_ip,
            signer_user_agent=(signer_user_agent or None) and signer_user_agent[:200],
            by_admin=by_admin,
        )
        now = datetime.now(timezone.utc)
        contract = self._put(
            contract.model_copy(
                update={
                    "signatures": [*contract.signatures, signature],
                    "status": CharterStatus.SENT
                    if contract.status is CharterStatus.DRAFT
                    else contract.status,
                    "updated_at": now,
                },
            ),
        )

        if contract.has_all_required_signatures():
            contract = await self.finalise(event_id)
        return contract

    async def finalise(self, event_id: UUID) -> CharterContract:
        """Composite the signatures into the PDF, seal it, and file it.

        Sealing is best-effort by design: if the seal is not configured or KMS
        is unreachable the signatures are still kept and the contract still
        counts as signed. An unsealed signed contract is worth far more than a
        signature refused because a certificate was missing.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.document_key:
            raise ValueError("vertrag_nicht_erzeugt")

        images: dict[SignatureRole, bytes] = {}
        for sig in contract.signatures:
            if sig.image_key:
                try:
                    images[sig.role] = self._read_object(sig.image_key)
                except Exception:  # noqa: BLE001 — a lost image must not lose the signature
                    logger.warning(
                        "Signature image unreadable; sealing without it",
                        extra={"key": sig.image_key},
                    )

        now = datetime.now(timezone.utc)
        signed_pdf = render_charter_pdf(
            contract, rendered_at=now, signatures=contract.signatures, signature_images=images,
        )

        bucket = self._require_bucket()
        key = sealed_document_key(event_id, contract.document_version)
        seal_key_id: str | None = None
        timestamped = False
        try:
            from .charter_seal import seal_pdf

            result = await seal_pdf(signed_pdf)
            signed_pdf, seal_key_id, timestamped = result.pdf, result.key_id, result.timestamped
        except Exception as exc:  # noqa: BLE001 — see the docstring
            logger.warning(
                "Charter contract stored without a seal",
                extra={"event_id": str(event_id), "error": str(exc)[:160]},
            )

        self.s3.put_object(
            Bucket=bucket, Key=key, Body=signed_pdf, ContentType=RENDERED_CONTENT_TYPE,
        )

        # The drawn signatures now live inside the sealed document; the loose
        # PNGs are redundant PII with a ten-year retention attached to them.
        for sig in contract.signatures:
            if sig.image_key:
                try:
                    self.s3.delete_object(Bucket=bucket, Key=sig.image_key)
                except ClientError:
                    logger.warning("Could not remove signature image", extra={"key": sig.image_key})

        sealed = self._put(
            contract.model_copy(
                update={
                    "status": CharterStatus.SIGNED,
                    "signed_on": now.astimezone(BERLIN_TZ).date(),
                    "signed_recorded_at": now,
                    "sealed_document_key": key,
                    "sealed_document_sha256": hashlib.sha256(signed_pdf).hexdigest(),
                    "sealed_at": now if seal_key_id else None,
                    "seal_key_id": seal_key_id,
                    "seal_timestamped": timestamped,
                    "signatures": [
                        sig.model_copy(update={"image_key": None}) for sig in contract.signatures
                    ],
                    "updated_at": now,
                },
            ),
        )

        # Deliberately last, and deliberately swallowing failures: by this point
        # the contract is signed, sealed and filed. A mail server being down
        # should cost a copy, never a signature.
        await self.send_sealed_copy(event_id)
        return sealed

    async def send_signing_link(self, event_id: UUID) -> CharterContract:
        """Mail the charterer the signing link plus the PDF.

        Reuses `send_to_charterer`'s dispatch entirely — same SMTP handling,
        same attachment, same status bookkeeping — and only adds the link to the
        body. One dispatch path, not two.

        Raises:
            ValueError: ``vertrag_nicht_gefunden``, ``vertrag_nicht_erzeugt``,
                ``keine_charterer_adresse``, ``smtp_nicht_konfiguriert``,
                ``versand_fehlgeschlagen``.
        """
        contract = await self.get_contract(event_id)
        if contract is None:
            raise ValueError("vertrag_nicht_gefunden")
        if not contract.sign_token or not contract.document_key:
            raise ValueError("vertrag_nicht_erzeugt")
        return await self.send_to_charterer(event_id, include_sign_link=True)

    async def send_sealed_copy(self, event_id: UUID) -> None:
        """Send the finished document to the charterer and to accounting.

        Best-effort: a contract is signed and filed whether or not this mail
        goes out, so every failure is logged and swallowed. Losing a signature
        because a mail server was down would be a much worse trade.

        The counterparty holding their own copy is the strongest tamper
        evidence available — a record the Verein cannot retroactively alter —
        which is why this runs even though the seal already exists.
        """
        contract = await self.get_contract(event_id)
        if contract is None or not contract.sealed_document_key:
            return

        recipients = [str(contract.charterer_email)] if contract.charterer_email else []
        # The address that already receives the finance report — one setting,
        # no second one, and no address in the source.
        finance = (get_settings().finance_report_inbox or "").strip()
        if finance:
            recipients.append(finance)
        if not recipients:
            logger.info(
                "Sealed charter contract not mailed: no recipient configured",
                extra={"event_id": str(event_id)},
            )
            return

        try:
            pdf_bytes = self._read_object(contract.sealed_document_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not read the sealed contract for dispatch",
                extra={"event_id": str(event_id), "error": str(exc)[:120]},
            )
            return

        for recipient in recipients:
            try:
                client = get_gmail_client()
                await client.send_email(
                    EmailMessage(
                        to=recipient,
                        subject=f"Unterschriebener Chartervertrag — {contract.charterer_name}",
                        body_text=_sealed_body(contract),
                        attachments=[
                            Attachment(
                                filename=f"Chartervertrag-{contract.charterer_name}-signiert.pdf",
                                content=pdf_bytes,
                                content_type=RENDERED_CONTENT_TYPE,
                            ),
                        ],
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — see the docstring
                logger.warning(
                    "Sealed charter contract could not be mailed",
                    extra={"event_id": str(event_id), "error": str(exc)[:120]},
                )


def _dispatch_date(contract: CharterContract) -> str:
    """The handover date for subject lines and file names, German notation."""
    if contract.uebergabe_at is None:
        return ""
    return contract.uebergabe_at.strftime("%d.%m.%Y")


def _dispatch_subject(contract: CharterContract) -> str:
    handover = _dispatch_date(contract)
    suffix = f" – {handover}" if handover else ""
    return f"Chartervertrag Schaluppe{suffix}"


def _dispatch_filename(contract: CharterContract) -> str:
    """ASCII-only and dated — the file lands in a Downloads folder next to
    twenty others."""
    stamp = contract.uebergabe_at.strftime("%Y-%m-%d") if contract.uebergabe_at else "ohne-datum"
    return f"chartervertrag-{stamp}-v{contract.document_version}.pdf"


def _dispatch_body(contract: CharterContract, *, include_sign_link: bool = False) -> str:
    """The accompanying mail.

    Says what has to be done with the attachment, because the attachment is
    also the durable copy of the terms: read them *before* signing, bring two
    printouts to the handover. Kept short — the contract is four pages, the
    mail should not be a fifth.
    """
    greeting = f"Hallo {contract.charterer_name}," if contract.charterer_name else "Hallo,"
    handover = _dispatch_date(contract)
    when = f" für den {handover}" if handover else ""
    text = (
        f"{greeting}\n\n"
        f"im Anhang findest du den Chartervertrag für die Schaluppe{when}.\n\n"
        "Bitte lies den Vertrag samt der Bedingungen in den Klauseln 1 bis 17 vor der "
        "Übergabe durch. Zur Übergabe bringst du ihn bitte zweimal ausgedruckt mit — "
        "unterschrieben wird vor Ort, ein Exemplar bleibt bei dir.\n\n"
        "Wenn etwas nicht stimmt, melde dich bitte vor der Übergabe.\n\n"
        "Viele Grüße\n"
        "Verein für mobile Machenschaften e.V."
    )

    if include_sign_link and contract.sign_token:
        base = (get_settings().base_url or "").rstrip("/")
        link = f"{base}/vertrag/{contract.event_id}/{contract.sign_token}"
        text += (
            "\n\nDu kannst auch direkt online unterschreiben:\n"
            f"{link}\n"
            "Der Link gilt nur fuer diese Fassung des Vertrags — wird der "
            "Vertrag geaendert, bekommst du einen neuen."
        )
    return text



# Singleton instance
_charter_service: CharterService | None = None


def get_charter_service() -> CharterService:
    """Get or create CharterService instance."""
    global _charter_service
    if _charter_service is None:
        _charter_service = CharterService()
    return _charter_service


# ---------------------------------------------------------------------------
# In-app signing and sealing (spec 025 addendum)
# ---------------------------------------------------------------------------


def signature_image_key(event_id: UUID, role: SignatureRole) -> str:
    """Transient home for a drawn signature.

    Deleted once the signature has been composited into the sealed document —
    keeping a standalone image of somebody's handwriting for ten years is
    exposure with no purpose, since the signature survives inside the PDF.
    """
    return f"contracts/{event_id}/sig-{role.value}.png"


def sealed_document_key(event_id: UUID, version: int) -> str:
    return f"contracts/{event_id}/v{version}-gesiegelt.pdf"


def _decode_signature_image(image_b64: str) -> bytes:
    """Decode and sanity-check a canvas PNG.

    Bounded and format-checked because it arrives from an unauthenticated
    endpoint: the token proves the person holds a signing link, not that they
    are sending a picture.
    """
    import base64

    payload = image_b64.split(",", 1)[-1]  # tolerate a data: URL prefix
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("unterschrift_ungueltig") from exc
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("unterschrift_ungueltig")
    if len(raw) > 512_000:
        raise ValueError("unterschrift_zu_gross")
    return raw


def _sealed_body(contract: CharterContract) -> str:
    """Body of the mail carrying the finished contract."""
    return (
        f"Moin {contract.charterer_name},\n\n"
        "der Chartervertrag ist unterschrieben — im Anhang findest du das "
        "fertige Dokument. Es ist digital gesiegelt: jede nachträgliche "
        "Änderung an der Datei wäre nachweisbar.\n\n"
        "Bitte bewahre diese Mail auf; sie ist dein Nachweis über das, was "
        "vereinbart wurde.\n\n"
        "Viele Grüße\n"
        "Verein für mobile Machenschaften e.V."
    )
