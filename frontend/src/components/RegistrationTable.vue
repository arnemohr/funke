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

      <table class="mobile-card-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>E-Mail</th>
            <th>Telefon</th>
            <th>Personen</th>
            <th>Status</th>
            <th v-if="showPromotedColumn">Bevorzugt</th>
            <th>Angemeldet am</th>
            <th v-if="showActions"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="reg in filteredRegistrations" :key="reg.id">
            <td data-label="Name">{{ reg.name }}</td>
            <td data-label="E-Mail"><a :href="`mailto:${reg.email}`">{{ reg.email }}</a></td>
            <td data-label="Telefon">
              <a
                v-if="reg.phone"
                :href="smsLink(reg)"
              >{{ reg.phone }}</a>
              <span v-else>&ndash;</span>
            </td>
            <td data-label="Personen">{{ reg.group_size }}</td>
            <td data-label="Status">
              <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                {{ formatRegistrationStatus(reg.status) }}
                <template v-if="reg.status === 'WAITLISTED' && reg.waitlist_position">
                  (#{{ reg.waitlist_position }})
                </template>
              </span>
              <span
                v-if="reg.status === 'CONFIRMED' && reg.page_viewed_at"
                class="viewed-badge"
                :title="`Seite zuletzt geöffnet: ${formatDate(reg.page_viewed_at)}`"
              >
                Gesehen
              </span>
            </td>
            <td v-if="showPromotedColumn" data-label="Bevorzugt">
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
            <td data-label="Angemeldet">{{ formatDate(reg.registered_at) }}</td>
            <td v-if="showActions" class="context-menu-cell">
              <template v-if="hasActions(reg)">
                <div class="card-actions">
                  <button
                    class="context-menu-trigger"
                    @click.stop="toggleMenu(reg.id)"
                    aria-label="Aktionen"
                  >
                    &hellip;
                  </button>
                  <div v-if="openMenuId === reg.id" class="context-menu" @click.stop @keydown="handleMenuKeydown($event, reg)">
                    <template v-if="reg.status === 'WAITLISTED' && eventStatus === 'CONFIRMED'">
                      <button
                        class="context-menu-item"
                        @click="doAction(() => $emit('promote-waitlisted', { registrationId: reg.id, targetStatus: 'CONFIRMED' }))"
                      >
                        Nachrücken
                      </button>
                      <button
                        class="context-menu-item"
                        @click="doAction(() => $emit('promote-waitlisted', { registrationId: reg.id, targetStatus: 'PARTICIPATING' }))"
                      >
                        Direkt bestätigen
                      </button>
                      <hr class="context-menu-divider" />
                    </template>
                    <button
                      v-if="reg.status !== 'CANCELLED'"
                      class="context-menu-item destructive"
                      @click="doAction(() => $emit('delete-registration', { registrationId: reg.id, name: reg.name }))"
                    >
                      Löschen
                    </button>
                  </div>
                </div>
              </template>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="total-info">
        {{ filteredRegistrations.length }} Buchungen,
        {{ spotsBy(filteredRegistrations) }} Personen
        <template v-if="filteredRegistrations.length !== activeRegistrations.length">
          ({{ activeRegistrations.length }} Buchungen gesamt)
        </template>
      </p>
    </template>

    <!-- Attendance summary for CONFIRMED events -->
    <div v-if="['CONFIRMED', 'COMPLETED'].includes(eventStatus)" class="confirmation-summary">
      <span class="confirmation-stat yes">
        {{ spotsByStatus('PARTICIPATING') }} Nimmt teil
      </span>
      <span class="confirmation-stat pending">
        {{ spotsByStatus('CONFIRMED') }} Ausstehend
      </span>
      <span v-if="spotsByStatus('WAITLISTED') > 0" class="confirmation-stat waitlisted">
        {{ spotsByStatus('WAITLISTED') }} Warteliste
      </span>
      <span v-if="spotsByStatus('CANCELLED') > 0" class="confirmation-stat no">
        {{ spotsByStatus('CANCELLED') }} Abgesagt
      </span>
    </div>
  </template>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { formatDate, formatRegistrationStatus } from '../utils/formatters.js'

const props = defineProps({
  registrations: { type: Array, required: true },
  eventStatus: { type: String, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  togglingId: { type: String, default: null },
})

defineEmits(['toggle-promoted', 'promote-waitlisted', 'delete-registration'])

const searchTerm = ref('')
const statusFilter = ref('')
const openMenuId = ref(null)

function hasActions(reg) {
  return reg.status !== 'CANCELLED'
}

function handleMenuKeydown(event, reg) {
  if (event.key === 'Escape') {
    openMenuId.value = null
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const items = event.currentTarget.querySelectorAll('.context-menu-item')
    const currentIndex = Array.from(items).indexOf(document.activeElement)
    let nextIndex
    if (event.key === 'ArrowDown') {
      nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0
    } else {
      nextIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1
    }
    items[nextIndex]?.focus()
  }
}

function toggleMenu(id) {
  openMenuId.value = openMenuId.value === id ? null : id
}

function doAction(fn) {
  openMenuId.value = null
  fn()
}

function closeMenu() {
  openMenuId.value = null
}

onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => document.removeEventListener('click', closeMenu))

const showPromotedColumn = computed(() => {
  return ['OPEN', 'REGISTRATION_CLOSED', 'LOTTERY_PENDING', 'CONFIRMED', 'COMPLETED'].includes(props.eventStatus)
})

const isPromotedEditable = computed(() => {
  return ['OPEN', 'REGISTRATION_CLOSED'].includes(props.eventStatus)
})

const showActions = computed(() => {
  return props.registrations.some(r => r.status !== 'CANCELLED')
    || (props.eventStatus === 'CONFIRMED'
      && props.registrations.some(r => r.status === 'WAITLISTED'))
})

const activeRegistrations = computed(() => {
  return props.registrations.filter(r => r.status !== 'CANCELLED')
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

function spotsBy(regs) {
  return regs.reduce((sum, r) => sum + r.group_size, 0)
}

function spotsByStatus(status) {
  return spotsBy(props.registrations.filter(r => r.status === status))
}

function smsLink(reg) {
  const url = `${window.location.origin}/registration/${reg.id}?token=${reg.registration_token}`
  const body = `Moin, Schaluppe hier! Kurze Erinnerung: Bitte bestätige noch deinen Platz an Bord oder sage bitte ab. :)\n${url}`
  return `sms:${reg.phone}?body=${encodeURIComponent(body)}`
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
  min-width: 0;
}

.status-filter {
  min-width: 0;
}

@media (max-width: 640px) {
  .filters {
    flex-direction: column;
  }
  .search-input,
  .status-filter {
    width: 100%;
  }
}

.promoted-toggle {
  margin: 0;
}

.promoted-toggle input[type="checkbox"] {
  margin: 0;
}

.viewed-badge {
  display: inline-block;
  margin-left: 0.35rem;
  padding: 0.15rem 0.4rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.65rem;
  font-weight: 500;
  background: #e0e7ff;
  color: #4f46e5;
  cursor: help;
}

.promoted-badge {
  color: #d97706;
  font-size: 1.2rem;
}

.context-menu-cell {
  position: relative;
  width: 2.5rem;
  text-align: center;
}

.context-menu-trigger {
  all: unset;
  cursor: pointer;
  font-size: 1.25rem;
  line-height: 1;
  padding: 0.25rem 0.5rem;
  border-radius: var(--pico-border-radius);
  color: var(--pico-muted-color);
  letter-spacing: 1px;
}

.context-menu-trigger:hover {
  background: #e2e8f0;
  color: #334155;
}

.context-menu {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 10;
  min-width: 160px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 0.25rem 0;
}

.context-menu-item {
  all: unset;
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  cursor: pointer;
  color: #334155;
}

.context-menu-item:hover {
  background: #f1f5f9;
}

.context-menu-item.destructive {
  color: #dc2626;
}

.context-menu-item.destructive:hover {
  background: #fef2f2;
}

.context-menu-divider {
  margin: 0.25rem 0;
  border: none;
  border-top: 1px solid #e2e8f0;
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
.confirmation-stat.waitlisted { background: #e5e7eb; color: #6b7280; }

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.context-menu-trigger:focus-visible {
  outline: 2px solid var(--pico-primary);
  outline-offset: 2px;
}

.context-menu-item:focus-visible {
  outline: 2px solid var(--pico-primary);
  outline-offset: -2px;
  background: #f1f5f9;
}

@media (max-width: 640px) {
  /* Name row is prominent — hide the ::before label for it */
  tbody td[data-label="Name"] {
    font-weight: 600;
    font-size: var(--text-lg);
    padding-bottom: 0.35rem;
    margin-bottom: 0.2rem;
    border-bottom: 1px solid var(--color-border);
  }
  tbody td[data-label="Name"]::before {
    display: none;
  }

  /* Status badge is self-labeling — hide the redundant "Status:" prefix */
  tbody td[data-label="Status"]::before {
    display: none;
  }

  /* Card actions: absolutely positioned at top-right of card */
  .context-menu-cell {
    display: block;
    padding: 0;
    border: none;
  }
  .card-actions {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
  }

  /* Context menu: position fixed to avoid viewport overflow */
  .context-menu {
    position: fixed;
    right: 1rem;
    left: auto;
  }

  /* Larger tap targets */
  .context-menu-trigger {
    min-height: 44px;
    min-width: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .context-menu-item {
    padding: 0.75rem 1rem;
    font-size: var(--text-base);
  }
}
</style>
