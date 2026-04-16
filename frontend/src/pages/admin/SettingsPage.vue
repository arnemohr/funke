<template>
  <article class="settings-page">
    <PageHeader>
      <template #title>Einstellungen</template>
    </PageHeader>

    <!-- Notifications -->
    <section class="card">
      <header class="card-header">
        <h3>Benachrichtigungen</h3>
      </header>

      <p v-if="!pushSupported" class="muted">
        Push-Benachrichtigungen werden in diesem Browser nicht unterstützt.
        Öffne die App zum Installieren in einem unterstützten Browser (Chrome, Edge, Firefox, Safari&nbsp;16.4+).
      </p>

      <template v-else>
        <!-- Explain what push is for -->
        <p class="description">
          Du erhältst Benachrichtigungen bei:
        </p>
        <ul class="feature-list">
          <li>neuen Anmeldungen</li>
          <li>Änderungen am Veranstaltungsstatus</li>
          <li>Abschluss der Verlosung</li>
        </ul>

        <!-- Active state -->
        <div v-if="pushSubscribed" class="state-row">
          <span class="state-ok" aria-hidden="true">●</span>
          <span>Aktiv</span>
          <button class="outline secondary" @click="handleUnsubscribe">Deaktivieren</button>
        </div>

        <!-- Permission denied in browser -->
        <div v-else-if="pushPermission === 'denied'" class="state-row denied">
          <div class="state-text">
            <strong>Benachrichtigungen blockiert</strong>
            <p class="muted">
              Die Berechtigung wurde im Browser verweigert. Öffne die Browser-Einstellungen und erlaube Benachrichtigungen für diese Seite, um sie zu aktivieren.
            </p>
          </div>
        </div>

        <!-- Default (not yet asked or dismissed) -->
        <div v-else class="state-row">
          <button class="outline" @click="handleSubscribe">
            Benachrichtigungen aktivieren
          </button>
        </div>
      </template>
    </section>

    <!-- App / PWA -->
    <section class="card">
      <header class="card-header">
        <h3>App</h3>
      </header>
      <dl class="info-list">
        <dt>Version</dt>
        <dd>
          <code
            class="version-code"
            @click="handleVersionTap"
            role="button"
            tabindex="0"
            @keydown.enter="handleVersionTap"
            @keydown.space.prevent="handleVersionTap"
          >
            {{ appVersion }}
          </code>
        </dd>

        <dt>Modus</dt>
        <dd>{{ isStandalone ? 'Installiert (PWA)' : 'Im Browser' }}</dd>
      </dl>

      <div v-if="canInstall" class="state-row">
        <button class="outline" @click="handleInstall">
          App installieren
        </button>
      </div>

      <p v-else-if="!isStandalone" class="hint">
        Installation wird vom Browser vorbereitet. Im Browser-Menü findest du „Zum Startbildschirm hinzufügen".
      </p>
    </section>

    <!-- Account -->
    <section class="card">
      <header class="card-header">
        <h3>Konto</h3>
      </header>
      <dl class="info-list">
        <dt>E-Mail</dt>
        <dd>{{ user?.email || '–' }}</dd>
      </dl>
      <div class="state-row">
        <button class="outline secondary" @click="handleLogout">Abmelden</button>
      </div>
    </section>

    <!-- Developer options (only shown when dev mode is on) -->
    <section v-if="devMode" class="card">
      <header class="card-header">
        <h3>Entwickleroptionen</h3>
      </header>
      <p class="muted small">
        Der „Debug"-Tab ist in der Navigation sichtbar. Tippe erneut auf die Version, um ihn auszublenden.
      </p>
      <div class="state-row">
        <button class="outline secondary" @click="toggleDev">
          Entwicklermodus deaktivieren
        </button>
      </div>
    </section>
  </article>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useAuth0 } from '@auth0/auth0-vue'
import { usePushNotifications } from '../../composables/usePushNotifications.js'
import { useInstallPrompt } from '../../composables/useInstallPrompt.js'
import { useDevMode } from '../../composables/useDevMode.js'
import { showToast } from '../../composables/useToast.js'
import PageHeader from '../../components/PageHeader.vue'

