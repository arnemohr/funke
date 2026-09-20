"""Tests for the Chartervertrag renderer and its transcribed template (spec 025).

**Why there is a PDF parser in here.** Spec 025 forbids new dependencies, and
`pypdf` is not installed — deliberately, since there is no form to fill. The
assertions that matter are about *words on the page*, though, so this module
carries a small reader for exactly the output fpdf2 produces: uncompressed (or
Flate'd) content streams, Identity-H encoded strings, one `/ToUnicode` CMap per
font. It is stdlib only and it is not a general PDF parser; it would choke on
almost any other producer. That is the trade against pulling a package
into a Lambda bundle for a test.

What is pinned here:

* two signature blocks in the normal case, three when the skipper is somebody
  else — asserted on extracted text, not on byte length;
* `€`, `–` and `„…“` survive, i.e. the regression the bundled DejaVu font
  exists to prevent;
* the provenance footer (template version + 12 hex of the render hash) on
  every page;
* the clause numbering gap at 12, which a future tidy-up must not close;
* no specimen data from the paper original leaked into the template;
* a handful of legally load-bearing sentences, verbatim.
"""

import dataclasses
import re
import zlib
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.charter import CharterContract
from app.models.fahrbericht import ExpenseLine
from app.services import charter_template
from app.services.charter_pdf import render_charter_pdf, signature_captions
from app.services.charter_template import (
    EXPECTED_CLAUSE_NUMBERS,
    SIGNATURE_CAPTION_CHARTERER,
    SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER,
    SIGNATURE_CAPTION_SKIPPER,
    SIGNATURE_CAPTION_VERCHARTERER,
    TEMPLATE_VERSION,
)

# --------------------------------------------------------------------------
# A minimal reader for fpdf2 output
# --------------------------------------------------------------------------

_OBJ_RE = re.compile(rb"(\d+)\s+0\s+obj\b(.*?)\bendobj", re.DOTALL)
# The negative lookbehind matters: "endstream" ends in "stream".
_STREAM_RE = re.compile(rb"(?<!end)stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_FONT_REF_RE = re.compile(rb"/(F\d+)\s+(\d+)\s+0\s+R")
_TOUNICODE_RE = re.compile(rb"/ToUnicode\s+(\d+)\s+0\s+R")
_BFCHAR_BLOCK_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
_BFRANGE_BLOCK_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
_BFCHAR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFRANGE_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_FONT_TF_RE = re.compile(rb"/(F\d+)\s+[\d.]+\s+Tf")
_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")

#: What `extract_text` emits for a CID the font's ToUnicode CMap does not
#: cover. Never expected — it would mean the renderer drew a glyph it cannot
#: describe — so the tests assert its absence.
UNMAPPED = "\ufffd"

_STRING_ESCAPES = {
    b"n": b"\n",
    b"r": b"\r",
    b"t": b"\t",
    b"b": b"\b",
    b"f": b"\f",
    b"(": b"(",
    b")": b")",
    b"\\": b"\\",
}


def _objects(data: bytes) -> dict[int, bytes]:
    return {int(number): body for number, body in _OBJ_RE.findall(data)}


def _stream_of(body: bytes) -> bytes | None:
    match = _STREAM_RE.search(body)
    if match is None:
        return None
    raw = match.group(1)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        # fpdf2 writes uncompressed streams unless asked otherwise.
        return raw


def _parse_cmap(text: bytes) -> dict[int, str]:
    """CID → unicode from a `/ToUnicode` CMap."""
    mapping: dict[int, str] = {}
    for block in _BFRANGE_BLOCK_RE.findall(text):
        for low, high, destination in _BFRANGE_RE.findall(block):
            start, end, target = int(low, 16), int(high, 16), int(destination, 16)
            for offset in range(end - start + 1):
                mapping[start + offset] = chr(target + offset)
    for block in _BFCHAR_BLOCK_RE.findall(text):
        for source, destination in _BFCHAR_RE.findall(block):
            mapping[int(source, 16)] = "".join(
                chr(int(destination[index : index + 4], 16))
                for index in range(0, len(destination), 4)
            )
    return mapping


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index : index + 1]
        if char == b"\\" and index + 1 < len(raw):
            following = raw[index + 1 : index + 2]
            if following in _STRING_ESCAPES:
                out += _STRING_ESCAPES[following]
                index += 2
                continue
            if following.isdigit():  # \ddd octal
                stop = index + 1
                while stop < len(raw) and stop < index + 4 and raw[stop : stop + 1].isdigit():
                    stop += 1
                out.append(int(raw[index + 1 : stop], 8))
                index = stop
                continue
        out += char
        index += 1
    return bytes(out)


