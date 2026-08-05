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

      <!-- Cancelled: no code, and say plainly that it no longer works. -->
      <section v-if="ticket.cancelled" class="callout callout-warning cancelled-box">
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

        <section v-if="ticket.slot_labels.length" class="days-section">
          <h3>Deine Tage</h3>
          <ul class="day-list">
            <li v-for="label in ticket.slot_labels" :key="label">{{ label }}</li>
          </ul>
        </section>
      </template>

      <!-- The read-only boundary, stated outright (spec 020 D1): this page
           holds no edit or cancel affordance, so the guest needs to know where
           changes actually happen. -->
      <section class="callout callout-info changes-box">
        <p class="callout-title">Etwas ändern?</p>
        <p>
          Änderungen — andere Tage, oder du kannst doch nicht — laufen über
          <strong>{{ ticket.contact_name }}</strong>. Die Anmeldung für euch alle läuft dort
          zusammen.
        </p>
      </section>

      <section v-if="ticket.participation_hint" class="callout callout-warm">
        <p class="callout-title">Pack mit an!</p>
        <p class="participation-hint-text" v-html="linkify(ticket.participation_hint)"></p>
      </section>

      <p v-if="ticket.contact_hint" class="contact-line">
        Fragen? <a :href="`mailto:${ticket.contact_hint}`">{{ ticket.contact_hint }}</a>
      </p>
    </template>
  </article>
</template>

<script setup>
import { onMounted, ref, watch, nextTick } from 'vue'
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

// Signed fresh by the backend on every load, so a rename or a slot change on
// the group never leaves this page showing a code the gate would reject.
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

onMounted(async () => {
  const token = route.query.token
  if (!token) {
    error.value = 'Dieser Link ist unvollständig.'
    loading.value = false
    return
  }

  try {
    ticket.value = await publicApi.getPersonTicket(
      props.eventId || route.params.eventId,
      props.registrationId || route.params.registrationId,
      props.personIndex || route.params.personIndex,
      token,
    )
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

.day-list {
  margin: 0;
  padding-left: var(--space-5);
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
</style>
