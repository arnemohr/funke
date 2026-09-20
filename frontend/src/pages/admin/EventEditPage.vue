<template>
  <article class="event-edit-page">
    <PageHeader
      :back="backTarget"
      back-label="Zurück"
    >
      <template #title>{{ isNew ? 'Neue Veranstaltung' : 'Veranstaltung bearbeiten' }}</template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">
      Veranstaltung wird geladen…
    </div>

    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <EventForm
      v-else
      :event="event"
      :disabled="submitting"
      :error="submitError"
      :locked-fields="lockedFields"
      :submit-label="isNew ? 'Erstellen' : 'Speichern'"
      :submit-busy-label="isNew ? 'Wird erstellt…' : 'Wird gespeichert…'"
      @submit="handleSubmit"
      @cancel="handleCancel"
    />

    <!-- Termin oder Ort nach dem Anmeldeschluss zu ändern heißt: alle
         Angemeldeten halten eine Mail mit der alten Angabe in der Hand. Funke
         verschickt bewusst nichts von selbst — also muss der Dialog
         unmissverständlich sagen, dass das Benachrichtigen Handarbeit ist. -->
    <dialog :open="pendingChange !== null">
      <article v-if="pendingChange">
        <header>
          <h3>Angemeldete werden nicht automatisch informiert</h3>
        </header>
        <p>Du änderst:</p>
        <ul>
          <li v-for="c in pendingChange.changes" :key="c.label">
            <strong>{{ c.label }}</strong>: {{ c.from }} → {{ c.to }}
          </li>
        </ul>
        <p>
          <strong>
            Funke verschickt dazu keine Mail. Alle bereits angemeldeten Personen
            haben die alten Angaben schriftlich und erfahren nichts von dieser
            Änderung, solange du sie nicht selbst informierst.
          </strong>
        </p>
        <p>
          <small>
            Dafür gibt es auf der Veranstaltungsseite den Tab „Nachrichten“ —
            dort erreichst du alle Angemeldeten auf einmal.
          </small>
        </p>
        <footer>
          <button type="button" class="secondary" @click="pendingChange = null">
            Abbrechen
          </button>
          <button type="button" @click="confirmSubmit">
            Verstanden — speichern
          </button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../services/api'
import EventForm from '../../components/EventForm.vue'
import PageHeader from '../../components/PageHeader.vue'
import { showToast } from '../../composables/useToast.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

const router = useRouter()

const event = ref(null)
const loading = ref(false)
const loadError = ref(null)
const submitting = ref(false)
const submitError = ref(null)

const isNew = computed(() => !props.eventId)
const pendingChange = ref(null)

const backTarget = computed(() =>
  isNew.value ? '/admin/events' : `/admin/events/${props.eventId}`,
)

// Vor dem Anmeldeschluss ist alles frei. Danach hat die Verlosung gegen Plätze
// und Frist gerechnet, und der Name hängt am Einlass (Spec 020: QR-Codes
// sterben beim Umbenennen) — also bleiben nur die drei Felder offen, die
// niemanden fehlleiten. Muss zur Whitelist im Backend passen.
const EDITABLE_AFTER_LOTTERY = ['description', 'startAt', 'location']
const ALL_FIELDS = [
  'name', 'location', 'description', 'startAt',
  'capacity', 'registrationDeadline', 'reminderSchedule', 'autopromoteWaitlist',
]
const OPEN_STATUSES = ['DRAFT', 'OPEN']

const lockedFields = computed(() => {
  if (isNew.value || !event.value) return []
  if (OPEN_STATUSES.includes(event.value.status)) return []
  return ALL_FIELDS.filter((f) => !EDITABLE_AFTER_LOTTERY.includes(f))
})

onMounted(async () => {
  if (isNew.value) return
  loading.value = true
  try {
    event.value = await adminApi.getEvent(props.eventId)
  } catch (err) {
    loadError.value = err.message || 'Veranstaltung konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
})

function formatWhen(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Nur Termin und Ort lösen den Dialog aus. Eine Beschreibung zu korrigieren
// führt niemanden an den falschen Steg, und ein Dialog, der bei jeder
// Kleinigkeit aufpoppt, wird nach dem dritten Mal weggeklickt.
function breakingChanges(formData) {
  if (isNew.value || !event.value) return []
  if (OPEN_STATUSES.includes(event.value.status)) return []

  const out = []
  const oldStart = event.value.start_at
  if (formData.start_at && new Date(formData.start_at).getTime() !== new Date(oldStart).getTime()) {
    out.push({ label: 'Datum & Uhrzeit', from: formatWhen(oldStart), to: formatWhen(formData.start_at) })
  }
  const oldLocation = event.value.location || ''
  if ((formData.location || '') !== oldLocation) {
    out.push({ label: 'Ort', from: oldLocation || '—', to: formData.location || '—' })
  }
  return out
}

async function handleSubmit(formData) {
  const changes = breakingChanges(formData)
  if (changes.length) {
    pendingChange.value = { formData, changes }
    return
  }
  await save(formData)
}

async function confirmSubmit() {
  const { formData } = pendingChange.value
  pendingChange.value = null
  await save(formData)
}

async function save(formData) {
  submitting.value = true
  submitError.value = null
  try {
    if (isNew.value) {
      const created = await adminApi.createEvent(formData)
      showToast('Veranstaltung erstellt', 'success')
      router.replace(`/admin/events/${created.id}`)
    } else {
      await adminApi.updateEvent(props.eventId, formData)
      showToast('Änderungen gespeichert', 'success')
      router.replace(`/admin/events/${props.eventId}`)
    }
  } catch (err) {
    submitError.value = err.message || 'Speichern fehlgeschlagen'
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  router.push(backTarget.value)
}
</script>

<style scoped>
.event-edit-page {
  padding-bottom: 2rem;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}
</style>
