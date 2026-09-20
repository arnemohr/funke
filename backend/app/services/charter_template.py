"""Chartervertrag boilerplate — the legally reviewed prose of the charter contract.

Spec 025. Transcribed character for character from the Word/PDF original the
Verein has been using; the verbatim source lives beside the spec at
`specs/025-chartervertrag-original.txt` (pdftotext -layout output). Only line
wrapping was changed — the renderer re-flows paragraphs anyway.

**This is legal text, not copy.** It is reviewed prose that must not be edited
casually: any wording change is a change to the contract the Verein signs, and
it goes through review, a bumped `TEMPLATE_VERSION`, and a deploy. Typos that
are in the original stay in the original's spelling (see the notes marked
`sic:` below) — correcting them silently would mean the paper somebody signed
and the PDF Funke stores are no longer the same document.

**Clause 12 does not exist.** The original jumps from "11. Rückgabe des
Schiffes" straight to "13. Haftung des Charterers und Vercharterers". The gap
is preserved deliberately; renumbering is not a transcriber's decision and
would break every reference to "§ 13" that anyone has ever written down.
`EXPECTED_CLAUSE_NUMBERS` pins this so a future tidy-up fails a test instead of
quietly shifting the numbering.

Everything here is data. The PDF layout — fonts, page breaks, the length of the
signature rules — belongs to the renderer; no fpdf2 import lives in this module.
"""

from collections.abc import Mapping
from dataclasses import dataclass

TEMPLATE_VERSION = "2026-01"


# --------------------------------------------------------------------------
# Vercharterer / Verein header block
# --------------------------------------------------------------------------

VEREIN_NAME = "Verein für mobile Machenschaften e.V."
VEREIN_ADDRESS_LINES: tuple[str, ...] = (
    "Vogelhüttendeich 67",
    "21107 Hamburg",
)
VEREIN_EMAIL_LINE = "E-Mail: info@mobilemachenschaften.de"
VEREIN_WEBSITE_LINE = "Website: mobilemachenschaften.de"
VEREIN_PHONE_LINE = "Telefon: 017655567803"
VEREIN_BANK_HEADING = "Bankverbindung:"
VEREIN_BANK_LINE = "GLS Bank | IBAN: DE80 4306 0967 2063 3374 00 | BIC: GENODEM1GLS"

DOCUMENT_TITLE = "Chartervertrag"


# --------------------------------------------------------------------------
# The vessel. One raft, one contract — parametrising this is explicitly out of
# scope until the Verein charters a second boat (spec 025, "Bewusst offen
# gelassen"). The registration is spelled with the brackets the original uses.
# --------------------------------------------------------------------------

VESSEL_NAME = "Schaluppe"
VESSEL_REGISTRATION = "[HH-AD-666]"


# --------------------------------------------------------------------------
# Variable slots
#
# Written as `{key}` inside the transcribed text and filled by the renderer via
# `fill()`. The specimen contract's own fill-ins — its charterer, its dates and
# times, its fee, its head count, its skipper and licence numbers — appear
# nowhere in this module. They were somebody's booking, not boilerplate.
# --------------------------------------------------------------------------

#: What an unfilled slot prints as — the underline rule of the paper original.
BLANK_SLOT = "____________________"

PLACEHOLDER_KEYS: frozenset[str] = frozenset(
    {
        "charterer_name",
        "sondervereinbarungen",
        "uebergabe_datum",
        "uebergabe_uhrzeit",
        "rueckgabe_datum",
        "rueckgabe_uhrzeit",
        "chartergebuehr",
        "sonderleistungen",
        "gesamtbetrag",
        "kaution",
        "sbfs",
        "sbfb",
        "personen_ohne_skipper",
        "skipper_name",
    },
)


