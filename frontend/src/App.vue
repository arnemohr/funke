<template>
  <ToastContainer />
  <main class="container">
    <header>
      <nav>
        <ul>
          <li><strong class="brand-name">⚓ Funke</strong></li>
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
import ToastContainer from './components/ToastContainer.vue'

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
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--color-border, #DFE2E6);
}

.brand-name {
  color: var(--color-brand, #0C1E3C);
  font-size: var(--text-sm);
  letter-spacing: 0.02em;
}

.user-email {
  font-size: var(--text-xs);
  color: var(--color-text-muted, #5C6470);
}

.debug-link {
  font-size: var(--text-xs);
  color: var(--color-text-muted, #5C6470);
  text-decoration: none;
}

.debug-link:hover {
  color: var(--pico-primary);
}

nav ul li button {
  margin: 0;
  font-size: var(--text-xs);
}

nav a.router-link-exact-active {
  font-weight: bold;
  color: var(--color-brand, #0C1E3C);
  border-bottom: 2px solid var(--color-accent, #E8722A);
  padding-bottom: 2px;
}

@media (max-width: 640px) {
  nav {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  nav ul:first-child {
    flex: 0 0 100%;
  }
  nav ul:last-child {
    gap: 0.5rem;
    flex-wrap: nowrap;
    overflow-x: auto;
  }
  .user-email {
    display: none;
  }
}
</style>
