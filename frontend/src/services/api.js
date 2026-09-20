/**
 * API service for communicating with the backend.
 */
import { auth0 } from '../plugins/auth0'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Token cache
let cachedToken = null
let tokenExpiry = null

/**
 * Get the access token from Auth0.
 * @returns {Promise<string|null>} Access token or null
 */
async function getAccessToken() {
  // Check cache first
  if (cachedToken && tokenExpiry && Date.now() < tokenExpiry) {
    return cachedToken
  }

  try {
    cachedToken = await auth0.getAccessTokenSilently()
    // Cache for 5 minutes (tokens typically last longer but this is safe)
    tokenExpiry = Date.now() + 5 * 60 * 1000
    return cachedToken
  } catch {
    cachedToken = null
    tokenExpiry = null
    return null
  }
}

/**
 * Make an API request with proper error handling.
 * @param {string} endpoint - API endpoint (e.g., '/api/public/events/abc123')
 * @param {object} options - Fetch options
 * @param {boolean} requiresAuth - Whether this request requires authentication
 * @returns {Promise<object>} Response data
 */
async function request(endpoint, options = {}, requiresAuth = false) {
  const url = `${API_BASE_URL}${endpoint}`

  const defaultHeaders = {
    'Content-Type': 'application/json',
  }

  // Add auth token if required
  if (requiresAuth) {
    const token = await getAccessToken()
    if (!token) {
      await auth0.loginWithRedirect({ appState: { targetUrl: window.location.pathname } })
      throw new Error('Sitzung abgelaufen. Du wirst zur Anmeldung weitergeleitet.')
    }
    defaultHeaders['Authorization'] = `Bearer ${token}`
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  }

  const response = await fetch(url, config)

  if (!response.ok) {
    // If auth failed, clear token cache so next request gets a fresh token
    if (requiresAuth && (response.status === 401 || response.status === 403)) {
      cachedToken = null
      tokenExpiry = null
    }

    let errorMessage = `Request failed with status ${response.status}`
    try {
      const errorText = await response.text()
      // Guard against HTML responses (e.g. from a redirect or misconfigured proxy)
      if (errorText.trimStart().startsWith('<')) {
        console.error('API returned HTML instead of JSON:', errorText.substring(0, 200))
        throw new Error(errorMessage)
      }
      const errorData = JSON.parse(errorText)
      // Handle FastAPI validation errors (detail is array) and regular errors (detail is string)
      if (Array.isArray(errorData.detail)) {
        errorMessage = errorData.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
      } else {
        errorMessage = errorData.detail || errorMessage
      }
      console.error('API Error:', errorData)
    } catch (parseErr) {
      if (parseErr.message === errorMessage) throw parseErr
      // Ignore JSON parse errors
    }
    const err = new Error(errorMessage)
    err.status = response.status
    throw err
  }

  // Handle empty responses
  const text = await response.text()
  if (!text) return null
  // Guard against HTML responses on success (e.g. SPA fallback serving index.html)
  if (text.trimStart().startsWith('<')) {
    console.error('API returned HTML instead of JSON:', text.substring(0, 200))
    throw new Error('Unerwartete Antwort vom Server. Bitte lade die Seite neu.')
  }
  return JSON.parse(text)
}

