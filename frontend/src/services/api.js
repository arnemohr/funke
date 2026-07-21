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