class _SlotMapping(dict):
    """Format mapping that renders an unsupplied slot as a blank rule."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return BLANK_SLOT


def fill(text: str, values: Mapping[str, str]) -> str:
    """Substitute the `{slot}` placeholders in a transcribed string.

    Missing keys become `BLANK_SLOT` rather than raising, so a half-filled
    draft still renders — `PUT` saves at every degree of completeness and the
    contract may legitimately be printed before every field is known.
    """
    return text.format_map(_SlotMapping(values))


# --------------------------------------------------------------------------
# Block types the renderer walks
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A justified body paragraph."""

    text: str


@dataclass(frozen=True, slots=True)
class Bullets:
    """A dashed list. Items carry their own trailing punctuation, which in the
    original is inconsistent (four commas, then two full stops) — sic."""

    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Field:
    """A caption plus a fill-in slot on one line.

    On paper these are the lines with underscore rules in them. `caption` is
    printed exactly as it stands, *including* its trailing colon where the
    original has one — SBFS and SBFB in clause 6 have none, so the renderer
    must not append a separator of its own.
    """

    caption: str
    value: str


Block = Paragraph | Bullets | Field


@dataclass(frozen=True, slots=True)
class Clause:
    number: int
    heading: str
    blocks: tuple[Block, ...]


# --------------------------------------------------------------------------
# Preamble
# --------------------------------------------------------------------------

INTRO_PARAGRAPH = (
    "Zwischen {charterer_name} (im Folgenden Charterer genannt) und dem Verein "
    "für mobile Machenschaften e.V. (im Folgenden Vercharterer genannt) wird "
    "folgende Chartervereinbarung getroffen:"
)


# --------------------------------------------------------------------------
# Clause 5 — Chartergebiet, lifted out as named constants because it is the
# clause people actually look up (which stretch of the Elbe, and what it costs
# to leave it).
# --------------------------------------------------------------------------

CHARTERGEBIET_DEFINITION = (
    "Das zulässige Gebiet der Nutzung ergibt sich aus der als Anlage beigefügten "
    "Karte, die Teil dieses Vertrages ist. Erlaubt sind: Elbe (Süderelbe, "
    "Norderelbe, Dove Elbe, Bille etc.); nicht erlaubt: Norderelbe flussabwärts "
    "ab unterer Mündung Baakenhafen, Süderelbe flussabwärts nach Einmündung "
    "Reiherstiegschleuse, Speicherstadt, Rethe ab Retheklappbrücke, "
    "Ellerholzhafen ab Ellerholzschleuse.."  # sic: doubled full stop
)

CHARTERGEBIET_VERTRAGSSTRAFE = (
    "Verlässt der Charterer dieses Gebiet, ist der Vercharterer dazu berechtigt, "
    "eine sofortige Rückkehr anzuordnen, ohne dass es hierdurch bedingt zu einer "
    "Verringerung der Chartergebühr käme. Der Charterer pflichtet sich für den "
    "Fall des Verlassens des Chartergebiets zu einer Vertragsstrafe in Höhe von "
    "EUR 200,00."
)


# --------------------------------------------------------------------------
# The clauses. Numbering runs 1..11, 13..17 — there is no 12, see the module
# docstring.
# --------------------------------------------------------------------------