const { user, logout } = useAuth0()
const {
  isSubscribed: pushSubscribed,
  isSupported: pushSupported,
  permission: pushPermission,
  subscribe,
  unsubscribe,
  checkSubscription,
} = usePushNotifications()

const { canInstall, isStandalone, promptInstall } = useInstallPrompt()
const { enabled: devMode, enable: enableDev, disable: disableDev, toggle: toggleDev } = useDevMode()

const appVersion = __APP_VERSION__ || '0.0.0'

// Hidden dev-mode activation: 5 quick taps on version
let tapCount = 0
let tapTimer = null
function handleVersionTap() {
  tapCount += 1
  clearTimeout(tapTimer)
  tapTimer = setTimeout(() => { tapCount = 0 }, 1500)
  if (tapCount >= 5) {
    tapCount = 0
    if (devMode.value) {
      disableDev()
      showToast('Entwicklermodus deaktiviert', 'success')
    } else {
      enableDev()
      showToast('Entwicklermodus aktiviert', 'success')
    }
  }
}

onMounted(() => {
  checkSubscription()
})

async function handleSubscribe() {
  try {
    const result = await subscribe()
    if (result.ok) {
      showToast('Benachrichtigungen aktiviert', 'success')
    } else if (result.reason === 'denied') {
      showToast('Berechtigung vom Browser blockiert', 'error')
    } else if (result.reason === 'unsupported') {
      showToast('In diesem Browser nicht unterstützt', 'error')
    } else {
      showToast('Abgebrochen', 'error')
    }
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

async function handleUnsubscribe() {
  try {
    await unsubscribe()
    showToast('Benachrichtigungen deaktiviert', 'success')
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

async function handleInstall() {
  const outcome = await promptInstall()
  if (outcome === 'accepted') {
    showToast('App wird installiert…', 'success')
  }
}

function handleLogout() {
  logout({ logoutParams: { returnTo: window.location.origin } })
}
</script>

<style scoped>
.settings-page {
  padding-bottom: 2rem;
}

.card {
  background: white;
  border: 1px solid var(--color-border, #DFE2E6);
  border-radius: var(--pico-border-radius);
  padding: 1rem;
  margin-bottom: 0.75rem;
}

.card-header {
  margin-bottom: 0.75rem;
}

.card-header h3 {
  margin: 0;
  font-size: 0.95rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--color-text-muted, #5C6470);
}

.description {
  margin: 0 0 0.5rem;
  font-size: var(--text-sm, 0.875rem);
  color: var(--color-text, #2C3441);
}

.feature-list {
  margin: 0 0 1rem;
  padding-left: 1.25rem;
  font-size: var(--text-sm, 0.875rem);
  color: var(--color-text-muted, #5C6470);
}

.feature-list li {
  margin-bottom: 0.15rem;
}

.info-list {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.35rem 1rem;
  margin: 0 0 0.75rem;
}

.info-list dt {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-muted, #5C6470);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.info-list dd {
  margin: 0;
  font-size: var(--text-sm, 0.875rem);
}

.version-code {
  display: inline-block;
  padding: 0.1rem 0.35rem;
  font-family: var(--pico-font-family-monospace, monospace);
  background: var(--color-bg-muted, #f5f5f5);
  border-radius: 3px;
  cursor: pointer;
  user-select: none;
}

.state-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.state-row button {
  width: auto;
  margin: 0;
}

.state-row.denied {
  align-items: flex-start;
}

.state-text {
  flex: 1;
}

.state-text p {
  margin: 0.25rem 0 0;
}

.state-ok {
  color: #16a34a;
  font-size: 1.2rem;
}

.muted {
  color: var(--color-text-muted, #5C6470);
  font-size: var(--text-sm, 0.875rem);
}

.muted.small {
  font-size: var(--text-xs, 0.75rem);
  margin-bottom: 0.75rem;
}

.hint {
  margin: 0.25rem 0 0;
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-muted, #5C6470);
}
</style>
