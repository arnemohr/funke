<template>
  <article style="position: relative;">
    <header class="page-header">
      <div>
        <nav class="breadcrumbs" aria-label="Breadcrumb">
          <a href="#" @click.prevent="goBack">Veranstaltungen</a>
          <span class="breadcrumb-sep">›</span>
          <span v-if="event">{{ event.name }}</span>
          <span class="breadcrumb-sep">›</span>
          <span>Verlosung</span>
        </nav>
        <h2>Verlosung</h2>
        <p class="muted">Verlosung durchführen und abschließen</p>
      </div>
      <div class="header-right">
        <HelpButton @click="help.toggle('lottery')" />
        <div class="status-chip" v-if="event">
          <span class="label">Status</span>
          <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
            {{ formatEventStatus(event.status) }}
          </span>
        </div>
      </div>
    </header>

    <HelpPanel
      :help-key="help.helpKey.value"
      :open="help.isOpen.value"
      ref="helpPanelRef"
      @close="help.close()"
    />

    <div v-if="loading" aria-busy="true">
      Verlosung wird geladen...
    </div>

    <div v-else-if="error" role="alert" class="error">
      {{ error }}
    </div>

    <template v-else>
      <section class="event-summary">
        <div>
          <h3>{{ event.name }}</h3>
          <p class="muted">
            {{ formatDate(event.start_at) }}
            <span v-if="event.location">• {{ event.location }}</span>
          </p>
        </div>
        <div class="summary-metrics">
          <div>
            <p class="label">Plätze</p>
            <p class="value">{{ event.capacity }}</p>
          </div>
          <div>
            <p class="label">Bestätigt</p>
            <p class="value">{{ event.confirmed_spots }}</p>
          </div>
          <div>
            <p class="label">Warteliste</p>
            <p class="value">{{ event.waitlist_count }}</p>
          </div>
          <div>
            <p class="label">Bevorzugt</p>
            <p class="value">{{ event.promoted_count || 0 }} <span class="value-detail">({{ event.promoted_spots || 0 }} Plätze)</span></p>
          </div>
        </div>
      </section>

      <!-- Promoted capacity warning -->
      <div v-if="event.promoted_spots > event.capacity" class="capacity-warning" role="alert">
        Achtung: Bevorzugte Anmeldungen ({{ event.promoted_spots }} Plätze) übersteigen die Kapazität ({{ event.capacity }}).
        Bitte Bevorzugungen anpassen, bevor die Verlosung gestartet wird.
      </div>

      <section class="panel">
        <header class="panel-header">
          <div>
            <h4>Verlosung steuern</h4>
            <p class="muted">
              Anmeldungen mischen, Gewinner prüfen und Benachrichtigungen versenden.
            </p>
          </div>
          <div class="actions">
            <button
              v-if="!lottery && event?.status !== 'CONFIRMED'"
              class="secondary"
              :disabled="running || (event?.promoted_spots > event?.capacity)"
              :aria-busy="running"
              @click="handleRun"
            >
              {{ running ? 'Läuft...' : 'Verlosung starten' }}
            </button>
            <button
              v-if="lottery && !lottery.is_finalized && event?.status !== 'CONFIRMED'"
              class="secondary"
              :disabled="running || (event?.promoted_spots > event?.capacity)"
              :aria-busy="running"
              @click="handleRun"
            >
              {{ running ? 'Läuft...' : 'Neu mischen' }}
            </button>
            <button
              v-if="lottery && !lottery.is_finalized && event?.status !== 'CONFIRMED'"
              :disabled="finalizing"
              :aria-busy="finalizing"
              @click="handleFinalize"
            >
              {{ finalizing ? 'Wird abgeschlossen...' : 'Abschließen & Benachrichtigen' }}
            </button>
          </div>
        </header>

        <div v-if="!lottery" class="empty">
          <p>Noch keine Verlosung durchgeführt. Schließe die Anmeldung und starte die Verlosung.</p>
        </div>

        <div v-else class="lottery-meta">
          <div>
            <p class="label">Seed</p>
            <p class="mono">{{ lottery.seed }}</p>
          </div>
          <div>
            <p class="label">Ausgeführt am</p>
            <p>{{ formatDate(lottery.executed_at) }}</p>
          </div>
          <div>
            <p class="label">Status</p>
            <p>
              <span
                :class="[
                  'status-badge',
                  lottery.is_finalized ? 'status-finalized' : 'status-registration_closed',
                ]"
              >
                {{ lottery.is_finalized ? 'ABGESCHLOSSEN' : 'PRÜFUNG AUSSTEHEND' }}
              </span>
              <span v-if="lottery.finalized_at" class="muted">
                (Abgeschlossen am {{ formatDate(lottery.finalized_at) }})
              </span>
            </p>
          </div>
        </div>

        <div v-if="lottery?.is_finalized" class="finalized-guidance">
          <p>Teilnehmende wurden benachrichtigt. Du kannst den Bestätigungsstatus in der Veranstaltungsübersicht verfolgen.</p>
          <a href="#" @click.prevent="goBack" class="outline" role="button">Zurück zur Übersicht</a>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header">
          <h4>Gewinner</h4>
          <p class="muted">Ausgewählte Anmeldungen innerhalb der Kapazität.</p>
        </header>

        <p v-if="!lottery || lottery.winners.length === 0" class="empty">
          Noch keine Gewinner. Starte die Verlosung.
        </p>

        <table v-else class="mobile-card-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>E-Mail</th>
              <th>Personen</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="winner in lottery.winners" :key="winner.id">
              <td data-label="Name">{{ winner.name }} <span v-if="winner.promoted" class="promoted-star" title="Bevorzugt">★</span></td>
              <td data-label="E-Mail" class="mono">{{ winner.email }}</td>
              <td data-label="Personen">{{ winner.group_size }}</td>
              <td data-label="Status">
                <span class="status-badge status-confirmed">BESTÄTIGT</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <header class="panel-header">
          <h4>Warteliste</h4>
          <p class="muted">Sortiert nach Verlosungsreihenfolge.</p>
        </header>

        <p v-if="!lottery || lottery.waitlist.length === 0" class="empty">
          Keine Wartelistenanmeldungen.
        </p>

        <table v-else class="mobile-card-table">
          <thead>
            <tr>
              <th>Position</th>
              <th>Name</th>
              <th>E-Mail</th>
              <th>Personen</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="wait in lottery.waitlist" :key="wait.id">
              <td data-label="Position">#{{ wait.waitlist_position || '-' }}</td>
              <td data-label="Name">{{ wait.name }}</td>
              <td data-label="E-Mail" class="mono">{{ wait.email }}</td>
              <td data-label="Personen">{{ wait.group_size }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </article>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi } from '../../../../services/api'
