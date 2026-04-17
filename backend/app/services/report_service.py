"""Closing report service (spec 013).

Persists per-version snapshots of a Fahrbericht, renders PDFs via WeasyPrint,
and emails finance. Reuses the existing SMTP pipeline (`email_client.py`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import (
    BarItem,
    EmailStatus,
    Fahrbericht,
    LineItem,
    ReportMeta,
    ReportResponse,
    ReportTotals,
    ReportVersion,
    Tour,
)
from ..models.report import ExpenseLine as ReportExpenseLine
from .bar_service import get_bar_service
from .booking_text import build_booking_text
from .config import (
    REPORT_PK_PREFIX,
    REPORT_SK_META,
    REPORT_SK_VERSION_PREFIX,
    REPORTS_LIST_PK,
    TOUR_PK_PREFIX,
    TOUR_SK_REPORT_POINTER,
    get_reports_table,
    get_settings,
    get_tours_table,
)
from .email_client import Attachment, EmailMessage, get_gmail_client
from .fahrbericht_service import get_fahrbericht_service
from .logging import get_logger
from .tour_service import get_tour_service

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    def _fmt(v) -> str:
        return f"{Decimal(v):.2f}" if v is not None else "—"

    env.filters["fmt"] = _fmt
    env.globals["fmt"] = _fmt  # template uses it as a function: {{ fmt(value) }}
    return env


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _req_dec(v) -> Decimal:
    return _dec(v) or Decimal("0")


def _meta_to_item(meta: ReportMeta) -> dict:
    return {
        "pk": f"{REPORT_PK_PREFIX}{meta.id}",
        "sk": REPORT_SK_META,
        "entity_type": "ReportMeta",
        "id": str(meta.id),
        "tour_id": str(meta.tour_id),
        "current_version": meta.current_version,
        "finance_recipient": meta.finance_recipient,
        "email_status": meta.email_status.value,
        "email_attempts": meta.email_attempts,
        "email_last_error": meta.email_last_error,
        "email_last_attempt_at": (
            meta.email_last_attempt_at.isoformat() if meta.email_last_attempt_at else None
        ),
        "sent_at": meta.sent_at.isoformat() if meta.sent_at else None,
        "created_at": meta.created_at.isoformat(),
        "updated_at": meta.updated_at.isoformat(),
        # GSI
        "list_pk": REPORTS_LIST_PK,
        "list_sk": f"{meta.updated_at.isoformat()}#{meta.id}",
    }


def _item_to_meta(item: dict) -> ReportMeta:
    return ReportMeta(
        id=UUID(item["id"]),
        tour_id=UUID(item["tour_id"]),
        current_version=int(item.get("current_version", 0)),
        finance_recipient=item.get("finance_recipient"),
        email_status=EmailStatus(item.get("email_status", "PENDING")),
        email_attempts=int(item.get("email_attempts", 0)),
        email_last_error=item.get("email_last_error"),
        email_last_attempt_at=(
            datetime.fromisoformat(item["email_last_attempt_at"])
            if item.get("email_last_attempt_at")
            else None
        ),
        sent_at=datetime.fromisoformat(item["sent_at"]) if item.get("sent_at") else None,
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def _version_to_item(v: ReportVersion) -> dict:
    return {
        "pk": f"{REPORT_PK_PREFIX}{v.report_id}",
        "sk": f"{REPORT_SK_VERSION_PREFIX}{v.version:04d}",
        "entity_type": "ReportVersion",
        "report_id": str(v.report_id),
        "version": v.version,
        "tour_id": str(v.tour_id),
        "fahrbericht_snapshot": v.fahrbericht_snapshot,
        "tour_snapshot": v.tour_snapshot,
        "bar_catalog_snapshot": v.bar_catalog_snapshot,
        "kiosk_summary": [li.model_dump(mode="json") for li in v.kiosk_summary],
        "crew_summary": [li.model_dump(mode="json") for li in v.crew_summary],
        "expenses_summary": [e.model_dump(mode="json") for e in v.expenses_summary],
        "totals": v.totals.model_dump(mode="json"),
        "booking_text": v.booking_text,
        "pdf_s3_key": v.pdf_s3_key,
        "generated_at": v.generated_at.isoformat(),
    }


def _item_to_version(item: dict) -> ReportVersion:
    totals_raw = item.get("totals") or {}
    return ReportVersion(
        report_id=UUID(item["report_id"]),
        version=int(item["version"]),
        tour_id=UUID(item["tour_id"]),
        fahrbericht_snapshot=item.get("fahrbericht_snapshot") or {},
        tour_snapshot=item.get("tour_snapshot") or {},
        bar_catalog_snapshot=item.get("bar_catalog_snapshot") or {},
        kiosk_summary=[LineItem(**li) for li in item.get("kiosk_summary") or []],
        crew_summary=[LineItem(**li) for li in item.get("crew_summary") or []],
        expenses_summary=[ReportExpenseLine(**e) for e in item.get("expenses_summary") or []],
        totals=ReportTotals(
            kiosk_total=_req_dec(totals_raw.get("kiosk_total")),
            crew_cost=_req_dec(totals_raw.get("crew_cost")),
            expenses_total=_req_dec(totals_raw.get("expenses_total")),
            soll=_req_dec(totals_raw.get("soll")),
            cash_amount=_dec(totals_raw.get("cash_amount")),
            cash_diff=_req_dec(totals_raw.get("cash_diff")),
        ),
        booking_text=item.get("booking_text", ""),
        pdf_s3_key=item.get("pdf_s3_key"),
        generated_at=datetime.fromisoformat(item["generated_at"]),
    )


class ReportService:
    def __init__(self):
        self._table = None
        self._tours_table = None
        self._s3 = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_reports_table()
        return self._table

    @property
    def tours_table(self) -> "Table":
        if self._tours_table is None:
            self._tours_table = get_tours_table()
        return self._tours_table

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=get_settings().aws_region)
        return self._s3

    # ----------------------------------------------------------------- CRUD
    async def list_reports(
        self,
        *,
        status: EmailStatus | None = None,
        limit: int = 100,
    ) -> list[ReportMeta]:
        try:
            resp = self.table.query(
                IndexName="reports-by-date-index",
                KeyConditionExpression=Key("list_pk").eq(REPORTS_LIST_PK),
                ScanIndexForward=False,
                Limit=limit,
            )
            items = resp.get("Items", [])
        except ClientError:
            scan = self.table.scan(FilterExpression=Attr("entity_type").eq("ReportMeta"))
            items = scan.get("Items", [])
            items.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        metas = [_item_to_meta(i) for i in items]
        if status:
            metas = [m for m in metas if m.email_status == status]
        return metas

    async def get_report(self, report_id: UUID) -> ReportMeta | None:
        resp = self.table.get_item(
            Key={"pk": f"{REPORT_PK_PREFIX}{report_id}", "sk": REPORT_SK_META},
        )
        item = resp.get("Item")
        return _item_to_meta(item) if item else None

    async def list_versions(self, report_id: UUID) -> list[int]:
        resp = self.table.query(
            KeyConditionExpression=(
                Key("pk").eq(f"{REPORT_PK_PREFIX}{report_id}")
                & Key("sk").begins_with(REPORT_SK_VERSION_PREFIX)
            ),
        )
        versions = [int(i["version"]) for i in resp.get("Items", [])]
        versions.sort()
        return versions

    async def get_version(self, report_id: UUID, version: int) -> ReportVersion | None:
        resp = self.table.get_item(
            Key={
                "pk": f"{REPORT_PK_PREFIX}{report_id}",
                "sk": f"{REPORT_SK_VERSION_PREFIX}{version:04d}",
            },
        )
        item = resp.get("Item")
        return _item_to_version(item) if item else None

    async def get_report_for_tour(self, tour_id: UUID) -> ReportMeta | None:
        pointer = self.tours_table.get_item(
            Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_REPORT_POINTER},
        ).get("Item")
        if not pointer:
            return None
        return await self.get_report(UUID(pointer["report_id"]))

    async def build_response(self, meta: ReportMeta) -> ReportResponse:
        versions = await self.list_versions(meta.id)
        return ReportResponse(**meta.model_dump(), versions=versions)

    # ------------------------------------------------------- create_or_update
    async def create_or_update_report(self, tour_id: UUID, version: int) -> ReportMeta:
        bericht = await get_fahrbericht_service().get(tour_id)
        if not bericht:
            raise ValueError("fahrbericht_not_found")
        tour = await get_tour_service().get_tour(tour_id)
        if not tour:
            raise ValueError("tour_not_found")

        bar_service = get_bar_service()
        catalog_list = await bar_service.list_bar_items()
        catalog = {b.id: b for b in catalog_list}

        existing_meta = await self.get_report_for_tour(tour_id)
        report_id = existing_meta.id if existing_meta else uuid4()
        created_at = existing_meta.created_at if existing_meta else datetime.now(timezone.utc)

        # Build snapshots + summaries.
        snap_version = _build_version_snapshot(
            report_id=report_id,
            version=version,
            tour=tour,
            bericht=bericht,
            catalog=catalog,
        )

        # Write the version row (idempotent per version).
        try:
            self.table.put_item(
                Item=_version_to_item(snap_version),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

        settings = get_settings()
        recipient = settings.finance_report_inbox
        email_status = (
            EmailStatus.SKIPPED_NO_RECIPIENT if not recipient else EmailStatus.PENDING
        )

        meta = ReportMeta(
            id=report_id,
            tour_id=tour_id,
            current_version=version,
            finance_recipient=recipient,
            email_status=email_status,
            email_attempts=0,
            email_last_error=None,
            email_last_attempt_at=None,
            sent_at=existing_meta.sent_at if existing_meta else None,
            created_at=created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.table.put_item(Item=_meta_to_item(meta))

        # Pointer row from Tour → Report (idempotent).
        try:
            self.tours_table.put_item(
                Item={
                    "pk": f"{TOUR_PK_PREFIX}{tour_id}",
                    "sk": TOUR_SK_REPORT_POINTER,
                    "entity_type": "TourReportPointer",
                    "tour_id": str(tour_id),
                    "report_id": str(report_id),
                },
                ConditionExpression=(
                    "attribute_not_exists(pk) OR report_id = :rid"
                ),
                ExpressionAttributeValues={":rid": str(report_id)},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

        # Kick off the email; never raise.
        try:
            await self.send_report_email(report_id)
        except Exception:  # noqa: BLE001
            logger.exception("report.send_email.unexpected", extra={"report_id": str(report_id)})

        # Reload META after send to return current email state.
        refreshed = await self.get_report(report_id)
        return refreshed or meta

    # ------------------------------------------------------ send_report_email
    async def send_report_email(self, report_id: UUID) -> None:
        meta = await self.get_report(report_id)
        if not meta:
            raise ValueError("report_not_found")
        if meta.email_status == EmailStatus.SKIPPED_NO_RECIPIENT:
            return
        if not meta.finance_recipient:
            self._update_email(report_id, status=EmailStatus.SKIPPED_NO_RECIPIENT)
            return

        version_snap = await self.get_version(report_id, meta.current_version)
        if not version_snap:
            raise ValueError("version_not_found")

        try:
            pdf_bytes = await self.render_pdf(report_id, meta.current_version)
        except Exception as exc:  # noqa: BLE001
            logger.exception("report.render_pdf.failed")
            self._update_email(
                report_id,
                status=EmailStatus.FAILED,
                attempts=meta.email_attempts + 1,
                error=f"PDF-Render fehlgeschlagen: {exc}",
                attempted_at=datetime.now(timezone.utc),
            )
            return

        date_str = version_snap.tour_snapshot.get("date", "")
        tour_name = version_snap.tour_snapshot.get("name") or "Fahrt"
        is_update = meta.current_version >= 2
        subject = (
            f"Schaluppe Fahrbericht (Aktualisierung v{meta.current_version}) – {date_str} – {tour_name}"
            if is_update
            else f"Schaluppe Fahrbericht – {date_str} – {tour_name}"
        )
        lead = (
            f"Hallo Finance-Team,\n\nanbei die aktualisierte Version v{meta.current_version} des Fahrberichts der Schaluppe vom {date_str}.\n\n"
            if is_update
            else f"Hallo Finance-Team,\n\nanbei der Fahrbericht der Schaluppe vom {date_str}.\n\n"
        )
        body = lead + version_snap.booking_text + "\n\n— Funke"
        filename = f"fahrbericht-{date_str}-v{meta.current_version}.pdf"

        message = EmailMessage(
            to=meta.finance_recipient,
            subject=subject,
            body_text=body,
            attachments=[
                Attachment(filename=filename, content=pdf_bytes, content_type="application/pdf"),
            ],
        )

        try:
            client = get_gmail_client()
        except ValueError:
            logger.warning("report.email.smtp_unconfigured", extra={"report_id": str(report_id)})
            self._update_email(
                report_id,
                status=EmailStatus.SKIPPED_NO_RECIPIENT,
                attempts=meta.email_attempts + 1,
                error="SMTP not configured",
                attempted_at=datetime.now(timezone.utc),
            )
            return

        try:
            result = await client.send_email(message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("report.email.send_failed", extra={"report_id": str(report_id)})
            self._update_email(
                report_id,
                status=EmailStatus.FAILED,
                attempts=meta.email_attempts + 1,
                error=str(exc),
                attempted_at=datetime.now(timezone.utc),
            )
            return

        if result.success:
            self._update_email(
                report_id,
                status=EmailStatus.SENT,
                attempts=meta.email_attempts + 1,
                error=None,
                attempted_at=datetime.now(timezone.utc),
                sent_at=datetime.now(timezone.utc),
            )
        else:
            self._update_email(
                report_id,
                status=EmailStatus.FAILED,
                attempts=meta.email_attempts + 1,
                error=result.error,
                attempted_at=datetime.now(timezone.utc),
            )

    def _update_email(
        self,
        report_id: UUID,
        *,
        status: EmailStatus,
        attempts: int | None = None,
        error: str | None = None,
        attempted_at: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        expr_parts = ["email_status = :s", "updated_at = :u"]
        values = {":s": status.value, ":u": datetime.now(timezone.utc).isoformat()}
        if attempts is not None:
            expr_parts.append("email_attempts = :a")
            values[":a"] = attempts
        if error is not None:
            expr_parts.append("email_last_error = :e")
            values[":e"] = error
        if attempted_at:
            expr_parts.append("email_last_attempt_at = :la")
            values[":la"] = attempted_at.isoformat()
        if sent_at:
            expr_parts.append("sent_at = :st")
            values[":st"] = sent_at.isoformat()
        self.table.update_item(
            Key={"pk": f"{REPORT_PK_PREFIX}{report_id}", "sk": REPORT_SK_META},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeValues=values,
        )

    # ------------------------------------------------------------- render_pdf
    async def render_pdf(self, report_id: UUID, version: int) -> bytes:
        snap = await self.get_version(report_id, version)
        if not snap:
            raise ValueError("version_not_found")

        settings = get_settings()
        bucket = settings.reports_s3_bucket
        if bucket and snap.pdf_s3_key:
            try:
                obj = self.s3.get_object(Bucket=bucket, Key=snap.pdf_s3_key)
                return obj["Body"].read()
            except ClientError:
                logger.warning("report.pdf.cache_miss", extra={"key": snap.pdf_s3_key})

        # Try WeasyPrint first (matches the HTML layout), fall back to fpdf2
        # if the native deps aren't available (prod without the layer).
        pdf_bytes: bytes | None = None
        try:
            html = _render_html(snap)
            pdf_bytes = _html_to_pdf(html)
        except Exception:  # noqa: BLE001 — template failures shouldn't block finance
            logger.exception("report.pdf.weasyprint_failed — falling back to fpdf")
            pdf_bytes = None
        if pdf_bytes is None:
            pdf_bytes = _snapshot_to_pdf_fpdf(snap)

        if bucket:
            key = f"reports/{report_id}/v{version}.pdf"
            try:
                self.s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=pdf_bytes,
                    ContentType="application/pdf",
                )
                self.table.update_item(
                    Key={
                        "pk": f"{REPORT_PK_PREFIX}{report_id}",
                        "sk": f"{REPORT_SK_VERSION_PREFIX}{version:04d}",
                    },
                    UpdateExpression="SET pdf_s3_key = :k",
                    ExpressionAttributeValues={":k": key},
                )
            except ClientError:
                logger.exception("report.pdf.upload_failed")

        return pdf_bytes


_service: ReportService | None = None


def get_report_service() -> ReportService:
    global _service
    if _service is None:
        _service = ReportService()
    return _service


# ---------------------------------------------------------------------------
# Helpers (snapshot building, HTML/PDF rendering)
# ---------------------------------------------------------------------------


def _tour_snapshot(tour: Tour) -> dict:
    return {
        "id": str(tour.id),
        "event_id": str(tour.event_id) if tour.event_id else None,
        "name": tour.name,
        "date": tour.date.isoformat(),
        "duration_hours": str(tour.duration_hours) if tour.duration_hours is not None else None,
        "guest_count": tour.guest_count,
        "charterer": tour.charterer,
        "funker_name": tour.funker.display_name if tour.funker else None,
        "skipper_name": tour.skipper.display_name if tour.skipper else None,
        "crew_names": ", ".join(c.display_name for c in tour.crew) if tour.crew else None,
        "status": tour.status.value,
    }


def _bar_catalog_snapshot(
    bericht: Fahrbericht,
    catalog: dict[UUID, BarItem],
) -> dict[str, dict]:
    referenced = set(bericht.kiosk_tally) | set(bericht.crew_tally)
    snap: dict[str, dict] = {}
    for bid in referenced:
        bar = catalog.get(bid)
        if not bar:
            continue
        snap[str(bid)] = {
            "name": bar.name,
            "serving_unit": bar.serving_unit,
            "package_unit": bar.package_unit,
            "servings_per_package": bar.servings_per_package,
            "category": bar.category.value,
            "note": bar.note,
            "ek": str(bar.ek),
            "kb": str(bar.kb),
        }
    return snap


def _build_version_snapshot(
    *,
    report_id: UUID,
    version: int,
    tour: Tour,
    bericht: Fahrbericht,
    catalog: dict[UUID, BarItem],
) -> ReportVersion:
    kiosk_summary: list[LineItem] = []
    kiosk_total = Decimal("0")
    for bid, qty in bericht.kiosk_tally.items():
        if not qty or bid not in catalog:
            continue
        bar = catalog[bid]
        total = Decimal(qty) * bar.kb
        kiosk_total += total
        kiosk_summary.append(
            LineItem(
                bar_item_id=bid,
                bar_item_name=bar.name,
                qty=qty,
                unit_price=bar.kb,
                line_total=total,
            ),
        )

    crew_summary: list[LineItem] = []
    crew_cost = Decimal("0")
    for bid, qty in bericht.crew_tally.items():
        if not qty or bid not in catalog:
            continue
        bar = catalog[bid]
        total = Decimal(qty) * bar.ek
        crew_cost += total
        crew_summary.append(
            LineItem(
                bar_item_id=bid,
                bar_item_name=bar.name,
                qty=qty,
                unit_price=bar.ek,
                line_total=total,
            ),
        )

    expenses_summary = [
        ReportExpenseLine(description=e.description, amount=e.amount) for e in bericht.expenses
    ]
    expenses_total = sum((e.amount for e in bericht.expenses), Decimal("0"))
    soll = kiosk_total + bericht.boarding_fee + bericht.bar_surcharge
    cash = bericht.cash_amount or Decimal("0")

    totals = ReportTotals(
        kiosk_total=kiosk_total,
        crew_cost=crew_cost,
        expenses_total=expenses_total,
        soll=soll,
        cash_amount=bericht.cash_amount,
        cash_diff=cash - soll,
    )

    booking_text = build_booking_text(bericht, tour, catalog)

    return ReportVersion(
        report_id=report_id,
        version=version,
        tour_id=tour.id,
        fahrbericht_snapshot=json.loads(bericht.model_dump_json()),
        tour_snapshot=_tour_snapshot(tour),
        bar_catalog_snapshot=_bar_catalog_snapshot(bericht, catalog),
        kiosk_summary=kiosk_summary,
        crew_summary=crew_summary,
        expenses_summary=expenses_summary,
        totals=totals,
        booking_text=booking_text,
    )


def _render_html(snap: ReportVersion) -> str:
    env = _jinja_env()
    template = env.get_template("report.html")
    ship_tiles = _ship_tiles(snap.fahrbericht_snapshot.get("ship_status") or {})
    cash_diff = snap.totals.cash_diff
    context: dict[str, Any] = {
        "version": snap.version,
        "generated_at": snap.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "tour": snap.tour_snapshot,
        "kiosk_summary": snap.kiosk_summary,
        "crew_summary": snap.crew_summary,
        "expenses_summary": snap.expenses_summary,
        "totals": {
            "kiosk_total": snap.totals.kiosk_total,
            "crew_cost": snap.totals.crew_cost,
            "expenses_total": snap.totals.expenses_total,
            "soll": snap.totals.soll,
            "cash_amount": snap.totals.cash_amount,
            "cash_diff": cash_diff,
            "cash_diff_ok": abs(cash_diff) < Decimal("0.5"),
            "cash_diff_signed_positive": cash_diff > 0,
        },
        "booking_text": snap.booking_text,
        "ship_tiles": ship_tiles,
        "new_notes": snap.fahrbericht_snapshot.get("new_notes") or [],
        "new_todos": snap.fahrbericht_snapshot.get("new_todos") or [],
        "report_id_short": str(snap.report_id)[:8],
    }
    return template.render(**context)


def _ship_tiles(ship_status: dict) -> list[dict]:
    def _or_dash(v: Any) -> str:
        return "—" if v is None else str(v)

    return [
        {"label": "Tank 1", "value": _or_dash(ship_status.get("tank1_pct")) + ("%" if ship_status.get("tank1_pct") is not None else "")},
        {"label": "Tank 2", "value": _or_dash(ship_status.get("tank2_pct")) + ("%" if ship_status.get("tank2_pct") is not None else "")},
        {"label": "Kanister an Bord", "value": _or_dash(ship_status.get("kanister_aboard"))},
        {"label": "Kanister Garage", "value": _or_dash(ship_status.get("kanister_garage"))},
        {"label": "Wasser gefüllt", "value": _or_dash(ship_status.get("water_filled_at"))},
        {"label": "CO₂", "value": _or_dash(ship_status.get("co2_level"))},
        {"label": "Batterie", "value": _or_dash(ship_status.get("battery_pct")) + ("%" if ship_status.get("battery_pct") is not None else "")},
        {"label": "Klo 1", "value": _or_dash(ship_status.get("klo1_level"))},
        {"label": "Klo 2", "value": _or_dash(ship_status.get("klo2_level"))},
        {"label": "Persennig", "value": _or_dash(ship_status.get("persennig_status"))},
    ]


def _html_to_pdf(html: str) -> bytes:
    """Render the report to PDF.

    Tries WeasyPrint first (HTML→PDF, matches the Jinja layout closely). When
    WeasyPrint isn't available — e.g. no Lambda layer attached — falls back to
    an `fpdf2` renderer that pulls the structured fields from the current
    snapshot. The fallback skips CSS styling but keeps all the data.
    """
    try:
        from weasyprint import HTML  # type: ignore

        return HTML(string=html).write_pdf()
    except ImportError:
        return None  # type: ignore[return-value]  # caller handles fpdf fallback


def _snapshot_to_pdf_fpdf(snap: "ReportVersion") -> bytes:
    """Fallback PDF renderer using fpdf2 (pure Python, no native deps).

    Produces a plain-but-legible A4 report: header, fahrt info, kiosk/crew
    line items, cash reconciliation, and the booking text block.
    """
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def header(text: str, size: int = 13) -> None:
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(26, 39, 68)  # navy
        pdf.cell(0, 8, _ascii(text), ln=1)
        pdf.set_text_color(0, 0, 0)

    def subhead(text: str) -> None:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(45, 140, 124)
        pdf.cell(0, 6, _ascii(text.upper()), ln=1, border="B")
        pdf.set_text_color(0, 0, 0)

    def kv(k: str, v: str) -> None:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(40, 5, _ascii(k), ln=0)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 5, _ascii(v), ln=1)

    def row(cols: list[tuple[str, int, str]]) -> None:
        pdf.set_font("Helvetica", "", 9)
        for text, width, align in cols:
            pdf.cell(width, 5, _ascii(text), ln=0, align=align)
        pdf.ln(5)

    header(f"Schaluppe Fahrbericht - v{snap.version}")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4, _ascii(f"Verein fuer mobile Machenschaften e.V.  |  generiert {snap.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"), ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    tour = snap.tour_snapshot or {}
    subhead("Fahrtinfo")
    kv("Datum", str(tour.get("date") or "-"))
    kv("Veranstaltung", str(tour.get("name") or "-"))
    kv("Dauer", f"{tour.get('duration_hours') or '-'} h")
    gc = tour.get("guest_count")
    kv("Gaeste", str(gc if gc is not None else "-"))
    kv("Charterer", str(tour.get("charterer") or "-"))
    kv("Funker*in", str(tour.get("funker_name") or "-"))
    kv("Skipper", str(tour.get("skipper_name") or "-"))
    if tour.get("crew_names"):
        kv("Crew", str(tour["crew_names"]))

    subhead("Kiosk-Einnahmen (8400)")
    if snap.kiosk_summary:
        pdf.set_font("Helvetica", "B", 8)
        row([("Getraenk", 90, "L"), ("Menge", 25, "R"), ("EUR/St.", 35, "R"), ("Summe", 30, "R")])
        for li in snap.kiosk_summary:
            row([
                (li.bar_item_name, 90, "L"),
                (str(li.qty), 25, "R"),
                (f"{li.unit_price:.2f}", 35, "R"),
                (f"{li.line_total:.2f}", 30, "R"),
            ])
        pdf.set_font("Helvetica", "B", 9)
        row([("", 150, "L"), ("Summe", 0, "R")])
        row([("", 115, "L"), (f"EUR {snap.totals.kiosk_total:.2f}", 65, "R")])
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, "- keine Kiosk-Einnahmen -", ln=1)

    subhead("Crew-Verkoestigung (4220)")
    if snap.crew_summary:
        pdf.set_font("Helvetica", "B", 8)
        row([("Getraenk", 90, "L"), ("Menge", 25, "R"), ("EK/St.", 35, "R"), ("Summe", 30, "R")])
        for li in snap.crew_summary:
            row([
                (li.bar_item_name, 90, "L"),
                (str(li.qty), 25, "R"),
                (f"{li.unit_price:.2f}", 35, "R"),
                (f"{li.line_total:.2f}", 30, "R"),
            ])
        pdf.set_font("Helvetica", "B", 9)
        row([("", 115, "L"), (f"EUR {snap.totals.crew_cost:.2f}", 65, "R")])
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, "- keine Crew-Verkoestigung -", ln=1)

    if snap.expenses_summary:
        subhead("Ausgaben waehrend Fahrt")
        for e in snap.expenses_summary:
            row([(e.description, 130, "L"), (f"EUR {e.amount:.2f}", 50, "R")])
        pdf.set_font("Helvetica", "B", 9)
        row([("Summe", 130, "L"), (f"EUR {snap.totals.expenses_total:.2f}", 50, "R")])

    subhead("Kassenabgleich")
    kv("Soll (Kiosk + Umlagen)", f"EUR {snap.totals.soll:.2f}")
    cash_amount = snap.totals.cash_amount
    kv("Ist (Bargeld Umschlag)", f"EUR {cash_amount:.2f}" if cash_amount is not None else "-")
    diff = snap.totals.cash_diff
    sign = "+" if diff > 0 else ""
    kv("Differenz", f"EUR {sign}{diff:.2f}")

    subhead("Buchungstext")
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(30, 30, 30)
    for line in snap.booking_text.splitlines():
        pdf.cell(0, 4, _ascii(line), ln=1)
    pdf.set_text_color(0, 0, 0)

    # Ship status + notes/todos
    ship = (snap.fahrbericht_snapshot or {}).get("ship_status") or {}
    if any(v is not None for v in ship.values()):
        subhead("Schiff-Status am Ende der Fahrt")
        for label, key, suffix in [
            ("Tank 1", "tank1_pct", "%"),
            ("Tank 2", "tank2_pct", "%"),
            ("Kanister an Bord", "kanister_aboard", ""),
            ("Kanister Garage", "kanister_garage", ""),
            ("Wasser gefuellt", "water_filled_at", ""),
            ("CO2", "co2_level", ""),
            ("Batterie", "battery_pct", "%"),
            ("Klo 1", "klo1_level", ""),
            ("Klo 2", "klo2_level", ""),
            ("Persennig", "persennig_status", ""),
        ]:
            val = ship.get(key)
            if val is not None:
                kv(label, f"{val}{suffix}")

    new_notes = (snap.fahrbericht_snapshot or {}).get("new_notes") or []
    new_todos = (snap.fahrbericht_snapshot or {}).get("new_todos") or []
    if new_notes or new_todos:
        subhead("Notizen & Todos")
        pdf.set_font("Helvetica", "", 9)
        if new_notes:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, "Notizen:", ln=1)
            pdf.set_font("Helvetica", "", 9)
            for n in new_notes:
                pdf.cell(0, 4, _ascii(f"  - {n}"), ln=1)
        if new_todos:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, "Offene Todos:", ln=1)
            pdf.set_font("Helvetica", "", 9)
            for t in new_todos:
                pdf.cell(0, 4, _ascii(f"  - {t}"), ln=1)

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(
        0,
        4,
        _ascii(f"Vertraulich - nur fuer internen Gebrauch  |  Report {str(snap.report_id)[:8]} v{snap.version}"),
        ln=1,
        align="C",
    )

    out = pdf.output(dest="S")
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1")
    return out  # type: ignore[return-value]


def _ascii(text: str) -> str:
    """Normalise text for the fpdf2 core fonts which are latin-1 only."""
    if text is None:
        return ""
    replacements = {
        "ä": "ae", "ö": "oe", "ü": "ue",
        "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
        "ß": "ss",
        "€": "EUR",
        "–": "-", "—": "-", "·": "|", "→": "->", "✅": "", "⚠️": "!", "⬆️": "^",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")
