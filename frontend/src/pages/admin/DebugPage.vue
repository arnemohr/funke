<template>
  <article class="debug-page">
    <header>
      <h2>Debug: Alle Veranstaltungen & Anmeldungen</h2>
      <button @click="loadAllData" :disabled="loading" class="small">
        {{ loading ? 'Lädt...' : 'Aktualisieren' }}
      </button>
    </header>

    <details class="flow-explanation">
      <summary>Anleitung: So funktioniert der Flow</summary>
      <div class="flow-content">
        <h4>Registrierungsflow</h4>
        <ol>
          <li><strong>Event erstellen</strong> → Status: DRAFT</li>
          <li><strong>Veröffentlichen</strong> → Status: OPEN, Registrierungslink aktiv</li>
          <li><strong>Nutzer registriert sich</strong> → Anmeldung: REGISTERED oder WAITLISTED</li>
          <li><strong>Anmeldung schließen</strong> → Status: REGISTRATION_CLOSED</li>
          <li><strong>Verlosung durchführen</strong> → Gewinner: CONFIRMED, Rest: WAITLISTED</li>
        </ol>

        <h4>Bestätigungsflow (X Tage vor Event)</h4>
        <ol>
          <li>System sendet Erinnerungsmail mit Bestätigungslinks</li>
          <li><strong>Nutzer klickt "Ja"</strong> → CONFIRMED → PARTICIPATING</li>
          <li><strong>Nutzer klickt "Nein"</strong> → CONFIRMED → CANCELLED (Platz frei für Warteliste)</li>
        </ol>

        <h4>Debug-Aktionen pro Anmeldung</h4>
        <table class="mini-table">
          <tr><td class="action-link manage">🔗</td><td>Anmeldung verwalten (öffnet Management-Seite)</td></tr>
        </table>

        <p class="tip">
          <strong>Tipp:</strong> Links öffnen in neuem Tab. Bei Rückkehr zu diesem Tab wird automatisch aktualisiert.
        </p>
      </div>
    </details>

    <div v-if="loading && events.length === 0" aria-busy="true">
      Daten werden geladen...
    </div>

    <div v-else-if="error" role="alert" class="error">
      {{ error }}
    </div>

    <div v-else-if="events.length === 0" class="empty">
      Keine Veranstaltungen vorhanden.
    </div>

    <div v-else class="events-list">
      <div v-for="event in events" :key="event.id" class="event-card">
        <header @click="toggleEvent(event.id)" class="event-header">
          <div class="event-toggle">
            <span class="toggle-icon">{{ expandedEvents.has(event.id) ? '▼' : '▶' }}</span>
            <strong>{{ event.name }}</strong>
          </div>
          <div class="event-meta">
            <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
              {{ event.status }}
            </span>
            <span>{{ formatDate(event.start_at) }}</span>
            <span>{{ event.registration_spots }} ({{ event.registration_count }}) · {{ event.confirmed_spots }}/{{ event.capacity }} Best (+{{ event.waitlist_spots }} WL)</span>
          </div>
        </header>

        <div v-if="expandedEvents.has(event.id)" class="event-content">
          <!-- Event-level actions -->
          <div class="event-actions">
            <span class="label">Registrierungslink:</span>
            <template v-if="event.registration_link_token && !['DRAFT', 'COMPLETED', 'CANCELLED'].includes(event.status)">
              <a :href="getRegistrationUrl(event)" target="_blank" class="link">
                {{ getRegistrationUrl(event) }}
              </a>
              <button @click="copyToClipboard(getRegistrationUrl(event))" class="tiny">📋</button>
              <span v-if="event.status !== 'OPEN'" class="muted">(Warteliste)</span>
            </template>
            <span v-else class="muted">Nicht verfügbar (Status: {{ event.status }})</span>
          </div>

          <!-- Registrations table -->
          <div v-if="loadingRegistrations.has(event.id)" aria-busy="true" class="loading-small">
            Anmeldungen werden geladen...
          </div>

          <div v-else-if="!registrationsByEvent[event.id] || registrationsByEvent[event.id].length === 0" class="empty-small">
            Keine Anmeldungen.
          </div>

          <table v-else class="registrations-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>E-Mail</th>
                <th>Kontakt</th>
                <th>Gr.</th>
                <th>Status</th>
                <th>#</th>
                <th>Angemeldet</th>
                <th>Beantwortet</th>
                <th>Nachger.</th>
                <th>Notizen</th>
                <th>Aktionen</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="reg in registrationsByEvent[event.id]" :key="reg.id">
                <td>{{ reg.name }}</td>
                <td class="mono"><a :href="`mailto:${reg.email}`">{{ reg.email }}</a></td>
                <td class="contact-cell">
                  <template v-if="reg.phone">
                    <span class="phone-number">{{ reg.phone }}</span>
                    <a :href="`tel:${reg.phone}`" class="contact-link phone" title="Anrufen">📞</a>
                    <a :href="getTelegramUrl(reg.phone)" target="_blank" class="contact-link telegram" title="Telegram">💬</a>
                  </template>
                  <span v-else>-</span>
                </td>
                <td>{{ reg.group_size }}</td>
                <td>
                  <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                    {{ reg.status }}
                  </span>
                </td>
                <td>{{ reg.waitlist_position || '-' }}</td>
                <td>{{ formatDateTime(reg.registered_at) }}</td>
                <td>{{ reg.responded_at ? formatDateTime(reg.responded_at) : '-' }}</td>
                <td>{{ reg.promoted_from_waitlist ? '✓' : '-' }}</td>
                <td class="notes-cell">{{ reg.notes || '-' }}</td>
                <td class="actions-cell">
                  <!-- Management page link -->
                  <a
                    :href="getManageUrl(reg)"
                    target="_blank"
                    class="action-link manage"
                    title="Anmeldung verwalten"
                  >🔗</a>

                  <span v-if="reg.status === 'CANCELLED'" class="muted">storniert</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { adminApi } from '../../services/api'

