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

  <!-- Bottom tab bar -->
  <nav v-if="showTabBar" class="bottom-nav">
    <a
      href="#"
      class="nav-tab"
      :class="{ 'is-active': isEventsActive }"
      :aria-current="isEventsActive ? 'page' : undefined"
      @click.prevent="navTo('/admin/events')"
    >
      <span class="nav-tab-indicator" aria-hidden="true" />
      <Calendar :size="22" class="nav-icon" aria-hidden="true" />
      <span>Events</span>
    </a>
    <a
      href="#"
      class="nav-tab"
      :class="{ 'is-active': isSettingsActive }"
      :aria-current="isSettingsActive ? 'page' : undefined"
      @click.prevent="navTo('/admin/settings')"
    >
      <span class="nav-tab-indicator" aria-hidden="true" />
      <Settings :size="22" class="nav-icon" aria-hidden="true" />
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
      <span class="nav-tab-indicator" aria-hidden="true" />
      <Wrench :size="22" class="nav-icon" aria-hidden="true" />
      <span>Debug</span>
    </a>
  </nav>
</template>

<script setup>
import { useAuth0 } from '@auth0/auth0-vue'
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Calendar, Settings, Wrench } from 'lucide-vue-next'
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
  if (route.path === path) {
    viewKey.value++
    window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
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
/* Banners */
.banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 0.6rem var(--space-4);
  padding-top: calc(0.6rem + env(safe-area-inset-top, 0));
  background: var(--color-brand);
  color: white;
  font-size: var(--text-base);
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.banner-install {
  top: auto;
  bottom: 3.5rem;
  padding-bottom: calc(0.6rem + env(safe-area-inset-bottom, 0));
  padding-top: 0.6rem;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.banner-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 2rem;
  min-width: 2rem;
  padding: 0 var(--space-3);
  margin: 0;
  background: transparent;
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  -webkit-tap-highlight-color: transparent;
}

.banner-btn.primary {
  background: white;
  color: var(--color-brand);
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
  background: var(--color-surface-raised);
  border-top: 1px solid var(--color-border);
  padding-bottom: env(safe-area-inset-bottom, 0);
  box-shadow: 0 -1px 3px rgba(12, 30, 60, 0.03);
}

.nav-tab {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  flex: 1;
  min-height: 44px;
  padding: var(--space-1) 0;
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: var(--text-sm);
  font-weight: 500;
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.15s;
  -webkit-tap-highlight-color: transparent;
}

.nav-tab-indicator {
  position: absolute;
  top: 0;
  left: 25%;
  right: 25%;
  height: 2px;
  background: transparent;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
  transition: background 0.15s;
}

.nav-tab:hover,
.nav-tab:focus-visible {
  color: var(--color-brand);
}

.nav-tab.is-active {
  color: var(--color-brand);
  font-weight: 600;
}

.nav-tab.is-active .nav-tab-indicator {
  background: var(--color-brand);
}

.nav-icon {
  display: block;
}
</style>
