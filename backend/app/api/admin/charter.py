"""Admin charter contract API endpoints (spec 025 — Chartervertrag).

The whole organiser side of one event's charter contract: the draft form, the
render, the dispatch, the upload handshake for the signed scan, the
countersignature, and discarding a signature to correct it.

Mounted under `/api/admin/events`, so every route carries the event in its path
and every handler resolves it through `event_service.get_event(org_id, …)`
first — an event ID from another organisation is simply not found, exactly as
in `admin/lost_and_found.py`. **There is no public route**: the charterer never
authenticates against Funke, which is spec 025's largest simplification.

Unlike the older admin routers, every route here carries an explicit
`require_role`. Reading (the contract and its PDFs) is open to VIEWER; every
write is OWNER/ADMIN, matching `AdminUser.can_edit_events()`. Spec 025 gates its
own routes completely from the start rather than waiting for the mechanical
fix that is coming for the six routers which do not.

The Lambda never streams a PDF to the browser: `GET .../pdf` answers 302 onto a
short-lived presigned GET. The upload works the same way in reverse — a
presigned POST nailed to one key.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ...models import (
    CharterAdminSignRequest,
    CharterContract,
    CharterContractResponse,
    CharterContractUpsert,
    CharterCountersign,
    CharterSignedConfirm,
    CharterUpload,
    Event,
    EventType,
)
from ...services.auth import CurrentUser, RequireAdmin, RequireViewer
from ...services.charter_service import CharterIncompleteError, get_charter_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger, log_admin_action

logger = get_logger(__name__)

router = APIRouter(tags=["admin.charter"])


# Spec 025 § Fehler, verbatim: the identifier travels as `detail` so the page
# can branch on it, the German line is what the organiser reads. Anything not
# in here is a bug, and answering 400 with the raw identifier makes that
# visible rather than hiding it behind a friendly sentence.
_ERROR_RESPONSES: dict[str, tuple[int, str]] = {
    "charter_nur_fuer_einzelfahrten": (
        status.HTTP_409_CONFLICT,
        "Ein Chartervertrag kann nur zu einer Einzelfahrt angelegt werden.",
    ),
    "vertrag_bereits_unterschrieben": (
        status.HTTP_409_CONFLICT,
        "Ein unterschriebener Vertrag kann nicht geändert werden. "
        "Zum Korrigieren zuerst die Unterschrift verwerfen.",
    ),
    "vertrag_nicht_erzeugt": (
        status.HTTP_409_CONFLICT,
        "Es gibt noch kein PDF. Bitte zuerst „PDF erzeugen“.",
    ),
    "keine_charterer_adresse": (
        status.HTTP_409_CONFLICT,
        "Für den Versand fehlt die E-Mail-Adresse des Charterers.",
    ),
    "smtp_nicht_konfiguriert": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Mailversand ist nicht eingerichtet. Bitte das PDF herunterladen und "
        "selbst verschicken.",
    ),
    "datei_nicht_hochgeladen": (
        status.HTTP_404_NOT_FOUND,
        "Die hochgeladene Datei ist nicht angekommen. Bitte den Upload wiederholen.",
    ),
    "vertrag_nicht_unterschrieben": (
        status.HTTP_409_CONFLICT,
        "Dieser Vertrag ist nicht als unterschrieben markiert.",
    ),
    "vertrag_bereits_erzeugt": (
        status.HTTP_409_CONFLICT,
        "Ein Vertrag mit erzeugtem PDF kann nicht gelöscht werden.",
    ),
    # Beyond the spec's table, because the routes need them: the table lists the
    # refusals the organiser can provoke by acting too early, not the plain
    # „there is nothing here" and „the storage is down" cases every route has.
    "vertrag_nicht_gefunden": (
        status.HTTP_404_NOT_FOUND,
        "Für dieses Event gibt es noch keinen Chartervertrag.",
    ),
    "bestaetigung_fehlt": (
        status.HTTP_400_BAD_REQUEST,
        "Bitte bestätige, dass der Vertrag unterschrieben ist.",
    ),
    "dateityp_nicht_erlaubt": (
        status.HTTP_400_BAD_REQUEST,
        "Der unterschriebene Vertrag muss ein PDF oder ein JPEG-Foto sein.",
    ),
    "versand_fehlgeschlagen": (
        status.HTTP_502_BAD_GATEWAY,
        "Die E-Mail konnte nicht verschickt werden. Bitte das PDF herunterladen und "
        "selbst verschicken.",
    ),
    "bucket_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Vertragsspeicher ist in dieser Umgebung nicht eingerichtet.",
    ),
    "dokument_nicht_gespeichert": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Das PDF konnte nicht abgelegt werden — bitte versuch es noch einmal.",
    ),
    "dokument_nicht_lesbar": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Das PDF konnte nicht geladen werden — bitte versuch es noch einmal.",
    ),
    "download_nicht_moeglich": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Download konnte nicht vorbereitet werden — bitte versuch es noch einmal.",
    ),
    "upload_nicht_moeglich": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Der Upload konnte nicht vorbereitet werden — bitte versuch es noch einmal.",
    ),
}


def _map_error(error: Exception | str) -> HTTPException:
    """Turn a service error into its HTTP status and German detail.

    `CharterIncompleteError` is the one that cannot be a table lookup: its
    German line names the fields that are still missing, which is the entire
    point of the 422.
    """
    if isinstance(error, CharterIncompleteError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Es fehlen noch Angaben: {', '.join(error.fields)}.",
        )

    key = str(error)
    status_code, detail = _ERROR_RESPONSES.get(key, (status.HTTP_400_BAD_REQUEST, key))
    return HTTPException(status_code=status_code, detail=detail)


def _get_org_id(user: CurrentUser) -> UUID:
    """Extract organization ID from user token."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization ID not found in token",
        )
    return UUID(user.org_id)


