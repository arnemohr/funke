<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — dein Eintritts-Code wird geladen ...
    </div>

    <!-- Error state: the backend returns one bare 404 for every rejection
         (wrong token, unknown person, removed member) — deliberately, so this
         page can't be used to probe who is in a group. -->
    <div v-else-if="error" role="alert" class="ticket-error">
      <h2>Dieser Eintritts-Code lässt sich nicht öffnen</h2>
      <p>{{ error }}</p>
      <p class="error-hint">
        Frag am besten die Person, die dich angemeldet hat — sie kann dir den Code nochmal
        schicken.
      </p>
    </div>

    <template v-else-if="ticket">
      <header class="ticket-header">
        <p class="eyebrow">Dein Eintritts-Code</p>
        <h2>{{ ticket.name }}</h2>
        <p class="event-line">{{ ticket.event_name }} · {{ ticket.event_period }}</p>
      </header>

      <!-- Self-removed (this session) or the whole registration is cancelled. -->
      <section v-if="selfCancelled" class="callout callout-warning cancelled-box">
        <p class="callout-title">Du bist abgemeldet</p>
        <p>
          Wir haben {{ ticket.contact_name }} Bescheid gegeben. Dein Eintritts-Code
          funktioniert nicht mehr.
        </p>
      </section>

      <section v-else-if="ticket.cancelled" class="callout callout-warning cancelled-box">
        <p class="callout-title">Diese Anmeldung ist storniert</p>
        <p>
          {{ ticket.contact_name }} hat die Anmeldung zurückgezogen — dein Eintritts-Code
          funktioniert nicht mehr.
        </p>
      </section>

      <template v-else>
        <section class="qr-section">
          <canvas ref="qrCanvas" class="qr-canvas"></canvas>
          <p class="qr-hint">
            Am Einlass zeigst du diesen Code vor — ein Screenshot reicht.
          </p>
        </section>

        <!-- Own days (spec 021). Editable only while the festival still accepts
             changes; otherwise the same days are shown read-only. -->
        <section class="days-section">
          <h3>Wann kommst du?</h3>

          <template v-if="ticket.editable">
            <p class="days-intro">
              Sag uns, an welchen Tagen du wirklich da bist — das hilft uns bei Essen und
              Planung. Das gilt nur für dich, nicht für die anderen aus deiner Gruppe.
            </p>

            <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>
            <div v-if="saveSuccess" role="status" class="success-msg">{{ saveSuccess }}</div>

            <label v-for="slot in ticket.all_slots" :key="slot.key" class="slot-checkbox">
              <input type="checkbox" v-model="chosenSlots[slot.key]" :disabled="saving" />
              <span>{{ slot.label }}</span>
            </label>

            <button
              type="button"
              class="save-days-btn"
              :disabled="saving || !anySlotChosen || !slotsChanged"
              :aria-busy="saving"
              @click="handleSaveSlots"
            >
              {{ saving ? 'Wird gespeichert ...' : 'Tage speichern' }}
            </button>
            <small v-if="!anySlotChosen" class="field-note">
              Wähle mindestens einen Tag — oder melde dich unten ganz ab.
            </small>
          </template>

          <ul v-else class="day-list">
            <li v-for="label in ticket.slot_labels" :key="label">{{ label }}</li>
            <li v-if="!ticket.slot_labels.length" class="day-list-empty">
              Noch keine Tage eingetragen
            </li>
          </ul>
        </section>
      </template>

      <!-- What this page can and cannot do — stated outright, because the guest
           needs to know where the rest lives (spec 020 D1 / 021 E3). -->
      <section v-if="!selfCancelled && !ticket.cancelled" class="callout callout-info changes-box">
        <p class="callout-title">Etwas anderes ändern?</p>
        <p>
          Deinen Namen, die Übernachtung oder die Anmeldung der ganzen Gruppe ändert
          <strong>{{ ticket.contact_name }}</strong> — dort läuft die Anmeldung für euch alle
          zusammen.
        </p>
      </section>

      <section v-if="ticket.participation_hint && !selfCancelled" class="callout callout-warm">
        <p class="callout-title">Pack mit an!</p>
        <p class="participation-hint-text" v-html="linkify(ticket.participation_hint)"></p>
      </section>

      <p v-if="ticket.contact_hint" class="contact-line">
        Fragen? <a :href="`mailto:${ticket.contact_hint}`">{{ ticket.contact_hint }}</a>
      </p>

      <!-- Self-removal (spec 021 E3), deliberately last and understated. -->
      <div
        v-if="ticket.editable && !selfCancelled && !ticket.cancelled"
        class="self-cancel-area"
      >
        <button type="button" class="outline secondary" @click="showCancelDialog = true">
          Ich kann doch nicht
        </button>
      </div>
    </template>

    <dialog :open="showCancelDialog">
      <article>
        <h3>Wirklich abmelden?</h3>
        <p>
          Du wirst aus der Anmeldung von {{ ticket?.contact_name }} ausgetragen und dein
          Eintritts-Code gilt nicht mehr. Das kannst du hier nicht rückgängig machen —
          nur {{ ticket?.contact_name }} kann dich wieder eintragen.
        </p>
        <div v-if="cancelError" role="alert" class="error">{{ cancelError }}</div>
        <footer>
          <button type="button" class="secondary" :disabled="cancelling" @click="showCancelDialog = false">
            Doch dabei bleiben
          </button>
          <button type="button" :disabled="cancelling" :aria-busy="cancelling" @click="handleSelfCancel">
            {{ cancelling ? 'Wird abgemeldet ...' : 'Ja, abmelden' }}
          </button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import QRCode from 'qrcode'
