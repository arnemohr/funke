<template>
  <article style="position: relative;">
    <header>
      <hgroup>
        <h2>Veranstaltungen</h2>
        <p>Verwalte deine Veranstaltungen</p>
      </hgroup>
      <div class="header-actions">
        <HelpButton @click="help.toggle(activeHelpKey)" />
        <button v-if="!accessDenied" @click="goToNew">Neue Veranstaltung</button>
      </div>
    </header>

    <HelpPanel
      :help-key="help.helpKey.value"
      :open="help.isOpen.value"
      ref="helpPanelRef"
      @close="help.close()"
    />

    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Veranstaltungen werden geladen...
    </div>

    <!-- Access Denied state -->
    <div v-else-if="accessDenied" class="access-denied">
      <h3>Zugriff verweigert</h3>
      <p>{{ error }}</p>
      <p>Falls du denkst, dass das ein Fehler ist, melde dich bei uns.</p>
      <button @click="logout" class="secondary">Abmelden</button>
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      {{ error }}
    </div>

    <!-- Events list -->
    <template v-else>
      <!-- Filter tabs -->
      <nav class="filter-nav">
        <ul class="filter-tabs">
          <li>
            <a href="#" :class="{ active: statusFilter === null }" @click.prevent="statusFilter = null">Alle ({{ filterCounts.all }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'DRAFT' }" @click.prevent="statusFilter = 'DRAFT'">Entwurf ({{ filterCounts.DRAFT }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'OPEN' }" @click.prevent="statusFilter = 'OPEN'">Offen ({{ filterCounts.OPEN }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'IN_PROGRESS' }" @click.prevent="statusFilter = 'IN_PROGRESS'">In Bearbeitung ({{ filterCounts.IN_PROGRESS }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'COMPLETED' }" @click.prevent="statusFilter = 'COMPLETED'">Abgeschlossen ({{ filterCounts.COMPLETED }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'CANCELLED' }" @click.prevent="statusFilter = 'CANCELLED'">Abgesagt ({{ filterCounts.CANCELLED }})</a>
          </li>
        </ul>
      </nav>

      <!-- Empty state -->
      <article v-if="filteredEvents.length === 0" style="text-align: center; padding: 2rem;">
        <p>Noch keine Veranstaltungen. Leg los und erstelle deine erste!</p>
        <button @click="goToNew">Neue Veranstaltung</button>
      </article>

      <!-- Events table -->
      <table v-else class="mobile-card-table">
        <thead>
          <tr>
            <th>Veranstaltung</th>
            <th>Datum</th>
            <th>Status</th>
            <th>Anmeldungen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="event in filteredEvents" :key="event.id">
            <td data-label="Veranstaltung">
              <router-link :to="`/admin/events/${event.id}`">
                <strong>{{ event.name }}</strong>
              </router-link>
              <br />
              <small>{{ event.location || 'Kein Ort angegeben' }}</small>
            </td>
            <td data-label="Datum">{{ formatDate(event.start_at) }}</td>
            <td data-label="Status">
              <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
                {{ formatEventStatus(event.status) }}
              </span>
            </td>
            <td data-label="Anmeldungen">
              <div>{{ event.registration_count }} Anmeldungen ({{ event.registration_spots }} Pers.)</div>
              <div style="font-size: var(--text-sm); color: var(--pico-muted-color);">{{ event.confirmed_spots }} / {{ event.capacity }} bestätigt<span v-if="event.waitlist_count"> · {{ event.waitlist_spots }} Warteliste</span></div>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

  </article>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth0 } from '@auth0/auth0-vue'
import { adminApi } from '../../services/api'
import HelpButton from '../../components/help/HelpButton.vue'
import HelpPanel from '../../components/help/HelpPanel.vue'
import { useHelp } from '../../components/help/useHelp.js'
import { formatDate, formatEventStatus } from '../../utils/formatters.js'

const router = useRouter()
const { logout: auth0Logout } = useAuth0()

// Help system
const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const activeHelpKey = computed(() => 'events-list')

// Core state
const loading = ref(true)
const error = ref(null)
const accessDenied = ref(false)
const events = ref([])
const statusFilter = ref(null)

// Computed
const IN_PROGRESS_STATUSES = ['REGISTRATION_CLOSED', 'LOTTERY_PENDING', 'CONFIRMED']

const filteredEvents = computed(() => {
  if (!statusFilter.value) return events.value
  if (statusFilter.value === 'IN_PROGRESS') {
    return events.value.filter(e => IN_PROGRESS_STATUSES.includes(e.status))
  }
  return events.value.filter(e => e.status === statusFilter.value)
})

const filterCounts = computed(() => {
  const all = events.value
  return {
    all: all.length,
    DRAFT: all.filter(e => e.status === 'DRAFT').length,
    OPEN: all.filter(e => e.status === 'OPEN').length,
    IN_PROGRESS: all.filter(e => IN_PROGRESS_STATUSES.includes(e.status)).length,
    COMPLETED: all.filter(e => e.status === 'COMPLETED').length,
    CANCELLED: all.filter(e => e.status === 'CANCELLED').length,
  }
})

// Helpers
function logout() {
  auth0Logout({ logoutParams: { returnTo: window.location.origin } })
}

// API actions
async function loadEvents() {
  loading.value = true
  error.value = null
  accessDenied.value = false
  try {
    const result = await adminApi.listEvents()
    events.value = result.items
  } catch (err) {
    const message = err.message || 'Veranstaltungen konnten nicht geladen werden'
    error.value = message
    if (message.includes('Access denied') || message.includes('403')) accessDenied.value = true
  } finally {
    loading.value = false
  }
}

function goToNew() {
  router.push('/admin/events/new')
}

onMounted(loadEvents)
</script>

<style scoped>
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.filter-nav {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 1rem;
}

.filter-tabs {
  display: flex;
  gap: 0.5rem;
  white-space: nowrap;
  list-style: none;
  padding: 0 2rem 2px 0;
  margin: 0;
}

/* Ensure tab links are touch-friendly */
.filter-tabs a {
  white-space: nowrap;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 0.875rem;
  text-decoration: none;
  border-radius: var(--pico-border-radius);
}

.filter-tabs a.active {
  background: var(--pico-primary);
  color: white;
}

dialog article { max-width: min(600px, calc(100vw - 2rem)); }
dialog article.modal-wide { max-width: min(750px, calc(100vw - 2rem)); }

dialog footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.access-denied {
  text-align: center;
  padding: 3rem 2rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--pico-border-radius);
  color: #991b1b;
}

.access-denied h3 { color: #dc2626; margin-bottom: 1rem; }
.access-denied p { margin-bottom: 0.5rem; }
.access-denied button { margin-top: 1.5rem; }

@media (max-width: 768px) {
  .filter-nav {
    /* Scroll hint: fade out on the right */
    mask-image: linear-gradient(to right, #000 85%, transparent 100%);
    -webkit-mask-image: linear-gradient(to right, #000 85%, transparent 100%);
  }
}

@media (max-width: 640px) {
  tbody td[data-label="Veranstaltung"] {
    font-weight: 600;
    font-size: var(--text-base);
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 0.4rem;
  }
  tbody td[data-label="Veranstaltung"]::before {
    display: none;
  }
  /* Status badge is self-explanatory, hide label */
  tbody td[data-label="Status"]::before {
    display: none;
  }
}
</style>