async def _get_event_or_404(org_id: UUID, event_id: UUID) -> Event:
    """Fetch the event within the caller's organisation, or 404.

    The only authorisation this router needs beyond the role guard: `get_event`
    reads `pk=ORG#{org_id}`, so another organisation's event ID never resolves
    and its contract can be neither read nor written.
    """
    event = await get_event_service().get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event nicht gefunden",
        )
    return event


# --- Request payloads ---


class CharterUploadRequest(BaseModel):
    """What the browser is about to upload as the signed contract.

    The type is pinned into the presign policy, so it has to be declared before
    the signature is minted rather than discovered afterwards.
    """

    content_type: str = Field(default="application/pdf")


class CharterSendResponse(BaseModel):
    """Dispatch result: the contract as it now stands, plus who got the mail."""

    contract: CharterContractResponse
    sent_to: str


# --- Helpers ---


def _download_filename(contract: CharterContract, *, signed: bool) -> str:
    """A name the organiser can find again in a Downloads folder.

    Always `.pdf`, following the key: spec 025 pins the scan's key to
    `v{n}-signiert.pdf` even though a phone photo may be uploaded as JPEG. The
    stored Content-Type is the JPEG's, so the browser renders it correctly
    either way and only the saved file's suffix is a white lie — the
    alternative is a second name for the same object.
    """
    stamp = contract.uebergabe_at.strftime("%Y-%m-%d") if contract.uebergabe_at else "ohne-datum"
    suffix = "-signiert" if signed else ""
    return f"chartervertrag-{stamp}-v{contract.document_version}{suffix}.pdf"


def _contract_response(contract: CharterContract) -> CharterContractResponse:
    """The contract as the form needs it: live total plus both download links.

    A link that cannot be signed comes back as `None` rather than failing the
    request — the form still works when only the download button is dead.
    """
    service = get_charter_service()
    return CharterContractResponse.from_contract(
        contract,
        download_url=service.presign_download_or_none(
            contract.document_key,
            filename=_download_filename(contract, signed=False),
        ),
        signed_download_url=service.presign_download_or_none(
            contract.signed_document_key,
            filename=_download_filename(contract, signed=True),
        ),
    )


# --- The contract ---


