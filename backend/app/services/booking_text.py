"""Booking-text builder for Leasy / NetXp (spec 012).

Single source of truth — mirrored by the frontend for live preview but
authoritative version lives here.
"""

from decimal import Decimal
from uuid import UUID

from ..models import BarItem, Fahrbericht, Tour


def _fmt(amount: Decimal) -> str:
    return f"{amount:.2f}"


def build_booking_text(
    bericht: Fahrbericht,
    tour: Tour,
    bar_catalog: dict[UUID, BarItem],
) -> str:
    kiosk_lines: list[str] = []
    kiosk_total = Decimal("0")
    for bid, qty in bericht.kiosk_tally.items():
        if not qty:
            continue
        bar = bar_catalog.get(bid)
        if not bar:
            continue
        total = Decimal(qty) * bar.kb
        kiosk_total += total
        kiosk_lines.append(f"  {bar.name} × {qty} = € {_fmt(total)}")

    crew_lines: list[str] = []
    crew_cost = Decimal("0")
    for bid, qty in bericht.crew_tally.items():
        if not qty:
            continue
        bar = bar_catalog.get(bid)
        if not bar:
            continue
        total = Decimal(qty) * bar.ek
        crew_cost += total
        crew_lines.append(f"  {bar.name} × {qty} = € {_fmt(total)}")

    expenses_total = sum((e.amount for e in bericht.expenses), Decimal("0"))
    soll = kiosk_total + bericht.boarding_fee + bericht.bar_surcharge
    cash = bericht.cash_amount or Decimal("0")
    diff = cash - soll

    funker = tour.funker.display_name if tour.funker else "—"

    parts = [
        "KASSENBUCH-EINGANG:",
        f"Datum: {tour.date.isoformat()}",
        f"Veranstaltung: {tour.name or ''} ({tour.guest_count if tour.guest_count is not None else '?'} Gäste)",
        f"Funker*in: {funker}",
        "",
        "EINNAHMEN (8400 / Erlöse Kiosk):",
    ]
    if kiosk_lines:
        parts.extend(kiosk_lines)
    else:
        parts.append("  — keine Kiosk-Einnahmen —")
    parts.extend(
        [
            "",
            f"SUMME EINNAHMEN: € {_fmt(kiosk_total)}",
            f"Umlage Boarding: € {_fmt(bericht.boarding_fee)}",
            f"Umlage Bar: € {_fmt(bericht.bar_surcharge)}",
            "─────────────────────────────────",
            f"SOLL Umschlag: € {_fmt(soll)}",
            f"IST Umschlag:  € {_fmt(cash)}",
            f"Differenz:     € {'+' if diff >= 0 else ''}{_fmt(diff)}",
            "",
            "AUSGABEN (4220 / Wareneinsatz Crew):",
        ],
    )
    if crew_lines:
        parts.extend(crew_lines)
    else:
        parts.append("  — keine Crew-Verköstigung —")
    parts.append(f"Crew-Wareneinsatz: € {_fmt(crew_cost)}")
    if expenses_total > 0:
        parts.append(f"Sonstige Ausgaben Fahrt: € {_fmt(expenses_total)}")
    return "\n".join(parts)
