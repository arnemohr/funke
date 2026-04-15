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
