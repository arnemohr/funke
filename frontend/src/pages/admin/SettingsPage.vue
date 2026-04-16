<template>
  <article class="settings-page">
    <h2>Einstellungen</h2>

    <!-- Push Notifications -->
    <section class="settings-section">
      <h3>Push-Benachrichtigungen</h3>
      <p v-if="!pushSupported" class="muted">
        Push-Benachrichtigungen werden in diesem Browser nicht unterstützt.
      </p>
      <template v-else>
        <button v-if="!pushSubscribed" @click="handleSubscribe" class="outline">
          Benachrichtigungen aktivieren
        </button>
        <button v-else @click="handleUnsubscribe" class="outline secondary">
          Benachrichtigungen deaktivieren
        </button>
      </template>
    </section>

    <!-- Account -->
    <section class="settings-section">
      <h3>Konto</h3>
      <dl class="account-info">
        <dt>E-Mail</dt>
        <dd>{{ user?.email || '–' }}</dd>
      </dl>
    </section>

    <!-- Logout -->
    <section class="settings-section">
      <button @click="handleLogout" class="secondary">Abmelden</button>
    </section>
  </article>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuth0 } from '@auth0/auth0-vue'
import { usePushNotifications } from '../../composables/usePushNotifications.js'
import { showToast } from '../../composables/useToast.js'

const { user, logout } = useAuth0()
const {
  isSubscribed: pushSubscribed,
  isSupported: pushSupported,
  subscribe,
  unsubscribe,
  checkSubscription,
} = usePushNotifications()

onMounted(() => {
  checkSubscription()
})

async function handleSubscribe() {
  try {
    const ok = await subscribe()
    if (ok) {
      showToast('Push-Benachrichtigungen aktiviert', 'success')
    } else {
      showToast('Berechtigung verweigert', 'error')
    }
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

async function handleUnsubscribe() {
  try {
    await unsubscribe()
    showToast('Push-Benachrichtigungen deaktiviert', 'success')
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

function handleLogout() {
  logout({ logoutParams: { returnTo: window.location.origin } })
}
</script>

<style scoped>
.settings-page h2 {
  margin-bottom: 1.5rem;
}

.settings-section {
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--color-border, #DFE2E6);
}

.settings-section:last-child {
  border-bottom: none;
}

.settings-section h3 {
  margin-bottom: 0.75rem;
  font-size: 1rem;
}

.muted {
  color: var(--color-text-muted, #5C6470);
  font-size: var(--text-sm);
}

.account-info {
  margin: 0;
}

.account-info dt {
  font-size: var(--text-xs);
  color: var(--color-text-muted, #5C6470);
  margin-bottom: 0.15rem;
}

.account-info dd {
  margin: 0 0 0.75rem;
  font-size: var(--text-sm);
}
</style>
