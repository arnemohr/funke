"""Chartervertrag PDF renderer (spec 025).

Sets the contract from `charter_template`'s transcribed prose and a
`CharterContract` row. Pure rendering: no S3, no DynamoDB, no FastAPI — the
caller gets bytes and decides where they go.

**Fidelity standard: wording identical, layout free** (spec 025, „PDF-Treue").
Every word comes out of `charter_template`; page breaks, line spacing and the
length of the underscore rules are this module's business and deliberately do
not reproduce the Word original.

Layout follows the Boardingzettel generator (`api/admin/events.py`): explicit
A4 constants, deliberate `set_auto_page_break` handling, `multi_cell` for
flowing text, manual checks against the bottom margin. Unlike the Boardingzettel
this document *flows*, so automatic page breaks stay on and the manual checks
guard only what must not be split — a clause heading from its first lines, a
signature rule from its caption.

The Unicode font is mandatory. fpdf2's core fonts cannot encode `€`, `–` or
`„…“` — they raise rather than substitute, and `report_service`'s `_ascii()`
transliteration is fine for an internal finance report and not for a contract:
a document that prints „EUR" where the original says „€" is not the same
document. If the bundled TTF is missing this module raises; it never falls
back to Helvetica.
"""

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models.charter import CharterContract
from .charter_template import (
    BLANK_SLOT,
    CLAUSES,
    DOCUMENT_TITLE,
    INTRO_PARAGRAPH,
    SIGNATURE_CAPTION_CHARTERER,
    SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER,
    SIGNATURE_CAPTION_SKIPPER,
    SIGNATURE_CAPTION_VERCHARTERER,
    TEMPLATE_VERSION,
    VEREIN_ADDRESS_LINES,
    VEREIN_BANK_HEADING,
    VEREIN_BANK_LINE,
    VEREIN_EMAIL_LINE,
    VEREIN_NAME,
    VEREIN_PHONE_LINE,
    VEREIN_WEBSITE_LINE,
    Bullets,
    Clause,
    Field,
    Paragraph,
    fill,
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# --------------------------------------------------------------------------
# Font
#
# Resolved off this file, never off the cwd: under Lambda the cwd is /var/task
# only by accident of the runtime, and the handler may chdir. `app/assets/` is
# not a package (no __init__.py), so this is a filesystem path rather than
# importlib.resources.
# --------------------------------------------------------------------------

FONT_FAMILY = "DejaVu"
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"


# --------------------------------------------------------------------------
# Layout (A4 portrait, millimetres)
# --------------------------------------------------------------------------

PAGE_WIDTH = 210
LEFT_MARGIN = 20
RIGHT_MARGIN = 20
TOP_MARGIN = 16
# Body must stop here; the footer lives below it on every page.
BOTTOM_MARGIN = 20
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN  # 170

TITLE_FONT_SIZE = 17
HEADING_FONT_SIZE = 10.5
BODY_FONT_SIZE = 9.5
SMALL_FONT_SIZE = 8.5
FOOTER_FONT_SIZE = 7

BODY_LINE_HEIGHT = 4.6
SMALL_LINE_HEIGHT = 4.0
HEADING_LINE_HEIGHT = 5.6

PARAGRAPH_SPACING = 1.8
CLAUSE_SPACING = 3.4
BULLET_INDENT = 5.0
#: Space between a `Field` caption and its value. A gap, not a separator — the
#: captions carry their own punctuation (`Field`'s docstring: SBFS and SBFB
#: have no colon and must not acquire one).
FIELD_GAP = 1.6

#: Vertical room left above a signature rule for an actual pen.
SIGNATURE_SPACE_ABOVE = 13.0
SIGNATURE_RULE_WIDTH = 110.0
#: What `ensure_space` reserves so a rule never lands on one page and its
#: caption on the next.
SIGNATURE_IMAGE_HEIGHT = 11.0
SIGNATURE_BLOCK_HEIGHT = SIGNATURE_SPACE_ABOVE + SMALL_LINE_HEIGHT + 6.0

#: fpdf2 has no faux-bold for TTF faces and only the regular DejaVu cut is
#: bundled, so headings are weighted by overprinting the outline. Kept small:
#: above ~0.25 the letters smear.
FAUX_BOLD_LINE_WIDTH = 0.18
#: Same trick at title size, where a thin stroke would disappear.
TITLE_STROKE_WIDTH = 0.3

#: How much of the render hash the footer shows. Enough to tell two renders of
#: the same contract apart by eye, short enough to read off a photographed scan.
RENDER_HASH_PREFIX_LENGTH = 12


class CharterFontMissingError(RuntimeError):
    """The bundled Unicode font is not on disk.

    Its own type because the only plausible cause is a deployment that dropped
    `app/assets/` — the CDK bundling excludes are the thing to look at, and the
    failure otherwise surfaces as a confusing fpdf2 encoding error much later.
    """


# --------------------------------------------------------------------------
# Value formatting
# --------------------------------------------------------------------------


def _format_money(value: Decimal | None) -> str | None:
    """German money as the original writes it: „EUR 1.250,00"."""
    if value is None:
        return None
    formatted = f"{value:,.2f}"  # 1,250.00
    # en → de: swap the two separators via a placeholder so the first
    # replacement does not eat the second.
    formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"EUR {formatted}"


def _to_berlin(value: datetime) -> datetime:
    """Local wall-clock time for a stored instant.

    A naive datetime is read as UTC rather than as the machine's local zone:
    the row is UTC by contract, and `astimezone` on a naive value would
    silently mean „whatever the Lambda's TZ happens to be" — the exact bug that
    prints a handover an hour off in summer.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BERLIN_TZ)


def _format_date(value: date | datetime | None) -> str | None:
    """`13.06.2026`. Datetimes are read in Europe/Berlin — the contract states
    local wall-clock times, and the row stores UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = _to_berlin(value).date()
    return value.strftime("%d.%m.%Y")


def _format_time(value: datetime | None) -> str | None:
    """`11:00`, Europe/Berlin."""
    if value is None:
        return None
    return _to_berlin(value).strftime("%H:%M")


def _format_licence(number: str | None, issued_on: date | None) -> str | None:
    """`(S190168991, 09.10.2023)` — the shape the specimen contract uses.

    Either half may be missing; only both missing leaves the rule blank.
    """
    parts = [p for p in (number, _format_date(issued_on)) if p]
    if not parts:
        return None
    return f"({', '.join(parts)})"


def _format_expense_lines(contract: CharterContract) -> str | None:
    """One line per `ExpenseLine`, description and amount. The renderer prints
    these stacked under the „Sonderleistungen:" caption."""
    if not contract.sonderleistungen:
        return None
    return "\n".join(
        f"{line.description} — {_format_money(line.amount)}" for line in contract.sonderleistungen
    )


def _skipper_name(contract: CharterContract) -> str:
    """Whose name goes in clause 17.

    When charterer and skipper are the same person the form mirrors the name,
    but a draft saved before the mirror ran still has an empty `skipper_name`;
    fall back to the charterer rather than printing a blank rule that
    contradicts the two-block signature layout below it.
    """
    if contract.skipper_name:
        return contract.skipper_name
    if contract.skipper_is_charterer:
        return contract.charterer_name
    return ""


def _build_slot_values(contract: CharterContract) -> dict[str, str]:
    """The `{slot}` values for `charter_template.fill`.

    Empty values are *omitted*, not passed as `""`: `fill` turns a missing key
    into `BLANK_SLOT`, which is how an unfilled line keeps its underscore rule.
    """
    candidates: dict[str, str | None] = {
        "charterer_name": contract.charterer_name or None,
        "sondervereinbarungen": contract.sondervereinbarungen,
        "uebergabe_datum": _format_date(contract.uebergabe_at),
        "uebergabe_uhrzeit": _format_time(contract.uebergabe_at),
        "rueckgabe_datum": _format_date(contract.rueckgabe_at),
        "rueckgabe_uhrzeit": _format_time(contract.rueckgabe_at),
        "chartergebuehr": _format_money(contract.chartergebuehr),
        "sonderleistungen": _format_expense_lines(contract),
        # The number the PDF prints is the one computed here, not the stored
        # `gesamtbetrag` — the stored value is what the *previous* render said.
        # A draft with neither fee nor extras gets a blank rule rather than
        # „EUR 0,00", which would read as an agreed price of nothing.
        "gesamtbetrag": (
            _format_money(contract.compute_gesamtbetrag())
            if contract.chartergebuehr is not None or contract.sonderleistungen
            else None
        ),
        "kaution": _format_money(contract.kaution),
        "sbfs": _format_licence(contract.sbfs_number, contract.sbfs_issued_on),
        "sbfb": _format_licence(contract.sbfb_number, contract.sbfb_issued_on),
        "personen_ohne_skipper": (
            str(contract.personen_ohne_skipper)
            if contract.personen_ohne_skipper is not None
            else None
        ),
        "skipper_name": _skipper_name(contract) or None,
    }
    return {key: value for key, value in candidates.items() if value}


def signature_captions(contract: CharterContract) -> tuple[str, ...]:
    """Two blocks in the normal case, three when the skipper is somebody else.

    The Vercharterer block is always printed and always blank: the
    countersignature is optional and may be filed years later (spec 025), so
    the paper has to carry a line for it either way.
    """
    if contract.skipper_is_charterer:
        return (
            SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER,
            SIGNATURE_CAPTION_VERCHARTERER,
        )
    return (
        SIGNATURE_CAPTION_CHARTERER,
        SIGNATURE_CAPTION_SKIPPER,
        SIGNATURE_CAPTION_VERCHARTERER,
    )


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def compute_render_hash(contract: CharterContract) -> str:
    """SHA-256 over the render *input*, hex.

    The footer has to name a hash, and the hash of the finished bytes cannot
    appear inside those bytes — stamping it would change them. Rendering twice
    does not help: the second pass produces different bytes than the ones that
    were hashed, so the printed value would be a lie in exactly the case
    somebody bothers to check it.

    So this hashes the payload instead: template version, document version,
    every filled slot, the charterer's address block and the signature captions
    — i.e. everything that decides what the document says. It answers „is this
    photographed sheet the render of these data?", which is the question the
    footer exists for. The hash of the stored bytes is a separate number,
    computed by the service over the actual object and kept in
    `document_sha256`.
    """
    payload = {
        "template_version": TEMPLATE_VERSION,
        "document_version": contract.document_version,
        "slots": _build_slot_values(contract),
        "charterer_address": contract.charterer_address,
        "charterer_email": contract.charterer_email or "",
        "charterer_phone": contract.charterer_phone or "",
        "signature_captions": list(signature_captions(contract)),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _footer_prefix(contract: CharterContract, render_hash: str) -> str:
    return (
        f"Vorlage {TEMPLATE_VERSION} · Dokument v{contract.document_version} · "
        f"Render {render_hash[:RENDER_HASH_PREFIX_LENGTH]}"
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


#: Cache for `_contract_pdf_class`; the class is built exactly once, so two
#: renders in the same Lambda do not each pay for it.
_PDF_CLASS = None


def _contract_pdf_class():
    """The `FPDF` subclass, built on first use.

    A subclass is needed because the footer has to be stamped on pages that
    `multi_cell` creates by itself mid-paragraph, and `footer()` is the only
    hook that sees those. Defining it lazily keeps the fpdf2 import off the
    cold-start path of every admin route, matching the two other PDF sites in
    this codebase.
    """
    global _PDF_CLASS
    if _PDF_CLASS is not None:
        return _PDF_CLASS

    from fpdf import FPDF

    class _ContractPDF(FPDF):
        #: Set by the renderer before the first page is added.
        footer_prefix = ""

        def footer(self) -> None:
            self.set_y(-BOTTOM_MARGIN + 6)
            self.set_font(FONT_FAMILY, "", FOOTER_FONT_SIZE)
            self.set_text_color(110, 110, 110)
            # `{nb}` is fpdf2's total-page alias, substituted at output time.
            self.cell(
                CONTENT_WIDTH,
                4,
                f"{self.footer_prefix} · Seite {self.page_no()}/{{nb}}",
                align="C",
            )
            self.set_text_color(0, 0, 0)

    _PDF_CLASS = _ContractPDF
    return _PDF_CLASS


class _ContractRenderer:
    """Cursor bookkeeping around the FPDF instance.

    Paragraphs are handed to `multi_cell` whole: fpdf2 justifies every line of
    a text block except the last, and a `multi_cell` fed one pre-wrapped line
    at a time would see nothing but last lines and justify none of them.
    Automatic page breaks therefore do the flowing, and the manual checks here
    are only about what must not be split: a clause heading from its first
    lines, a signature rule from its caption.
    """

    def __init__(self, pdf) -> None:
        self.pdf = pdf

    # -- page mechanics ---------------------------------------------------

    def ensure_space(self, needed: float) -> None:
        """Break early so `needed` millimetres stay together."""
        if self.pdf.will_page_break(needed):
            self.pdf.add_page()

    # -- text primitives --------------------------------------------------

    def paragraph(self, text: str, *, size: float = BODY_FONT_SIZE, align: str = "J") -> None:
        self.pdf.set_font(FONT_FAMILY, "", size)
        self.pdf.set_x(LEFT_MARGIN)
        self.pdf.multi_cell(CONTENT_WIDTH, BODY_LINE_HEIGHT, text, align=align)
        self.pdf.ln(PARAGRAPH_SPACING)

    def heading(self, text: str) -> None:
        self.pdf.set_font(FONT_FAMILY, "", HEADING_FONT_SIZE)
        with self.pdf.local_context(text_mode="FILL_STROKE", line_width=FAUX_BOLD_LINE_WIDTH):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, HEADING_LINE_HEIGHT, text)
        self.pdf.ln(1.2)

    def bullets(self, items: tuple[str, ...]) -> None:
        """A dashed list with a hanging indent: the dash sits in the margin and
        wrapped lines align under the text, not under the dash. Achieved by
        moving the left margin for the duration of the item, which is also what
        keeps the indent across an automatic page break."""
        body_width = CONTENT_WIDTH - BULLET_INDENT
        for item in items:
            self.ensure_space(BODY_LINE_HEIGHT * 2)
            self.pdf.set_font(FONT_FAMILY, "", BODY_FONT_SIZE)
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.cell(BULLET_INDENT, BODY_LINE_HEIGHT, "-")
            self.pdf.set_left_margin(LEFT_MARGIN + BULLET_INDENT)
            try:
                self.pdf.multi_cell(body_width, BODY_LINE_HEIGHT, item, align="J")
            finally:
                self.pdf.set_left_margin(LEFT_MARGIN)
        self.pdf.ln(PARAGRAPH_SPACING)

    def field(self, caption: str, value: str) -> None:
        """Caption and value on one line, the value's further lines stacked
        under it. The caption is printed verbatim — no colon, dash or other
        separator is appended (`charter_template.Field`)."""
        self.ensure_space(BODY_LINE_HEIGHT * 2)
        self.pdf.set_font(FONT_FAMILY, "", BODY_FONT_SIZE)
        caption_width = self.pdf.get_string_width(caption) + FIELD_GAP
        self.pdf.set_x(LEFT_MARGIN)
        self.pdf.cell(caption_width, BODY_LINE_HEIGHT, caption)
        self.pdf.set_left_margin(LEFT_MARGIN + caption_width)
        try:
            self.pdf.multi_cell(CONTENT_WIDTH - caption_width, BODY_LINE_HEIGHT, value)
        finally:
            self.pdf.set_left_margin(LEFT_MARGIN)
        self.pdf.ln(PARAGRAPH_SPACING)

    def signature_block(
        self,
        caption: str,
        *,
        signature: object | None = None,
        image: bytes | None = None,
    ) -> None:
        """One Datum/Unterschrift line, optionally already signed.

        A signature sits *above* the rule, like ink on paper. The typed name is
        printed under the date either way — a drawn scrawl is not identifying
        on its own, and a typed name alone is a valid simple electronic
        signature, so the name is the part that always appears.
        """
        self.ensure_space(SIGNATURE_BLOCK_HEIGHT)
        self.pdf.ln(SIGNATURE_SPACE_ABOVE)

        if signature is not None:
            top = self.pdf.get_y()
            if image:
                import io

                try:
                    # Sized to sit on the rule without overrunning the caption.
                    self.pdf.image(
                        io.BytesIO(image),
                        x=LEFT_MARGIN + 2,
                        y=top - SIGNATURE_IMAGE_HEIGHT,
                        h=SIGNATURE_IMAGE_HEIGHT,
                        keep_aspect_ratio=True,
                    )
                except Exception:  # noqa: BLE001 — a bad PNG must not lose the contract
                    pass
            self.pdf.set_xy(LEFT_MARGIN + SIGNATURE_RULE_WIDTH + 3, top - 4.0)
            self.pdf.set_font(FONT_FAMILY, "", SMALL_FONT_SIZE)
            stamp = signature.signed_at.astimezone(BERLIN_TZ).strftime("%d.%m.%Y")
            self.pdf.cell(0, SMALL_LINE_HEIGHT, stamp)
            self.pdf.set_xy(LEFT_MARGIN, top)

        rule_y = self.pdf.get_y()
        self.pdf.line(LEFT_MARGIN, rule_y, LEFT_MARGIN + SIGNATURE_RULE_WIDTH, rule_y)
        self.pdf.set_xy(LEFT_MARGIN, rule_y + 1.2)
        self.pdf.set_font(FONT_FAMILY, "", SMALL_FONT_SIZE)
        self.pdf.multi_cell(CONTENT_WIDTH, SMALL_LINE_HEIGHT, caption)
        if signature is not None:
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(
                CONTENT_WIDTH, SMALL_LINE_HEIGHT, f"gezeichnet: {signature.signed_name}",
            )
        self.pdf.ln(2.0)

    # -- document sections ------------------------------------------------

    def verein_header(self) -> None:
        self.pdf.set_font(FONT_FAMILY, "", SMALL_FONT_SIZE)
        with self.pdf.local_context(text_mode="FILL_STROKE", line_width=FAUX_BOLD_LINE_WIDTH):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, SMALL_LINE_HEIGHT, VEREIN_NAME)
        for line in (
            *VEREIN_ADDRESS_LINES,
            "",
            VEREIN_EMAIL_LINE,
            VEREIN_WEBSITE_LINE,
            VEREIN_PHONE_LINE,
            "",
            VEREIN_BANK_HEADING,
            VEREIN_BANK_LINE,
        ):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, SMALL_LINE_HEIGHT, line)
        self.pdf.ln(6)

    def title(self) -> None:
        self.pdf.set_font(FONT_FAMILY, "", TITLE_FONT_SIZE)
        with self.pdf.local_context(text_mode="FILL_STROKE", line_width=TITLE_STROKE_WIDTH):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, 9, DOCUMENT_TITLE, align="C")
        self.pdf.ln(5)

    def charterer_block(self, contract: CharterContract) -> None:
        """Name, postal address and — when known — phone and e-mail.

        Not in the paper original, which names the charterer only in the intro
        sentence. Spec 025 nonetheless makes `charterer_address` part of the
        mandatory set, and a contract that captures a party's address and then
        does not print it is missing the point. This is a party block, not a
        clause, so it leaves the „wording identical" standard untouched.
        """
        lines = [line for line in contract.charterer_address.splitlines() if line.strip()]
        if not (contract.charterer_name or lines or contract.charterer_phone):
            return
        self.pdf.set_font(FONT_FAMILY, "", SMALL_FONT_SIZE)
        with self.pdf.local_context(text_mode="FILL_STROKE", line_width=FAUX_BOLD_LINE_WIDTH):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, SMALL_LINE_HEIGHT, "Charterer")
        for line in (
            contract.charterer_name or BLANK_SLOT,
            *(lines or [BLANK_SLOT]),
            *([f"Telefon: {contract.charterer_phone}"] if contract.charterer_phone else []),
            *([f"E-Mail: {contract.charterer_email}"] if contract.charterer_email else []),
        ):
            self.pdf.set_x(LEFT_MARGIN)
            self.pdf.multi_cell(CONTENT_WIDTH, SMALL_LINE_HEIGHT, line)
        self.pdf.ln(CLAUSE_SPACING)

    def clause(self, clause: Clause, values: dict[str, str]) -> None:
        # Keep the heading with the first lines of what follows; an orphaned
        # clause number at the foot of a page reads as a missing clause.
        self.ensure_space(HEADING_LINE_HEIGHT + BODY_LINE_HEIGHT * 2)
        self.heading(f"{clause.number}. {clause.heading}")
        for block in clause.blocks:
            if isinstance(block, Paragraph):
                self.paragraph(fill(block.text, values))
            elif isinstance(block, Bullets):
                self.bullets(tuple(fill(item, values) for item in block.items))
            elif isinstance(block, Field):
                self.field(block.caption, fill(block.value, values))
            else:  # pragma: no cover - the union is closed
                raise TypeError(f"Unknown block type: {type(block)!r}")
        self.pdf.ln(CLAUSE_SPACING - PARAGRAPH_SPACING)