@router.get(
    "/{event_id}/chartervertrag",
    response_model=CharterContractResponse,
    dependencies=[RequireViewer],
)
async def get_charter_contract(event_id: UUID, user: CurrentUser) -> CharterContractResponse:
    """Read the contract, or 404 when the event has none.

    `gesamtbetrag` is recomputed here rather than echoed from the row, so the
    form shows the total of what is currently typed; the stored value stays the
    one the last PDF printed.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    contract = await get_charter_service().get_contract(event_id)
    if contract is None:
        raise _map_error("vertrag_nicht_gefunden")

    return _contract_response(contract)


@router.put(
    "/{event_id}/chartervertrag",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def upsert_charter_contract(
    event_id: UUID,
    payload: CharterContractUpsert,
    user: CurrentUser,
) -> CharterContractResponse:
    """Create the contract on the first save, replace the typed fields after.

    Saves at any degree of completeness — the mandatory set is checked when a
    PDF is produced, not while somebody is still typing. The status stays
    `draft`.

    A FESTIVAL event is refused here and only here: a contract is one
    counterpart, one raft, one day. The row would sit under a FESTIVAL just as
    well, and since this is the only route that can create one, refusing it
    here means no festival can ever carry a contract.
    """
    org_id = _get_org_id(user)
    event = await _get_event_or_404(org_id, event_id)

    if event.event_type is EventType.FESTIVAL:
        raise _map_error("charter_nur_fuer_einzelfahrten")

    try:
        contract = await get_charter_service().upsert_contract(event_id, payload)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.save",
        user.email,
        str(event_id),
        {"status": contract.status.value},
    )

    return _contract_response(contract)


@router.delete(
    "/{event_id}/chartervertrag",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RequireAdmin],
)
async def delete_charter_contract(event_id: UUID, user: CurrentUser) -> None:
    """Delete the contract — only while it is a draft that never rendered.

    Once a PDF exists the row is the only thing that knows its key and hash,
    and the object is never deleted from the bucket.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        await get_charter_service().delete_contract(event_id)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action("charter.contract.delete", user.email, str(event_id))


# --- The document ---


@router.post(
    "/{event_id}/chartervertrag/render",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def render_charter_contract(event_id: UUID, user: CurrentUser) -> CharterContractResponse:
    """Check the mandatory set, render the PDF, store it as a new version.

    422 with a German field list when something is still missing — the point of
    this feature is that the contract is *correctly* filled in, so this is the
    one place that refuses on incompleteness.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().render(event_id)
    except CharterIncompleteError as e:
        raise _map_error(e) from e
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.render",
        user.email,
        str(event_id),
        {"document_version": contract.document_version},
    )

    return _contract_response(contract)


@router.get(
    "/{event_id}/chartervertrag/pdf",
    dependencies=[RequireViewer],
)
async def download_charter_pdf(
    event_id: UUID,
    user: CurrentUser,
    variant: str | None = Query(
        default=None,
        description="„signiert“ für den hochgeladenen Scan, sonst das erzeugte PDF.",
    ),
) -> RedirectResponse:
    """302 onto a short-lived presigned GET.

    A redirect rather than a streamed body: the Lambda has no business carrying
    the bytes, and the browser follows a navigation to S3 without a CORS
    preflight — which is why the bucket needs a POST rule for the upload and no
    GET rule for this.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    contract = await get_charter_service().get_contract(event_id)
    if contract is None:
        raise _map_error("vertrag_nicht_gefunden")

    signed = variant == "signiert"
    key = contract.signed_document_key if signed else contract.document_key
    if not key:
        raise _map_error("datei_nicht_hochgeladen" if signed else "vertrag_nicht_erzeugt")

    try:
        url = get_charter_service().presign_download(
            key,
            filename=_download_filename(contract, signed=signed),
        )
    except ValueError as e:
        raise _map_error(e) from e

    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.post(
    "/{event_id}/chartervertrag/senden",
    response_model=CharterSendResponse,
    dependencies=[RequireAdmin],
)
async def send_charter_contract(event_id: UUID, user: CurrentUser) -> CharterSendResponse:
    """Mail the rendered PDF to the charterer as an attachment.

    The attachment is also the copy on a durable medium (§ 312f Abs. 2 BGB) and,
    for an external charterer, the step that incorporates the clauses at all
    (§ 305 Abs. 2 BGB) — a fifteen-minute link would be neither. Status → sent.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().send_to_charterer(event_id)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.send",
        user.email,
        str(event_id),
        {"document_version": contract.document_version},
    )

    return CharterSendResponse(
        contract=_contract_response(contract),
        sent_to=contract.sent_to or "",
    )


# --- The signature ---


@router.post(
    "/{event_id}/chartervertrag/upload",
    response_model=CharterUpload,
    dependencies=[RequireAdmin],
)
async def create_charter_upload(
    event_id: UUID,
    body: CharterUploadRequest,
    user: CurrentUser,
) -> CharterUpload:
    """Mint one presigned POST for the signed scan.

    The browser uploads straight to S3 with the existing `postPresignedForm`
    and then calls `.../signiert`. Nailed to one key, one content type and a
    size window; anything else is refused by S3 rather than by us.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        upload = await get_charter_service().create_signed_upload(event_id, body.content_type)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.upload.mint",
        user.email,
        str(event_id),
        {"content_type": body.content_type},
    )

    return upload