CLAUSES: tuple[Clause, ...] = (
    Clause(
        number=1,
        heading="Vertragsgegenstand, Charterzeit (einschließlich Ein- und Auscheckzeit)",
        blocks=(
            Paragraph(
                f"Der Charterer chartert das Floß „{VESSEL_NAME}“, "
                f"Kennzeichen {VESSEL_REGISTRATION}",
            ),
            Field("Sondervereinbarungen:", "{sondervereinbarungen}"),
            Field("Übergabe Floß:", "Datum {uebergabe_datum} Uhrzeit {uebergabe_uhrzeit}"),
            Field("Rückgabe Floß:", "Datum {rueckgabe_datum} Uhrzeit {rueckgabe_uhrzeit}"),
            # Trailing comma is the original's; the sentence simply stops there.
            Paragraph("jeweils im Ruderverein Wilhelmsburg,"),
            Paragraph(
                "Wird der Charterzeitraum überzogen, werden ab der 31. Minute der "
                "Überziehung 35 € je angefangener halben Stunde fällig. Sollte es "
                "durch die Überziehung des Charterzeitraums dazu kommen, dass eine "
                "anschließende Vermietung nicht stattfinden kann, kann der "
                "Vercharterer die Mietausfallkosten vom Charterer einfordern.",
            ),
        ),
    ),
    Clause(
        number=2,
        heading="Chartergebühren",
        blocks=(
            Field("Chartergebühr:", "{chartergebuehr}"),
            # May expand to several lines — one per ExpenseLine.
            Field("Sonderleistungen:", "{sonderleistungen}"),
            Field("Gesamtbetrag:", "{gesamtbetrag}"),
            Paragraph(
                "Der Charterpreis beinhaltet die Nutzung der Bootes und ihrer "  # sic: "der Bootes"
                "Einrichtungen, den damit verbundenen natürlichen Verschleiß des "
                "Bootes und seiner Einrichtungen, sowie die Betriebsmittel.",
            ),
            Paragraph(
                "Kaution: Es ist zusätzlich vor Fahrtantritt eine Kaution in Höhe "
                "von {kaution} zu hinterlegen.",
            ),
            Paragraph(
                "Wird die nach Punkt 3 fällige Anzahlung auch nach Mahnung nicht "
                "bezahlt, so ist der Vercharterer berechtigt, die Charter zu "
                "stornieren und über das Schiff anderweitig zu verfügen. Kommt ein "
                "weiterer Chartervertrag nicht oder nur über einen Teil der "
                "vorstehend unter Punkt 1 angegebenen Charterdauer zustande, so hat "
                "der Vercharterer dennoch Anspruch gegen den Charterer auf Bezahlung "
                "des vollen Charterpreises bzw. auf die Differenz.",
            ),
        ),
    ),
    Clause(
        number=3,
        heading="Zahlungsbedingungen",
        blocks=(
            Paragraph(
                "Der Vercharterer ist berechtigt, die Leistung einer Vorkasse i.H.v. "
                "50 % der Chartergebühren zur Bedingung einer verbindlichen "
                "Reservierung zu machen. Die Zahlung ist spätestens 14 Tage nach "
                "erfolgter Nutzung auf das genannte Konto des Vercharterers zu "
                "leisten. Eine Stornierung der Buchung ist bis sieben Tage vor "
                "Fahrtantritt kostenfrei möglich, hiernach fällt für die Stornierung "
                "eine Gebühr i.H.v. 50 % der Chartergebühren an.",
            ),
        ),
    ),
    Clause(
        number=4,
        heading="Versicherungen",
        blocks=(
            Paragraph(
                "Haftpflichtversicherung und Vollkaskoversicherung der Schaluppe "
                "werden vom Vercharterer getragen.",
            ),
        ),
    ),
    Clause(
        number=5,
        heading="Chartergebiet",
        blocks=(
            Paragraph(CHARTERGEBIET_DEFINITION),
            Paragraph(CHARTERGEBIET_VERTRAGSSTRAFE),
        ),
    ),
    Clause(
        number=6,
        heading="Schiffsführer",
        blocks=(
            Paragraph(
                "Der Charterer erklärt, dass er bzw. der Schiffsführer über alle "
                "seemännischen Kenntnisse verfügt, die zum Führen der Schaluppe auf "
                "der Elbe erforderlich sind. Der angegebene Schiffsführer ist "
                "Besitzer der folgenden Scheine (genaue Bezeichnung, Nr. und Datum):",
            ),
            Field("SBFS", "{sbfs}"),
            Field("SBFB", "{sbfb}"),
            Paragraph(
                "Die entsprechenden Papiere sind jederzeit mitzuführen und der "
                "Wasserschutzpolizei auf Verlangen vorzulegen. Im Falle einer "
                "Haverie sind die Papiere unverzüglich der Versicherung zur "
                "Verfügung zu stellen.",
            ),
        ),
    ),
    Clause(
        number=7,
        heading="Allgemeine Obliegenheiten",
        blocks=(
            Paragraph("Der Charterer verpflichtet sich,"),
            Bullets(
                (
                    "die Schaluppe im Sinne einer verantwortungsbewussten Führung zu "
                    "handhaben und sich in jeder Situation so zu verhalten, als ob "
                    "das Schiff sein eigenes wäre,",
                    "die Schaluppe nicht an Dritte weiterzugeben oder zu vermieten,",
                    "keine anderen Fahrzeuge zu schleppen, wenn kein Seenotfall "
                    "besteht oder andere Rettungsmöglichkeiten bestehen,",
                    "nicht mit mehr Personen zu belegen als zulässig und bei der "
                    "Anmeldung angegeben (gilt auch für Kinder),",
                    "die Schiffsnutzungsbedingungen und -hinweise einzuhalten und zu befolgen.",
                    "die Schaluppe gemäß den gesetzlichen Vorgaben zu betreiben.",
                ),
            ),
            Paragraph(
                "Bei Nichteinhaltung vorerwähnter Verpflichtungen gegenüber dem "
                "Vercharterer hat der Charterer die daraus erwachsenden Folgen in "
                "vollem Umfang zu vertreten und dafür zu haften.",
            ),
        ),
    ),
    Clause(
        number=8,
        heading="Besondere Obliegenheiten",
        blocks=(
            Paragraph(
                "Bei Schäden, Kollision, Havarien und sonstigen außergewöhnlichen "
                "Vorkommnissen ist umgehend eine Niederschrift darüber anzufertigen "
                "und der Vercharterer zu informieren.",
            ),
            Paragraph(
                "Der Charterer hat alles zu unternehmen, was Schaden und "
                "Folgeschäden (z.B. Ausfall) mindert. Sind Beschlagnahme oder "
                "Behinderung schuldhaft durch den Charterer ausgelöst, so haftet er "
                "für die Folgen gegenüber dem Vercharterer. Der Chartervertrag gilt "
                "bis zur Rückgabe des Schiffes als verlängert, mit der Verpflichtung "
                "der doppelten Gebührenzahlung durch den Charterer. Unberührt "
                "hiervon bleibt der Anspruch auf Schadenersatz.",
            ),
        ),
    ),
    Clause(
        number=9,
        heading="Rücktritt",
        blocks=(
            Paragraph(
                "Der Vercharterer kann nach eigenem Ermessen aufgrund schlechten "
                "Wetters oder einer sonstigen Beeinträchtigung des sicheren Betriebs "
                "der Schaluppe vom Vertrag zurücktreten. Er kann auch einen Abbruch "
                "der Fahrt anweisen, wenn das Wetter sich überraschend ändert und "
                "hierdurch Gefahren für das Schiff oder Leib und Leben entstehen. "
                "Der Charterer kann bei extremem Regen oder extremer Kälte "
                "zurücktreten. Bei einem Rücktritt nach erfolgtem Fahrtantritt sind "
                "die Gebühren anteilig nach Zeit zu entrichten.",
            ),
        ),
    ),
    Clause(
        number=10,
        heading="Übernahme des Schiffes",
        blocks=(
            Paragraph(
                "Dem Charterer wird das Schiff vollgetankt übergeben. Es muss von "
                "ihm nicht getankt werden.",
            ),
        ),
    ),
    Clause(
        number=11,
        heading="Rückgabe des Schiffes",
        blocks=(
            Paragraph(
                "Nach Beendigung der Charter übergibt der Charterer das Schiff dem "
                "Vercharterer zur Überprüfung über Zustand und Vollständigkeit in "
                "gereinigtem Zustand (außen und innen). Verlorengegangene, "
                "beschädigte oder nicht mehr funktionsfähige Gegenstände sind dem "
                "Vercharterer nach Rückkehr sofort anzuzeigen. Geleistete Kautionen "
                "werden bei Schadensfreiheit ohne Abzug nach Beendigung der Charter "
                "zurückbezahlt. Verschwiegene Schäden hat der Charterer auch nach "
                "Kautionsrückzahlung noch zu ersetzen.",
            ),
        ),
    ),
    # --- no clause 12 in the original; do not fill this gap ---
    Clause(
        number=13,
        heading="Haftung des Charterers und Vercharterers",
        blocks=(
            Paragraph(
                "Tritt nach Übernahme des Schiffes durch den Charterer während der "
                "Charterzeit ein Schaden ein, der geeignet ist, die Fahrt ganz oder "
                "teilweise unmöglich zu machen, so hat der Charterer keinerlei "
                "Ansprüche gegen den Vercharterer, wenn es sich um einen Fall "
                "höherer Gewalt (insbesondere Witterungseinflüsse) oder um "
                "Drittverschulden handelt. Liegt ein Verschleißschaden vor, so hat "
                "der Charterer Anspruch auf anteilige Rückerstattung der "
                "Chartergebühren. Beide Vertragsteile haften nur für zu vertretendes "
                "Verschulden.",
            ),
        ),
    ),
    Clause(
        number=14,
        heading="Gesetzeswidrige Nutzung",
        blocks=(
            Paragraph(
                "Der Charterer haftet voll für einen selbst verantworteten "
                "verordnungs- oder gesetzeswidrigen Betrieb. Er haftet nicht für "
                "etwaige Bußgelder, Strafzahlungen oder ähnliche Ansprüche, die den "
                "Betrieb der Schaluppe als Ganzes betreffen.",
            ),
        ),
    ),
    Clause(
        number=15,
        heading="Kulturklausel",
        blocks=(
            Paragraph(
                "Bei der Nutzung ist der Vereinszweck zu berücksichtigen. Auf "
                "Charterfahrten müssen kulturelle Aktivitäten stattfinden.",
            ),
        ),
    ),
    Clause(
        number=16,
        heading="Gerichtsstand",
        blocks=(
            Paragraph(
                "Die Parteien vereinbaren im gesetzlich zulässigen Rahmen die "
                "Anwendung des Rechts der Bundesrepublik Deutschland mit "
                "ausschließlichem Gerichtsstand Hamburg. Sind einzelne Bestimmungen "
                "dieses Vertrages nichtig oder rechtsunwirksam, wird die Gültigkeit "
                "des Vertrages im Übrigen nicht berührt. Die Vercharterung eines "
                "Schiffes fällt nicht unter Reiserecht, sondern ist eine "
                "Dienstleistung.",
            ),
        ),
    ),
    Clause(
        number=17,
        heading="Crew",
        blocks=(
            Field("Anzahl der mitfahrenden Personen ohne Skipper:", "{personen_ohne_skipper}"),
            Field("Schiffsführer - Name:", "{skipper_name}"),
            Paragraph(
                "(Bitte ausfüllen, wenn Charterer und Schiffsführer nicht "
                "personengleich sind). Alle Crewmitglieder gelten als "
                "Erfüllungsgehilfen.",
            ),
        ),
    ),
)


#: Canonical numbering, gap included. A test pins this so that "fixing" the
#: missing 12 fails loudly instead of silently renumbering a signed contract.
EXPECTED_CLAUSE_NUMBERS: tuple[int, ...] = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17,
)  # fmt: skip


# --------------------------------------------------------------------------
# Signature captions
#
# The original prints three blocks. Spec 025 defaults to two, because the
# charterer is normally a crew member skippering that day; the combined caption
# below is the only string here that is not in the original, and it is a
# contraction of the first two, not new wording.
#
# Note the dashes: the first two captions use an en dash, the Vercharterer line
# a plain hyphen. That is what the original does — sic, and left alone.
# --------------------------------------------------------------------------

SIGNATURE_CAPTION_CHARTERER = "Datum / Unterschrift – Charterer"
SIGNATURE_CAPTION_SKIPPER = "Datum / Unterschrift – Schiffsführer"
SIGNATURE_CAPTION_CHARTERER_AND_SKIPPER = "Datum / Unterschrift – Charterer und Schiffsführer"
SIGNATURE_CAPTION_VERCHARTERER = "Datum / Unterschrift - für den Vercharterer"