const loading = ref(true)
const error = ref(null)
const events = ref([])
const expandedEvents = ref(new Set())
const loadingRegistrations = ref(new Set())
const registrationsByEvent = reactive({})

// Format date for display
function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

// Format datetime for display
function formatDateTime(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Get registration URL for an event
function getRegistrationUrl(event) {
  return `${window.location.origin}/register/${event.registration_link_token}`
}

// Get management page URL for a registration
function getManageUrl(reg) {
  return `${window.location.origin}/registration/${reg.id}?token=${reg.registration_token}`
}

// Get Telegram URL for a phone number
function getTelegramUrl(phone) {
  // Clean phone number: remove spaces, dashes, parentheses
  const cleaned = phone.replace(/[\s\-\(\)]/g, '')
  // Telegram expects format: https://t.me/+49123456789
  return `https://t.me/${cleaned}`
}

// Copy to clipboard
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert('Link kopiert!')
  }).catch(() => {
    prompt('Link kopieren:', text)
  })
}

// Toggle event expansion
async function toggleEvent(eventId) {
  if (expandedEvents.value.has(eventId)) {
    expandedEvents.value.delete(eventId)
    expandedEvents.value = new Set(expandedEvents.value)
  } else {
    expandedEvents.value.add(eventId)
    expandedEvents.value = new Set(expandedEvents.value)

    // Load registrations if not already loaded
    if (!registrationsByEvent[eventId]) {
      await loadRegistrations(eventId)
    }
  }
}

// Load registrations for an event
async function loadRegistrations(eventId) {
  loadingRegistrations.value.add(eventId)
  loadingRegistrations.value = new Set(loadingRegistrations.value)

  try {
    const result = await adminApi.listRegistrations(eventId)
    registrationsByEvent[eventId] = result.items
  } catch (err) {
    console.error('Failed to load registrations:', err)
    registrationsByEvent[eventId] = []
  } finally {
    loadingRegistrations.value.delete(eventId)
    loadingRegistrations.value = new Set(loadingRegistrations.value)
  }
}

// Load all data
async function loadAllData() {
  loading.value = true
  error.value = null

  try {
    const result = await adminApi.listEvents()
    events.value = result.items

    // Reload registrations for expanded events
    for (const eventId of expandedEvents.value) {
      await loadRegistrations(eventId)
    }
  } catch (err) {
    error.value = err.message || 'Daten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
}

// Auto-refresh when tab becomes visible (after clicking action links)
function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    loadAllData()
  }
}

