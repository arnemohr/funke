<template>
  <article>
    <header class="page-header">
      <div>
        <p class="back-link">
          <a href="#" @click.prevent="goBack">← Back to Events</a>
        </p>
        <h2>Lottery</h2>
        <p class="muted">Run and finalize lottery for this event</p>
      </div>
      <div class="status-chip" v-if="event">
        <span class="label">Event Status</span>
        <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
          {{ event.status }}
        </span>
      </div>
    </header>

    <div v-if="loading" aria-busy="true">
      Loading lottery...
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
            <p class="label">Capacity</p>
            <p class="value">{{ event.capacity }}</p>
          </div>
          <div>
            <p class="label">Confirmed Spots</p>
            <p class="value">{{ event.confirmed_spots }}</p>
          </div>
          <div>
            <p class="label">Waitlist</p>
            <p class="value">{{ event.waitlist_count }}</p>
          </div>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header">
          <div>
            <h4>Lottery Control</h4>
            <p class="muted">
              Shuffle registrations, review winners, and finalize notifications.
            </p>
          </div>
          <div class="actions">
            <button
              class="secondary"
              :disabled="running || finalizing || lottery?.is_finalized"
              :aria-busy="running"
              @click="handleRun"
            >
              {{ running ? 'Running...' : 'Run Lottery' }}
            </button>
            <button
              v-if="lottery"
              :disabled="lottery.is_finalized || finalizing"
              :aria-busy="finalizing"
              @click="handleFinalize"
            >
              {{ finalizing ? 'Finalizing...' : lottery.is_finalized ? 'Finalized' : 'Finalize & Notify' }}
            </button>
          </div>
        </header>

        <div v-if="!lottery" class="empty">
          <p>No lottery has been run yet. Close registration and run the lottery to generate winners.</p>
        </div>

        <div v-else class="lottery-meta">
          <div>
            <p class="label">Seed</p>
            <p class="mono">{{ lottery.seed }}</p>
          </div>
          <div>
            <p class="label">Executed At</p>
            <p>{{ formatDate(lottery.executed_at) }}</p>
          </div>
          <div>
            <p class="label">Status</p>
            <p>
              <span
                :class="[
                  'status-badge',
                  lottery.is_finalized ? 'status-confirmed' : 'status-registration_closed',
                ]"
              >
                {{ lottery.is_finalized ? 'FINALIZED' : 'PENDING REVIEW' }}
              </span>
              <span v-if="lottery.finalized_at" class="muted">
                (Finalized {{ formatDate(lottery.finalized_at) }})
              </span>
            </p>
          </div>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header">
          <h4>Winners</h4>
          <p class="muted">Registrations selected within capacity.</p>
        </header>

        <p v-if="!lottery || lottery.winners.length === 0" class="empty">
          No winners yet. Run the lottery to generate winners.
        </p>

        <table v-else>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Group Size</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="winner in lottery.winners" :key="winner.id">
              <td>{{ winner.name }}</td>
              <td class="mono">{{ winner.email }}</td>
              <td>{{ winner.group_size }}</td>
              <td>
                <span class="status-badge status-confirmed">CONFIRMED</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <header class="panel-header">
          <h4>Waitlist</h4>
          <p class="muted">Ordered by lottery draw.</p>
        </header>

        <p v-if="!lottery || lottery.waitlist.length === 0" class="empty">
          No waitlisted registrations.
        </p>

        <table v-else>
          <thead>
            <tr>
              <th>Position</th>
              <th>Name</th>
              <th>Email</th>
              <th>Group Size</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="wait in lottery.waitlist" :key="wait.id">
              <td>#{{ wait.waitlist_position || '-' }}</td>
              <td>{{ wait.name }}</td>
              <td class="mono">{{ wait.email }}</td>
              <td>{{ wait.group_size }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </article>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi } from '../../../../services/api'

const route = useRoute()
const router = useRouter()
const eventId = route.params.eventId

const event = ref(null)
const lottery = ref(null)
const loading = ref(true)
const error = ref(null)
const running = ref(false)
const finalizing = ref(false)

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return date.toLocaleString('de-DE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

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
      // No lottery yet
      lottery.value = null
    }
  } catch (err) {
    error.value = err.message || 'Failed to load lottery data'
  } finally {
    loading.value = false
  }
}

async function handleRun() {
  running.value = true
  error.value = null
  try {
    lottery.value = await adminApi.runLottery(eventId)
    // Refresh event to reflect status change
    event.value = await adminApi.getEvent(eventId)
  } catch (err) {
    error.value = err.message || 'Failed to run lottery'
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
    error.value = err.message || 'Failed to finalize lottery'
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

.back-link {
  margin: 0;
}

.muted {
  color: var(--pico-muted-color);
  margin: 0.25rem 0 0;
}

.status-chip {
  text-align: right;
}

.status-badge {
  display: inline-block;
  padding: 0.35rem 0.65rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.8rem;
  font-weight: 600;
}

.status-confirmed {
  background: #dcfce7;
  color: #16a34a;
}

.status-registration_closed {
  background: #fef3c7;
  color: #d97706;
}

.status-draft {
  background: #e2e8f0;
  color: #64748b;
}

.status-open {
  background: #dbeafe;
  color: #2563eb;
}

.status-lottery_pending {
  background: #ede9fe;
  color: #7c3aed;
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
  grid-template-columns: repeat(3, minmax(120px, 1fr));
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
</style>
