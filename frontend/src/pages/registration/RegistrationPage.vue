<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Veranstaltung wird geladen...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert">
      <h2>Veranstaltung nicht verfügbar</h2>
      <p>{{ error }}</p>
      <p v-if="eventClosed">Diese Veranstaltung nimmt keine Anmeldungen mehr an.</p>
    </div>

    <!-- Event info and registration form -->
    <template v-else-if="event">
      <header>
        <h2>{{ event.name }}</h2>
        <p v-if="event.description">{{ event.description }}</p>
      </header>

      <section>
        <h3>Details</h3>
        <dl>
          <dt>Datum</dt>
          <dd>{{ formatDate(event.start_at) }}</dd>
          <dt>Ort</dt>
          <dd>{{ event.location || 'Wird noch bekannt gegeben' }}</dd>
          <dt>Plätze</dt>
          <dd>{{ event.capacity }}</dd>
          <dt>Anmeldeschluss</dt>
          <dd :class="{ 'deadline-passed': deadlinePassed }">
            {{ formatDate(event.registration_deadline) }}
            <span v-if="deadlinePassed"> (Warteliste möglich)</span>
          </dd>
        </dl>
      </section>

      <!-- Late signup notice (after deadline) -->
      <section v-if="isLateSignup && !submitted" class="late-signup-notice">
        <p>Der Anmeldeschluss ist bereits vorbei. Du kannst dich aber noch auf die Warteliste setzen lassen — falls ein Platz frei wird, melden wir uns bei dir.</p>
      </section>

      <!-- Registration form -->
      <section v-if="!submitted">
        <h3>{{ isLateSignup ? 'Auf die Warteliste setzen' : 'Jetzt anmelden' }}</h3>
        <form @submit.prevent="handleSubmit">
          <label for="name">
            Name *
            <input
              id="name"
              v-model="form.name"
              type="text"
              required
              placeholder="Dein vollständiger Name"
              :disabled="submitting"
            />
          </label>

          <label for="email">
            E-Mail *
            <input
              id="email"
              v-model="form.email"
              type="email"
              required
              placeholder="deine@email.de"
              :disabled="submitting"
            />
          </label>

          <label for="phone">
            Telefon (optional)
            <input
              id="phone"
              v-model="form.phone"
              type="tel"
              placeholder="+49 123 456789"
              :disabled="submitting"
            />
          </label>

          <label for="groupSize">
            Gruppengröße *
            <select
              id="groupSize"
              v-model.number="form.groupSize"
              required
              :disabled="submitting"
            >
              <option v-for="n in 10" :key="n" :value="n">
                {{ n }} {{ n === 1 ? 'Person' : 'Personen' }}
              </option>
            </select>
          </label>

          <label for="notes">
            Anmerkungen (optional)
            <textarea
              id="notes"
              v-model="form.notes"
              placeholder="Besondere Wünsche oder Hinweise"
              :disabled="submitting"
            />
          </label>

          <div v-if="submitError" role="alert" class="error">
            {{ submitError }}
          </div>

          <button type="submit" :disabled="submitting" :aria-busy="submitting">
            {{ submitting ? 'Wird gesendet...' : (isLateSignup ? 'Auf Warteliste setzen' : 'Anmelden') }}
          </button>
        </form>
      </section>

      <!-- Success state -->
      <section v-if="submitted" class="success">
        <h3>{{ registration?.status === 'WAITLISTED' ? 'Du stehst auf der Warteliste!' : 'Du stehst auf der Liste!' }}</h3>

        <p v-if="registration?.status === 'WAITLISTED'">
          Die Anmeldephase für <strong>{{ event?.name }}</strong> ist bereits vorbei, aber du stehst auf der Warteliste.
          Sobald ein Platz frei wird, melden wir uns bei dir.
        </p>
        <p v-else>
          Deine Anmeldung für <strong>{{ event?.name }}</strong> ist eingegangen.
          Falls mehr Anmeldungen als Plätze eingehen, wird nach Anmeldeschluss per Los entschieden.
          Du wirst per E-Mail über das Ergebnis informiert.
        </p>

        <div v-if="registration" class="registration-details">
          <p><strong>Name:</strong> {{ registration.name }}</p>
          <p><strong>E-Mail:</strong> <a :href="`mailto:${registration.email}`">{{ registration.email }}</a></p>
          <p><strong>Personen:</strong> {{ registration.group_size }}</p>
        </div>

        <div class="info-box">
          <p>
            <strong>Bestätigungs-E-Mail:</strong> Eine E-Mail wurde an {{ registration?.email }} gesendet.
            Über den Link in der E-Mail kannst du deine Anmeldung bei Bedarf stornieren.
          </p>
        </div>
      </section>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { publicApi } from '../../services/api'

