"""Booking-text builder for Leasy / NetXp (spec 012, updated in spec 014).

Single source of truth — mirrored by the frontend for live preview but the
authoritative version lives here. Reads display fields off the Event (name,
date) and trip-shape fields off the Fahrbericht (funker, guest_count).
"""

from decimal import Decimal
from uuid import UUID

from ..models import BarItem, Event, Fahrbericht


def _fmt(amount: Decimal) -> str:
    return f"{amount:.2f}"


def build_booking_text(
    bericht: Fahrbericht,
    event: Event,
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
    bar_surcharge = kiosk_total + crew_cost
    soll = bericht.boarding_fee + bar_surcharge
    cash = bericht.cash_amount or Decimal("0")
    diff = cash - soll

    funker = bericht.funker.display_name if bericht.funker else "—"
    guest_count = bericht.guest_count if bericht.guest_count is not None else "?"

    parts = [
        "KASSENBUCH-EINGANG:",
        f"Datum: {event.start_at.date().isoformat()}",
        f"Veranstaltung: {event.name} ({guest_count} Gäste)",
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
            f"Umlage Bar: € {_fmt(bar_surcharge)}",
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
