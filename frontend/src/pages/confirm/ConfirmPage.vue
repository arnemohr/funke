<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Anmeldung wird geladen...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      <h2>Fehler</h2>
      <p>{{ error }}</p>
    </div>

    <!-- Already participating -->
    <section v-else-if="registration?.status === 'PARTICIPATING'" class="status-card success">
      <div class="status-icon">✓</div>
      <h2>Du hast bereits zugesagt</h2>
      <p>Wir freuen uns auf dich!</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
        <p><strong>Personen:</strong> {{ registration.group_size }}</p>
      </div>

      <router-link to="/" class="button">Zur Startseite</router-link>
    </section>

    <!-- Already cancelled -->
    <section v-else-if="registration?.status === 'CANCELLED'" class="status-card cancelled">
      <div class="status-icon">✕</div>
      <h2>Anmeldung storniert</h2>
      <p>Diese Anmeldung wurde bereits storniert.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
      </div>

      <router-link to="/" class="button">Zur Startseite</router-link>
    </section>

    <!-- Waitlisted (can't confirm yet) -->
    <section v-else-if="registration?.status === 'WAITLISTED'" class="status-card waitlist">
      <div class="status-icon">#{{ registration.waitlist_position }}</div>
      <h2>Du stehst auf der Warteliste</h2>
      <p>
        Sobald ein Platz frei wird, rückst du automatisch nach und wirst benachrichtigt.
      </p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
        <p><strong>Wartelistenplatz:</strong> #{{ registration.waitlist_position }}</p>
      </div>

      <router-link to="/" class="button">Zur Startseite</router-link>
    </section>

    <!-- Confirmation success -->
    <section v-else-if="confirmed" class="status-card" :class="confirmedYes ? 'success' : 'cancelled'">
      <div class="status-icon">{{ confirmedYes ? '✓' : '✕' }}</div>
      <h2 v-if="confirmedYes">Du bist dabei!</h2>
      <h2 v-else>Schade, dass du nicht dabei sein kannst</h2>
      <p>{{ confirmMessage }}</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
        <p><strong>Personen:</strong> {{ registration.group_size }}</p>
      </div>

      <router-link to="/" class="button">Zur Startseite</router-link>
    </section>

    <!-- Confirmation form (status is CONFIRMED) -->
    <section v-else-if="registration?.status === 'CONFIRMED'">
      <header>
        <h2>Teilnahme bestätigen</h2>
        <p>Bitte bestätige, ob du an der Veranstaltung teilnehmen wirst.</p>
      </header>

      <div class="registration-details">
        <h3>Deine Anmeldung</h3>
        <dl>
          <dt>Name</dt>
          <dd>{{ registration.name }}</dd>
          <dt>E-Mail</dt>
          <dd>{{ registration.email }}</dd>
          <dt>Personen</dt>
          <dd>{{ registration.group_size }}</dd>
        </dl>
      </div>

      <div v-if="confirmError" role="alert" class="error">
        {{ confirmError }}
      </div>

      <div class="confirmation-buttons">
        <button
          @click="handleConfirm('yes')"
          class="confirm-yes"
          :disabled="confirming"
          :aria-busy="confirming && pendingResponse === 'yes'"
        >
          {{ confirming && pendingResponse === 'yes' ? 'Wird bestätigt...' : 'Ja, ich bin dabei!' }}
        </button>
        <button
          @click="handleConfirm('no')"
          class="confirm-no"
          :disabled="confirming"
          :aria-busy="confirming && pendingResponse === 'no'"
        >
          {{ confirming && pendingResponse === 'no' ? 'Wird storniert...' : 'Nein, ich kann nicht' }}
        </button>
      </div>

      <p class="info">
        Falls du nicht teilnehmen kannst, wird dein Platz automatisch an jemanden auf der Warteliste vergeben.
      </p>
    </section>

    <!-- Unknown/other status -->
    <section v-else-if="registration" class="status-card">
      <h2>Status: {{ registration.status }}</h2>
      <p>Dein aktueller Anmeldestatus ist <strong>{{ formatStatus(registration.status) }}</strong>.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> {{ registration.email }}</p>
      </div>

      <router-link to="/" class="button">Zur Startseite</router-link>
    </section>
  </article>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { publicApi } from '../../services/api'

const route = useRoute()

const loading = ref(true)
const error = ref(null)
const registration = ref(null)
const confirmed = ref(false)
const confirmedYes = ref(false)
const confirmMessage = ref('')
const confirming = ref(false)
const confirmError = ref(null)
const pendingResponse = ref(null)

// Format status for display
function formatStatus(status) {
  const statusLabels = {
    'REGISTERED': 'Angemeldet',
    'CONFIRMED': 'Wartet auf Bestätigung',
    'PARTICIPATING': 'Nimmt teil',
    'WAITLISTED': 'Warteliste',
    'CANCELLED': 'Storniert',
    'CHECKED_IN': 'Eingecheckt',
  }
  return statusLabels[status] || status
}

// Load registration status
async function loadRegistration() {
  const registrationId = route.params.registrationId
  const token = route.query.token
  const responseParam = route.query.response

  if (!registrationId || !token) {
    error.value = 'Ungültiger Bestätigungslink. Bitte prüfe den Link in deiner E-Mail.'
    loading.value = false
    return
  }

  try {
    // Get current status
    const result = await publicApi.getAttendanceStatus(registrationId, token)
    registration.value = result.registration

    // If response parameter is present and status is CONFIRMED, auto-submit
    if (responseParam && registration.value.status === 'CONFIRMED') {
      loading.value = false
      await handleConfirm(responseParam)
    }
  } catch (err) {
    if (err.message.includes('404')) {
      error.value = 'Anmeldung nicht gefunden oder ungültiger Link.'
    } else {
      error.value = err.message || 'Anmeldung konnte nicht geladen werden.'
    }
  } finally {
    loading.value = false
  }
}

// Handle confirmation
async function handleConfirm(response) {
  const registrationId = route.params.registrationId
  const token = route.query.token

  confirming.value = true
  confirmError.value = null
  pendingResponse.value = response

  try {
    const result = await publicApi.confirmAttendance(registrationId, token, response)
    registration.value = result.registration
    confirmMessage.value = result.message
    confirmed.value = true
    confirmedYes.value = response === 'yes'
  } catch (err) {
    if (err.message.includes('already recorded')) {
      confirmError.value = 'Du hast bereits geantwortet.'
      // Reload to show current status
      await loadRegistration()
    } else {
      confirmError.value = err.message || 'Bestätigung fehlgeschlagen. Bitte versuche es erneut.'
    }
  } finally {
    confirming.value = false
    pendingResponse.value = null
  }
}

onMounted(loadRegistration)
</script>

<style scoped>
.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.status-card {
  text-align: center;
  padding: 2rem;
  border-radius: var(--pico-border-radius);
}

.status-card.success {
  background: var(--pico-color-green-50, #f0fff4);
}

.status-card.success h2 {
  color: var(--pico-color-green-600, #2f855a);
}

.status-card.cancelled {
  background: #fef2f2;
}

.status-card.cancelled h2 {
  color: #dc2626;
}

.status-card.waitlist {
  background: #f5f5f5;
}

.status-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.status-card.success .status-icon {
  color: var(--pico-color-green-600, #2f855a);
}

.status-card.cancelled .status-icon {
  color: #dc2626;
}

.status-card.waitlist .status-icon {
  color: #6b7280;
  font-weight: bold;
}

.registration-details {
  background: white;
  padding: 1rem;
  border-radius: var(--pico-border-radius);
  margin: 1.5rem 0;
  text-align: left;
}

.registration-details dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  margin: 0;
}

.registration-details dt {
  font-weight: bold;
}

.confirmation-buttons {
  display: flex;
  gap: 1rem;
  justify-content: center;
  margin: 2rem 0;
  flex-wrap: wrap;
}

.confirm-yes {
  background: #16a34a !important;
  border-color: #16a34a !important;
  color: white !important;
  padding: 1rem 2rem;
  font-size: 1.1rem;
}

.confirm-yes:hover:not(:disabled) {
  background: #15803d !important;
  border-color: #15803d !important;
}

.confirm-no {
  background: #dc2626 !important;
  border-color: #dc2626 !important;
  color: white !important;
  padding: 1rem 2rem;
  font-size: 1.1rem;
}

.confirm-no:hover:not(:disabled) {
  background: #b91c1c !important;
  border-color: #b91c1c !important;
}

.info {
  font-size: 0.9em;
  color: var(--pico-muted-color);
  margin-top: 1rem;
}

.button {
  display: inline-block;
  text-decoration: none;
  padding: 0.75rem 1.5rem;
  border-radius: var(--pico-border-radius);
  background: var(--pico-primary);
  color: white;
  margin-top: 1rem;
}

.button:hover {
  background: var(--pico-primary-hover);
}
</style>
