<template>
  <article>
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — die Gästeliste wird geladen ...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="guestlist-error">
      <h2>Diese Gästeliste lässt sich nicht öffnen</h2>
      <p>{{ error }}</p>
    </div>

    <template v-else-if="guestlist">
      <header class="guestlist-header">
        <p class="eyebrow">Gästeliste</p>
        <h2>{{ guestlist.invite_label }}</h2>
        <p class="event-line">
          {{ guestlist.event_name }} ·
          {{ formatDateLong(guestlist.start_at) }}
          <template v-if="guestlist.end_at"> – {{ formatDateLong(guestlist.end_at) }}</template>
        </p>
      </header>

      <section class="quota-card">
        <p class="quota-numbers">
          <strong>{{ guestlist.use_count }}</strong> von <strong>{{ guestlist.max_uses }}</strong>
          Anmeldungen genutzt
          <template v-if="usesLeft > 0"> — noch {{ usesLeft }} frei</template>
        </p>
        <progress :value="guestlist.use_count" :max="guestlist.max_uses"></progress>
        <p v-if="guestlist.max_group_size > 1" class="quota-hint">
          Jede Anmeldung kann bis zu {{ guestlist.max_group_size }} Personen umfassen.
        </p>
        <p v-if="!guestlist.can_register" class="quota-closed">
          Über diesen Link sind keine weiteren Anmeldungen möglich.
        </p>
        <a v-else role="button" class="register-cta" :href="registerUrl">Zur Anmeldung</a>
      </section>

      <section class="registrations-section">
        <h3>Wer ist schon dabei?</h3>

        <p v-if="guestlist.registrations.length === 0" class="empty-hint">
          Noch niemand — teile den Einladungslink, damit sich deine Leute anmelden können.
        </p>

        <ul v-else class="registration-list">
          <li v-for="(reg, i) in guestlist.registrations" :key="i" class="registration-card">
            <div class="registration-name">
              <strong>{{ reg.name }}</strong>
              <span v-if="reg.group_size > 1" class="group-badge">+{{ reg.group_size - 1 }}</span>
            </div>
            <div v-if="reg.attendance_slots.length" class="registration-days">
              {{ slotLabels(reg.attendance_slots) }}
            </div>
          </li>
        </ul>

        <p class="privacy-hint">
          Diese Seite zeigt nur Namen und Tage — keine Kontaktdaten.
        </p>
      </section>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { publicApi } from '../../services/api'
import { formatDateLong } from '../../utils/formatters'

const props = defineProps({
  inviteToken: { type: String, default: null },
})

const loading = ref(true)
const error = ref(null)
const guestlist = ref(null)

const usesLeft = computed(() =>
  guestlist.value ? Math.max(0, guestlist.value.max_uses - guestlist.value.use_count) : 0,
)

const registerUrl = computed(() => `/invite/${props.inviteToken}`)

function slotLabels(keys) {
  const byKey = new Map((guestlist.value?.slots || []).map((s) => [s.key, s.label]))
  return keys.map((k) => byKey.get(k) || k).join(', ')
}

onMounted(async () => {
  try {
    guestlist.value = await publicApi.getInviteGuestlist(props.inviteToken)
  } catch (err) {
    error.value = err.message || 'Die Gästeliste konnte nicht geladen werden.'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.loading-state {
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.guestlist-error {
  padding: var(--space-4);
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
  border-radius: var(--radius-md);
}

.guestlist-error h2 {
  font-size: var(--text-lg);
  margin-bottom: var(--space-2);
  color: inherit;
}

.guestlist-header {
  margin-bottom: var(--space-4);
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: 0.15rem;
}

.guestlist-header h2 {
  margin-bottom: 0.25rem;
}

.event-line {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.quota-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  margin-bottom: var(--space-5);
}

.quota-numbers {
  margin-bottom: var(--space-2);
}

.quota-hint {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin-bottom: var(--space-2);
}

.quota-closed {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  margin-bottom: 0;
}

.register-cta {
  display: inline-block;
  width: auto;
  min-height: 44px;
  margin-bottom: 0;
}

.registrations-section h3 {
  margin-bottom: var(--space-3);
}

.empty-hint {
  color: var(--color-text-muted);
}

.registration-list {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--space-3);
}

.registration-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-2);
}

.registration-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.group-badge {
  background: var(--color-bg-muted);
  border-radius: var(--radius-pill);
  padding: 0.05rem 0.5rem;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.registration-days {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin-top: 0.15rem;
}

.privacy-hint {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}
</style>
