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

    <table v-else>
      <thead>
        <tr>
          <th>Name</th>
          <th>E-Mail</th>
          <th>Personen</th>
          <th>Status</th>
          <th>Angemeldet am</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="reg in registrations" :key="reg.id">
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
          <td>{{ formatDate(reg.registered_at) }}</td>
        </tr>
      </tbody>
    </table>

    <p class="total-info">
      Gesamt: {{ registrations.length }} Anmeldung(en),
      {{ registrations.reduce((sum, r) => sum + r.group_size, 0) }} Platz/Plätze
    </p>

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
defineProps({
  registrations: { type: Array, required: true },
  eventStatus: { type: String, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
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
    'CONFIRMED': 'Wartet auf Bestätigung',
    'PARTICIPATING': 'Nimmt teil',
    'WAITLISTED': 'Warteliste',
    'CANCELLED': 'Abgesagt',
    'CHECKED_IN': 'Eingecheckt',
  }
  return statusLabels[status] || status
}
</script>

<style scoped>
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
