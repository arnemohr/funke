<template>
  <article>
    <header>
      <hgroup>
        <h2>Admin-Bereich</h2>
        <p>Melde dich an, um deine Veranstaltungen zu verwalten</p>
      </hgroup>
    </header>

    <!-- Loading state while checking auth -->
    <div v-if="isLoading" aria-busy="true">
      Authentifizierung wird geprüft...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      {{ error.message }}
    </div>

    <!-- Login button -->
    <div v-else class="login-container">
      <button @click="handleLogin" :disabled="isLoading">
        Anmelden
      </button>
    </div>
  </article>
</template>

<script setup>
import { watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth0 } from '@auth0/auth0-vue'

const router = useRouter()
const { loginWithRedirect, isLoading, isAuthenticated, error } = useAuth0()

// Redirect to admin if already authenticated
watch(isAuthenticated, (authenticated) => {
  if (authenticated) {
    router.push('/admin/events')
  }
}, { immediate: true })

function handleLogin() {
  loginWithRedirect({
    appState: {
      target: '/admin/events',
    },
  })
}
</script>

<style scoped>
article {
  max-width: 400px;
  margin: 2rem auto;
  text-align: center;
}

.login-container {
  padding: 2rem 0;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}
</style>