import { publicApi } from '../../services/api'
import { linkify } from '../../utils/linkify.js'

const props = defineProps({
  eventId: { type: String, default: '' },
  registrationId: { type: String, default: '' },
  personIndex: { type: [String, Number], default: '' },
})

const route = useRoute()

const loading = ref(true)
const error = ref(null)
const ticket = ref(null)
const qrCanvas = ref(null)

const saving = ref(false)
const saveError = ref(null)
const saveSuccess = ref(null)
const cancelling = ref(false)
const cancelError = ref(null)
const showCancelDialog = ref(false)
const selfCancelled = ref(false)

// Checkbox state keyed by slot key, plus a snapshot of what was loaded so the
// save button can stay disabled until something actually changed.
const chosenSlots = ref({})
const loadedSlots = ref([])

const anySlotChosen = computed(() => Object.values(chosenSlots.value).some(Boolean))

const selectedKeys = computed(() =>
  (ticket.value?.all_slots || []).map((s) => s.key).filter((k) => chosenSlots.value[k]),
)

const slotsChanged = computed(() => {
  const before = [...loadedSlots.value].sort().join(',')
  const now = [...selectedKeys.value].sort().join(',')
  return before !== now
})

function applyTicket(payload) {
  ticket.value = payload
  const map = {}
  for (const slot of payload.all_slots || []) {
    map[slot.key] = (payload.own_slots || []).includes(slot.key)
  }
  chosenSlots.value = map
  loadedSlots.value = [...(payload.own_slots || [])]
}

function ids() {
  return [
    props.eventId || route.params.eventId,
    props.registrationId || route.params.registrationId,
    props.personIndex || route.params.personIndex,
    route.query.token,
  ]
}

// Signed fresh by the backend on every load, so a rename or a day change on the
// group never leaves this page showing a code the gate would reject.
async function renderQr() {
  await nextTick()
  if (!qrCanvas.value || !ticket.value?.ticket_code) return
  try {
    await QRCode.toCanvas(qrCanvas.value, ticket.value.ticket_code, { width: 260, margin: 2 })
  } catch {
    // Non-critical — the canvas stays blank and the guest falls back to the
    // gate's name search.
  }
}

watch(ticket, renderQr)

async function handleSaveSlots() {
  saveError.value = null
  saveSuccess.value = null
  if (!anySlotChosen.value) return

  saving.value = true
  try {
    const payload = await publicApi.updatePersonSlots(...ids(), selectedKeys.value)
    applyTicket(payload)
    saveSuccess.value = 'Alles klar — wir haben deine Tage gespeichert!'
    setTimeout(() => { saveSuccess.value = null }, 3000)
  } catch (err) {
    saveError.value = err.message || 'Speichern hat nicht geklappt. Versuch es nochmal.'
  } finally {
    saving.value = false
  }
}

async function handleSelfCancel() {
  cancelError.value = null
  cancelling.value = true
  try {
    await publicApi.cancelPersonTicket(...ids())
    selfCancelled.value = true
    showCancelDialog.value = false
  } catch (err) {
    cancelError.value = err.message || 'Das hat nicht geklappt. Versuch es nochmal.'
  } finally {
    cancelling.value = false
  }
}

onMounted(async () => {
  const [eventId, registrationId, personIndex, token] = ids()
  if (!token) {
    error.value = 'Dieser Link ist unvollständig.'
    loading.value = false
    return
  }

  try {
    applyTicket(await publicApi.getPersonTicket(eventId, registrationId, personIndex, token))
  } catch (err) {
    error.value = err.message || 'Der Eintritts-Code konnte nicht geladen werden.'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.loading-state {
  padding: var(--space-6) 0;
  text-align: center;
}

.ticket-error {
  padding: var(--space-4) 0;
}

.error-hint {
  color: var(--pico-muted-color);
  font-size: 0.9rem;
}

.ticket-header {
  margin-bottom: var(--space-5);
}

.eyebrow {
  margin: 0;
  font-size: 0.85rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--pico-muted-color);
}

.ticket-header h2 {
  margin: var(--space-1) 0 var(--space-2);
}

.event-line {
  margin: 0;
  color: var(--pico-muted-color);
}

.qr-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--space-5);
}

.qr-canvas {
  max-width: 100%;
  height: auto;
  border: 1px solid var(--pico-muted-border-color);
  border-radius: var(--pico-border-radius);
  background: #fff;
}

.qr-hint {
  margin: var(--space-2) 0 0;
  color: var(--pico-muted-color);
  font-size: 0.9rem;
  text-align: center;
}

.days-section {
  margin-bottom: var(--space-5);
}

.days-section h3 {
  font-size: 1rem;
  margin-bottom: var(--space-2);
}

.days-intro {
  color: var(--pico-muted-color);
  font-size: 0.9rem;
  margin-bottom: var(--space-3);
}

.slot-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.save-days-btn {
  margin-top: var(--space-3);
}

.success-msg {
  color: var(--pico-ins-color, #16a34a);
  margin-bottom: var(--space-2);
}

.day-list {
  margin: 0;
  padding-left: var(--space-5);
}

.day-list-empty {
  color: var(--pico-muted-color);
  list-style: none;
  margin-left: calc(-1 * var(--space-5));
}

.cancelled-box,
.changes-box {
  margin-bottom: var(--space-4);
}

.participation-hint-text {
  white-space: pre-line;
}

.contact-line {
  color: var(--pico-muted-color);
  font-size: 0.9rem;
}

/* Understated on purpose — a real action, but not one to invite by accident. */
.self-cancel-area {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid var(--pico-muted-border-color);
}
</style>