// Public API (no auth required)
export const publicApi = {
  /**
   * The charter contract behind a signing link (spec 025).
   * The token in the path is the whole credential; every rejection is a 404.
   */
  async getCharterForSigning(eventId, token) {
    return request(`/api/public/vertrag/${eventId}/${token}`)
  },

  /**
   * Record the charterer's signature. `document_sha256` pins the render the
   * signer was shown — the server refuses a stale one.
   */
  async signCharter(eventId, token, payload) {
    return request(`/api/public/vertrag/${eventId}/${token}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /**
   * Get event info for registration.
   * @param {string} linkToken - Public registration link token
   * @returns {Promise<object>} Event public info
   */
  async getEventInfo(linkToken) {
    return request(`/api/public/events/${linkToken}`)
  },

  /**
   * Submit a registration.
   * @param {string} linkToken - Public registration link token
   * @param {object} data - Registration data: { name, email, phone?, notes?, group_size, group_members? }.
   *   group_members is optional; when provided, it is the full passenger list including the registrant
   *   (length ≤ group_size). Backend stores it as-is.
   * @returns {Promise<object>} Registration result
   */
  async submitRegistration(linkToken, data) {
    return request(`/api/public/events/${linkToken}/registrations`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /**
   * Cancel a registration.
   * @param {string} registrationId - Registration ID
   * @param {string} token - Cancellation token
   * @returns {Promise<object>} Cancellation result
   */
  async cancelRegistration(registrationId, token) {
    return request(`/api/public/registrations/${registrationId}/cancel?token=${token}`, {
      method: 'POST',
    })
  },

  /**
   * Get attendance status for a registration.
   * @param {string} registrationId - Registration ID
   * @param {string} token - Registration token
   * @returns {Promise<object>} Attendance status with registration info
   */
  async getAttendanceStatus(registrationId, token) {
    return request(`/api/public/registrations/${registrationId}/attendance-status?token=${token}`)
  },

  /**
   * Get registration info for cancellation page.
   * @param {string} registrationId - Registration ID
   * @param {string} token - Registration token
   * @returns {Promise<object>} Registration info
   */
  async getRegistrationInfo(registrationId, token) {
    return request(`/api/public/registrations/${registrationId}?token=${token}`)
  },

  /**
   * Confirm or decline attendance.
   * @param {string} registrationId - Registration ID
   * @param {string} token - Registration token
   * @param {string} response - 'yes' or 'no'
   * @returns {Promise<object>} Updated registration
   */
  async confirmAttendance(registrationId, token, response) {
    return request(`/api/public/registrations/${registrationId}/confirm?token=${token}&response=${response}`, {
      method: 'POST',
    })
  },

  /**
   * Get registration for management page.
   */
  async getRegistrationManage(registrationId, token) {
    return request(`/api/public/registrations/${registrationId}/manage?token=${token}`)
  },

  /**
   * Confirm participation with group member names.
   */
  async confirmWithNames(registrationId, token, groupMembers) {
    return request(`/api/public/registrations/${registrationId}/confirm-with-names?token=${token}`, {
      method: 'POST',
      body: JSON.stringify({ group_members: groupMembers }),
    })
  },

  /**
   * Update group member names (may also reduce group size).
   */
  async updateGroupMembers(registrationId, token, groupMembers) {
    return request(`/api/public/registrations/${registrationId}/group-members?token=${token}`, {
      method: 'PUT',
      body: JSON.stringify({ group_members: groupMembers }),
    })
  },

  /**
   * Get form-boot info for a festival invite link (spec 019).
   * @param {string} inviteToken - Invite token
   * @returns {Promise<object>} Invite info: event details, slots, participation hint
   */
  async getInviteInfo(inviteToken) {
    return request(`/api/public/invites/${inviteToken}`)
  },

  /**
   * Get the public guestlist view for an invite link (contingent status
   * plus who registered — names and days only).
   * @param {string} inviteToken - Invite token
   * @returns {Promise<object>} Guestlist: counts, can_register, registrations
   */
  async getInviteGuestlist(inviteToken) {
    return request(`/api/public/invites/${inviteToken}/guestlist`)
  },

  /**
   * Redeem an invite and create a festival registration (spec 019).
   * @param {string} inviteToken - Invite token
   * @param {object} payload - Festival registration data
   * @returns {Promise<object>} Registration result plus manage_url
   */
  async createFestivalRegistration(inviteToken, payload) {
    return request(`/api/public/invites/${inviteToken}/registrations`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /**
   * Self-service edit of a festival registration's attendance (spec 019).
   * @param {string} registrationId - Registration ID
   * @param {string} token - Registration token
   * @param {object} payload - Attendance patch (slots, tent_count, camper_count, phone, group_members)
   * @returns {Promise<object>} Updated registration
   */
  async updateFestivalAttendance(registrationId, token, payload) {
    return request(`/api/public/registrations/${registrationId}/festival-attendance?token=${token}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },

  /**
   * Get one companion's read-only ticket page (spec 020).
   *
   * The token is a per-person capability, NOT the group's registration token —
   * it grants read access to this one person's own row and nothing else.
   * `eventId` is part of the path so the backend can fetch the registration
   * directly instead of scanning.
   *
   * @param {string} eventId - Event ID
   * @param {string} registrationId - Registration ID
   * @param {number|string} personIndex - Person index (1.. — 0 is the contact)
   * @param {string} token - Per-person page token
   * @returns {Promise<object>} Name, event period, own days, own ticket code
   */
  async getPersonTicket(eventId, registrationId, personIndex, token) {
    return request(
      `/api/public/tickets/${eventId}/${registrationId}/${personIndex}?token=${token}`,
    )
  },

  /**
   * A companion sets their OWN attendance days (spec 021).
   *
   * Scoped by the same per-person token to exactly one index — it cannot reach
   * another person's days or the group's grid.
   *
   * @param {string} eventId - Event ID
   * @param {string} registrationId - Registration ID
   * @param {number|string} personIndex - Person index (1..)
   * @param {string} token - Per-person page token
   * @param {string[]} attendanceSlots - The slot keys this person is coming on
   * @returns {Promise<object>} The refreshed ticket payload
   */
  async updatePersonSlots(eventId, registrationId, personIndex, token, attendanceSlots) {
    return request(
      `/api/public/tickets/${eventId}/${registrationId}/${personIndex}?token=${token}`,
      { method: 'PATCH', body: JSON.stringify({ attendance_slots: attendanceSlots }) },
    )
  },

  /**
   * A companion removes themselves from the group (spec 021).
   *
   * Tombstones their entry, so everyone else's person_index — and therefore
   * every already-issued QR — stays valid. Irreversible from this page.
   *
   * @param {string} eventId - Event ID
   * @param {string} registrationId - Registration ID
   * @param {number|string} personIndex - Person index (1..)
   * @param {string} token - Per-person page token
   * @returns {Promise<object>} `{cancelled, group_size, message}`
   */
  async cancelPersonTicket(eventId, registrationId, personIndex, token) {
    return request(
      `/api/public/tickets/${eventId}/${registrationId}/${personIndex}/cancel?token=${token}`,
      { method: 'POST' },
    )
  },

  /**
   * The public Fundsachen page (spec 023).
   *
   * The token in the path is the whole authorisation, and the backend answers
   * one bare 404 to every rejection — wrong token, unpublished, expired,
   * anonymised. Callers branch on `err.status === 404` and must not tell the
   * reader which of those it was.
   *
   * @param {string} eventId - Event ID
   * @param {string} token - Page token (43 characters)
   * @returns {Promise<object>} Copy, coordinator and the photos with signed URLs
   */
  async getLostFound(eventId, token) {
    return request(
      `/api/public/lostfound/${encodeURIComponent(eventId)}/${encodeURIComponent(token)}`,
    )
  },

  /**
   * The public photo upload page (spec 024).
   *
   * The mirror image of `getLostFound`: there the public direction is reading,
   * here it is writing. This payload therefore carries copy, contact, the
   * window state, the limits and a single aggregate count — and by design no
   * `photo_id`, no S3 key and no image URL, because guests never read from
   * this collection, not even their own upload. `upload_open` is the computed
   * window (switch AND `closes_at` AND retention), not the stored switch.
   *
   * Every rejection that falls before or on the token comparison is one bare
   * 404 — wrong token, non-ASCII token, unknown event, no collection. Callers
   * branch on `err.status === 404` and must not tell the reader which it was.
   *
   * @param {string} eventId - Event ID
   * @param {string} token - Upload token (43 characters)
   * @returns {Promise<object>} Copy, contact, limits and `photo_count` ("ca.")
   */
  async getPhotoUploadPage(eventId, token) {
    return request(
      `/api/public/photos/${encodeURIComponent(eventId)}/${encodeURIComponent(token)}`,
    )
  },

  /**
   * Mint presigned POSTs for one batch of at most 30 photos (spec 024).
   *
   * `count` reserves that many slots against the 2000-photo cap before a
   * single byte moves, so a full collection answers 409 instead of handing
   * out signatures. `uploader_name` and `note` are typed once for the whole
   * drop and stored on every row of it.
   *
   * Failures here are distinguishable because they all land *after* the token
   * matched and therefore reveal nothing: 409 closed, 409 collection full,
   * 429 hourly quota, 400 batch over 30.
   *
   * @param {string} eventId - Event ID
   * @param {string} token - Upload token
   * @param {object} batch - { count, uploader_name?, note? }
   * @returns {Promise<object>} { uploads: [{ photo_id, full, thumb }] }
   */
  async createPhotoUploads(eventId, token, { count, uploader_name = null, note = null } = {}) {
    return request(
      `/api/public/photos/${encodeURIComponent(eventId)}/${encodeURIComponent(token)}/uploads`,
      {
        method: 'POST',
        body: JSON.stringify({ count, uploader_name, note }),
      },
    )
  },

  /**
   * Flip PENDING rows to READY — the only way a photo becomes visible to the
   * organiser, and the only thing the browser knows that the backend cannot:
   * pixel dimensions, byte size and `file.lastModified` as `captured_at_hint`.
   *
   * The body is a **bare JSON array**, not a wrapper object (spec 024, unlike
   * `lostFound.confirmPhotos`). Deliberately not window-gated: a batch that
   * started while the page was open must be allowed to finish.
   *
   * A partial batch is a 200 with a lower `confirmed` and says nothing about
   * which entries failed — the caller already knows which uploads it managed
   * to put on S3 and tracks the rest itself. An empty array is a 200 with
   * `confirmed: 0`, more than 30 entries is a 422.
   *
   * @param {string} eventId - Event ID
   * @param {string} token - Upload token
   * @param {Array<object>} items - [{ photo_id, width, height, bytes, captured_at_hint? }]
   * @returns {Promise<object>} { confirmed }
   */
  async confirmPhotoUploads(eventId, token, items) {
    return request(
      `/api/public/photos/${encodeURIComponent(eventId)}/${encodeURIComponent(token)}/confirm`,
      {
        method: 'POST',
        body: JSON.stringify(items),
      },
    )
  },
}

// Scanner check-in API (no auth required — the gate token IS the auth,
// spec.md:336). Every call is scoped to one gate token.
export const checkinApi = {
  /**
   * Boot payload for the scanner PWA: event info, slot labels, and the
   * offline verification secret.
   * @param {string} gateToken - Scanner gate token
   * @returns {Promise<object>} Boot response
   */
  async boot(gateToken) {
    return request(`/api/public/checkin/${gateToken}`)
  },

  /**
   * One-tap QR scan. Always resolves with a structured result
   * (`result`/`reason`/`card`/`scan_id`/`already_checked_in`) — the caller
   * branches on the body, not on HTTP status.
   * @param {string} gateToken - Scanner gate token
   * @param {string} code - The scanned ticket code
   * @returns {Promise<object>} Scan result
   */
  async scan(gateToken, code) {
    return request(`/api/public/checkin/${gateToken}/scan`, {
      method: 'POST',
      body: JSON.stringify({ code }),
    })
  },

  /**
   * Override check-in — either `{ code }` ("Trotzdem einchecken" on an
   * already-checked-in ticket) or `{ registration_id, person_index }`
   * (the name-search check-in target).
   * @param {string} gateToken - Scanner gate token
   * @param {object} body - `{ code }` or `{ registration_id, person_index }`
   * @returns {Promise<object>} Scan result (same shape as `scan`)
   */
  async override(gateToken, body) {
    return request(`/api/public/checkin/${gateToken}/override`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  /**
   * Undo a scan within its ~60s window.
   * @param {string} gateToken - Scanner gate token
   * @param {string} scanId - The scan_id returned by `scan`/`override`
   * @returns {Promise<object>} `{ ok: boolean }`
   */
  async undo(gateToken, scanId) {
    return request(`/api/public/checkin/${gateToken}/undo`, {
      method: 'POST',
      body: JSON.stringify({ scan_id: scanId }),
    })
  },

  /**
   * Name-search fallback (no QR). `q` must be at least 2 characters.
   * @param {string} gateToken - Scanner gate token
   * @param {string} q - Search query
   * @returns {Promise<object>} `{ matches: [...] }`
   */
  async search(gateToken, q) {
    return request(`/api/public/checkin/${gateToken}/search?q=${encodeURIComponent(q)}`)
  },
}

/**
 * Shared blob-download helper for the festival registrations CSV export
 * (T206) — used for the printable gate list (`view=gate`). Mirrors
 * `exportBoardingPdf`'s pattern: raw `fetch` with a bearer token,
 * `response.blob()`, object URL + temp `<a download>` click, filename
 * from `Content-Disposition`.
 * @param {string} eventId - Festival event ID
 * @param {string} view - 'gate'
 * @returns {Promise<void>} Triggers file download
 */
async function downloadFestivalCsv(eventId, view) {
  const token = await getAccessToken()
  const url = `${API_BASE_URL}/api/admin/festival/${eventId}/registrations/export-csv?view=${view}`
  const response = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  })
  if (!response.ok) {
    throw new Error(`Export failed with status ${response.status}`)
  }
  const blob = await response.blob()
  const downloadUrl = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = downloadUrl
  const disposition = response.headers.get('Content-Disposition')
  const match = disposition && disposition.match(/filename="?([^"]+)"?/)
  a.download = match ? match[1] : `${view}_${eventId}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(downloadUrl)
}

/**
 * Post one variant to S3 with a presigned POST.
 *
 * Field order is load-bearing: S3 ignores every form field that follows the
 * file part, so the policy fields all go in first and the blob goes last. And
 * no Content-Type header on the fetch — only the browser can put the multipart
 * boundary there.
 *
 * Shared between the Fundsachen upload (spec 023) and the event photo upload
 * (spec 024, guest drop and „unkenntlich machen" alike): three call sites
 * writing this form by hand is three chances to get the order wrong, and the
 * failure mode is a silent policy violation, not an exception.
 * @param {{url: string, fields: object}} target - Presigned POST descriptor
 * @param {Blob} blob - JPEG payload
 */
export async function postPresignedForm(target, blob) {
  const form = new FormData()
  for (const [key, value] of Object.entries(target.fields)) {
    form.append(key, value)
  }
  form.append('file', blob)

  const response = await fetch(target.url, { method: 'POST', body: form })
  if (!response.ok) {
    throw new Error(`s3_${response.status}`)
  }
}

// Admin API (requires auth)
export const adminApi = {
  /**
   * List all events.
   * @param {string} [status] - Optional status filter
   * @returns {Promise<object>} Events list
   */
  async listEvents(status) {
    const query = status ? `?status=${status}` : ''
    return request(`/api/admin/events${query}`, {}, true)
  },

  /**
   * Get event details.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Event details
   */
  async getEvent(eventId) {
    return request(`/api/admin/events/${eventId}`, {}, true)
  },

  /**
   * Create a new event.
   * @param {object} data - Event data
   * @returns {Promise<object>} Created event
   */
  async createEvent(data) {
    return request('/api/admin/events', {
      method: 'POST',
      body: JSON.stringify(data),
    }, true)
  },

  /**
   * Update an event.
   * @param {string} eventId - Event ID
   * @param {object} data - Update data
   * @returns {Promise<object>} Updated event
   */
  async updateEvent(eventId, data) {
    return request(`/api/admin/events/${eventId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }, true)
  },

  /**
   * Publish an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Published event
   */
  async publishEvent(eventId) {
    return request(`/api/admin/events/${eventId}/publish`, {
      method: 'POST',
    }, true)
  },

  /**
   * Clone an event.
   * @param {string} eventId - Source event ID
   * @param {string} startAt - New start date/time
   * @returns {Promise<object>} Cloned event
   */
  async cloneEvent(eventId, startAt) {
    return request(`/api/admin/events/${eventId}/clone`, {
      method: 'POST',
      body: JSON.stringify({ start_at: startAt }),
    }, true)
  },

  /**
   * Cancel an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Cancelled event
   */
  async cancelEvent(eventId) {
    return request(`/api/admin/events/${eventId}/cancel`, {
      method: 'POST',
    }, true)
  },

  /**
   * Delete an event (only allowed for CANCELLED events).
   * @param {string} eventId - Event ID
   * @returns {Promise<void>}
   */
  async deleteEvent(eventId) {
    return request(`/api/admin/events/${eventId}`, {
      method: 'DELETE',
    }, true)
  },

  /**
   * Anonymize an event's personal data (spec 022).
   *
   * Serves SINGLE and FESTIVAL events alike — the backend route is shared.
   * Only COMPLETED/CANCELLED events qualify; anything else 409s. Permanent:
   * names and addresses are overwritten with digests, while the rows (and so
   * every headcount and statistic) survive.
   *
   * A festival with thousands of guests, scans and sent mails cannot be
   * rewritten inside one request — API Gateway cuts the connection at 29s and
   * the caller got a 504. The backend now scrubs what it can and answers
   * `completed: false`, so this repeats the call until the event is done and
   * reports the accumulated totals. Each pass is idempotent, so a pass lost to
   * a flaky connection costs nothing but the retry.
   *
   * @param {string} eventId - Event ID
   * @param {object} [options]
   * @param {(progress: {rows: number, pass: number}) => void} [options.onProgress]
   *   Called after every pass, for a modal that would otherwise sit still for
   *   minutes on a large event.
   * @returns {Promise<object>} Last pass's response, with `rows_touched` and
   *   `passes` covering the whole run
   */
  async anonymizeEvent(eventId, { onProgress } = {}) {
    // Enough for ~100k rows at the backend's per-pass budget. A ceiling only
    // exists so a backend that never reports `completed` cannot spin forever.
    const MAX_PASSES = 40
    let rows = 0
    let result

    for (let pass = 1; pass <= MAX_PASSES; pass++) {
      result = await request(`/api/admin/events/${eventId}/anonymize`, {
        method: 'POST',
      }, true)

      rows += result.rows_touched
      if (onProgress) onProgress({ rows, pass })

      if (result.completed) {
        return { ...result, rows_touched: rows, passes: pass }
      }
      // An unfinished pass that touched nothing means the run is stuck rather
      // than slow. Failing here beats hammering the endpoint 40 times.
      if (result.rows_touched === 0) {
        throw new Error('Anonymisierung kommt nicht voran — bitte erneut versuchen.')
      }
    }

    throw new Error(
      'Anonymisierung ist noch nicht fertig — bitte erneut starten, ' +
      `bereits bereinigt: ${rows} Datensätze.`,
    )
  },

  /**
   * Close registration for an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Updated event
   */
  async closeRegistration(eventId) {
    return request(`/api/admin/events/${eventId}/close-registration`, {
      method: 'POST',
    }, true)
  },

  /**
   * Reopen registration for an event (REGISTRATION_CLOSED -> OPEN).
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Updated event
   */
  async reopenRegistration(eventId) {
    return request(`/api/admin/events/${eventId}/reopen-registration`, {
      method: 'POST',
    }, true)
  },

  /**
   * Complete an event (CONFIRMED -> COMPLETED).
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Updated event
   */
  async completeEvent(eventId) {
    return request(`/api/admin/events/${eventId}/complete`, {
      method: 'POST',
    }, true)
  },

  /**
   * List registrations for an event.
   * @param {string} eventId - Event ID
   * @param {string} [status] - Optional status filter
   * @param {string} [search] - Optional search term
   * @returns {Promise<object>} Registrations list
   */
  async listRegistrations(eventId, status, search) {
    const params = new URLSearchParams()
    if (status) params.append('status', status)
    if (search) params.append('search', search)
    const query = params.toString() ? `?${params.toString()}` : ''
    return request(`/api/admin/events/${eventId}/registrations${query}`, {}, true)
  },

  /**
   * Run lottery for an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Lottery result
   */
  async runLottery(eventId) {
    return request(`/api/admin/events/${eventId}/lottery/run`, {
      method: 'POST',
    }, true)
  },

  /**
   * Get latest lottery result for an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Lottery result
   */
  async getLottery(eventId) {
    return request(`/api/admin/events/${eventId}/lottery`, {}, true)
  },

  /**
   * Finalize lottery and send notifications.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Finalized lottery result
   */
  async finalizeLottery(eventId) {
    return request(`/api/admin/events/${eventId}/lottery/finalize`, {
      method: 'POST',
    }, true)
  },

  /**
   * Export boarding list as PDF.
   * @param {string} eventId - Event ID
   * @returns {Promise<void>} Triggers file download
   */
  async exportBoardingPdf(eventId) {
    const token = await getAccessToken()
    const url = `${API_BASE_URL}/api/admin/events/${eventId}/registrations/export`
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!response.ok) {
      throw new Error(`Export failed with status ${response.status}`)
    }
    const blob = await response.blob()
    const downloadUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    const disposition = response.headers.get('Content-Disposition')
    const match = disposition && disposition.match(/filename="?([^"]+)"?/)
    a.download = match ? match[1] : `boardingzettel_${eventId}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(downloadUrl)
  },

  /**
   * Send a custom message to selected registrations.
   * @param {string} eventId - Event ID
   * @param {object} data - { registration_ids: string[], subject: string, body: string }
   * @returns {Promise<object>} Send result { sent, failed, total }
   */
  async sendCustomMessage(eventId, data) {
    return request(`/api/admin/events/${eventId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }, true)
  },

  /**
   * List sent messages for an event.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Messages list
   */
  async listMessages(eventId) {
    return request(`/api/admin/events/${eventId}/messages`, {}, true)
  },

  /**
   * Toggle promoted flag on a registration.
   * @param {string} eventId - Event ID
   * @param {string} registrationId - Registration ID
   * @param {boolean} promoted - Whether to promote
   * @returns {Promise<object>} Updated registration
   */
  async togglePromoted(eventId, registrationId, promoted) {
    return request(`/api/admin/events/${eventId}/registrations/${registrationId}/promote`, {
      method: 'PATCH',
      body: JSON.stringify({ promoted }),
    }, true)
  },

  /**
   * Get unacknowledged (CONFIRMED) registrations for preview.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Registrations list
   */
  async getUnacknowledged(eventId) {
    return request(`/api/admin/events/${eventId}/registrations/unacknowledged`, {}, true)
  },

  /**
   * Discard selected unacknowledged registrations.
   * @param {string} eventId - Event ID
   * @param {string[]} registrationIds - Registration IDs to discard
   * @param {string} [reason] - Optional custom cancellation message
   * @returns {Promise<object>} { discarded_count, discarded_spots }
   */
  async discardUnacknowledged(eventId, registrationIds, reason, subject) {
    return request(`/api/admin/events/${eventId}/registrations/discard-unacknowledged`, {
      method: 'POST',
      body: JSON.stringify({ registration_ids: registrationIds, reason, subject }),
    }, true)
  },

  /**
   * Manually promote a waitlisted registration.
   * @param {string} eventId - Event ID
   * @param {string} registrationId - Registration ID
   * @param {string} targetStatus - 'CONFIRMED' or 'PARTICIPATING'
   * @returns {Promise<object>} Updated registration
   */
  async promoteFromWaitlist(eventId, registrationId, targetStatus = 'CONFIRMED') {
    return request(`/api/admin/events/${eventId}/registrations/${registrationId}/promote-from-waitlist`, {
      method: 'POST',
      body: JSON.stringify({ target_status: targetStatus }),
    }, true)
  },

  /**
   * Admin: delete a single registration permanently.
   */
  async deleteRegistration(eventId, registrationId) {
    return request(`/api/admin/events/${eventId}/registrations/${registrationId}`, {
      method: 'DELETE',
    }, true)
  },

  /**
   * Admin: fetch a single registration for the detail page (spec 018).
   */
  async getAdminRegistration(eventId, registrationId) {
    return request(`/api/admin/events/${eventId}/registrations/${registrationId}`, {}, true)
  },

  /**
   * Admin: partial update of a single registration (spec 018).
   *
   * Accepts a `patch` object with any subset of:
   *   { name, phone, notes, group_size, group_members }
   *
   * Throws on non-OK responses. On 409 (concurrency conflict), the thrown
   * Error carries `.status === 409` and `.data === { detail, registration }`
   * so callers can rehydrate their form from the embedded current state.
   */
  async updateAdminRegistration(eventId, registrationId, patch) {
    const url = `${API_BASE_URL}/api/admin/events/${eventId}/registrations/${registrationId}`
    const token = await getAccessToken()
    if (!token) {
      await auth0.loginWithRedirect({ appState: { targetUrl: window.location.pathname } })
      throw new Error('Sitzung abgelaufen. Du wirst zur Anmeldung weitergeleitet.')
    }

    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(patch),
    })

    if (response.status === 409) {
      const data = await response.json().catch(() => ({}))
      const err = new Error('Die Anmeldung wurde zwischenzeitlich aktualisiert.')
      err.status = 409
      err.data = data
      throw err
    }

    if (!response.ok) {
      let detail = `Request failed with status ${response.status}`
      try {
        const body = await response.json()
        if (Array.isArray(body.detail)) {
          detail = body.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
        } else if (body.detail) {
          detail = body.detail
        }
      } catch {
        // Ignore JSON parse errors
      }
      const err = new Error(detail)
      err.status = response.status
      throw err
    }

    return response.json()
  },

  // Push notification endpoints

  async getVapidKey() {
    return request('/api/admin/push/vapid-key', {}, true)
  },

  async subscribePush(subscription) {
    return request('/api/admin/push/subscribe', {
      method: 'POST',
      body: JSON.stringify(subscription),
    }, true)
  },

  async unsubscribePush() {
    return request('/api/admin/push/subscribe', {
      method: 'DELETE',
    }, true)
  },

  // ------------------------------------------------------------------ Profile
  async getProfile() {
    return request('/api/admin/me', {}, true)
  },
  async updateProfile(patch) {
    return request('/api/admin/me', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }, true)
  },
  async listCrewSuggestions({ role, q, limit = 10 } = {}) {
    const params = new URLSearchParams()
    if (role) params.set('role', role)
    if (q) params.set('q', q)
    if (limit) params.set('limit', String(limit))
    const qs = params.toString()
    return request(`/api/admin/crew-suggestions${qs ? `?${qs}` : ''}`, {}, true)
  },

  // ----------------------------------------------------------------- Bar items
  bar: {
    async list(params = {}) {
      const qs = new URLSearchParams(params).toString()
      return request(`/api/admin/bar-items${qs ? `?${qs}` : ''}`, {}, true)
    },
    async create(body) {
      return request('/api/admin/bar-items', {
        method: 'POST',
        body: JSON.stringify(body),
      }, true)
    },
    async get(id) {
      return request(`/api/admin/bar-items/${id}`, {}, true)
    },
    async patch(id, body) {
      return request(`/api/admin/bar-items/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }, true)
    },
    async delete(id) {
      return request(`/api/admin/bar-items/${id}`, { method: 'DELETE' }, true)
    },
    async adjustStock(id, body) {
      return request(`/api/admin/bar-items/${id}/adjust-stock`, {
        method: 'POST',
        body: JSON.stringify(body),
      }, true)
    },
    async seed() {
      return request('/api/admin/bar-items/seed', { method: 'POST' }, true)
    },
  },

  // -------------------------------------------------------------------- Ship
  ship: {
    async getState() {
      return request('/api/admin/ship/state', {}, true)
    },
    async patchState(body) {
      return request('/api/admin/ship/state', {
        method: 'PATCH',
        body: JSON.stringify(body),
      }, true)
    },
    async addNote(text) {
      return request('/api/admin/ship/notes', {
        method: 'POST',
        body: JSON.stringify({ text }),
      }, true)
    },
    async removeNote(noteId) {
      return request(`/api/admin/ship/notes/${noteId}`, { method: 'DELETE' }, true)
    },
    async addTodo(text) {
      return request('/api/admin/ship/todos', {
        method: 'POST',
        body: JSON.stringify({ text }),
      }, true)
    },
    async patchTodo(todoId, body) {
      return request(`/api/admin/ship/todos/${todoId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }, true)
    },
    async removeTodo(todoId) {
      return request(`/api/admin/ship/todos/${todoId}`, { method: 'DELETE' }, true)
    },
  },

  // --------------------------------------------------------------- Fahrbericht
  fahrbericht: {
    async get(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht`, {}, true)
    },
    async createDraft(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht`, {
        method: 'POST',
      }, true)
    },
    async put(eventId, patch) {
      return request(`/api/admin/events/${eventId}/fahrbericht`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      }, true)
    },
    async submit(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht/submit`, {
        method: 'POST',
      }, true)
    },
    async reopen(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht/reopen`, {
        method: 'POST',
      }, true)
    },
    async reapply(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht/reapply-side-effects`, {
        method: 'POST',
      }, true)
    },
    async delete(eventId) {
      return request(`/api/admin/events/${eventId}/fahrbericht`, {
        method: 'DELETE',
      }, true)
    },
  },

  // ------------------------------------------------------------ Chartervertrag
  // Spec 025 — one contract per SINGLE event, filled in here, rendered to PDF,
  // signed with a pen at the jetty and scanned back in. Flat on `adminApi`
  // rather than a block of its own: there is exactly one contract per event,
  // so there is nothing to namespace, and the page reads better spelt out.
  //
  // The scan travels straight to S3 through the shared `postPresignedForm`
  // exported above — `requestCharterUpload` mints the target, the browser
  // posts the file, `confirmCharterSigned` makes it count.

  /**
   * The event's charter contract.
   *
   * **404 means „kein Vertrag angelegt"** — that is the empty state, not a
   * failure, so callers catch `err.status === 404` and show „Vertrag anlegen"
   * (same shape as `eventPhotos.getConfig`).
   *
   * `gesamtbetrag` is computed live from what is currently typed (Chartergebühr
   * plus Sonderleistungen, deliberately without the refundable Kaution) and can
   * differ from the total the last PDF printed. `download_url` and
   * `signed_download_url` arrive presigned — link to them, do not rebuild them.
   *
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} Contract plus `gesamtbetrag`, `download_url`,
   *   `signed_download_url` and `can_edit`
   */
  async getCharterContract(eventId) {
    return request(`/api/admin/events/${eventId}/chartervertrag`, {}, true)
  },

  /**
   * Create or update the draft. Idempotent, and a half-filled body is fine:
   * the mandatory set is checked when the PDF is rendered, not on every save.
   *
   * 409 `vertrag_bereits_unterschrieben` once the contract is signed (discard
   * the signature first), 409 `charter_nur_fuer_einzelfahrten` on a FESTIVAL
   * event.
   *
   * @param {string} eventId - Event ID
   * @param {object} payload - Charterer, Zeitraum, Kosten, Schiffsführer and
   *   Sondervereinbarungen; unknown keys are rejected by the backend
   * @returns {Promise<object>} The stored contract
   */
  async saveCharterContract(eventId, payload) {
    return request(`/api/admin/events/${eventId}/chartervertrag`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }, true)
  },

  /**
   * Render the PDF: the server checks the mandatory set, raises
   * `document_version` and stores `v{n}.pdf`. Nothing is ever overwritten, so
   * a link already mailed out keeps pointing at the version that was sent.
   *
   * 422 `vertrag_unvollstaendig` carries the missing fields as German names in
   * `detail` — print that string, do not re-derive the list here.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} The contract with the freshly rendered document
   */
  async renderCharterContract(eventId) {
    return request(`/api/admin/events/${eventId}/chartervertrag/render`, {
      method: 'POST',
    }, true)
  },

  /**
   * Mail the contract to the charterer, the PDF as an attachment rather than a
   * link: this is also the copy on a durable medium, and a link expires.
   *
   * 409 without a rendered PDF or without an address, 503
   * `smtp_nicht_konfiguriert` when mail is not set up at all — that one is a
   * hint to download and send it by hand, not an error to retry.
   * @param {string} eventId - Event ID
   * @param {object} [options]
   * @param {boolean} [options.cc_self] - Copy to the sending organiser
   * @returns {Promise<object>} The contract, now `sent`
   */
  async sendCharterContract(eventId, { cc_self = false } = {}) {
    return request(`/api/admin/events/${eventId}/chartervertrag/senden`, {
      method: 'POST',
      body: JSON.stringify({ cc_self }),
    }, true)
  },

  /**
   * Presigned POST for the signed scan: exactly one key, the content type
   * pinned, 1..15 MB, 15 minutes. Hand the result to `postPresignedForm`, then
   * call `confirmCharterSigned` — until that confirm runs the upload counts
   * for nothing, because nobody has hashed it.
   *
   * 409 `vertrag_nicht_erzeugt` while no PDF has been rendered: there is no
   * version to be the signed copy of.
   * @param {string} eventId - Event ID
   * @param {object} options
   * @param {string} options.content_type - MIME type of the file to upload
   * @returns {Promise<object>} { url, fields, key }
   */
  async requestCharterUpload(eventId, { content_type }) {
    return request(`/api/admin/events/${eventId}/chartervertrag/upload`, {
      method: 'POST',
      body: JSON.stringify({ content_type }),
    }, true)
  },

  /**
   * Record the signature: the server checks the object arrived, streams it once
   * for the SHA-256 and sets `status = signed`.
   *
   * `signed_on` is the date written on the paper, which is not necessarily
   * today. The Vercharterer's countersignature is deliberately not asked for
   * here — it is optional and never blocks `signed`.
   *
   * 404 `datei_nicht_hochgeladen` when the upload never made it to S3.
   * @param {string} eventId - Event ID
   * @param {object} body
   * @param {string} body.signed_on - Date on the paper (YYYY-MM-DD)
   * @param {boolean} body.alle_parteien_unterschrieben - The mandatory
   *   confirmation checkbox
   * @returns {Promise<object>} The contract, now `signed`
   */
  async confirmCharterSigned(eventId, { signed_on, alle_parteien_unterschrieben }) {
    return request(`/api/admin/events/${eventId}/chartervertrag/signiert`, {
      method: 'POST',
      body: JSON.stringify({ signed_on, alle_parteien_unterschrieben }),
    }, true)
  },

  /**
   * Add the Vercharterer's countersignature after the fact. Touches neither
   * status nor document nor hash, and stays available forever — years later on
   * a long-signed contract included.
   * @param {string} eventId - Event ID
   * @param {object} body
   * @param {string} body.countersigned_on - Date on the paper (YYYY-MM-DD)
   * @param {string} [body.countersigned_by] - Who countersigned, if it was not
   *   the person operating the page
   * @returns {Promise<object>} The contract with the countersignature recorded
   */
  async recordCharterCountersign(eventId, { countersigned_on, countersigned_by = null }) {
    // Send `countersigned_by` only when the page actually knows a name: the
    // backend fills it from the token otherwise, and it rejects unknown keys,
    // so a null would cost the request rather than mean „unbekannt".
    const body = countersigned_by
      ? { countersigned_on, countersigned_by }
      : { countersigned_on }
    return request(`/api/admin/events/${eventId}/chartervertrag/gegenzeichnung`, {
      method: 'POST',
      body: JSON.stringify(body),
    }, true)
  },

  /**
   * Discard the signature and go back to `draft`, editable again. The scan is
   * not deleted — its key is kept in `superseded_signed_keys` and the object
   * stays in the bucket. 409 `vertrag_nicht_unterschrieben` if there is
   * nothing to discard.
   * @param {string} eventId - Event ID
   * @returns {Promise<object>} The contract, back in `draft`
   */
  async sendCharterSigningLink(eventId) {
    return request(`/api/admin/events/${eventId}/chartervertrag/signaturlink`, { method: 'POST' }, true)
  },

  async signCharterAsAdmin(eventId, payload) {
    return request(`/api/admin/events/${eventId}/chartervertrag/unterschreiben`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }, true)
  },

  async unsignCharterContract(eventId) {
    return request(`/api/admin/events/${eventId}/chartervertrag/unsign`, {
      method: 'POST',
    }, true)
  },

  /**
   * Delete the contract row. Only while it is still a draft *and* nothing has
   * been rendered; once a PDF exists the answer is 409
   * `vertrag_bereits_erzeugt`, because that PDF may already be in a mailbox.
   * @param {string} eventId - Event ID
   * @returns {Promise<void>}
   */
  async deleteCharterContract(eventId) {
    return request(`/api/admin/events/${eventId}/chartervertrag`, {
      method: 'DELETE',
    }, true)
  },

  // ------------------------------------------------------------------- Reports
  reports: {
    async get(id) {
      return request(`/api/admin/reports/${id}`, {}, true)
    },
    async getVersion(id, version) {
      return request(`/api/admin/reports/${id}/versions/${version}`, {}, true)
    },
    async resend(id) {
      return request(`/api/admin/reports/${id}/resend`, { method: 'POST' }, true)
    },
    async getForEvent(eventId) {
      return request(`/api/admin/events/${eventId}/report`, {}, true)
    },
    pdfUrl(id) {
      return `${API_BASE_URL}/api/admin/reports/${id}/pdf`
    },
    versionPdfUrl(id, version) {
      return `${API_BASE_URL}/api/admin/reports/${id}/versions/${version}/pdf`
    },
  },

  // --------------------------------------------------------------- Fundsachen
  // Spec 023 — one page per event, SINGLE and FESTIVAL alike.
  lostFound: {
    /**
     * Config plus every photo row, including PENDING ones (admin view).
     * `configured: false` means the page does not exist yet.
     * @param {string} eventId - Event ID
     * @returns {Promise<object>} Admin payload with presigned view URLs
     */
    async get(eventId) {
      return request(`/api/admin/events/${eventId}/lostfound`, {}, true)
    },

    /**
     * Create or update the page. First call mints the page token.
     * @param {string} eventId - Event ID
     * @param {object} patch - { coordinator_email, coordinator_name, intro_text,
     *   published, retention_days }
     * @returns {Promise<object>} Admin payload
     */
    async save(eventId, patch) {
      return request(`/api/admin/events/${eventId}/lostfound`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      }, true)
    },

    /**
     * Fresh page token — every link already sent stops working.
     * @param {string} eventId - Event ID
     * @returns {Promise<object>} Admin payload with the new public URL
     */
    async rotateToken(eventId) {
      return request(`/api/admin/events/${eventId}/lostfound/rotate-token`, {
        method: 'POST',
      }, true)
    },

    /**
     * Delete config, photo rows and S3 objects.
     *
     * A page with hundreds of photos does not fit in one request — the backend
     * deletes what it can and answers `completed: false`, so this repeats until
     * the page is gone and reports the accumulated count (same pattern as
     * `adminApi.anonymizeEvent`). Every pass is idempotent.
     *
     * @param {string} eventId - Event ID
     * @param {object} [options]
     * @param {(progress: {photos: number, pass: number}) => void} [options.onProgress]
     * @returns {Promise<object>} { deleted_photos, completed, passes }
     */
    async deletePage(eventId, { onProgress } = {}) {
      const MAX_PASSES = 40
      let photos = 0
      let result

      for (let pass = 1; pass <= MAX_PASSES; pass++) {
        result = await request(`/api/admin/events/${eventId}/lostfound`, {
          method: 'DELETE',
        }, true)

        photos += result.deleted_photos
        if (onProgress) onProgress({ photos, pass })

        if (result.completed) {
          return { ...result, deleted_photos: photos, passes: pass }
        }
        // An unfinished pass that deleted nothing is stuck, not slow.
        if (result.deleted_photos === 0) {
          throw new Error('Löschen kommt nicht voran — bitte erneut versuchen.')
        }
      }

      throw new Error(
        'Die Seite ist noch nicht vollständig gelöscht — bitte erneut starten, ' +
        `bereits entfernt: ${photos} Fotos.`,
      )
    },

    /**
     * Mint presigned POSTs for a whole batch in one call (1..50).
     * Each entry carries its final number, so the browser can label rows
     * before the upload finishes.
     * @param {string} eventId - Event ID
     * @param {number} count - Number of photos in this batch
     * @returns {Promise<object>} { uploads: [{ photo_id, number, display, thumb }] }
     */
    async createUploads(eventId, count) {
      return request(`/api/admin/events/${eventId}/lostfound/uploads`, {
        method: 'POST',
        body: JSON.stringify({ count }),
      }, true)
    },

    /**
     * Flip PENDING rows to READY — only for photos whose both variants are up.
     *
     * A batch can land partially: `not_confirmed` names the ids whose row was
     * gone by the time the call arrived (deleted in parallel, or pruned after
     * 24 h). Everything else is live and must not be uploaded again — a second
     * upload draws fresh numbers, so the page would show the same item twice.
     * Only a batch that confirmed nothing at all is a 404.
     *
     * @param {string} eventId - Event ID
     * @param {Array<object>} photos - [{ photo_id, width, height, caption }]
     * @returns {Promise<object>} { confirmed, photos, not_confirmed }
     */
    async confirmPhotos(eventId, photos) {
      return request(`/api/admin/events/${eventId}/lostfound/photos/confirm`, {
        method: 'POST',
        body: JSON.stringify({ photos }),
      }, true)
    },

    /**
     * Set or clear one photo's caption (max 200 characters).
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @param {string|null} caption - Caption, or null to clear it
     * @returns {Promise<object>} Updated photo object
     */
    async updatePhoto(eventId, photoId, caption) {
      return request(`/api/admin/events/${eventId}/lostfound/photos/${photoId}`, {
        method: 'PATCH',
        body: JSON.stringify({ caption }),
      }, true)
    },

    /**
     * Delete one photo (row plus both S3 objects). Its number stays retired —
     * a guest answering a three-day-old mail still means the old number 14.
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @returns {Promise<void>}
     */
    async deletePhoto(eventId, photoId) {
      return request(`/api/admin/events/${eventId}/lostfound/photos/${photoId}`, {
        method: 'DELETE',
      }, true)
    },
  },

  // -------------------------------------------------------------- Eventfotos
  // Spec 024 — one collection per event, SINGLE and FESTIVAL alike. The mirror
  // image of `lostFound` above: there the public direction is reading, here it
  // is writing, and none of it is shared — not the token, not the bucket, not
  // the retention screw.
  eventPhotos: {
    /**
     * The collection's configuration plus the effective retention window.
     *
     * **404 means „no collection yet"** (unlike `lostFound.get`, which answers
     * `configured: false`), and so does `listPhotos` — one 404 drives both the
     * empty form and the empty grid. A fresh form therefore has no
     * server-provided default for `retention_days`; send `null` to mean
     * „environment default" on the first save.
     *
     * `public_url` comes assembled — it is the string the QR code encodes, and
     * rebuilding it in the frontend is how the printed sheet and the backend
     * drift apart. `upload_open` is the stored switch, `window_open` the
     * computed state; they are two fields on purpose.
     *
     * @param {string} eventId - Event ID
     * @returns {Promise<object>} Config, counts and `limits`
     */
    async getConfig(eventId) {
      return request(`/api/admin/events/${eventId}/photos/config`, {}, true)
    },

    /**
     * Create or update the collection. The first call mints the upload token,
     * and it needs a contact — without a mail address or a Telegram link
     * there is no first save (400 `contact_required`), because a page where
     * guests hand in photos of other people must say whom to ask to get one
     * removed. The last remaining contact cannot be cleared either.
     *
     * @param {string} eventId - Event ID
     * @param {object} patch - { contact_email, contact_telegram_url, contact_name,
     *   intro_text, upload_open, closes_at, retention_days } — all optional,
     *   unknown keys are rejected by the backend
     * @returns {Promise<object>} Config response
     */
    async saveConfig(eventId, patch) {
      return request(`/api/admin/events/${eventId}/photos/config`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      }, true)
    },

    /**
     * Fresh upload token — the emergency brake. Every printed sheet and every
     * link already shared stops working; the photos already in the collection
     * stay.
     * @param {string} eventId - Event ID
     * @returns {Promise<object>} Config response with the new public URL
     */
    async rotateToken(eventId) {
      return request(`/api/admin/events/${eventId}/photos/rotate-token`, {
        method: 'POST',
      }, true)
    },

    /**
     * One page of READY photos, each with two presigned GETs (15 minutes).
     *
     * Sort and day-group by **`taken_at`** — the backend has already applied
     * the plausibility rule to `captured_at_hint` and fallen back to
     * `uploaded_at`; re-deriving that in JS gives a second, differing answer.
     *
     * PENDING rows are not in `photos`, only in `pending_count`: here the
     * uploader is a guest, so a broken tile is one nobody in this view could
     * ever fix. The 24 h sweep clears them.
     *
     * @param {string} eventId - Event ID
     * @param {object} [query]
     * @param {string} [query.filter] - 'all' | 'starred' | 'unedited'
     * @param {number} [query.offset] - Skip this many (default 0)
     * @param {number} [query.limit] - Page size 1..500 (default 120)
     * @returns {Promise<object>} { photos, total, offset, limit, pending_count,
     *   url_ttl_seconds }
     */
    async listPhotos(eventId, { filter = 'all', offset = 0, limit = 120 } = {}) {
      const params = new URLSearchParams({
        filter,
        offset: String(offset),
        limit: String(limit),
      })
      return request(`/api/admin/events/${eventId}/photos?${params}`, {}, true)
    },

    /**
     * Set the star and/or the organiser's note on one photo. An absent or
     * `null` field is left alone, `note: ''` clears it — so a star toggle
     * sends only `starred` and cannot wipe a note by omission.
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @param {object} patch - { starred?, note? } (max 300 characters)
     * @returns {Promise<object>} Updated photo object
     */
    async patchPhoto(eventId, photoId, patch) {
      return request(`/api/admin/events/${eventId}/photos/${photoId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }, true)
    },

    /**
     * Delete one photo: the row plus both S3 objects. No number is retired
     * because none was ever handed out — nobody quotes a photo in a mail.
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @returns {Promise<void>}
     */
    async deletePhoto(eventId, photoId) {
      return request(`/api/admin/events/${eventId}/photos/${photoId}`, {
        method: 'DELETE',
      }, true)
    },

    /**
     * Delete a selection — deleting 300 photos one by one is not a tool.
     *
     * Chunked at `BULK_DELETE_CHUNK`, because the endpoint caps `photo_ids` at
     * 500 and „Alle sichtbaren" has no cap of its own: six taps of „Mehr laden"
     * put 720 ids in the selection, and a single request with all of them is
     * refused by pydantic before the handler runs. That failure deletes nothing
     * and surfaces as a raw English validation message, on the one action an
     * organiser reaches for when they want a collection of strangers' faces
     * gone. So the cap is a client-side concern here, not a user-facing one.
     *
     * Idempotent and never a 404: an id that is already gone simply does not
     * count towards `deleted`. `completed: false` means the request ran out of
     * time, not that something failed, so each chunk repeats until it is done
     * and the counts are accumulated over all of them (same pattern as
     * `deletePage` below).
     *
     * @param {string} eventId - Event ID
     * @param {Array<string>} photoIds - Photo IDs
     * @returns {Promise<object>} { requested, deleted, completed, passes }
     */
    async bulkDelete(eventId, photoIds) {
      // Mirrors `_MAX_BULK_DELETE` in api/admin/event_photos.py.
      const BULK_DELETE_CHUNK = 500
      const MAX_PASSES = 20
      let deleted = 0
      let passes = 0

      for (let start = 0; start < photoIds.length; start += BULK_DELETE_CHUNK) {
        const chunk = photoIds.slice(start, start + BULK_DELETE_CHUNK)
        let done = false

        for (let pass = 1; pass <= MAX_PASSES; pass++) {
          const result = await request(`/api/admin/events/${eventId}/photos/bulk-delete`, {
            method: 'POST',
            body: JSON.stringify({ photo_ids: chunk }),
          }, true)

          deleted += result.deleted
          passes += 1
          if (result.completed) {
            done = true
            break
          }
          // An unfinished pass that deleted nothing is stuck, not slow.
          if (result.deleted === 0) {
            throw new Error('Löschen kommt nicht voran — bitte erneut versuchen.')
          }
        }

        if (!done) {
          throw new Error(
            'Die Auswahl ist noch nicht vollständig gelöscht — bitte erneut starten, ' +
            `bereits entfernt: ${deleted} Fotos.`,
          )
        }
      }

      return { requested: photoIds.length, deleted, completed: true, passes }
    },

    /**
     * Two fresh presigned POSTs for the same keys, to overwrite `full` and
     * `thumb` with the pixelated version.
     *
     * Both, always: a thumbnail with an untouched face would undo the whole
     * exercise. The bucket is unversioned, so this is final — which is what
     * the button promises.
     *
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @returns {Promise<object>} { photo_id, full, thumb }
     */
    async createEditUploads(eventId, photoId) {
      return request(`/api/admin/events/${eventId}/photos/${photoId}/edit-uploads`, {
        method: 'POST',
      }, true)
    },

    /**
     * Record the edit: sets `edited_at` and the new dimensions. Call this only
     * once **both** variants are on S3 — a row marked edited whose thumb is
     * still the original is the one lie this feature cannot afford.
     * @param {string} eventId - Event ID
     * @param {string} photoId - Photo ID
     * @param {object} dimensions - { width, height, bytes } of the new `full`
     * @returns {Promise<object>} Updated photo object
     */
    async confirmEdit(eventId, photoId, dimensions) {
      return request(`/api/admin/events/${eventId}/photos/${photoId}/edit-confirm`, {
        method: 'POST',
        body: JSON.stringify(dimensions),
      }, true)
    },

    /**
     * The download list: one presigned GET per photo, valid an hour.
     *
     * Fetched with a bearer token rather than linked to, so there is no URL
     * helper for it — and read as text, because `request()` parses JSON. No
     * ZIP: API Gateway caps a response at 10 MB and cuts at 29 s, and a
     * collection is two orders of magnitude above that.
     *
     * Returns the one-liner the file itself carries. Show *that* string, do
     * not compose your own: the printed command has to skip the `#` header
     * lines, or `xargs` hands them to curl as URLs.
     *
     * @param {string} eventId - Event ID
     * @param {string} [filter] - 'all' | 'starred'
     * @returns {Promise<object>} { text, filename, urls, oneliner }
     */
    async fetchManifest(eventId, filter = 'all') {
      const token = await getAccessToken()
      const url =
        `${API_BASE_URL}/api/admin/events/${eventId}/photos/download-manifest?filter=${filter}`
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })
      if (!response.ok) {
        const err = new Error(`Downloadliste fehlgeschlagen (${response.status})`)
        err.status = response.status
        throw err
      }

      const text = await response.text()
      const disposition = response.headers.get('Content-Disposition')
      const match = disposition && disposition.match(/filename="?([^"]+)"?/)
      const lines = text.split('\n').map(line => line.trim()).filter(Boolean)

      return {
        text,
        filename: match ? match[1] : `fotos-${eventId}.txt`,
        urls: lines.filter(line => !line.startsWith('#')),
        // The header line that contains the command, minus its comment marker.
        oneliner: (lines.find(line => line.startsWith('#') && line.includes('curl')) || '')
          .replace(/^#\s*/, ''),
      }
    },

    /**
     * Fetch the manifest and hand it to the browser as a file, in one
     * round-trip — a second call would mint a second set of signatures for
     * nothing. Returns the same object as `fetchManifest`, so the page can
     * print the one-liner next to the saved file.
     * @param {string} eventId - Event ID
     * @param {string} [filter] - 'all' | 'starred'
     * @returns {Promise<object>} { text, filename, urls, oneliner }
     */
    async downloadManifest(eventId, filter = 'all') {
      // Through `adminApi`, not `this`: a page that destructures this block
      // („const { downloadManifest } = adminApi.eventPhotos“) would otherwise
      // call it with an undefined receiver.
      const manifest = await adminApi.eventPhotos.fetchManifest(eventId, filter)
      const blob = new Blob([manifest.text], { type: 'text/plain;charset=utf-8' })
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = manifest.filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(downloadUrl)
      return manifest
    },

    /**
     * Delete the whole collection: config, every row, every S3 object.
     *
     * Two thousand photos do not fit in one request — the backend deletes what
     * it can and answers `completed: false`, so this repeats until the
     * collection is gone and reports the accumulated count (same pattern as
     * `lostFound.deletePage` and `adminApi.anonymizeEvent`). Every pass is
     * idempotent, and a `completed: false` deliberately blocks deleting the
     * event rather than leaving orphaned objects in the bucket.
     *
     * @param {string} eventId - Event ID
     * @param {object} [options]
     * @param {(progress: {photos: number, pass: number}) => void} [options.onProgress]
     * @returns {Promise<object>} { photos, completed, passes }
     */
    async deleteCollection(eventId, { onProgress } = {}) {
      const MAX_PASSES = 40
      let photos = 0
      let result

      for (let pass = 1; pass <= MAX_PASSES; pass++) {
        result = await request(`/api/admin/events/${eventId}/photos`, {
          method: 'DELETE',
        }, true)

        photos += result.photos
        if (onProgress) onProgress({ photos, pass })

        if (result.completed) {
          return { ...result, photos, passes: pass }
        }
        // An unfinished pass that deleted nothing is stuck, not slow.
        if (result.photos === 0) {
          throw new Error('Löschen kommt nicht voran — bitte erneut versuchen.')
        }
      }

      throw new Error(
        'Die Sammlung ist noch nicht vollständig gelöscht — bitte erneut starten, ' +
        `bereits entfernt: ${photos} Fotos.`,
      )
    },
  },

  // ---------------------------------------------------------------- Festival
  festival: {
    async createEvent(data) {
      return request('/api/admin/festival/events', {
        method: 'POST',
        body: JSON.stringify(data),
      }, true)
    },
    async listEvents() {
      return request('/api/admin/festival/events', {}, true)
    },
    async getEvent(eventId) {
      return request(`/api/admin/festival/${eventId}`, {}, true)
    },
    async updateEvent(eventId, data) {
      return request(`/api/admin/festival/${eventId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }, true)
    },
    async deleteEvent(eventId) {
      return request(`/api/admin/festival/${eventId}`, {
        method: 'DELETE',
      }, true)
    },
    async setStatus(eventId, status) {
      return request(`/api/admin/festival/${eventId}/status`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      }, true)
    },
    async createInvites(eventId, batch) {
      return request(`/api/admin/festival/${eventId}/invites`, {
        method: 'POST',
        body: JSON.stringify(batch),
      }, true)
    },
    async listInvites(eventId) {
      return request(`/api/admin/festival/${eventId}/invites`, {}, true)
    },
    async patchInvite(eventId, inviteId, patch) {
      return request(`/api/admin/festival/${eventId}/invites/${inviteId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }, true)
    },
    async sendInviteEmail(eventId, inviteId) {
      return request(`/api/admin/festival/${eventId}/invites/${inviteId}/send-email`, {
        method: 'POST',
      }, true)
    },
    async markInviteSent(eventId, inviteId) {
      return request(`/api/admin/festival/${eventId}/invites/${inviteId}/mark-sent`, {
        method: 'POST',
      }, true)
    },

    /**
     * Export the printable gate list as CSV (Ä9 floor).
     * @param {string} eventId - Festival event ID
     * @returns {Promise<void>} Triggers file download
     */
    async exportGateCsv(eventId) {
      return downloadFestivalCsv(eventId, 'gate')
    },

    /**
     * Slot x tier headcount board (T201/T202).
     * @param {string} eventId - Festival event ID
     * @returns {Promise<object>} Headcount board payload
     */
    async headcount(eventId) {
      return request(`/api/admin/festival/${eventId}/headcount`, {}, true)
    },

    /**
     * List festival registrations for the admin registrations page (T203).
     * @param {string} eventId - Festival event ID
     * @param {object} [opts] - { status, search }
     * @returns {Promise<object>} { items, total }
     */
    async listRegistrations(eventId, { status, search } = {}) {
      const params = new URLSearchParams()
      if (status) params.append('status_filter', status)
      if (search) params.append('search', search)
      const query = params.toString() ? `?${params.toString()}` : ''
      return request(`/api/admin/festival/${eventId}/registrations${query}`, {}, true)
    },

    /**
     * Admin cancel for a festival registration (T203).
     * @param {string} eventId - Festival event ID
     * @param {string} registrationId - Registration ID
     * @returns {Promise<object>} Cancelled registration
     */
    async cancelRegistration(eventId, registrationId) {
      return request(`/api/admin/festival/${eventId}/registrations/${registrationId}/cancel`, {
        method: 'POST',
      }, true)
    },

    /**
     * Partial update of a festival registration (T205) — reuses the
     * existing spec-018 admin-update route (same registrations resource,
     * festival events included); shares its 409-conflict handling
     * (`err.status === 409`, `err.data`) rather than duplicating it.
     * @param {string} eventId - Festival event ID
     * @param {string} registrationId - Registration ID
     * @param {object} patch - Partial registration update
     * @returns {Promise<object>} Updated registration
     */
    async updateRegistration(eventId, registrationId, patch) {
      return adminApi.updateAdminRegistration(eventId, registrationId, patch)
    },

    /**
     * Mail every approved-but-not-yet-notified overnight group (F8 catch-up).
     * Idempotent — already-notified groups are skipped server-side, so a
     * second press mails nobody twice.
     * @param {string} eventId - Festival event ID
     * @returns {Promise<object>} { sent, skipped, failed }
     */
    async notifyOvernightApprovals(eventId) {
      return request(`/api/admin/festival/${eventId}/overnight-notifications`, {
        method: 'POST',
      }, true)
    },

    /**
     * Get (lazily generating) the scanner gate link (T303).
     * @param {string} eventId - Festival event ID
     * @returns {Promise<object>} { gate_url }
     */
    async getGateToken(eventId) {
      return request(`/api/admin/festival/${eventId}/gate-token`, {}, true)
    },

    /**
     * Rotate the scanner gate link — the old link dies immediately (T303).
     * @param {string} eventId - Festival event ID
     * @returns {Promise<object>} { gate_url }
     */
    async rotateGateToken(eventId) {
      return request(`/api/admin/festival/${eventId}/gate-token/rotate`, {
        method: 'POST',
      }, true)
    },
  },
}

export default { publicApi, adminApi }
