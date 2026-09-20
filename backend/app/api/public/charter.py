"""Public charter-contract signing (spec 025 addendum).

Two routes, no authentication: the `sign_token` in the URL **is** the
permission, exactly as for the Fundsachen page, the gate and a companion's
personal ticket. The `event_id` beside it is deliberately not a secret — it
lets the row be fetched with a plain `GetItem` rather than paying for another
GSI, and on its own it opens nothing.

Every rejection answers with the same bare 404 and the same sentence. A 403, or
a second distinguishable message, would confirm that a contract exists for a
given event and turn this into an oracle for probing.

The token dies on every re-render, so a link always shows the document it was
issued for or nothing at all.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from ...models.charter import CharterPublicView, CharterSignRequest, SignatureRole
from ...services.charter_service import get_charter_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger, token_hint

logger = get_logger(__name__)

router = APIRouter()

# One answer for every rejection, as one constant, so no later branch can grow
# its own more helpful wording.
_NOT_FOUND_DETAIL = "Diesen Vertrag gibt es nicht (mehr)."

# Reachable only after the token has already matched, so it gives a prober
# nothing — and „the contract moved" needs its own words, because reloading is
# the fix and giving up is not.
_CHANGED_DETAIL = (
    "Der Vertrag wurde inzwischen geändert. Bitte lade die Seite neu und prüfe die neue Fassung."
)
_ALREADY_DETAIL = "Für diese Rolle liegt bereits eine Unterschrift vor."


def _not_found(event_id: UUID, token: str, reason: str) -> HTTPException:
    logger.info(
        "Charter signing link rejected",
        extra={"event_id": str(event_id), "token": token_hint(token), "reason": reason},
    )
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)


def _client_ip(request: Request) -> str | None:
    """The signer's address, from the one source they cannot write.

    Same reasoning as the photo upload endpoint: under Mangum
    `request.client.host` is the address API Gateway itself observed, not a
    header. `X-Forwarded-For` is deliberately not consulted — every hop in
    front of us appends to it, so a caller's forgery lands at the front of the
    list. For a signature audit record that would be worse than storing
    nothing, because it would look authoritative and be attacker-chosen.
    """
    return request.client.host if request.client else None


@router.get("/{event_id}/{token}", response_model=CharterPublicView)
async def get_contract_for_signing(
    event_id: UUID,
    token: str,
    request: Request,
) -> CharterPublicView:
    """What the signing page needs: the terms, and a link to the actual PDF."""
    service = get_charter_service()
    try:
        await service.get_by_sign_token(event_id, token)
    except ValueError as exc:
        raise _not_found(event_id, token, str(exc)) from exc

    # The event supplies only its name. Everything else on the page comes from
    # the contract row, which is the thing being agreed.
    event = await get_event_service().get_event_by_id(event_id)
    event_name = event.name if event else ""

    try:
        return await service.public_view(event_id, token, event_name=event_name)
    except ValueError as exc:
        # `vertrag_nicht_erzeugt`: a token cannot exist without a render, so
        # this means the object went missing rather than that the caller is
        # wrong. Still a 404 — there is nothing for them to sign.
        raise _not_found(event_id, token, str(exc)) from exc


@router.post("/{event_id}/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def sign_contract(
    event_id: UUID,
    token: str,
    payload: CharterSignRequest,
    request: Request,
) -> None:
    """Record the charterer's signature.

    Answers 204 with no body: the page has nothing to render afterwards but a
    thank-you, and the contract's internals are none of the charterer's
    business beyond the copy they are mailed.
    """
    service = get_charter_service()
    try:
        await service.get_by_sign_token(event_id, token)
    except ValueError as exc:
        raise _not_found(event_id, token, str(exc)) from exc

    try:
        await service.add_signature(
            event_id,
            SignatureRole.CHARTERER,
            signed_name=payload.signed_name,
            document_sha256=payload.document_sha256,
            image_b64=payload.image_b64,
            signer_ip=_client_ip(request),
            signer_user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        code = str(exc)
        if code == "vertrag_wurde_geaendert":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=_CHANGED_DETAIL,
            ) from exc
        if code == "bereits_unterschrieben":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_DETAIL,
            ) from exc
        if code in ("unterschrift_ungueltig", "unterschrift_zu_gross"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Die Unterschrift konnte nicht gelesen werden. Bitte nochmal zeichnen.",
            ) from exc
        raise _not_found(event_id, token, code) from exc

    logger.info(
        "Charter contract signed by the charterer",
        extra={"event_id": str(event_id)},
    )
