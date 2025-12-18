<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Loading registration information...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      <h2>Unable to Load Registration</h2>
      <p>{{ error }}</p>
    </div>

    <!-- Already cancelled -->
    <section v-else-if="registration?.status === 'CANCELLED'" class="already-cancelled">
      <h2>Registration Already Cancelled</h2>
      <p>This registration has already been cancelled.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>Email:</strong> {{ registration.email }}</p>
        <p><strong>Status:</strong> {{ registration.status }}</p>
      </div>
    </section>

    <!-- Cancellation confirmation -->
    <section v-else-if="cancelled" class="success">
      <h2>Registration Cancelled</h2>
      <p>Your registration has been successfully cancelled.</p>

      <div class="registration-details">
        <p><strong>Name:</strong> {{ registration.name }}</p>
        <p><strong>Email:</strong> {{ registration.email }}</p>
      </div>

      <p class="info">
        A confirmation email has been sent to {{ registration.email }}.
      </p>

      <router-link to="/" class="button">Return Home</router-link>
    </section>

    <!-- Cancellation form -->
    <section v-else-if="registration">
      <header>
        <h2>Cancel Registration</h2>
        <p>Are you sure you want to cancel your registration?</p>
      </header>

      <div class="registration-details">
        <h3>Registration Details</h3>
        <dl>
          <dt>Name</dt>
          <dd>{{ registration.name }}</dd>
          <dt>Email</dt>
          <dd>{{ registration.email }}</dd>
          <dt>Group Size</dt>
          <dd>{{ registration.groupSize }} {{ registration.groupSize === 1 ? 'person' : 'people' }}</dd>
          <dt>Status</dt>
          <dd>{{ registration.status }}</dd>
          <dt v-if="registration.waitlistPosition">Waitlist Position</dt>
          <dd v-if="registration.waitlistPosition">#{{ registration.waitlistPosition }}</dd>
        </dl>
      </div>

      <div class="warning">
        <strong>Warning:</strong> This action cannot be undone. If you want to attend the event after cancelling, you will need to register again.
      </div>

      <div v-if="cancelError" role="alert" class="error">
        {{ cancelError }}
      </div>

      <div class="actions">
        <router-link to="/" class="button secondary">Keep Registration</router-link>
        <button
          @click="handleCancel"
          class="contrast"
          :disabled="cancelling"
          :aria-busy="cancelling"
        >
          {{ cancelling ? 'Cancelling...' : 'Cancel Registration' }}
        </button>
      </div>
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
const cancelled = ref(false)
const cancelling = ref(false)
const cancelError = ref(null)

// Load registration info
async function loadRegistration() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  if (!registrationId || !token) {
    error.value = 'Invalid cancellation link. Please check your email for the correct link.'
    loading.value = false
    return
  }

  try {
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/public/registrations/${registrationId}?token=${token}`
    )

    if (!response.ok) {
      if (response.status === 404) {
        error.value = 'Registration not found or invalid token.'
      } else {
        error.value = 'Failed to load registration information.'
      }
      return
    }

    registration.value = await response.json()
  } catch (err) {
    error.value = err.message || 'Failed to load registration information.'
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
    cancelError.value = err.message || 'Failed to cancel registration. Please try again.'
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
  background: var(--pico-secondary-background);
  color: var(--pico-secondary);
  border: 1px solid var(--pico-secondary);
}
</style>