onMounted(() => {
  loadAllData()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.debug-page {
  font-size: 0.85rem;
}

.flow-explanation {
  margin-bottom: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  background: #f8fafc;
}

.flow-explanation summary {
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.8rem;
  color: #475569;
}

.flow-explanation summary:hover {
  background: #f1f5f9;
}

.flow-content {
  padding: 0.75rem;
  border-top: 1px solid #e2e8f0;
  font-size: 0.75rem;
}

.flow-content h4 {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  color: #334155;
}

.flow-content h4:not(:first-child) {
  margin-top: 1rem;
}

.flow-content ol {
  margin: 0 0 0.5rem;
  padding-left: 1.25rem;
}

.flow-content li {
  margin-bottom: 0.25rem;
}

.mini-table {
  margin: 0.5rem 0;
  font-size: 0.75rem;
}

.mini-table td {
  padding: 0.2rem 0.5rem;
  border: none;
}

.mini-table td:first-child {
  width: 1.5rem;
  text-align: center;
}

.tip {
  margin: 0.75rem 0 0;
  padding: 0.5rem;
  background: #fef3c7;
  border-radius: 3px;
  font-size: 0.7rem;
  color: #92400e;
}

.debug-page header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
}

.debug-page h2 {
  margin: 0;
  font-size: 1.25rem;
}

.muted {
  color: var(--pico-muted-color);
  font-size: 0.8rem;
}

button.small {
  padding: 0.25rem 0.75rem;
  font-size: 0.8rem;
}

button.tiny {
  padding: 0.15rem 0.4rem;
  font-size: 0.7rem;
  margin-left: 0.25rem;
}

.error {
  color: #dc2626;
  padding: 0.75rem;
  background: #fef2f2;
  border-radius: var(--pico-border-radius);
}

.empty, .empty-small {
  color: var(--pico-muted-color);
  padding: 1rem;
  text-align: center;
}

.empty-small {
  padding: 0.5rem;
  font-size: 0.8rem;
}

.loading-small {
  padding: 0.5rem;
  font-size: 0.8rem;
}

.events-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.event-card {
  border: 1px solid var(--pico-muted-border-color, #e2e8f0);
  border-radius: var(--pico-border-radius);
  background: white;
  overflow: hidden;
}

.event-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: #f8fafc;
  cursor: pointer;
  gap: 1rem;
  flex-wrap: wrap;
}

.event-header:hover {
  background: #f1f5f9;
}

.event-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.toggle-icon {
  font-size: 0.7rem;
  width: 1rem;
}

.event-meta {
  display: flex;
  gap: 1rem;
  align-items: center;
  font-size: 0.8rem;
}

.event-content {
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--pico-muted-border-color, #e2e8f0);
}

.event-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  font-size: 0.8rem;
  flex-wrap: wrap;
}

.event-actions .label {
  font-weight: 600;
}

.event-actions .link {
  word-break: break-all;
  font-size: 0.75rem;
}

.registrations-table {
  width: 100%;
  font-size: 0.75rem;
  border-collapse: collapse;
}

.registrations-table th,
.registrations-table td {
  padding: 0.35rem 0.5rem;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}

.registrations-table th {
  background: #f1f5f9;
  font-weight: 600;
  font-size: 0.7rem;
  text-transform: uppercase;
}

.registrations-table .mono {
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  font-size: 0.7rem;
}

.registrations-table .notes-cell {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions-cell {
  display: flex;
  gap: 0.35rem;
}

.contact-cell {
  display: flex;
  gap: 0.25rem;
  align-items: center;
}

.phone-number {
  font-size: 0.7rem;
  margin-right: 0.25rem;
}

.contact-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 3px;
  text-decoration: none;
  font-size: 0.75rem;
}

.contact-link.phone {
  background: #dbeafe;
}

.contact-link.phone:hover {
  background: #bfdbfe;
}

.contact-link.telegram {
  background: #e0f2fe;
}

.contact-link.telegram:hover {
  background: #bae6fd;
}

.action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 3px;
  text-decoration: none;
  font-size: 0.8rem;
  font-weight: bold;
}

.action-link.manage {
  background: #dbeafe;
  color: #2563eb;
}

.action-link.manage:hover {
  background: #bfdbfe;
}

/* Status badges */
.status-badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
}

.status-draft {
  background: #e2e8f0;
  color: #64748b;
}

.status-open {
  background: #dcfce7;
  color: #16a34a;
}

.status-registration_closed {
  background: #fef3c7;
  color: #d97706;
}

.status-lottery_pending {
  background: #ede9fe;
  color: #7c3aed;
}

.status-confirmed {
  background: #fef3c7;
  color: #d97706;
}

.status-completed {
  background: #dbeafe;
  color: #2563eb;
}

.status-cancelled {
  background: #fee2e2;
  color: #dc2626;
}

.status-registered {
  background: #e0e7ff;
  color: #4f46e5;
}

.status-participating {
  background: #dcfce7;
  color: #16a34a;
}

.status-waitlisted {
  background: #e5e7eb;
  color: #6b7280;
}

.status-checked_in {
  background: #dbeafe;
  color: #2563eb;
}
</style>