import { formatDate, formatEventStatus } from '../../../../utils/formatters.js'
import HelpButton from '../../../../components/help/HelpButton.vue'
import HelpPanel from '../../../../components/help/HelpPanel.vue'
import { useHelp } from '../../../../components/help/useHelp.js'

const route = useRoute()
const router = useRouter()
const eventId = route.params.eventId

const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const event = ref(null)
const lottery = ref(null)
const loading = ref(true)
const error = ref(null)
const running = ref(false)
const finalizing = ref(false)

function goBack() {
  router.push({ name: 'admin-events' })
}

async function loadData() {
  loading.value = true
  error.value = null

  try {
    event.value = await adminApi.getEvent(eventId)
    try {
      lottery.value = await adminApi.getLottery(eventId)
    } catch (err) {
      // Noch keine Verlosung
      lottery.value = null
    }
  } catch (err) {
    error.value = err.message || 'Verlosungsdaten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
}

async function handleRun() {
  running.value = true
  error.value = null
  try {
    lottery.value = await adminApi.runLottery(eventId)
    // Aktualisiere Event um Statusänderung anzuzeigen
    event.value = await adminApi.getEvent(eventId)
  } catch (err) {
    error.value = err.message || 'Verlosung konnte nicht gestartet werden'
  } finally {
    running.value = false
  }
}

async function handleFinalize() {
  if (!lottery.value) return
  finalizing.value = true
  error.value = null

  try {
    lottery.value = await adminApi.finalizeLottery(eventId)
    event.value = await adminApi.getEvent(eventId)
  } catch (err) {
    error.value = err.message || 'Verlosung konnte nicht abgeschlossen werden'
  } finally {
    finalizing.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.breadcrumbs {
  font-size: var(--text-sm);
  margin: 0 0 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.breadcrumb-sep {
  color: var(--pico-muted-color);
}

.muted {
  color: var(--pico-muted-color);
  margin: 0.25rem 0 0;
}

.header-right {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.status-chip {
  text-align: right;
}

.event-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--pico-card-background-color, #f8fafc);
  padding: 1.25rem;
  border-radius: var(--pico-border-radius);
  border: 1px solid var(--pico-muted-border-color, #e2e8f0);
  gap: 1rem;
  flex-wrap: wrap;
}

.summary-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 1rem;
}

.label {
  font-size: 0.85rem;
  color: var(--pico-muted-color);
  margin: 0 0 0.2rem;
}

.value {
  font-size: 1.2rem;
  font-weight: 700;
  margin: 0;
}

.panel {
  margin-top: 1.5rem;
  padding: 1.25rem;
  border: 1px solid var(--pico-muted-border-color, #e2e8f0);
  border-radius: var(--pico-border-radius);
  background: white;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-wrap: wrap;
}

.actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.lottery-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}

.mono {
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.empty {
  color: var(--pico-muted-color);
}

table {
  width: 100%;
}

th {
  text-align: left;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
}

.value-detail {
  font-size: 0.75rem;
  font-weight: normal;
  color: var(--pico-muted-color);
}

.capacity-warning {
  margin-top: 1rem;
  padding: 1rem;
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: var(--pico-border-radius);
  color: #92400e;
  font-weight: 500;
}

.promoted-star {
  color: #d97706;
  font-size: 0.9rem;
}

.finalized-guidance {
  margin-top: 1rem;
  padding: 1rem;
  background: var(--color-success-bg);
  border-radius: var(--pico-border-radius);
  color: var(--color-success-text);
}

.finalized-guidance p {
  margin-bottom: 0.75rem;
}

/* Mobile card layout for tables */
@media (max-width: 640px) {
  .mobile-card-table tbody td[data-label="Name"] {
    font-weight: 600;
    font-size: var(--text-base, 0.875rem);
    border-bottom: 1px solid var(--pico-muted-border-color, #e2e8f0);
    padding-bottom: 0.4rem;
    margin-bottom: 0.2rem;
  }
  .mobile-card-table tbody td[data-label="Name"]::before {
    display: none;
  }
  .mobile-card-table tbody td[data-label="Status"]::before {
    display: none;
  }
}
</style>
