/**
 * Client-side booking-text renderer (spec 012, updated in spec 014).
 *
 * Mirrors `backend/app/services/booking_text.py` for instant preview. Reads
 * display fields off the Event (name, start_at) and trip-shape fields off the
 * Fahrbericht (funker, guest_count). If the formats ever diverge, the backend
 * is authoritative.
 */

function fmt(n) {
  return Number(n || 0).toFixed(2)
}

function eventDateString(event) {
  if (!event?.start_at) return ''
  return String(event.start_at).slice(0, 10)
}

export function buildBookingText({ bericht, event, catalog }) {
  const kioskLines = []
  let kioskTotal = 0
  for (const [bid, qty] of Object.entries(bericht?.kiosk_tally || {})) {
    if (!qty) continue
    const bar = catalog?.[bid]
    if (!bar) continue
    const total = qty * Number(bar.kb)
    kioskTotal += total
    kioskLines.push(`  ${bar.name} × ${qty} = € ${fmt(total)}`)
  }

  const crewLines = []
  let crewCost = 0
  for (const [bid, qty] of Object.entries(bericht?.crew_tally || {})) {
    if (!qty) continue
    const bar = catalog?.[bid]
    if (!bar) continue
    const total = qty * Number(bar.ek)
    crewCost += total
    crewLines.push(`  ${bar.name} × ${qty} = € ${fmt(total)}`)
  }

  const expensesTotal = (bericht?.expenses || []).reduce(
    (s, e) => s + Number(e.amount || 0),
    0,
  )
  const boarding = Number(bericht?.boarding_fee || 0)
  const surcharge = kioskTotal + crewCost
  const soll = boarding + surcharge
  const cash = Number(bericht?.cash_amount || 0)
  const diff = cash - soll

  const funker = bericht?.funker?.display_name || '—'
  const guestCount = bericht?.guest_count ?? '?'

  const parts = [
    'KASSENBUCH-EINGANG:',
    `Datum: ${eventDateString(event)}`,
    `Veranstaltung: ${event?.name || ''} (${guestCount} Gäste)`,
    `Funker*in: ${funker}`,
    '',
    'EINNAHMEN (8400 / Erlöse Kiosk):',
  ]
  if (kioskLines.length) parts.push(...kioskLines)
  else parts.push('  — keine Kiosk-Einnahmen —')
  parts.push(
    '',
    `SUMME EINNAHMEN: € ${fmt(kioskTotal)}`,
    `Umlage Boarding: € ${fmt(boarding)}`,
    `Umlage Bar: € ${fmt(surcharge)}`,
    '─────────────────────────────────',
    `SOLL Umschlag: € ${fmt(soll)}`,
    `IST Umschlag:  € ${fmt(cash)}`,
    `Differenz:     € ${diff >= 0 ? '+' : ''}${fmt(diff)}`,
    '',
    'AUSGABEN (4220 / Wareneinsatz Crew):',
  )
  if (crewLines.length) parts.push(...crewLines)
  else parts.push('  — keine Crew-Verköstigung —')
  parts.push(`Crew-Wareneinsatz: € ${fmt(crewCost)}`)
  if (expensesTotal > 0) {
    parts.push(`Sonstige Ausgaben Fahrt: € ${fmt(expensesTotal)}`)
  }
  return parts.join('\n')
}
