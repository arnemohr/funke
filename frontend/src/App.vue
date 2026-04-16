<template>
  <!-- Update banner — explicit action, no auto-reload -->
  <div v-if="updateAvailable && !dismissed" class="banner banner-update" role="status">
    <span>Neue Version verfügbar.</span>
    <div class="banner-actions">
      <button class="banner-btn primary" @click="applyUpdate">Aktualisieren</button>
      <button class="banner-btn ghost" aria-label="Später" @click="dismissUpdate">Später</button>
    </div>
  </div>

  <!-- Install banner — contextual, dismissible -->
  <div v-if="showInstallBanner" class="banner banner-install" role="status">
    <span>App installieren für schnelleren Zugriff.</span>
    <div class="banner-actions">
      <button class="banner-btn primary" @click="onInstall">Installieren</button>
      <button class="banner-btn ghost" aria-label="Später" @click="dismissBanner">Später</button>
    </div>
  </div>

  <ToastContainer />
  <main class="container" :class="{ 'has-bottom-nav': showTabBar }">
    <router-view :key="viewKey" />
  </main>

  <!-- Bottom tab bar (authenticated, and not suppressed by route) -->
  <nav v-if="showTabBar" class="bottom-nav">
    <a
      href="#"
      class="nav-tab"
      :class="{ 'is-active': isEventsActive }"
      :aria-current="isEventsActive ? 'page' : undefined"
      @click.prevent="navTo('/admin/events')"
    >
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
      <span>Events</span>
    </a>
    <a
      href="#"
      class="nav-tab"
      :class="{ 'is-active': isSettingsActive }"
      :aria-current="isSettingsActive ? 'page' : undefined"
      @click.prevent="navTo('/admin/settings')"
    >
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
      <span>Einstellungen</span>
    </a>
    <a
      v-if="devMode"
      href="#"
      class="nav-tab"
      :class="{ 'is-active': isDebugActive }"
      :aria-current="isDebugActive ? 'page' : undefined"
      @click.prevent="navTo('/admin/debug')"
    >
      <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
      </svg>
      <span>Debug</span>
    </a>
  </nav>
</template>

<script setup>
import { useAuth0 } from '@auth0/auth0-vue'
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ToastContainer from './components/ToastContainer.vue'
import { useAppUpdate } from './composables/useAppUpdate.js'
import { useInstallPrompt } from './composables/useInstallPrompt.js'
import { useDevMode } from './composables/useDevMode.js'
import { showToast } from './composables/useToast.js'

const { isAuthenticated } = useAuth0()
const router = useRouter()
const route = useRoute()

const { updateAvailable, dismissed, applyUpdate, dismissUpdate } = useAppUpdate()
const { shouldShowBanner: showInstallBanner, promptInstall, dismissBanner } = useInstallPrompt()
const { enabled: devMode } = useDevMode()

const viewKey = ref(0)

const showTabBar = computed(() => isAuthenticated.value && !route.meta?.hideTabBar)

const isEventsActive = computed(() =>
  route.path === '/admin/events' || route.path.startsWith('/admin/events/'),
)
const isSettingsActive = computed(() => route.path === '/admin/settings')
const isDebugActive = computed(() => route.path === '/admin/debug')

function navTo(path) {
  // Same route: scroll to top and reset stacked state via viewKey bump.
  if (route.path === path) {
    viewKey.value++
    window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  // Sub-path of target (e.g. /admin/events/123 when tapping Events): go up to list.
  if (path === '/admin/events' && route.path.startsWith('/admin/events/')) {
    router.push('/admin/events')
    return
  }
  router.push(path)
}

async function onInstall() {
  const outcome = await promptInstall()
  if (outcome === 'accepted') {
    showToast('App wird installiert…', 'success')
  } else if (outcome === 'dismissed') {
    dismissBanner()
  }
}
</script>

<style scoped>
/* Banners — unified look, stack at top */
.banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  padding-top: calc(0.6rem + env(safe-area-inset-top, 0));
  background: var(--color-brand, #0C1E3C);
  color: white;
  font-size: var(--text-sm, 0.875rem);
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.banner-install {
  top: auto;
  bottom: 3.5rem;
  padding-bottom: calc(0.6rem + env(safe-area-inset-bottom, 0));
  padding-top: 0.6rem;
  background: var(--color-brand, #0C1E3C);
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-shrink: 0;
}

.banner-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2rem;
  min-width: 2rem;
  padding: 0 0.75rem;
  margin: 0;
  background: transparent;
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 0.375rem;
  font-size: var(--text-xs, 0.75rem);
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  -webkit-tap-highlight-color: transparent;
}

.banner-btn.primary {
  background: white;
  color: var(--color-brand, #0C1E3C);
  border-color: white;
}

.banner-btn.primary:hover {
  background: #f0f0f0;
}

.banner-btn.ghost:hover,
.banner-btn.ghost:focus-visible {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.6);
}

/* Bottom-nav spacing */
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
  align-items: stretch;
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
  min-height: 44px;
  padding: 0.25rem 0;
  color: var(--color-text-muted, #5C6470);
  text-decoration: none;
  font-size: 0.7rem;
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

.nav-tab.is-active {
  color: var(--color-brand, #0C1E3C);
  font-weight: 700;
}

.nav-icon {
  width: 1.4rem;
  height: 1.4rem;
}
</style>
