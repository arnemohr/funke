<template>
  <article class="settings-page">
    <PageHeader>
      <template #title>Einstellungen</template>
    </PageHeader>

    <!-- Mein Profil -->
    <div class="section-heading">
      <h3>Mein Profil</h3>
    </div>
    <div class="list-group">
      <ListItemButton :icon="User" chevron @click="$router.push('/admin/profile')">
        Profil &amp; Crew-Rollen
      </ListItemButton>
    </div>

    <!-- Notifications -->
    <div class="section-heading">
      <h3>Benachrichtigungen</h3>
    </div>

    <p v-if="!pushSupported" class="description">
      Push-Benachrichtigungen werden in diesem Browser nicht unterstützt.
      Öffne die App zum Installieren in einem unterstützten Browser (Chrome, Edge, Firefox, Safari&nbsp;16.4+).
    </p>

    <template v-else>
      <p class="description">
        Du wirst benachrichtigt bei neuen Anmeldungen, Statusänderungen und dem Abschluss der Verlosung.
      </p>

      <div class="list-group">
        <ListItemButton
          v-if="pushSubscribed"
          :icon="Bell"
          @click="handleUnsubscribe"
        >
          Push-Benachrichtigungen
          <template #trailing>
            <span class="state-pill state-pill--ok">Aktiv</span>
          </template>
        </ListItemButton>

        <ListItemButton
          v-else-if="pushPermission === 'denied'"
          :icon="BellOff"
          variant="static"
        >
          Push-Benachrichtigungen
          <template #detail>
            Im Browser blockiert — Seiteneinstellungen öffnen, um Benachrichtigungen zu erlauben
          </template>
          <template #trailing>
            <span class="state-pill state-pill--muted">Blockiert</span>
          </template>
        </ListItemButton>

        <ListItemButton
          v-else
          :icon="Bell"
          @click="handleSubscribe"
        >
          Push-Benachrichtigungen
          <template #trailing>
            <span class="state-pill state-pill--muted">Inaktiv</span>
          </template>
        </ListItemButton>
      </div>
    </template>

    <!-- App -->
    <div class="section-heading">
      <h3>App</h3>
    </div>
    <div class="list-group">
      <ListItemButton
        :icon="Tag"
        variant="static"
      >
        Version
        <template #trailing>
          <code
            class="version-code"
            :class="{ 'version-code--active': tapCount > 0 }"
            @click.stop="handleVersionTap"
            role="button"
            tabindex="0"
            :aria-label="`Version ${appVersion}`"
            @keydown.enter="handleVersionTap"
            @keydown.space.prevent="handleVersionTap"
          >
            {{ appVersion }}
          </code>
        </template>
      </ListItemButton>

      <ListItemButton
        :icon="isStandalone ? Smartphone : Globe"
        variant="static"
      >
        Modus
        <template #trailing>
          <span class="mode-label">{{ isStandalone ? 'Installiert' : 'Im Browser' }}</span>
        </template>
      </ListItemButton>

      <ListItemButton
        v-if="canInstall"
        :icon="Download"
        chevron
        @click="handleInstall"
      >
        App installieren
      </ListItemButton>
    </div>

    <p v-if="!canInstall && !isStandalone" class="hint">
      Installation wird vom Browser vorbereitet. Im Browser-Menü findest du „Zum Startbildschirm hinzufügen".
    </p>

    <!-- Account -->
    <div class="section-heading">
      <h3>Konto</h3>
    </div>
    <div class="list-group">
      <ListItemButton
        :icon="Mail"
        variant="static"
      >
        E-Mail
        <template #trailing>
          <span class="email-label">{{ user?.email || '–' }}</span>
        </template>
      </ListItemButton>
      <ListItemButton
        :icon="LogOut"
        variant="danger"
        @click="handleLogout"
      >
        Abmelden
      </ListItemButton>
    </div>

    <!-- Developer options -->
    <template v-if="devMode">
      <div class="section-heading">
        <h3>Entwickleroptionen</h3>
      </div>
      <p class="description small">
        Der „Debug"-Tab ist in der Navigation sichtbar. Tippe erneut 5× auf die Version, um ihn auszublenden.
      </p>
      <div class="list-group">
        <ListItemButton
          :icon="Wrench"
          @click="toggleDev"
        >
          Entwicklermodus deaktivieren
        </ListItemButton>
      </div>
    </template>
  </article>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useAuth0 } from '@auth0/auth0-vue'
import {
  Bell, BellOff, Tag, Smartphone, Globe, Download, Mail, LogOut, Wrench, User,
} from 'lucide-vue-next'
import { usePushNotifications } from '../../composables/usePushNotifications.js'
import { useInstallPrompt } from '../../composables/useInstallPrompt.js'
import { useDevMode } from '../../composables/useDevMode.js'
import { showToast } from '../../composables/useToast.js'
import PageHeader from '../../components/PageHeader.vue'
import ListItemButton from '../../components/ListItemButton.vue'

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
const tapCount = ref(0)
let tapTimer = null
function handleVersionTap() {
  tapCount.value += 1
  clearTimeout(tapTimer)
  tapTimer = setTimeout(() => { tapCount.value = 0 }, 1500)
  if (tapCount.value >= 5) {
    tapCount.value = 0
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

.description {
  margin: 0 0 var(--space-3);
  padding: 0 var(--space-1);
  font-size: var(--text-base);
  color: var(--color-text-muted);
}

.description.small {
  font-size: var(--text-sm);
}

.hint {
  margin: var(--space-2) var(--space-1) 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* State pills in trailing slot */
.state-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px var(--space-2);
  border-radius: var(--radius-pill);
  font-size: var(--text-sm);
  font-weight: 600;
}

.state-pill--ok {
  background: var(--color-success-bg);
  color: var(--color-success-text);
}

.state-pill--muted {
  background: var(--color-neutral-bg);
  color: var(--color-neutral-text);
}

.mode-label,
.email-label {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-code {
  display: inline-block;
  padding: 2px 6px;
  font-family: var(--pico-font-family-monospace, monospace);
  background: var(--color-bg-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
  font-size: var(--text-sm);
  transition: background 0.15s;
}

.version-code--active {
  background: var(--color-brand-subtle);
}
</style>
