<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Anmeldung wird geladen...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      <h2>Anmeldung nicht gefunden</h2>
      <p>{{ error }}</p>
    </div>

    <!-- Already cancelled -->
    <section v-else-if="registration?.status === 'CANCELLED'" class="already-cancelled">
      <h2>Bereits storniert</h2>
      <p>Diese Anmeldung wurde bereits storniert.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
        <p><strong>Status:</strong> {{ registration.status }}</p>
      </div>
    </section>

    <!-- Cannot cancel (PARTICIPATING or CHECKED_IN) -->
    <section v-else-if="registration && !canCancel" class="already-cancelled">
      <h2>Stornierung nicht möglich</h2>
      <p v-if="registration.status === 'PARTICIPATING'">
        Du hast deine Teilnahme bereits bestätigt. Eine Stornierung ist nicht mehr möglich.
        Bei Fragen, einfach melden!
      </p>
      <p v-else-if="registration.status === 'CHECKED_IN'">
        Du bist bereits eingecheckt. Eine Stornierung ist nicht mehr möglich.
      </p>
      <p v-else>
        Eine Stornierung ist für den aktuellen Status nicht möglich.
      </p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
      </div>
    </section>

    <!-- Cancellation confirmation -->
    <section v-else-if="cancelled" class="success">
      <h2>Anmeldung storniert</h2>
      <p>Deine Anmeldung wurde erfolgreich storniert.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
      </div>

      <p class="info">
        Eine Bestätigung wurde an {{ registration.email }} gesendet.
      </p>

      <router-link to="/" class="button">Zurück zur Startseite</router-link>
    </section>

    <!-- Cancellation form -->
    <section v-else-if="registration">
      <header>
        <h2>Anmeldung stornieren</h2>
        <p>Möchtest du deine Anmeldung wirklich stornieren?</p>
      </header>

      <div class="registration-details">
        <h3>Deine Anmeldung</h3>
        <dl>
          <dt>Name</dt>
          <dd>{{ registration.name }}</dd>
          <dt>E-Mail</dt>
          <dd>{{ registration.email }}</dd>
          <dt>Gruppengröße</dt>
          <dd>{{ registration.group_size }} {{ registration.group_size === 1 ? 'Person' : 'Personen' }}</dd>
          <dt>Status</dt>
          <dd>{{ registration.status }}</dd>
          <dt v-if="registration.waitlist_position">Wartelistenplatz</dt>
          <dd v-if="registration.waitlist_position">#{{ registration.waitlist_position }}</dd>
        </dl>
      </div>

      <div class="warning">
        <strong>Hinweis:</strong> Diese Aktion kann nicht rückgängig gemacht werden. Wenn du doch teilnehmen möchtest, musst du dich erneut anmelden.
      </div>

      <div v-if="cancelError" role="alert" class="error">
        {{ cancelError }}
      </div>

      <div class="actions">
        <router-link to="/" class="button secondary">Anmeldung behalten</router-link>
        <button
          @click="handleCancel"
          class="contrast"
          :disabled="cancelling"
          :aria-busy="cancelling"
        >
          {{ cancelling ? 'Wird storniert...' : 'Stornieren' }}
        </button>
      </div>
    </section>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { publicApi } from '../../services/api'

const route = useRoute()

const loading = ref(true)
const error = ref(null)
const registration = ref(null)
const cancelled = ref(false)
const cancelling = ref(false)
const cancelError = ref(null)

const CANCELLABLE_STATUSES = ['REGISTERED', 'CONFIRMED', 'WAITLISTED']
const canCancel = computed(() =>
  registration.value && CANCELLABLE_STATUSES.includes(registration.value.status),
)

// Load registration info
async function loadRegistration() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  if (!registrationId || !token) {
    error.value = 'Ungültiger Stornierungslink. Bitte prüfe den Link in deiner E-Mail.'
    loading.value = false
    return
  }

  try {
    registration.value = await publicApi.getRegistrationInfo(registrationId, token)
  } catch (err) {
    if (err.message?.includes('404')) {
      error.value = 'Anmeldung nicht gefunden oder ungültiger Link.'
    } else {
      error.value = err.message || 'Anmeldung konnte nicht geladen werden.'
    }
  } finally {
    loading.value = false
  }
}

// Handle cancellation
async function handleCancel() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  cancelling.value = true
  cancelError.value = null

  try {
    const result = await publicApi.cancelRegistration(registrationId, token)
    registration.value = result.registration
    cancelled.value = true
  } catch (err) {
    cancelError.value = err.message || 'Stornierung fehlgeschlagen. Bitte versuche es erneut.'
  } finally {
    cancelling.value = false
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

.success {
  text-align: center;
  padding: 2rem;
  background: var(--pico-color-green-50, #f0fff4);
  border-radius: var(--pico-border-radius);
}

.success h2 {
  color: var(--pico-color-green-600, #2f855a);
}

.already-cancelled {
  text-align: center;
  padding: 2rem;
  background: #f5f5f5;
  border-radius: var(--pico-border-radius);
}

.registration-details {
  background: white;
  padding: 1rem;
  border-radius: var(--pico-border-radius);
  margin: 1rem 0;
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

.warning {
  padding: 1rem;
  background: var(--pico-color-yellow-50, #fffbeb);
  border: 1px solid var(--pico-color-yellow-200, #fde68a);
  border-radius: var(--pico-border-radius);
  margin: 1rem 0;
}

.info {
  font-size: 0.9em;
  color: var(--pico-muted-color);
  margin-top: 1rem;
}

.actions {
  display: flex;
  gap: 1rem;
  justify-content: center;
  margin-top: 1.5rem;
}

.button {
  text-decoration: none;
  padding: 0.5rem 1rem;
  border-radius: var(--pico-border-radius);
}

.button.secondary {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.button.secondary:hover {
  background: #e2e8f0;
}
</style>