def _read_string(content: bytes, start: int) -> tuple[bytes, int]:
    """Read the `( ... )` literal beginning at `start`; returns it and the
    index just past the closing paren.

    Doing this with a scanner rather than a regex is not fussiness: under
    Identity-H a glyph id of 10 is a raw `\\n` byte *inside* the string, so any
    line-oriented pattern silently loses whole headings.
    """
    depth, cursor = 1, start + 1
    body_start = cursor
    while cursor < len(content) and depth:
        char = content[cursor : cursor + 1]
        if char == b"\\":
            cursor += 2
            continue
        if char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
        cursor += 1
    return content[body_start : cursor - 1], cursor


def _show_operations(content: bytes) -> list[tuple[str, list[bytes]]]:
    """Every `Tj` / `TJ` in stream order, with the font in force at the time."""
    operations: list[tuple[str, list[bytes]]] = []
    current = ""
    pending: list[bytes] = []
    index = 0
    while index < len(content):
        if content[index : index + 1] == b"(":
            literal, index = _read_string(content, index)
            pending.append(literal)
            continue
        font = _FONT_TF_RE.match(content, index)
        if font is not None:
            current = font.group(1).decode()
            index = font.end()
            continue
        if content[index : index + 2] in (b"Tj", b"TJ"):
            operations.append((current, pending))
            pending = []
            index += 2
            continue
        index += 1
    return operations


def extract_text(data: bytes) -> str:
    """Every string drawn in the document, one show operation per line."""
    objects = _objects(data)
    cmaps: dict[str, dict[int, str]] = {}
    for name, number in _FONT_REF_RE.findall(data):
        font = objects.get(int(number), b"")
        reference = _TOUNICODE_RE.search(font)
        if reference is None:
            continue
        cmap = _stream_of(objects.get(int(reference.group(1)), b""))
        if cmap is not None:
            cmaps[name.decode()] = _parse_cmap(cmap)

    lines: list[str] = []
    for body in objects.values():
        content = _stream_of(body)
        if content is None or b"Tj" not in content:
            continue
        for font_name, literals in _show_operations(content):
            cmap = cmaps.get(font_name, {})
            text = ""
            for literal in literals:
                raw = _unescape(literal)
                for offset in range(0, len(raw) - 1, 2):
                    # Identity-H: two bytes per glyph. An unmapped CID would be
                    # a bug in the renderer, so it must not decode silently.
                    text += cmap.get(raw[offset] << 8 | raw[offset + 1], UNMAPPED)
            lines.append(text)
    return "\n".join(lines)


def page_count(data: bytes) -> int:
    return len(_PAGE_RE.findall(data))


def flatten(text: str) -> str:
    """Collapse the renderer's line breaks so wrapped prose can be matched."""
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

# Deliberately unlike the specimen in the paper original: different name,
# different dates, different amounts. The leak tests below depend on that.
UEBERGABE = datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc)
RUECKGABE = datetime(2026, 7, 4, 16, 0, tzinfo=timezone.utc)
RENDERED_AT = datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc)


