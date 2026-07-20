/**
 * Shared formatting utilities for the Funke frontend.
 * Consolidates duplicated formatDate/formatStatus/berlinToUTCISO functions.
 */

/**
 * Format an ISO date string for display (short format, with time).
 * Used in admin tables, modals, and lists.
 * Example: "3. Jan. 2026, 14:30"
 */
export function formatDate(dateStr, fallback = 'Noch offen') {
  if (!dateStr) return fallback
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Format an ISO date string for public-facing display (long format, with weekday).
 * Used on the registration page.
 * Example: "Samstag, 3. Januar 2026, 14:30"
 */
export function formatDateLong(dateStr, fallback = 'Wird noch bekannt gegeben') {
  if (!dateStr) return fallback
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Format an ISO date string as date only (no time).
 * Used in the debug page for compact display.
 * Example: "03.01.2026"
 */
export function formatDateOnly(dateStr, fallback = '-') {
  if (!dateStr) return fallback
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleDateString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

/**
 * Format an ISO date string as short date + time (no year).
 * Used in the debug page for registration timestamps.
 * Example: "03.01. 14:30"
 */
export function formatDateTime(dateStr, fallback = '-') {
  if (!dateStr) return fallback
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Translate event-level status codes to German.
 */
export function formatEventStatus(status) {
  const labels = {
    DRAFT: 'Entwurf',
    OPEN: 'Offen',
    REGISTRATION_CLOSED: 'Anmeldung geschlossen',
    LOTTERY_PENDING: 'Verlosung ausstehend',
    CONFIRMED: 'Bestätigt',
    COMPLETED: 'Abgeschlossen',
    CANCELLED: 'Abgesagt',
  }
  return labels[status] || status
}

/**
 * Translate registration-level status codes to German.
 */
export function formatRegistrationStatus(status) {
  const labels = {
    REGISTERED: 'Angemeldet',
    CONFIRMED: 'Bestätigung ausstehend',
    PARTICIPATING: 'Nimmt teil',
    WAITLISTED: 'Warteliste',
    CANCELLED: 'Abgesagt',
    CHECKED_IN: 'Eingecheckt',
  }
  return labels[status] || status
}

/**
 * Translate Tour status to German (spec 010).
 */
export function formatTourStatus(status) {
  const labels = {
    PLANNED: 'Geplant',
    IN_PROGRESS: 'Läuft',
    COMPLETED: 'Abgeschlossen',
    ARCHIVED: 'Archiviert',
  }
  return labels[status] || status
}

/**
 * Translate Fahrbericht status to German (spec 012).
 */
export function formatFahrberichtStatus(status) {
  const labels = { DRAFT: 'Entwurf', SUBMITTED: 'Eingereicht' }
  return labels[status] || status
}

/**
 * Translate Report email status to German (spec 013).
 */
export function formatEmailStatus(status) {
  const labels = {
    PENDING: 'Wird versendet',
    SENT: 'Versendet',
    FAILED: 'Fehler',
    SKIPPED_NO_RECIPIENT: 'Kein Empfänger',
  }
  return labels[status] || status
}

/**
 * Translate a CrewRole to German.
 */
export function formatCrewRole(role) {
  const labels = {
    FUNKER: 'Funker*in',
    SKIPPER: 'Skipper',
    BARCREW: 'Bar-Crew',
    BOARDING: 'Boarding',
    ALLROUNDER: 'Allrounder',
  }
  return labels[role] || role
}

/**
 * Translate a BarItem category to German.
 */
export function formatBarCategory(cat) {
  const labels = {
    BIER_FASS: 'Bier vom Faß',
    BIER_FLASCHE: 'Flaschenbier',
    ALKOHOLFREI: 'Alkoholfrei',
    SEKT_WEIN: 'Sekt & Wein',
    SOFTES: 'Softes',
    HARTES: 'Hartes',
    SHOTS: 'Shots',
  }
  return labels[cat] || cat
}

/**
 * Format an ISO date string as a `datetime-local` input value (Berlin wall-clock time).
 * Inverse of `berlinToUTCISO` — used to pre-fill event/festival edit forms.
 * (Originally a local function in EventForm.vue:131 — extracted here so
 * FestivalPage.vue can use it without reusing EventForm.vue itself, spec 019 T118.)
 */
export function formatDateTimeLocal(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const parts = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Berlin',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date)
  const get = (type) => parts.find(p => p.type === type).value
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}

/**
 * Convert a datetime-local input value (Berlin wall-clock time) to UTC ISO string.
 * Used when submitting event forms.
 */
export function berlinToUTCISO(localDateStr) {
  if (!localDateStr) return null
  const asUTC = new Date(localDateStr + 'Z')
  const berlinStr = asUTC.toLocaleString('sv-SE', { timeZone: 'Europe/Berlin', hourCycle: 'h23' })
  const berlinMs = new Date(berlinStr + 'Z').getTime()
  const offsetMs = berlinMs - asUTC.getTime()
  return new Date(asUTC.getTime() - offsetMs).toISOString()
}
