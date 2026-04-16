<template>
  <div v-if="showUpdateBanner" class="update-banner">
    Neue Version wird geladen...
  </div>
  <ToastContainer />
  <main class="container" :class="{ 'has-bottom-nav': isAuthenticated }">
    <router-view :key="viewKey" />
  </main>

  <!-- Bottom tab bar (only for authenticated admin users) -->
  <nav v-if="isAuthenticated" class="bottom-nav">
    <a href="#" class="nav-tab" :class="{ 'router-link-active': route.path.startsWith('/admin/events') }" @click.prevent="navTo('/admin/events')">
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/>
        <line x1="8" y1="2" x2="8" y2="6"/>
        <line x1="3" y1="10" x2="21" y2="10"/>
      </svg>
      <span>Events</span>
    </a>
    <a href="#" class="nav-tab" :class="{ 'router-link-active': route.path === '/admin/debug' }" @click.prevent="navTo('/admin/debug')">
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
      </svg>
      <span>Debug</span>
    </a>
    <button class="nav-tab" @click="handleLogout">
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
        <polyline points="16 17 21 12 16 7"/>
        <line x1="21" y1="12" x2="9" y2="12"/>
      </svg>
      <span>Abmelden</span>
    </button>
  </nav>
</template>

<script setup>
import { useAuth0 } from '@auth0/auth0-vue'
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ToastContainer from './components/ToastContainer.vue'
import { useAppUpdate } from './composables/useAppUpdate.js'

const { isAuthenticated, logout } = useAuth0()
const { showUpdateBanner } = useAppUpdate()
const router = useRouter()
const route = useRoute()

const viewKey = ref(0)

function navTo(path) {
  if (route.path === path || route.path.startsWith(path + '/')) {
    // Same route: bump key to remount component (resets all modal state)
    viewKey.value++
  } else {
    router.push(path)
  }
}

function handleLogout() {
  logout({
    logoutParams: {
      returnTo: window.location.origin,
    },
  })
}
</script>

<style scoped>
.update-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  padding: 0.5rem 1rem;
  background: var(--color-brand, #0C1E3C);
  color: white;
  text-align: center;
  font-size: var(--text-xs);
  font-weight: 600;
}

/* Add bottom padding so content doesn't hide behind the fixed nav */
.has-bottom-nav {
  padding-bottom: 4.5rem;
}

/* Bottom navigation bar */
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  justify-content: space-around;
  align-items: center;
  height: 3.5rem;
  background: white;
  border-top: 1px solid var(--color-border, #DFE2E6);
  padding-bottom: env(safe-area-inset-bottom, 0);
}

.nav-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.15rem;
  flex: 1;
  height: 100%;
  padding: 0.25rem 0;
  color: var(--color-text-muted, #5C6470);
  text-decoration: none;
  font-size: 0.65rem;
  font-weight: 500;
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.15s;
  -webkit-tap-highlight-color: transparent;
}

.nav-tab:hover,
.nav-tab:focus-visible {
  color: var(--color-brand, #0C1E3C);
}

.nav-tab.router-link-active {
  color: var(--color-brand, #0C1E3C);
  font-weight: 700;
}

.nav-icon {
  width: 1.25rem;
  height: 1.25rem;
}
</style>