def _contract(**overrides) -> CharterContract:
    base = {
        "event_id": uuid4(),
        "document_version": 2,
        "charterer_name": "Testfirma Wasserwege GmbH",
        "charterer_address": "Deichstraße 9\n21107 Hamburg",
        "charterer_email": "charter@example.org",
        "uebergabe_at": UEBERGABE,
        "rueckgabe_at": RUECKGABE,
        "chartergebuehr": Decimal("450.00"),
        "sonderleistungen": [ExpenseLine(description="Grillkohle", amount=Decimal("25.50"))],
        "kaution": Decimal("500.00"),
        "personen_ohne_skipper": 8,
        "sbfs_number": "T111222333",
        "sbfs_issued_on": date(2021, 3, 15),
    }
    base.update(overrides)
    return CharterContract(**base)


@pytest.fixture
def contract_same_person() -> CharterContract:
    """The normal case: the charterer skippers their own charter."""
    return _contract(skipper_is_charterer=True)


@pytest.fixture
def contract_separate_skipper() -> CharterContract:
    return _contract(skipper_is_charterer=False, skipper_name="Testperson Steuerfrau")


@pytest.fixture
def rendered_same_person(contract_same_person) -> bytes:
    return render_charter_pdf(contract_same_person, rendered_at=RENDERED_AT)


@pytest.fixture
def rendered_separate_skipper(contract_separate_skipper) -> bytes:
    return render_charter_pdf(contract_separate_skipper, rendered_at=RENDERED_AT)


# --------------------------------------------------------------------------
# The PDF itself
# --------------------------------------------------------------------------


class TestDocument:
    def test_output_is_a_valid_multi_page_pdf(self, rendered_same_person):
        assert rendered_same_person.startswith(b"%PDF-")
        assert rendered_same_person.rstrip().endswith(b"%%EOF")
        assert page_count(rendered_same_person) > 1

    def test_extractor_decodes_every_glyph(self, rendered_same_person):
        """Guards the reader above as much as the renderer: a replacement
        character means a CID the ToUnicode CMap does not cover."""
        assert UNMAPPED not in extract_text(rendered_same_person)

    def test_an_empty_draft_still_renders(self):
        """`PUT` saves at any degree of completeness, so the page may ask for a
        preview of a row that is almost entirely `None`."""
        pdf = render_charter_pdf(CharterContract(event_id=uuid4()), rendered_at=RENDERED_AT)
        assert pdf.startswith(b"%PDF-")
        assert "Chartervertrag" in extract_text(pdf)

    def test_the_typed_data_reaches_the_page(self, rendered_same_person):
        text = flatten(extract_text(rendered_same_person))
        assert "Testfirma Wasserwege GmbH" in text
        assert "04.07.2026" in text  # Berlin wall clock, not UTC
        assert "EUR 450,00" in text
        assert "EUR 500,00" in text  # Kaution
        assert "EUR 475,50" in text  # Gesamtbetrag, Kaution excluded
        assert "T111222333" in text


class TestUnicode:
    """The regression the bundled DejaVu font exists to prevent.

    fpdf2's core fonts raise on these characters rather than substituting, so
    „a document that prints EUR where the original says €" is not the failure
    mode — a 500 on „PDF erzeugen" is.
    """

    @pytest.mark.parametrize(
        ("character", "what"),
        [
            ("€", "Euro-Zeichen"),
            ("–", "Gedankenstrich"),
            ("„", "Anführung unten"),
            ("“", "Anführung oben"),
            ("ß", "Eszett"),
            ("ü", "Umlaut"),
        ],
    )
    def test_character_survives_rendering(self, rendered_same_person, character, what):
        assert character in extract_text(rendered_same_person), what

    def test_a_charterer_name_full_of_diacritics_does_not_raise(self):
        contract = _contract(charterer_name="Jörg Weiß-Müller (Straße 3) — „Möwe“")
        text = extract_text(render_charter_pdf(contract, rendered_at=RENDERED_AT))
        assert "Jörg Weiß-Müller" in flatten(text)


