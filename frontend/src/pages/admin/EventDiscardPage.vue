<template>
  <article class="event-discard-page">
    <PageHeader
      :back="`/admin/events/${eventId}`"
      back-label="Zurück"
    >
      <template #title>Unbestätigte verwerfen</template>
      <template #subtitle>
        Teilnehmer ohne Bestätigung werden von der Liste entfernt und erhalten eine Absage-Mail.
      </template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">
      Anmeldungen werden geladen…
    </div>

    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <template v-else>
      <div v-if="candidates.length === 0" class="empty-state">
        <p>Keine unbestätigten Anmeldungen vorhanden.</p>
        <button class="secondary" @click="goBack">Zurück zur Veranstaltung</button>
      </div>

      <template v-else>
        <section class="card">
          <div class="card-head">
            <h3>Auswahl</h3>
            <button
              type="button"
              class="link-btn"
              @click="toggleAll"
            >
              {{ allSelected ? 'Alle abwählen' : 'Alle auswählen' }}
            </button>
          </div>
          <div class="discard-list">
            <label
              v-for="reg in candidates"
              :key="reg.id"
              class="discard-item"
            >
              <input
                type="checkbox"
                :checked="selected.has(reg.id)"
                @change="toggle(reg.id)"
              />
              <span>
                {{ reg.name }}
                <small>({{ reg.group_size }} {{ reg.group_size === 1 ? 'Person' : 'Personen' }})</small>
              </span>
            </label>
          </div>
        </section>

        <section class="card">
          <h3>Benachrichtigung</h3>
          <label for="discardSubject">
            Betreff
            <input
              id="discardSubject"
              v-model="subject"
              type="text"
              :disabled="submitting"
            />
          </label>
          <label for="discardMessage">
            Nachricht an die Teilnehmer
            <textarea
              id="discardMessage"
              v-model="message"
              rows="5"
              :disabled="submitting"
            ></textarea>
          </label>
          <p class="hint">
            Leere Nachrichten werden nicht versendet. Die Teilnehmer werden dann stillschweigend entfernt.
          </p>
        </section>

        <div v-if="submitError" role="alert" class="error">
          {{ submitError }}
        </div>
      </template>
    </template>

    <!-- Sticky action footer -->
    <div v-if="!loading && candidates.length > 0" class="sticky-footer">
      <button
        type="button"
        class="secondary"
        :disabled="submitting"
        @click="goBack"
      >
        Abbrechen
      </button>
      <button
        type="button"
        class="btn-danger"
        :disabled="selected.size === 0 || submitting"
        :aria-busy="submitting"
        @click="handleConfirm"
      >
        {{ submitting ? 'Wird verworfen…' : `${selected.size} verwerfen` }}
      </button>
    </div>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../services/api'
import PageHeader from '../../components/PageHeader.vue'
import { showToast } from '../../composables/useToast.js'

const props = defineProps({
  eventId: { type: String, required: true },
})

const router = useRouter()

const event = ref(null)
const candidates = ref([])
const selected = ref(new Set())
const subject = ref('')
const message = ref('')

const loading = ref(true)
const loadError = ref(null)
const submitting = ref(false)
const submitError = ref(null)

const allSelected = computed(
  () => candidates.value.length > 0 && selected.value.size === candidates.value.length,
)

onMounted(async () => {
  try {
    const [evt, regs] = await Promise.all([
      adminApi.getEvent(props.eventId),
      adminApi.listRegistrations(props.eventId),
    ])
    event.value = evt
    candidates.value = regs.items.filter(r => r.status === 'CONFIRMED')
    selected.value = new Set(candidates.value.map(r => r.id))
    subject.value = `Absage: ${evt.name}`
    message.value =
      'Leider haben wir innerhalb der Frist keine Rückmeldung von dir erhalten, ob du wirklich mit an Bord kommst. Daher mussten wir deinen Platz an einen anderen Fisch aus unserem Schwarm weitergeben.\n\nFalls du beim nächsten Mal wieder anheuern möchtest, freuen wir uns sehr auf dich!'
  } catch (err) {
    loadError.value = err.message || 'Daten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
})

function toggle(id) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleAll() {
  if (allSelected.value) {
    selected.value = new Set()
  } else {
    selected.value = new Set(candidates.value.map(r => r.id))
  }
}

function goBack() {
  router.push(`/admin/events/${props.eventId}`)
}

async function handleConfirm() {
  if (selected.value.size === 0) return
  submitting.value = true
  submitError.value = null
  try {
    const result = await adminApi.discardUnacknowledged(
      props.eventId,
      [...selected.value],
      message.value.trim() || undefined,
      subject.value.trim() || undefined,
    )
    showToast(
      `${result.discarded_count} Anmeldungen verworfen (${result.discarded_spots} Plätze).`,
      'success',
    )
    router.push(`/admin/events/${props.eventId}`)
  } catch (err) {
    submitError.value = err.message || 'Verwerfen fehlgeschlagen'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.event-discard-page {
  padding-bottom: 6rem;
}

.card {
  background: white;
  border: 1px solid var(--color-border, #DFE2E6);
  border-radius: var(--pico-border-radius);
  padding: 1rem;
  margin-bottom: 1rem;
}

.card h3 {
  margin: 0 0 0.75rem;
  font-size: 1rem;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.card-head h3 {
  margin: 0;
}

.link-btn {
  background: none;
  border: none;
  color: var(--color-brand, #0C1E3C);
  font-size: var(--text-sm, 0.875rem);
  font-weight: 500;
  padding: 0.25rem 0;
  cursor: pointer;
  width: auto;
  margin: 0;
  min-width: 0;
}

.link-btn:hover {
  text-decoration: underline;
}

.discard-list {
  max-height: 40vh;
  overflow-y: auto;
}

.discard-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0;
  min-height: 44px;
  border-bottom: 1px solid var(--color-border, #DFE2E6);
  cursor: pointer;
}

.discard-item:last-child {
  border-bottom: none;
}

.discard-item input[type="checkbox"] {
  margin: 0;
  flex-shrink: 0;
}

.discard-item small {
  color: var(--color-text-muted, #5C6470);
}

.hint {
  margin: 0.5rem 0 0;
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-muted, #5C6470);
}

.empty-state {
  padding: 2rem 1rem;
  text-align: center;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.sticky-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 50;
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  padding-bottom: calc(0.75rem + env(safe-area-inset-bottom, 0));
  background: white;
  border-top: 1px solid var(--color-border, #DFE2E6);
}

.sticky-footer button {
  flex: 1;
  margin: 0;
}
</style>
