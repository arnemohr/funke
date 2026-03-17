<template>
  <main class="container">
    <header>
      <nav>
        <ul>
          <li><strong>Funke</strong></li>
        </ul>
        <ul>
          <li v-if="isAuthenticated">
            <router-link to="/admin/events">Veranstaltungen</router-link>
          </li>
          <li v-if="isAuthenticated">
            <router-link to="/admin/debug" class="debug-link">Debug</router-link>
          </li>
          <li v-if="isAuthenticated">
            <span class="user-email">{{ user?.email }}</span>
          </li>
          <li>
            <button v-if="isAuthenticated" @click="handleLogout" class="outline secondary">
              Abmelden
            </button>
            <router-link v-else to="/login">
              <button class="outline">Anmelden</button>
            </router-link>
          </li>
        </ul>
      </nav>
    </header>
    <router-view />
  </main>
</template>

<script setup>
import { useAuth0 } from '@auth0/auth0-vue'

const { isAuthenticated, user, logout } = useAuth0()

function handleLogout() {
  logout({
    logoutParams: {
      returnTo: window.location.origin,
    },
  })
}
</script>

<style scoped>
header {
  margin-bottom: 2rem;
}

.user-email {
  font-size: 0.875rem;
  color: var(--pico-muted-color);
}

.debug-link {
  font-size: 0.8rem;
  color: var(--pico-muted-color);
  text-decoration: none;
}

.debug-link:hover {
  color: var(--pico-primary);
}

nav ul li button {
  margin: 0;
}
</style>
