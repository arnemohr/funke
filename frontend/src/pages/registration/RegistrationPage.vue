<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Loading event information...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert">
      <h2>Unable to Load Event</h2>
      <p>{{ error }}</p>
      <p v-if="eventClosed">This event is no longer accepting registrations.</p>
    </div>

    <!-- Event info and registration form -->
    <template v-else-if="event">
      <header>
        <h2>{{ event.name }}</h2>
        <p v-if="event.description">{{ event.description }}</p>
      </header>

      <section>
        <h3>Event Details</h3>
        <dl>
          <dt>Date</dt>
          <dd>{{ formatDate(event.start_at) }}</dd>
          <dt>Location</dt>
          <dd>{{ event.location || 'TBD' }}</dd>
          <dt>Capacity</dt>
          <dd>{{ event.capacity }} spots</dd>
          <dt>Registration Deadline</dt>
          <dd>{{ formatDate(event.registration_deadline) }}</dd>
        </dl>
      </section>

      <!-- Registration form -->
      <section v-if="!submitted">
        <h3>Register for this Event</h3>
        <form @submit.prevent="handleSubmit">
          <label for="name">
            Name *
            <input
              id="name"
              v-model="form.name"
              type="text"
              required
              placeholder="Your full name"
              :disabled="submitting"
            />
          </label>

          <label for="email">
            Email *
            <input
              id="email"
              v-model="form.email"
              type="email"
              required
              placeholder="your@email.com"
              :disabled="submitting"
            />
          </label>

          <label for="phone">
            Phone (optional)
            <input
              id="phone"
              v-model="form.phone"
              type="tel"
              placeholder="+49 123 456789"
              :disabled="submitting"
            />
          </label>

          <label for="groupSize">
            Group Size *
            <select
              id="groupSize"
              v-model.number="form.groupSize"
              required
              :disabled="submitting"
            >
              <option v-for="n in 10" :key="n" :value="n">
                {{ n }} {{ n === 1 ? 'person' : 'people' }}
              </option>
            </select>
          </label>

          <label for="notes">
            Notes (optional)
            <textarea
              id="notes"
              v-model="form.notes"
              placeholder="Any special requirements or comments"
              :disabled="submitting"
            />
          </label>

          <div v-if="submitError" role="alert" class="error">
            {{ submitError }}
          </div>

          <button type="submit" :disabled="submitting" :aria-busy="submitting">
            {{ submitting ? 'Registering...' : 'Register' }}
          </button>
        </form>
      </section>

      <!-- Success state -->
      <section v-else class="success">
        <h3 v-if="registration?.status === 'CONFIRMED'">
          Registration Confirmed!
        </h3>
        <h3 v-else>
          Added to Waitlist
        </h3>

        <p>{{ successMessage }}</p>

        <div v-if="registration" class="registration-details">
          <p><strong>Name:</strong> {{ registration.name }}</p>
          <p><strong>Email:</strong> {{ registration.email }}</p>
          <p><strong>Group Size:</strong> {{ registration.group_size }}</p>
          <p><strong>Status:</strong> {{ registration.status }}</p>
          <p v-if="registration.waitlist_position">
            <strong>Waitlist Position:</strong> #{{ registration.waitlist_position }}
          </p>
        </div>

        <p class="info">
          A confirmation email has been sent to {{ registration?.email }}.
          You can use the link in the email to cancel your registration if needed.
        </p>
      </section>
    </template>
  </article>
</template>

<script setup>
import { ref, onMounted } from 'vue'
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

const form = ref({
  name: '',
  email: '',
  phone: '',
  groupSize: 1,
  notes: '',
})

// Format date for display
function formatDate(dateStr) {
  if (!dateStr) return 'TBD'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
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
    error.value = 'Invalid registration link'
    loading.value = false
    return
  }

  try {
    event.value = await publicApi.getEventInfo(token)
  } catch (err) {
    if (err.message.includes('410') || err.message.includes('closed')) {
      error.value = 'This event is no longer accepting registrations.'
      eventClosed.value = true
    } else if (err.message.includes('404')) {
      error.value = 'Event not found. Please check your registration link.'
    } else {
      error.value = err.message || 'Failed to load event information.'
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
      submitError.value = 'This email is already registered for this event.'
    } else if (err.message.includes('deadline')) {
      submitError.value = 'Registration deadline has passed.'
    } else {
      submitError.value = err.message || 'Failed to submit registration. Please try again.'
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

dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
}

dt {
  font-weight: bold;
}
</style>