def render_charter_pdf(
    contract: CharterContract,
    *,
    rendered_at: datetime | None = None,
    signatures: list | None = None,
    signature_images: dict | None = None,
) -> bytes:
    """Render the charter contract to PDF bytes.

    `rendered_at` only sets the PDF's creation date; pass the timestamp that
    goes on the row so the document and the row agree. Nothing here reads the
    clock for content — the contract's own dates come from the row.
    """
    if not FONT_PATH.is_file():
        raise CharterFontMissingError(
            f"Unicode-Schrift fehlt: {FONT_PATH}. Ohne sie kann der Chartervertrag nicht "
            "gesetzt werden (Kernschriften können € und „…“ nicht darstellen).",
        )

    values = _build_slot_values(contract)
    render_hash = compute_render_hash(contract)

    pdf = _contract_pdf_class()(orientation="P", unit="mm", format="A4")
    pdf.footer_prefix = _footer_prefix(contract, render_hash)
    pdf.set_margins(LEFT_MARGIN, TOP_MARGIN, RIGHT_MARGIN)
    # On, and with room reserved for the footer: paragraphs flow across pages.
    pdf.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)
    pdf.add_font(FONT_FAMILY, "", str(FONT_PATH))
    # No bold cut is bundled, and a silent fall back to a core font would lose
    # the very characters the Unicode font is here for. Registering the regular
    # file under "B" keeps `set_font(..., "B")` from raising; visual weight
    # comes from the stroke overprint in `heading()`.
    pdf.add_font(FONT_FAMILY, "B", str(FONT_PATH))
    pdf.set_font(FONT_FAMILY, "", BODY_FONT_SIZE)
    pdf.set_title(DOCUMENT_TITLE)
    pdf.set_author(VEREIN_NAME)
    pdf.set_subject(f"{DOCUMENT_TITLE} v{contract.document_version} ({TEMPLATE_VERSION})")
    pdf.set_lang("de-DE")
    if rendered_at is not None:
        pdf.creation_date = rendered_at

    renderer = _ContractRenderer(pdf)
    pdf.add_page()
    renderer.verein_header()
    renderer.title()
    renderer.charterer_block(contract)
    renderer.paragraph(fill(INTRO_PARAGRAPH, values))
    pdf.ln(CLAUSE_SPACING)

    for clause in CLAUSES:
        renderer.clause(clause, values)

    captions = signature_captions(contract)
    # Captions are ordered charterer, [skipper,] Vercharterer — the same order
    # `signature_captions` builds them in, so index maps to role.
    from ..models.charter import SignatureRole

    roles: list[SignatureRole] = [SignatureRole.CHARTERER]
    if not contract.skipper_is_charterer:
        roles.append(SignatureRole.SKIPPER)
    roles.append(SignatureRole.VERCHARTERER)
    by_role = {sig.role: sig for sig in (signatures or [])}
    images = signature_images or {}
    # All signature blocks on one page: whoever signs should see every line
    # they are signing next to each other, and two of three on a fresh page
    # invites one of them to be missed.
    renderer.ensure_space(SIGNATURE_BLOCK_HEIGHT * len(captions))
    for caption, role in zip(captions, roles, strict=False):
        sig = by_role.get(role)
        renderer.signature_block(caption, signature=sig, image=images.get(role) if sig else None)

    return bytes(pdf.output())