class TestSignatureBlocks:
    """Two blocks or three — decided at render time, spec 025."""

    def test_skipper_is_charterer_gives_two_blocks(self, rendered_same_person):
        text = extract_text(rendered_same_person)
        assert text.count(SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER) == 1
        assert text.count(SIGNATURE_CAPTION_VERCHARTERER) == 1
        assert SIGNATURE_CAPTION_SKIPPER not in text
        assert _signature_caption_count(text) == 2

    def test_separate_skipper_gives_three_blocks(self, rendered_separate_skipper):
        text = extract_text(rendered_separate_skipper)
        assert text.count(SIGNATURE_CAPTION_CHARTERER) == 1
        assert text.count(SIGNATURE_CAPTION_SKIPPER) == 1
        assert text.count(SIGNATURE_CAPTION_VERCHARTERER) == 1
        assert SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER not in text
        assert _signature_caption_count(text) == 3

    def test_the_vercharterer_block_is_printed_but_left_blank(
        self,
        rendered_same_person,
        contract_same_person,
    ):
        """The countersignature is optional and may be filed years later, so
        the paper carries a line for it either way."""
        assert contract_same_person.countersigned_on is None
        assert SIGNATURE_CAPTION_VERCHARTERER in extract_text(rendered_same_person)

    def test_captions_helper_agrees_with_the_document(
        self,
        contract_same_person,
        rendered_same_person,
    ):
        for caption in signature_captions(contract_same_person):
            assert caption in extract_text(rendered_same_person)


def _signature_caption_count(text: str) -> int:
    """Every line that is a Datum/Unterschrift caption, however worded."""
    return sum(1 for line in text.splitlines() if line.startswith("Datum / Unterschrift"))


class TestFooterProvenance:
    """`template_version`, `document_version` and 12 hex of the render hash on
    every page — that is what makes a later photograph self-describing."""

    def test_every_page_carries_the_footer(self, rendered_same_person):
        text = extract_text(rendered_same_person)
        pages = page_count(rendered_same_person)
        footers = [line for line in text.splitlines() if line.startswith("Vorlage ")]
        assert len(footers) == pages

        pattern = re.compile(
            rf"^Vorlage {re.escape(TEMPLATE_VERSION)} · Dokument v2 · Render ([0-9a-f]{{12}})",
        )
        matches = [pattern.match(footer) for footer in footers]
        assert all(matches), footers
        # One document, one render hash.
        assert len({match.group(1) for match in matches}) == 1

    def test_the_footer_hash_tracks_the_content(self, contract_same_person):
        """Change what the contract says and the printed hash must move —
        otherwise it cannot answer „is this a photo of exactly this sheet?"."""
        first = _footer_hash(render_charter_pdf(contract_same_person, rendered_at=RENDERED_AT))
        other = contract_same_person.model_copy(update={"chartergebuehr": Decimal("451.00")})
        second = _footer_hash(render_charter_pdf(other, rendered_at=RENDERED_AT))
        assert first != second


def _footer_hash(data: bytes) -> str:
    match = re.search(r"Render ([0-9a-f]{12})", extract_text(data))
    assert match is not None
    return match.group(1)


# --------------------------------------------------------------------------
# The transcribed template
# --------------------------------------------------------------------------


class TestClauseNumbering:
    """The paper original jumps from 11 to 13. Renumbering is not a
    transcriber's decision, and a well-meaning cleanup must fail loudly."""

    def test_expected_numbering_has_the_gap(self):
        assert EXPECTED_CLAUSE_NUMBERS == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17)
        assert 12 not in EXPECTED_CLAUSE_NUMBERS

    def test_the_clauses_match_the_expected_numbering(self):
        assert tuple(clause.number for clause in charter_template.CLAUSES) == (
            EXPECTED_CLAUSE_NUMBERS
        )

    def test_no_clause_twelve_is_printed(self, rendered_same_person):
        headings = _clause_headings(extract_text(rendered_same_person))
        assert 11 in headings
        assert 13 in headings
        assert 12 not in headings
        assert sorted(headings) == list(EXPECTED_CLAUSE_NUMBERS)

    def test_headings_are_printed_verbatim(self, rendered_same_person):
        text = extract_text(rendered_same_person)
        for clause in charter_template.CLAUSES:
            assert f"{clause.number}. {clause.heading}" in text


