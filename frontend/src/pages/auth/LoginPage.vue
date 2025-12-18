<template>
  <article>
    <header>
      <hgroup>
        <h2>Admin Login</h2>
        <p>Sign in to manage your funke events</p>
      </hgroup>
    </header>

    <!-- Loading state while checking auth -->
    <div v-if="isLoading" aria-busy="true">
      Checking authentication...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      {{ error.message }}
    </div>

    <!-- Login button -->
    <div v-else class="login-container">
      <p>Click the button below to sign in with your account.</p>
      <button @click="handleLogin" :disabled="isLoading">
        Sign In
      </button>
    </div>
  </article>
</template>

<script setup>
import { useAuth0 } from '@auth0/auth0-vue'

const { loginWithRedirect, isLoading, error } = useAuth0()

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
