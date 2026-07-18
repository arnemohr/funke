"""Closing report service (specs 013 + 014).

Persists per-version snapshots of a Fahrbericht, renders PDFs (WeasyPrint when
available, fpdf2 fallback), emails finance. Reuses the existing SMTP pipeline
(`email_client.py`).

Spec 014: Fahrbericht is a direct child of Event — Report pointer row lives at
`pk = EVENT#{event_id}`, `sk = REPORT` in the events table.
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
    Event,
    Fahrbericht,
    LineItem,
    ReportMeta,
    ReportResponse,
    ReportTotals,
    ReportVersion,
)
from ..models.report import ExpenseLine as ReportExpenseLine
from .bar_service import get_bar_service
from .booking_text import build_booking_text
from .config import (
    EVENT_PK_PREFIX,
    EVENT_SK_REPORT_POINTER,
    REPORT_PK_PREFIX,
    REPORT_SK_META,
    REPORT_SK_VERSION_PREFIX,
    REPORTS_LIST_PK,
    get_events_table,
    get_reports_table,
    get_settings,
)
from .email_client import Attachment, EmailMessage, get_gmail_client
from .event_service import get_event_service
from .fahrbericht_service import get_fahrbericht_service
from .logging import get_logger

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
        "event_id": str(meta.event_id),
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
        event_id=UUID(item["event_id"]),
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
        "event_id": str(v.event_id),
        "fahrbericht_snapshot": v.fahrbericht_snapshot,
        "event_snapshot": v.event_snapshot,
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
        event_id=UUID(item["event_id"]),
        fahrbericht_snapshot=item.get("fahrbericht_snapshot") or {},
        event_snapshot=item.get("event_snapshot") or {},
        bar_catalog_snapshot=item.get("bar_catalog_snapshot") or {},
        kiosk_summary=[LineItem(**li) for li in item.get("kiosk_summary") or []],
        crew_summary=[LineItem(**li) for li in item.get("crew_summary") or []],
        expenses_summary=[ReportExpenseLine(**e) for e in item.get("expenses_summary") or []],
        totals=ReportTotals(
            kiosk_total=_req_dec(totals_raw.get("kiosk_total")),
            crew_cost=_req_dec(totals_raw.get("crew_cost")),
            expenses_total=_req_dec(totals_raw.get("expenses_total")),
            bar_surcharge=_req_dec(totals_raw.get("bar_surcharge")),
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
        self._events_table = None
        self._s3 = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_reports_table()
        return self._table

    @property
    def events_table(self) -> "Table":
        if self._events_table is None:
            self._events_table = get_events_table()
        return self._events_table

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

    async def get_report_for_event(self, event_id: UUID) -> ReportMeta | None:
        pointer = self.events_table.get_item(
            Key={"pk": f"{EVENT_PK_PREFIX}{event_id}", "sk": EVENT_SK_REPORT_POINTER},
        ).get("Item")
        if not pointer:
            return None
        return await self.get_report(UUID(pointer["report_id"]))

    async def build_response(self, meta: ReportMeta) -> ReportResponse:
        versions = await self.list_versions(meta.id)
        return ReportResponse(**meta.model_dump(), versions=versions)

    # ------------------------------------------------------- create_or_update
    async def create_or_update_report(
        self,
        event_id: UUID,
        version: int,
        *,
        org_id: UUID | None = None,
    ) -> ReportMeta:
        bericht = await get_fahrbericht_service().get(event_id)
        if not bericht:
            raise ValueError("fahrbericht_not_found")

        # Event lookup: prefer the explicit org_id path (fast GetItem). When the
        # caller doesn't know it, fall back to a scan by id — used only by the
        # reapply path for already-persisted reports.
        event = await _resolve_event(event_id, org_id)
        if not event:
            raise ValueError("event_not_found")

        bar_service = get_bar_service()
        catalog_list = await bar_service.list_bar_items()
        catalog = {b.id: b for b in catalog_list}

        existing_meta = await self.get_report_for_event(event_id)
        report_id = existing_meta.id if existing_meta else uuid4()
        created_at = existing_meta.created_at if existing_meta else datetime.now(timezone.utc)

        # Build snapshots + summaries.
        snap_version = _build_version_snapshot(
            report_id=report_id,
            version=version,
            event=event,
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
            event_id=event_id,
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

        # Pointer row from Event → Report (idempotent) in the events table.
        try:
            self.events_table.put_item(
                Item={
                    "pk": f"{EVENT_PK_PREFIX}{event_id}",
                    "sk": EVENT_SK_REPORT_POINTER,
                    "entity_type": "EventReportPointer",
                    "event_id": str(event_id),
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

        date_str = version_snap.event_snapshot.get("date", "")
        event_name = version_snap.event_snapshot.get("name") or "Fahrt"
        is_update = meta.current_version >= 2
        subject = (
            f"Schaluppe Fahrbericht (Aktualisierung v{meta.current_version}) – {date_str} – {event_name}"
            if is_update
            else f"Schaluppe Fahrbericht – {date_str} – {event_name}"
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


def _event_snapshot(event: Event, bericht: Fahrbericht) -> dict:
    """Combined event/trip shape — the snapshot the PDF and email read from.

    Pulls display-facing fields from whichever source owns them now that the
    Tour entity is gone: Event carries `name` and the trip date; Fahrbericht
    carries crew, duration, charterer, guest count.
    """
    return {
        "id": str(event.id),
        "name": event.name,
        "date": event.start_at.date().isoformat(),
        "duration_hours": str(bericht.duration_hours) if bericht.duration_hours is not None else None,
        "guest_count": bericht.guest_count,
        "charterer": bericht.charterer,
        "funker_name": bericht.funker.display_name if bericht.funker else None,
        "skipper_name": bericht.skipper.display_name if bericht.skipper else None,
        "crew_names": ", ".join(c.display_name for c in bericht.crew) if bericht.crew else None,
        "status": event.status.value,
    }


async def _resolve_event(event_id: UUID, org_id: UUID | None) -> Event | None:
    """Fetch an Event given an id. Prefers the org-scoped lookup; falls back
    to a scan by id when the caller doesn't have the org_id handy (reapply
    path).
    """
    svc = get_event_service()
    if org_id is not None:
        return await svc.get_event(org_id, event_id)
    # Slow path — scan. Only hit during manual reapply or legacy callers.
    from boto3.dynamodb.conditions import Attr

    table = get_events_table()
    resp = table.scan(FilterExpression=Attr("id").eq(str(event_id)), Limit=1)
    items = resp.get("Items") or []
    if not items:
        return None
    found_org = items[0].get("org_id")
    if not found_org:
        return None
    return await svc.get_event(UUID(found_org), event_id)


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
    event: Event,
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
    bar_surcharge = kiosk_total + crew_cost
    soll = bericht.boarding_fee + bar_surcharge
    cash = bericht.cash_amount or Decimal("0")

    totals = ReportTotals(
        kiosk_total=kiosk_total,
        crew_cost=crew_cost,
        expenses_total=expenses_total,
        bar_surcharge=bar_surcharge,
        soll=soll,
        cash_amount=bericht.cash_amount,
        cash_diff=cash - soll,
    )

    booking_text = build_booking_text(bericht, event, catalog)

    return ReportVersion(
        report_id=report_id,
        version=version,
        event_id=event.id,
        fahrbericht_snapshot=json.loads(bericht.model_dump_json()),
        event_snapshot=_event_snapshot(event, bericht),
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
        "event": snap.event_snapshot,
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

    event_info = snap.event_snapshot or {}
    subhead("Fahrtinfo")
    kv("Datum", str(event_info.get("date") or "-"))
    kv("Veranstaltung", str(event_info.get("name") or "-"))
    kv("Dauer", f"{event_info.get('duration_hours') or '-'} h")
    gc = event_info.get("guest_count")
    kv("Gaeste", str(gc if gc is not None else "-"))
    kv("Charterer", str(event_info.get("charterer") or "-"))
    kv("Funker*in", str(event_info.get("funker_name") or "-"))
    kv("Skipper", str(event_info.get("skipper_name") or "-"))
    if event_info.get("crew_names"):
        kv("Crew", str(event_info["crew_names"]))

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