def _clause_headings(text: str) -> list[int]:
    """Clause numbers as actually printed, from lines shaped `13. Haftung …`."""
    headings = {clause.heading for clause in charter_template.CLAUSES}
    numbers = []
    for line in text.splitlines():
        match = re.match(r"^(\d+)\. (.+)$", line)
        if match and match.group(2) in headings:
            numbers.append(int(match.group(1)))
    return numbers


# Specimen fill-ins from the scanned original. None of them is boilerplate;
# every one of them would be somebody else's data printed on a live contract.
SPECIMEN_DATA = ("Frederik Klein", "Arne-Christian Mohr", "S190168991", "13.06.2026")


def _template_strings() -> list[tuple[str, str]]:
    """Every string reachable from a module-level constant, with its origin."""
    collected: list[tuple[str, str]] = []

    def walk(origin: str, value: object) -> None:
        if isinstance(value, str):
            collected.append((origin, value))
        elif isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                walk(origin, item)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(origin, key)
                walk(origin, item)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field in dataclasses.fields(value):
                walk(origin, getattr(value, field.name))

    for name, value in vars(charter_template).items():
        if name.startswith("_"):
            continue
        walk(name, value)
    return collected


class TestNoSampleDataLeaked:
    @pytest.mark.parametrize("specimen", SPECIMEN_DATA)
    def test_specimen_absent_from_template_constants(self, specimen):
        offenders = [origin for origin, text in _template_strings() if specimen in text]
        assert not offenders, f"{specimen!r} steht noch in {sorted(set(offenders))}"

    @pytest.mark.parametrize("specimen", SPECIMEN_DATA)
    def test_specimen_absent_from_a_rendered_contract(self, specimen, rendered_same_person):
        assert specimen not in flatten(extract_text(rendered_same_person))

    def test_the_walk_actually_sees_the_clause_prose(self):
        """Without this the two tests above would pass on an empty list."""
        strings = _template_strings()
        assert len(strings) > 50
        assert any("Kulturklausel" in text for _origin, text in strings)


# Sentences that carry legal weight: the surprising clauses (§ 305c BGB) and
# the one that states the Vereinszweck. Copied from
# `specs/025-chartervertrag-original.txt`; `TestOriginalWording` below proves
# these literals are the original's own words and not a plausible paraphrase.
VERBATIM_PHRASES = (
    "Der Charterer pflichtet sich für den Fall des Verlassens des Chartergebiets zu einer "
    "Vertragsstrafe in Höhe von EUR 200,00.",
    "Bei der Nutzung ist der Vereinszweck zu berücksichtigen. Auf Charterfahrten müssen "
    "kulturelle Aktivitäten stattfinden.",
    "Erlaubt sind: Elbe (Süderelbe, Norderelbe, Dove Elbe, Bille etc.); nicht erlaubt:",
    "Wird der Charterzeitraum überzogen, werden ab der 31. Minute der Überziehung 35 € je "
    "angefangener halben Stunde fällig.",
    "mit der Verpflichtung der doppelten Gebührenzahlung durch den Charterer.",
    "Der Charterer chartert das Floß „Schaluppe“, Kennzeichen [HH-AD-666]",
)

ORIGINAL_TEXT_PATH = (
    Path(__file__).resolve().parents[3] / "specs" / "025-chartervertrag-original.txt"
)


class TestOriginalWording:
    """Wording is the fidelity standard; layout is not (spec 025, „PDF-Treue")."""

    @pytest.mark.parametrize("phrase", VERBATIM_PHRASES)
    def test_phrase_survives_into_the_pdf(self, phrase, rendered_same_person):
        assert phrase in flatten(extract_text(rendered_same_person))

    @pytest.mark.parametrize("phrase", VERBATIM_PHRASES)
    def test_phrase_is_really_the_originals_wording(self, phrase):
        if not ORIGINAL_TEXT_PATH.is_file():
            pytest.skip(f"Originaltext nicht vorhanden: {ORIGINAL_TEXT_PATH}")
        original = flatten(ORIGINAL_TEXT_PATH.read_text(encoding="utf-8"))
        assert phrase in original
