/**
 * API service for communicating with the backend.
 */
import { useAuth0 } from '@auth0/auth0-vue'

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
    const { getAccessTokenSilently } = useAuth0()
    cachedToken = await getAccessTokenSilently()
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
      const { loginWithRedirect } = useAuth0()
      await loginWithRedirect({ appState: { targetUrl: window.location.pathname } })
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
    let errorMessage = `Request failed with status ${response.status}`
    try {
      const errorData = await response.json()
      // Handle FastAPI validation errors (detail is array) and regular errors (detail is string)
      if (Array.isArray(errorData.detail)) {
        errorMessage = errorData.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
      } else {
        errorMessage = errorData.detail || errorMessage
      }
      console.error('API Error:', errorData)
    } catch {
      // Ignore JSON parse errors
    }
    throw new Error(errorMessage)
  }

  // Handle empty responses
  const text = await response.text()
  return text ? JSON.parse(text) : null
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
   * @param {object} data - Registration data
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
   * Export registrations as CSV.
   * @param {string} eventId - Event ID
   * @returns {Promise<void>} Triggers file download
   */
  async exportRegistrationsCsv(eventId) {
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
    // Extract filename from Content-Disposition header or use default
    const disposition = response.headers.get('Content-Disposition')
    const match = disposition && disposition.match(/filename="?([^"]+)"?/)
    a.download = match ? match[1] : `registrations_${eventId}.csv`
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
}

export default { publicApi, adminApi }
