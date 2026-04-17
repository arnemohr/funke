"""Closing report admin routes (specs 013 + 014)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...models import ReportMeta, ReportResponse, ReportVersion
from ...services.auth import CurrentUser
from ...services.report_service import get_report_service

router = APIRouter(prefix="/reports", tags=["admin.reports"])


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(report_id: UUID, _: CurrentUser) -> ReportResponse:
    service = get_report_service()
    meta = await service.get_report(report_id)
    if not meta:
        raise HTTPException(404, "not_found")
    return await service.build_response(meta)


@router.get("/{report_id}/versions/{version}", response_model=ReportVersion)
async def get_report_version(
    report_id: UUID,
    version: int,
    _: CurrentUser,
) -> ReportVersion:
    snap = await get_report_service().get_version(report_id, version)
    if not snap:
        raise HTTPException(404, "version_not_found")
    return snap


def _pdf_response(pdf_bytes: bytes, filename: str) -> StreamingResponse:
    from io import BytesIO

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{report_id}/pdf")
async def get_pdf(report_id: UUID, _: CurrentUser) -> StreamingResponse:
    service = get_report_service()
    meta = await service.get_report(report_id)
    if not meta:
        raise HTTPException(404, "not_found")
    pdf_bytes = await service.render_pdf(report_id, meta.current_version)
    snap = await service.get_version(report_id, meta.current_version)
    date_str = (snap.event_snapshot.get("date") if snap else "fahrbericht") or "fahrbericht"
    return _pdf_response(pdf_bytes, f"fahrbericht-{date_str}-v{meta.current_version}.pdf")


@router.get("/{report_id}/versions/{version}/pdf")
async def get_version_pdf(
    report_id: UUID,
    version: int,
    _: CurrentUser,
) -> StreamingResponse:
    service = get_report_service()
    snap = await service.get_version(report_id, version)
    if not snap:
        raise HTTPException(404, "version_not_found")
    pdf_bytes = await service.render_pdf(report_id, version)
    date_str = snap.event_snapshot.get("date", "fahrbericht")
    return _pdf_response(pdf_bytes, f"fahrbericht-{date_str}-v{version}.pdf")


@router.post("/{report_id}/resend", response_model=ReportResponse)
async def resend(report_id: UUID, _: CurrentUser) -> ReportResponse:
    service = get_report_service()
    meta = await service.get_report(report_id)
    if not meta:
        raise HTTPException(404, "not_found")
    await service.send_report_email(report_id)
    refreshed = await service.get_report(report_id)
    assert refreshed
    return await service.build_response(refreshed)


# ---------------------------------------------------------------------------
# Convenience lookup from an Event.
# ---------------------------------------------------------------------------

event_report_router = APIRouter(prefix="/events", tags=["admin.reports"])


@event_report_router.get("/{event_id}/report", response_model=ReportResponse)
async def get_report_for_event(event_id: UUID, _: CurrentUser) -> ReportResponse:
    service = get_report_service()
    meta = await service.get_report_for_event(event_id)
    if not meta:
        raise HTTPException(404, "not_found")
    return await service.build_response(meta)


routers = [router, event_report_router]