const route = useRoute()

const loading = ref(true)
const error = ref(null)
const eventClosed = ref(false)
const event = ref(null)
const submitted = ref(false)
const submitting = ref(false)
const submitError = ref(null)
const registration = ref(null)
const successMessage = ref('')

const deadlinePassed = computed(() => {
  if (!event.value?.registration_deadline) return false
  return new Date(event.value.registration_deadline) < new Date()
})

const isLateSignup = computed(() => {
  if (!event.value) return false
  return event.value.status !== 'OPEN' || deadlinePassed.value
})

const form = ref({
  name: '',
  email: '',
  phone: '',
  groupSize: 1,
  notes: '',
})

// Format date for display
function formatDate(dateStr) {
  if (!dateStr) return 'Wird noch bekannt gegeben'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
    timeZone: 'Europe/Berlin',
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Load event info
async function loadEvent() {
  const token = route.params.token
  if (!token) {
    error.value = 'Ungültiger Anmeldelink'
    loading.value = false
    return
  }

  try {
    event.value = await publicApi.getEventInfo(token)
  } catch (err) {
    if (err.message.includes('410') || err.message.includes('closed')) {
      error.value = 'Diese Veranstaltung nimmt keine Anmeldungen mehr an.'
      eventClosed.value = true
    } else if (err.message.includes('404')) {
      error.value = 'Veranstaltung nicht gefunden. Bitte prüfe deinen Anmeldelink.'
    } else {
      error.value = err.message || 'Veranstaltung konnte nicht geladen werden.'
    }
  } finally {
    loading.value = false
  }
}

// Handle form submission
async function handleSubmit() {
  submitting.value = true
  submitError.value = null

  const token = route.params.token

  try {
    const result = await publicApi.submitRegistration(token, {
      name: form.value.name.trim(),
      email: form.value.email.trim().toLowerCase(),
      phone: form.value.phone?.trim() || null,
      group_size: form.value.groupSize,
      notes: form.value.notes?.trim() || null,
    })

    registration.value = result.registration
    successMessage.value = result.message
    submitted.value = true
  } catch (err) {
    if (err.message.includes('already registered')) {
      submitError.value = 'Diese E-Mail-Adresse ist bereits für diese Veranstaltung angemeldet.'
    } else if (err.message.includes('deadline')) {
      submitError.value = 'Der Anmeldeschluss ist bereits vorbei.'
    } else {
      submitError.value = err.message || 'Anmeldung fehlgeschlagen. Bitte versuche es erneut.'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(loadEvent)
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

.success h3 {
  color: var(--pico-color-green-600, #2f855a);
}

.registration-details {
  text-align: left;
  background: white;
  padding: 1rem;
  border-radius: var(--pico-border-radius);
  margin: 1rem 0;
}

.info {
  font-size: 0.9em;
  color: var(--pico-muted-color);
  margin-top: 1rem;
}

.info-box {
  text-align: left;
  background: white;
  padding: 1rem;
  border-radius: var(--pico-border-radius);
  margin-top: 1.5rem;
  border-left: 4px solid var(--pico-primary);
}

.info-box p {
  margin: 0.5rem 0;
  font-size: 0.9em;
}

.info-box p:first-child {
  margin-top: 0;
}

.info-box p:last-child {
  margin-bottom: 0;
}

.deadline-passed {
  color: var(--pico-color-red-500, #dc3545);
  font-weight: bold;
}

.deadline-notice {
  padding: 2rem;
  background: var(--pico-color-amber-50, #fffbeb);
  border-radius: var(--pico-border-radius);
  border-left: 4px solid var(--pico-color-amber-500, #f59e0b);
  text-align: center;
}

.late-signup-notice {
  padding: 1rem;
  background: #eff6ff;
  border-radius: var(--pico-border-radius);
  border-left: 4px solid #3b82f6;
  margin-bottom: 1rem;
  font-size: 0.95em;
  color: #1e40af;
}

dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
}

dt {
  font-weight: bold;
}
</style>
