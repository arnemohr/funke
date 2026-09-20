<template>
  <article style="position: relative;">
    <PageHeader back="/admin/festival" back-label="Festivals">
      <template #title>
        <span v-if="festivalEvent">{{ festivalEvent.name }}</span>
        <span v-else>Festival</span>
      </template>
      <template #chip>
        <span
          v-if="festivalEvent"
          :class="['status-badge', `status-${festivalEvent.status.toLowerCase()}`]"
        >
          {{ formatEventStatus(festivalEvent.status) }}
        </span>
      </template>
    </PageHeader>

    <!-- Loading -->
    <div v-if="loading" aria-busy="true">
      Festival wird geladen...
    </div>

    <!-- Error -->
    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <template v-else-if="festivalEvent">
      <FestivalHelp title="Wie's weitergeht">
        <p>Die Zeitfenster unten sind die Kästchen im Anmeldeformular. Kontakt-Adresse und Mitmach-Hinweis landen automatisch in den Mails und auf der Anmeldeseite.</p>
        <p>Wenn das Festival „Offen" ist: Gästelisten anlegen und die Einladungslinks verschicken — erst Kern-Crew, dann der Rest.</p>
        <p>Anmelden und Ändern geht bis zum Schluss. Früher dicht machen: „Anmeldung schließen" oben.</p>
        <p>Fürs Tor: Scanner-Link an die Tor-Crew schicken und die Gate-Liste ausdrucken — Papier geht immer.</p>
      </FestivalHelp>

      <div v-if="availableTransitions.length" class="festival-toolbar">
        <div class="status-actions">
          <button
            v-for="t in availableTransitions"
            :key="t.status"
            type="button"
            class="outline"
            :class="{ secondary: t.status === 'CANCELLED' }"
            :disabled="transitioning === t.status"
            :aria-busy="transitioning === t.status"
            @click="handleTransition(t.status)"
          >
            {{ t.label }}
          </button>
        </div>
      </div>

      <!-- Section shortcuts: the working areas of a festival -->
      <nav class="section-nav" aria-label="Festival-Bereiche">
        <button type="button" class="outline" @click="goToInvites">Gästelisten</button>
        <button type="button" class="outline" @click="goToHeadcount">Wer kommt wann</button>
        <button type="button" class="outline" @click="goToRegistrations">Anmeldungen</button>
        <button type="button" class="outline" @click="goToLostFound">Fundsachen</button>
        <button type="button" class="outline" @click="goToEventPhotos">Fotos</button>
      </nav>

      <!-- Einlass: scanner gate link (T303) + CSV exports -->
      <div class="gate-section">
        <h4>Einlass &amp; Listen</h4>
        <div v-if="gateUrl" class="gate-link-row">
          <code class="gate-url">{{ gateUrl }}</code>
          <button type="button" class="outline" @click="copyGateLink">
            Scanner-Link kopieren
          </button>
          <button
            type="button"
            class="outline secondary"
            :disabled="rotatingGate"
            :aria-busy="rotatingGate"
            @click="handleRotateGateToken"
          >
            Link erneuern
          </button>
        </div>
        <div v-else-if="loadingGate" aria-busy="true">Scanner-Link wird geladen ...</div>
        <p v-else-if="gateError" class="gate-error" role="alert">{{ gateError }}</p>

        <div class="export-row">
          <button
            type="button"
            class="secondary outline"
            :disabled="exporting !== null"
            :aria-busy="exporting === 'gate'"
            @click="handleExport('gate')"
          >
            Gate-Liste (CSV)
          </button>
        </div>
      </div>

      <!-- Settings + slot editor form -->
      <form class="compact-form" @submit.prevent="handleSubmit">
        <label for="festName">
          Name *
          <input id="festName" v-model="form.name" type="text" required placeholder="Betriebsfeier Julius Grube Schiffswerft" :disabled="submitting" />
        </label>

        <label for="festDescription">
          Beschreibung
          <textarea id="festDescription" v-model="form.description" rows="2" :disabled="submitting" />
        </label>

        <div class="form-row">
          <label for="festLocation">
            Ort
            <input id="festLocation" v-model="form.location" type="text" :disabled="submitting" />
          </label>
          <label for="festCapacity">
            Gesamt-Kapazität
            <input id="festCapacity" v-model.number="form.capacity" type="number" min="1" max="2000" :disabled="submitting" />
            <small>Richtwert für euch — blockiert nie eine Anmeldung</small>
          </label>
        </div>

        <div class="form-row">
          <label for="festStartAt">
            Beginn *
            <input id="festStartAt" v-model="form.startAt" type="datetime-local" required :disabled="submitting" />
          </label>
          <label for="festEndAt">
            Ende *
            <input id="festEndAt" v-model="form.endAt" type="datetime-local" required :disabled="submitting" />
          </label>
        </div>

        <label for="festContactHint">
          Kontakt-Adresse
          <input id="festContactHint" v-model="form.contactHint" type="text" placeholder="z.B. werft@funke.example" :disabled="submitting" />
          <small>Für Rückfragen der Gäste — landet in den Mails und auf der Anmeldeseite</small>
        </label>

        <label for="festParticipationHint">
          Mitmach-Hinweis
          <textarea id="festParticipationHint" v-model="form.participationHint" rows="3" :disabled="submitting" />
          <small>Steht auf der Anmeldeseite und in der Bestätigungs-Mail — am besten mit Schichtplan-Link</small>
        </label>

        <fieldset class="slot-editor">
          <legend>Zeitfenster</legend>

          <div v-for="(slot, i) in form.slots" :key="i" class="slot-row">
            <input
              v-model="slot.label"
              type="text"
              placeholder="Label, z.B. Freitag"
              required
              :disabled="submitting"
              class="slot-label"
            />
            <input v-model="slot.date" type="date" required :disabled="submitting" class="slot-date" />
            <label class="slot-night">
              <input type="checkbox" v-model="slot.is_night" :disabled="submitting" />
              Nacht
            </label>
            <input
              v-model.number="slot.capacity"
              type="number"
              min="1"
              placeholder="Kapazität (optional)"
              :disabled="submitting"
              class="slot-capacity"
            />
            <div class="slot-row-actions">
              <button type="button" class="outline slot-btn" title="Nach oben" :disabled="submitting || i === 0" @click="moveSlot(i, -1)">↑</button>
              <button type="button" class="outline slot-btn" title="Nach unten" :disabled="submitting || i === form.slots.length - 1" @click="moveSlot(i, 1)">↓</button>
              <button type="button" class="outline slot-btn remove-btn" title="Zeitfenster entfernen" :disabled="submitting" @click="removeSlot(i)">✕</button>
            </div>
          </div>

          <button type="button" class="outline" :disabled="submitting" @click="addSlot">
            + Zeitfenster hinzufügen
          </button>

          <p v-if="slotsUnsorted" class="hint-warning">
            Zeitfenster sind nicht chronologisch nach Datum sortiert — das Speichern wird abgelehnt.
          </p>
        </fieldset>

        <footer>
          <button type="submit" :disabled="submitting" :aria-busy="submitting">
            {{ submitting ? 'Wird gespeichert...' : 'Speichern' }}
          </button>
        </footer>
      </form>

      <!-- Datenschutz: anonymisieren (nur nach Abschluss/Absage — vorher
           braucht das Festival seine Adressen noch) -->
      <div v-if="canAnonymize || isAnonymized" class="danger-zone">
        <h4>Datenschutz</h4>
        <p v-if="isAnonymized">
          <small>
            Personendaten anonymisiert am {{ formatDateTimeLocal(festivalEvent.anonymized_at) }}.
            Namen, Adressen und Telefonnummern sind entfernt; Zahlen, Zeitfenster
            und Check-ins bleiben erhalten.
          </small>
        </p>
        <button
          v-else
          type="button"
          class="btn-danger outline"
          @click="anonymizeModalOpen = true"
        >
          Personendaten anonymisieren
        </button>
      </div>

      <!-- Gefahrenzone: delete (only once cancelled, mirrors the regular
           event delete guard — DELETE /api/admin/events/{id} requires
           CANCELLED too) -->
      <div v-if="festivalEvent.status === 'CANCELLED'" class="danger-zone">
        <h4>Gefahrenzone</h4>
        <button type="button" class="btn-danger outline" @click="deleteModalOpen = true">
          Festival löschen
        </button>
      </div>
    </template>

    <!-- Anonymize modal -->
    <dialog :open="anonymizeModalOpen">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="closeAnonymizeModal" />
          <h3>Personendaten anonymisieren</h3>
        </header>
        <p>
          Namen, E-Mail-Adressen, Telefonnummern, Anmerkungen und alle
          verschickten Mails werden unwiderruflich durch Pseudonyme ersetzt —
          in Anmeldungen, Einladungen und im Check-in-Protokoll.
        </p>
        <p>
          <strong>Erhalten bleiben:</strong> Gruppengrößen, Zeitfenster, Zelt-/
          Camper-Zahlen, Übernachtungs-Zusagen, Kontingent-Zahlen und alle
          Check-in-Auswertungen.
        </p>
        <p>
          <small>
            Alle bereits verschickten Verwaltungs-, Ticket- und Einladungslinks
            hören danach auf zu funktionieren. Diese Aktion kann nicht rückgängig
            gemacht werden.
          </small>
        </p>
        <div v-if="anonymizeError" role="alert" class="error-message">{{ anonymizeError }}</div>
        <!-- Ein großes Festival braucht mehrere Durchläufe — Fortschritt statt Stillstand. -->
        <p v-else-if="anonymizing && anonymizeProgress" role="status">
          <small>{{ anonymizeProgress }} Datensätze bereinigt...</small>
        </p>
        <footer>
          <button type="button" class="secondary" :disabled="anonymizing" @click="closeAnonymizeModal">
            Abbrechen
          </button>
          <button
            type="button"
            class="btn-danger"
            :disabled="anonymizing"
            :aria-busy="anonymizing"
            @click="handleAnonymize"
          >
            {{ anonymizing ? 'Wird anonymisiert...' : 'Anonymisieren' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Delete modal -->
    <dialog :open="deleteModalOpen">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="closeDeleteModal" />
          <h3>Festival löschen</h3>
        </header>
        <p>Festival endgültig löschen? Alle Einladungen, Anmeldungen und Check-ins werden unwiderruflich gelöscht.</p>
        <p><small>Diese Aktion kann nicht rückgängig gemacht werden.</small></p>
        <div v-if="deleteError" role="alert" class="error-message">{{ deleteError }}</div>
        <footer>
          <button type="button" class="secondary" :disabled="deleting" @click="closeDeleteModal">Abbrechen</button>
          <button type="button" class="btn-danger" :disabled="deleting" :aria-busy="deleting" @click="handleDeleteFestival">
            {{ deleting ? 'Wird gelöscht...' : 'Löschen' }}
          </button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../../services/api'
import PageHeader from '../../../components/PageHeader.vue'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'
import { showToast } from '../../../composables/useToast.js'
import { berlinToUTCISO, formatDateTimeLocal, formatEventStatus } from '../../../utils/formatters.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

const router = useRouter()

const loading = ref(true)
const loadError = ref(null)
const submitting = ref(false)
const transitioning = ref(null)
const exporting = ref(null)

const festivalEvent = ref(null)

const gateUrl = ref(null)
const loadingGate = ref(false)
const rotatingGate = ref(false)
const gateError = ref('')

const deleteModalOpen = ref(false)
const deleting = ref(false)
const deleteError = ref(null)

const anonymizeModalOpen = ref(false)
const anonymizing = ref(false)
const anonymizeError = ref(null)
// Rows done so far, counted across the backend's passes (see adminApi.anonymizeEvent).
const anonymizeProgress = ref(0)

const isAnonymized = computed(() => Boolean(festivalEvent.value?.anonymized_at))

// Mirrors the backend guard (ANONYMIZABLE_STATUSES): before the festival is
// over it still has to be able to mail people.
const canAnonymize = computed(
  () => ['COMPLETED', 'CANCELLED'].includes(festivalEvent.value?.status),
)

function emptySlot() {
  return { label: '', date: '', is_night: false, capacity: null, _key: null, _persisted: false }
}

const form = reactive({
  name: '',
  description: '',
  location: '',
  capacity: 500,
  startAt: '',
  endAt: '',
  contactHint: '',
  participationHint: '',
  slots: [],
})

// Festival admin reads/writes go through EVENT_STATUS_TRANSITIONS (event.py:35) —
// mirrored here since the frontend has no direct access to the backend dict.
// LOTTERY_PENDING is deliberately excluded from the UI: the festival runbook's
// status machine is DRAFT → OPEN → REGISTRATION_CLOSED → CONFIRMED → COMPLETED
// (spec.md:279) — festivals never run a lottery, even though the underlying
// transitions dict is shared with SINGLE events.
const STATUS_TRANSITIONS = {
  DRAFT: ['OPEN', 'CANCELLED'],
  OPEN: ['REGISTRATION_CLOSED', 'CANCELLED'],
  REGISTRATION_CLOSED: ['OPEN', 'LOTTERY_PENDING', 'CONFIRMED', 'CANCELLED'],
  LOTTERY_PENDING: ['CONFIRMED', 'CANCELLED'],
  CONFIRMED: ['COMPLETED', 'CANCELLED'],
  COMPLETED: [],
  CANCELLED: [],
}

function labelForTransition(current, target) {
  if (target === 'OPEN' && current === 'REGISTRATION_CLOSED') return 'Anmeldung wieder öffnen'
  const labels = {
    OPEN: 'Veröffentlichen',
    REGISTRATION_CLOSED: 'Anmeldung schließen',
    CONFIRMED: 'Bestätigen',
    COMPLETED: 'Abschließen',
    CANCELLED: 'Absagen',
  }
  return labels[target] || target
}

const availableTransitions = computed(() => {
  if (!festivalEvent.value) return []
  const next = STATUS_TRANSITIONS[festivalEvent.value.status] || []
  return next
    .filter((s) => s !== 'LOTTERY_PENDING')
    .map((s) => ({ status: s, label: labelForTransition(festivalEvent.value.status, s) }))
})

const slotsUnsorted = computed(() => {
  const dates = form.slots.map((s) => s.date).filter(Boolean)
  const sorted = [...dates].sort()
  return dates.length > 1 && JSON.stringify(dates) !== JSON.stringify(sorted)
})

function populateForm(event) {
  form.name = event.name
  form.description = event.description || ''
  form.location = event.location || ''
  form.capacity = event.capacity
  form.startAt = formatDateTimeLocal(event.start_at)
  form.endAt = formatDateTimeLocal(event.end_at)
  form.contactHint = event.contact_hint || ''
  form.participationHint = event.participation_hint || ''
  form.slots = (event.festival_slots || []).map((slot) => ({
    label: slot.label,
    date: slot.date,
    is_night: slot.is_night,
    capacity: slot.capacity ?? null,
    _key: slot.key,
    _persisted: true,
  }))
}

function slugifyBase(label) {
  return (
    (label || '')
      .trim()
      .toLowerCase()
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'zeitfenster'
  )
}

// Existing (already-persisted) slots keep their server-assigned key even if the
// label is edited afterwards — only brand-new rows get a freshly slugified key.
// This avoids silently reshuffling `attendance_slots` keys already referenced by
// registrations just because an admin tweaked a label's wording.
function buildSlotsPayload() {
  const usedKeys = new Set(form.slots.filter((s) => s._key).map((s) => s._key))
  return form.slots.map((slot) => {
    let key = slot._key
    if (!key) {
      const base = slugifyBase(slot.label)
      let candidate = base
      let i = 2
      while (usedKeys.has(candidate)) {
        candidate = `${base}-${i}`
        i += 1
      }
      usedKeys.add(candidate)
      key = candidate
    }
    return {
      key,
      label: slot.label.trim(),
      date: slot.date,
      is_night: slot.is_night,
      capacity: slot.capacity || null,
    }
  })
}

function buildPayload() {
  return {
    name: form.name.trim(),
    description: form.description?.trim() || null,
    location: form.location?.trim() || null,
    capacity: form.capacity,
    start_at: berlinToUTCISO(form.startAt),
    end_at: berlinToUTCISO(form.endAt),
    // Anmeldeschluss knob removed (Ä14/Ä20) — registration simply runs
    // until the festival ends, so the deadline always equals end_at.
    registration_deadline: berlinToUTCISO(form.endAt),
    contact_hint: form.contactHint?.trim() || null,
    participation_hint: form.participationHint?.trim() || null,
    festival_slots: buildSlotsPayload(),
  }
}

function addSlot() {
  form.slots.push(emptySlot())
}

function removeSlot(index) {
  const slot = form.slots[index]
  if (slot._persisted) {
    const ok = window.confirm(
      'Zeitfenster mit Anmeldungen nicht löschen — erst mit dem Team klären. Trotzdem entfernen?',
    )
    if (!ok) return
  }
  form.slots.splice(index, 1)
}

function moveSlot(index, delta) {
  const target = index + delta
  if (target < 0 || target >= form.slots.length) return
  const slots = form.slots
  const [moved] = slots.splice(index, 1)
  slots.splice(target, 0, moved)
}

async function loadFestival() {
  loading.value = true
  loadError.value = null
  try {
    const result = await adminApi.festival.getEvent(props.eventId)
    festivalEvent.value = result
    populateForm(result)
    loadGateToken()
  } catch (err) {
    loadError.value = err.message || 'Festival konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
}

// Gate / scanner link (T303) — lazy GET generates the token server-side on
// first call and is idempotent afterwards, so we just fetch it eagerly here.
async function loadGateToken() {
  loadingGate.value = true
  gateError.value = ''
  try {
    const result = await adminApi.festival.getGateToken(festivalEvent.value.id)
    gateUrl.value = result.gate_url
  } catch (err) {
    gateError.value = err.message || 'Scanner-Link konnte nicht geladen werden'
  } finally {
    loadingGate.value = false
  }
}

function copyGateLink() {
  const url = gateUrl.value
  navigator.clipboard.writeText(url).then(
    () => showToast('Scanner-Link kopiert!', 'success'),
    () => prompt('Kopiere diesen Link:', url),
  )
}

async function handleRotateGateToken() {
  const ok = window.confirm(
    'Neuen Scanner-Link erzeugen? Der alte Scanner-Link funktioniert danach nicht mehr.',
  )
  if (!ok) return

  rotatingGate.value = true
  try {
    const result = await adminApi.festival.rotateGateToken(festivalEvent.value.id)
    gateUrl.value = result.gate_url
    showToast('Scanner-Link erneuert', 'success')
  } catch (err) {
    showToast(err.message || 'Scanner-Link konnte nicht erneuert werden', 'error')
  } finally {
    rotatingGate.value = false
  }
}

async function handleSubmit() {
  submitting.value = true
  try {
    const payload = buildPayload()
    const updated = await adminApi.festival.updateEvent(festivalEvent.value.id, payload)
    festivalEvent.value = updated
    populateForm(updated)
    showToast('Änderungen gespeichert', 'success')
  } catch (err) {
    showToast(err.message || 'Speichern fehlgeschlagen', 'error')
  } finally {
    submitting.value = false
  }
}

async function handleTransition(status) {
  if (status === 'CANCELLED') {
    const ok = window.confirm('Festival wirklich absagen? Das lässt sich nicht rückgängig machen.')
    if (!ok) return
  }
  // COMPLETED is a one-way door with teeth: the gate scanner refuses to boot
  // for a completed event (checkin.py `_GATE_OPEN_STATUSES`) and every admin
  // edit is frozen. From CONFIRMED it sits one unguarded click away from
  // „Absagen", which is exactly the misclick this catches. `window.confirm`
  // rather than a <dialog>, to match the branch above — same shape, no new
  // state to get wrong.
  if (status === 'COMPLETED') {
    const ok = window.confirm(
      'Festival wirklich abschließen?\n\n' +
        'Der Einlass-Scanner funktioniert danach nicht mehr, und Anmeldungen ' +
        'lassen sich nicht mehr bearbeiten.\n\n' +
        'Das lässt sich nicht rückgängig machen.',
    )
    if (!ok) return
  }
  transitioning.value = status
  try {
    const updated = await adminApi.festival.setStatus(festivalEvent.value.id, status)
    festivalEvent.value = updated
    showToast('Status aktualisiert', 'success')
    if (status === 'CANCELLED') {
      router.push('/admin/festival')
      return
    }
    populateForm(updated)
  } catch (err) {
    showToast(err.message || 'Status konnte nicht geändert werden', 'error')
  } finally {
    transitioning.value = null
  }
}

// CSV download (T206 helper): printable gate/door list (Ä9 floor,
// reprinted every festival evening).
async function handleExport(view) {
  exporting.value = view
  try {
    await adminApi.festival.exportGateCsv(festivalEvent.value.id)
  } catch (err) {
    showToast(err.message || 'Export fehlgeschlagen', 'error')
  } finally {
    exporting.value = null
  }
}

function closeDeleteModal() {
  deleteModalOpen.value = false
  deleteError.value = null
}

async function handleDeleteFestival() {
  deleting.value = true
  deleteError.value = null
  try {
    await adminApi.festival.deleteEvent(festivalEvent.value.id)
    deleteModalOpen.value = false
    showToast('Festival gelöscht', 'success')
    router.push('/admin/festival')
  } catch (err) {
    deleteError.value = err.message || 'Festival konnte nicht gelöscht werden'
  } finally {
    deleting.value = false
  }
}

function closeAnonymizeModal() {
  anonymizeModalOpen.value = false
  anonymizeError.value = null
  anonymizeProgress.value = 0
}

async function handleAnonymize() {
  anonymizing.value = true
  anonymizeError.value = null
  anonymizeProgress.value = 0
  try {
    // Shared route for SINGLE and FESTIVAL events — the work is identical.
    const result = await adminApi.anonymizeEvent(festivalEvent.value.id, {
      onProgress: ({ rows }) => {
        anonymizeProgress.value = rows
      },
    })
    festivalEvent.value = { ...festivalEvent.value, anonymized_at: result.anonymized_at }
    anonymizeModalOpen.value = false
    showToast(`Anonymisiert — ${result.rows_touched} Datensätze bereinigt`, 'success')
  } catch (err) {
    anonymizeError.value = err.message || 'Anonymisierung fehlgeschlagen'
  } finally {
    anonymizing.value = false
  }
}

function goToInvites() {
  router.push(`/admin/festival/${festivalEvent.value.id}/invites`)
}

function goToHeadcount() {
  router.push(`/admin/festival/${festivalEvent.value.id}/headcount`)
}

function goToRegistrations() {
  router.push(`/admin/festival/${festivalEvent.value.id}/registrations`)
}

// Spec 023 — the Fundsachen page is shared with SINGLE events and lives under
// /admin/events/…, so it is addressed by route name rather than by path.
function goToLostFound() {
  router.push({ name: 'admin-lost-and-found', params: { eventId: festivalEvent.value.id } })
}

// Spec 024 — same arrangement for the photo collection: one admin page under
// /admin/events/…, reached by name from both event kinds.
function goToEventPhotos() {
  router.push({ name: 'admin-event-photos', params: { eventId: festivalEvent.value.id } })
}

onMounted(loadFestival)
</script>

<style scoped>
.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.festival-toolbar {
  margin-bottom: var(--space-4);
}

.status-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.status-actions button {
  width: auto;
  margin: 0;
  min-height: 44px;
}

/* The working areas — full-width tap targets on phones. */
.section-nav {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}

.section-nav button {
  margin: 0;
  min-height: 44px;
}

.gate-section {
  margin-bottom: var(--space-5);
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.gate-section h4 {
  margin-bottom: var(--space-2);
}

.gate-link-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.gate-url {
  flex: 1 1 auto;
  overflow-wrap: anywhere;
}

.gate-link-row button {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.export-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.export-row button {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.gate-error {
  color: var(--color-danger-text);
  margin: 0;
}

.compact-form label {
  margin-bottom: 0.75rem;
}

.compact-form textarea {
  margin-bottom: 0;
}

.compact-form small {
  color: var(--color-text-muted);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.form-row label {
  margin-bottom: 0.75rem;
}

.slot-editor {
  border: none;
  padding: 0;
  margin: 0 0 var(--pico-spacing);
}

.slot-editor legend {
  padding: 0;
  font-weight: bold;
  margin-bottom: 0.5rem;
}

.slot-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--pico-border-radius);
}

.slot-row input {
  margin-bottom: 0;
}

.slot-label {
  flex: 2;
  min-width: 8rem;
}

.slot-date {
  flex: 1;
  min-width: 9rem;
}

.slot-night {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  white-space: nowrap;
  margin-bottom: 0;
}

.slot-capacity {
  flex: 1;
  min-width: 8rem;
}

.slot-row-actions {
  display: flex;
  gap: 0.25rem;
  margin-left: auto;
}

.slot-btn {
  width: auto;
  min-width: 2.25rem;
  padding: 0.4rem 0.6rem;
  margin: 0;
}

.remove-btn {
  color: var(--color-danger-text);
  border-color: var(--color-danger-text);
}

.hint-warning {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  padding: 0.5rem 0.75rem;
  border-radius: var(--pico-border-radius);
  font-size: var(--text-sm);
}

footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}

.danger-zone {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-border);
}

.danger-zone h4 {
  margin-bottom: 0.5rem;
}

.danger-zone .btn-danger {
  width: auto;
}

@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  .section-nav {
    grid-template-columns: 1fr;
  }

  /* Slot rows stack into a card on phones — full-width inputs, 44px targets. */
  .slot-label,
  .slot-date,
  .slot-capacity {
    flex: 1 1 100%;
    min-width: 0;
  }

  .slot-night {
    width: 100%;
    min-height: 44px;
  }

  .slot-row-actions {
    margin-left: 0;
    width: 100%;
    justify-content: flex-end;
  }

  .slot-btn {
    min-height: 44px;
    min-width: 44px;
  }
}
</style>