@router.post(
    "/{event_id}/chartervertrag/signiert",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def confirm_charter_signed(
    event_id: UUID,
    body: CharterSignedConfirm,
    user: CurrentUser,
) -> CharterContractResponse:
    """Confirm the upload: the date on the paper plus the mandatory checkbox.

    The server checks the object is actually there, hashes exactly the bytes
    S3 holds, and only then sets `signed`. The Vercharterer's countersignature
    is deliberately not asked for — it never gates this.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().confirm_signed(
            event_id,
            body,
            signed_by=user.email,
        )
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.signed",
        user.email,
        str(event_id),
        {
            "signed_on": body.signed_on.isoformat(),
            "bytes": contract.signed_document_bytes,
        },
    )

    return _contract_response(contract)


@router.post(
    "/{event_id}/chartervertrag/signaturlink",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def send_signing_link(
    event_id: UUID,
    user: CurrentUser,
) -> CharterContractResponse:
    """Mail the charterer the signing link, with the PDF attached.

    The attachment is not redundant with the link: it is the § 312f Abs. 2 copy
    on a durable medium, and for an external charterer it is what puts the AGB
    in front of them before they agree rather than at the pontoon.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().send_signing_link(event_id)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action("charter.contract.sign_link", user.email, str(event_id))
    return _contract_response(contract)


@router.post(
    "/{event_id}/chartervertrag/unterschreiben",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def sign_charter_contract_as_admin(
    event_id: UUID,
    body: CharterAdminSignRequest,
    user: CurrentUser,
) -> CharterContractResponse:
    """Sign as the Schiffsführer or for the Vercharterer.

    Both are people with a login — the skipper is a crew member — so neither
    needs a public token. That is why there is exactly one signing link per
    contract and not three.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    contract = await get_charter_service().get_contract(event_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vertrag_nicht_gefunden")

    try:
        contract = await get_charter_service().add_signature(
            event_id,
            body.role,
            signed_name=body.signed_name,
            document_sha256=contract.document_sha256 or "",
            image_b64=body.image_b64,
            by_admin=user.email,
        )
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.sign",
        user.email,
        str(event_id),
        {"role": body.role.value},
    )
    return _contract_response(contract)


@router.post(
    "/{event_id}/chartervertrag/gegenzeichnung",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def countersign_charter_contract(
    event_id: UUID,
    body: CharterCountersign,
    user: CurrentUser,
) -> CharterContractResponse:
    """File the Vercharterer's countersignature, whenever it happens.

    Allowed at any time, years later included, and on a contract that is not
    signed yet. Touches neither the status nor the document nor either hash —
    the countersignature is a separate fact about a separate line.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().countersign(
            event_id,
            body.countersigned_on,
            countersigned_by=user.email,
        )
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.countersign",
        user.email,
        str(event_id),
        {"countersigned_on": body.countersigned_on.isoformat()},
    )

    return _contract_response(contract)


@router.post(
    "/{event_id}/chartervertrag/unsign",
    response_model=CharterContractResponse,
    dependencies=[RequireAdmin],
)
async def unsign_charter_contract(event_id: UUID, user: CurrentUser) -> CharterContractResponse:
    """Discard the signature so the contract can be corrected.

    The old key moves into `superseded_signed_keys` and the object stays in the
    bucket — with a signed contract the bytes *are* the agreement, so nothing
    about them is ever quietly replaced. Status → draft, and the form unlocks.
    """
    org_id = _get_org_id(user)
    await _get_event_or_404(org_id, event_id)

    try:
        contract = await get_charter_service().unsign(event_id)
    except ValueError as e:
        raise _map_error(e) from e

    log_admin_action(
        "charter.contract.unsign",
        user.email,
        str(event_id),
        {"superseded": len(contract.superseded_signed_keys)},
    )

    return _contract_response(contract)
