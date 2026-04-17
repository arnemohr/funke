/**
 * Client-side booking-text renderer (spec 012).
 *
 * Mirrors `backend/app/services/booking_text.py` for instant preview. If the
 * formats ever diverge, the backend version is authoritative.
 */

function fmt(n) {
  return Number(n || 0).toFixed(2)
}

export function buildBookingText({ bericht, tour, catalog }) {
  const kioskLines = []
  let kioskTotal = 0
  for (const [bid, qty] of Object.entries(bericht.kiosk_tally || {})) {
    if (!qty) continue
    const bar = catalog[bid]
    if (!bar) continue
    const total = qty * Number(bar.kb)
    kioskTotal += total
    kioskLines.push(`  ${bar.name} × ${qty} = € ${fmt(total)}`)
  }

  const crewLines = []
  let crewCost = 0
  for (const [bid, qty] of Object.entries(bericht.crew_tally || {})) {
    if (!qty) continue
    const bar = catalog[bid]
    if (!bar) continue
    const total = qty * Number(bar.ek)
    crewCost += total
    crewLines.push(`  ${bar.name} × ${qty} = € ${fmt(total)}`)
  }

  const expensesTotal = (bericht.expenses || []).reduce(
    (s, e) => s + Number(e.amount || 0),
    0,
  )
  const boarding = Number(bericht.boarding_fee || 0)
  const surcharge = Number(bericht.bar_surcharge || 0)
  const soll = kioskTotal + boarding + surcharge
  const cash = Number(bericht.cash_amount || 0)
  const diff = cash - soll

  const funker = tour?.funker?.display_name || '—'
  const parts = [
    'KASSENBUCH-EINGANG:',
    `Datum: ${tour?.date || ''}`,
    `Veranstaltung: ${tour?.name || ''} (${tour?.guest_count ?? '?'} Gäste)`,
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
