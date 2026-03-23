<template>
  <div v-if="loading" aria-busy="true">
    Anmeldungen werden geladen...
  </div>

  <div v-else-if="error" role="alert" class="error">
    {{ error }}
  </div>

  <template v-else>
    <p v-if="registrations.length === 0">
      Noch keine Anmeldungen für diese Veranstaltung.
    </p>

    <template v-else>
      <!-- Filters -->
      <div class="filters">
        <input
          v-model="searchTerm"
          type="search"
          placeholder="Name oder E-Mail suchen..."
          class="search-input"
        />
        <select v-model="statusFilter" class="status-filter">
          <option value="">Alle</option>
          <option value="REGISTERED">Angemeldet</option>
          <option value="CONFIRMED">Bestätigung ausstehend</option>
          <option value="PARTICIPATING">Nimmt teil</option>
          <option value="WAITLISTED">Warteliste</option>
          <option value="CANCELLED">Abgesagt</option>
          <option value="CHECKED_IN">Eingecheckt</option>
          <option value="PROMOTED">Bevorzugt</option>
        </select>
      </div>

      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>E-Mail</th>
            <th>Personen</th>
            <th>Status</th>
            <th v-if="showPromotedColumn">Bevorzugt</th>
            <th>Angemeldet am</th>
            <th v-if="showActions">Aktionen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="reg in filteredRegistrations" :key="reg.id">
            <td>{{ reg.name }}</td>
            <td><a :href="`mailto:${reg.email}`">{{ reg.email }}</a></td>
            <td>{{ reg.group_size }}</td>
            <td>
              <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                {{ formatStatus(reg.status) }}
                <template v-if="reg.status === 'WAITLISTED' && reg.waitlist_position">
                  (#{{ reg.waitlist_position }})
                </template>
              </span>
            </td>
            <td v-if="showPromotedColumn">
              <template v-if="isPromotedEditable">
                <label class="promoted-toggle" :title="'Garantierte Teilnahme bei der Verlosung'">
                  <input
                    type="checkbox"
                    role="switch"
                    :checked="reg.promoted"
                    :disabled="togglingId === reg.id"
                    @change="$emit('toggle-promoted', { registrationId: reg.id, promoted: !reg.promoted })"
                  />
                </label>
              </template>
              <template v-else>
                <span v-if="reg.promoted" class="promoted-badge" title="Bevorzugt">★</span>
              </template>
            </td>
            <td>{{ formatDate(reg.registered_at) }}</td>
            <td v-if="showActions">
              <template v-if="reg.status === 'WAITLISTED' && eventStatus === 'CONFIRMED'">
                <div class="promote-actions">
                  <button
                    class="small-button"
                    @click="$emit('promote-waitlisted', { registrationId: reg.id, targetStatus: 'CONFIRMED' })"
                  >
                    Nachrücken
                  </button>
                  <button
                    class="small-button secondary"
                    @click="$emit('promote-waitlisted', { registrationId: reg.id, targetStatus: 'PARTICIPATING' })"
                    title="Direkt als teilnehmend markieren"
                  >
                    Direkt
                  </button>
                </div>
              </template>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="total-info">
        Gesamt: {{ filteredRegistrations.length }} Anmeldung(en),
        {{ filteredRegistrations.reduce((sum, r) => sum + r.group_size, 0) }} Platz/Plätze
        <template v-if="filteredRegistrations.length !== registrations.length">
          ({{ registrations.length }} insgesamt)
        </template>
      </p>
    </template>

    <!-- Attendance summary for CONFIRMED events -->
    <div v-if="['CONFIRMED', 'COMPLETED'].includes(eventStatus)" class="confirmation-summary">
      <strong>Teilnahmestatus:</strong>
      <span class="confirmation-stat yes">
        {{ registrations.filter(r => r.status === 'PARTICIPATING').length }} bestätigt
      </span>
      <span class="confirmation-stat no">
        {{ registrations.filter(r => r.status === 'CANCELLED').length }} abgesagt
      </span>
      <span class="confirmation-stat pending">
        {{ registrations.filter(r => r.status === 'CONFIRMED').length }} ausstehend
      </span>
    </div>
  </template>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  registrations: { type: Array, required: true },
  eventStatus: { type: String, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  togglingId: { type: String, default: null },
})

defineEmits(['toggle-promoted', 'promote-waitlisted'])

const searchTerm = ref('')
const statusFilter = ref('')

const showPromotedColumn = computed(() => {
  return ['OPEN', 'REGISTRATION_CLOSED', 'LOTTERY_PENDING', 'CONFIRMED', 'COMPLETED'].includes(props.eventStatus)
})

const isPromotedEditable = computed(() => {
  return ['OPEN', 'REGISTRATION_CLOSED'].includes(props.eventStatus)
})

const showActions = computed(() => {
  return props.eventStatus === 'CONFIRMED'
    && props.registrations.some(r => r.status === 'WAITLISTED')
})

const filteredRegistrations = computed(() => {
  let result = props.registrations

  // Status filter
  if (statusFilter.value === 'PROMOTED') {
    result = result.filter(r => r.promoted)
  } else if (statusFilter.value) {
    result = result.filter(r => r.status === statusFilter.value)
  }

  // Search filter
  if (searchTerm.value) {
    const term = searchTerm.value.toLowerCase()
    result = result.filter(r =>
      r.name.toLowerCase().includes(term) || r.email.toLowerCase().includes(term)
    )
  }

  return result
})

function formatDate(dateStr) {
  if (!dateStr) return 'Noch offen'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatStatus(status) {
  const statusLabels = {
    'REGISTERED': 'Angemeldet',
    'CONFIRMED': 'Bestätigung ausstehend',
    'PARTICIPATING': 'Nimmt teil',
    'WAITLISTED': 'Warteliste',
    'CANCELLED': 'Abgesagt',
    'CHECKED_IN': 'Eingecheckt',
  }
  return statusLabels[status] || status
}
</script>

<style scoped>
.filters {
  display: flex;
  gap: 1rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.search-input {
  flex: 1;
  min-width: 200px;
}

.status-filter {
  min-width: 180px;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.75rem;
  font-weight: bold;
  text-transform: uppercase;
}

.status-registered { background: #e0e7ff; color: #4f46e5; }
.status-confirmed { background: #fef3c7; color: #d97706; }
.status-participating { background: #dcfce7; color: #16a34a; }
.status-waitlisted { background: #e5e7eb; color: #6b7280; }
.status-cancelled { background: #fee2e2; color: #dc2626; }
.status-checked_in { background: #dbeafe; color: #2563eb; }

.promoted-toggle {
  margin: 0;
}

.promoted-toggle input[type="checkbox"] {
  margin: 0;
}

.promoted-badge {
  color: #d97706;
  font-size: 1.2rem;
}

.promote-actions {
  display: flex;
  gap: 0.25rem;
}

.small-button {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  margin: 0;
  white-space: nowrap;
}

.small-button.secondary {
  background: transparent;
  border: 1px solid var(--pico-muted-border-color);
  color: var(--pico-muted-color);
}

.total-info {
  margin-top: 1rem;
  font-size: 0.875rem;
  color: var(--pico-muted-color);
}

.confirmation-summary {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  font-size: 0.875rem;
  color: #334155;
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
}

.confirmation-stat {
  padding: 0.25rem 0.5rem;
  border-radius: var(--pico-border-radius);
  font-weight: 500;
}

.confirmation-stat.yes { background: #dcfce7; color: #16a34a; }
.confirmation-stat.no { background: #fee2e2; color: #dc2626; }
.confirmation-stat.pending { background: #fef3c7; color: #d97706; }

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}
</style>
