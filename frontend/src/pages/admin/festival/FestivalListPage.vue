<template>
  <article style="position: relative;">
    <header>
      <hgroup>
        <h2>Festivals</h2>
        <p>Mehrtägige Feste: Einladungslinks verschicken, Anmeldungen sammeln, am Einlass scannen.</p>
      </hgroup>
      <button type="button" @click="goToNew">Neues Festival</button>
    </header>

    <FestivalHelp title="Wie das hier funktioniert">
      <p>Du legst ein Festival an und sagst, an welchen Tagen es läuft.</p>
      <p>Dann verschickst du Einladungslinks — erst an Werft und Helfer:innen, später an den Rest.</p>
      <p>In den Gästelisten siehst du, wer sich schon angemeldet hat. Wer noch nicht: einfach nochmal anschreiben.</p>
      <p>Unter „Wer kommt wann" siehst du, wie voll die Tage werden. Ist noch Platz, schickst du mehr Links raus.</p>
      <p>Beim Festival dann: QR-Code scannen, Bändchen ans Handgelenk, fertig.</p>
    </FestivalHelp>

    <!-- Loading -->
    <div v-if="loading" aria-busy="true">
      Festivals werden geladen...
    </div>

    <!-- Error -->
    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <!-- Empty state -->
    <article v-else-if="festivals.length === 0" class="empty-state">
      <p>Noch kein Festival angelegt — leg direkt los!</p>
      <button @click="goToNew">Neues Festival</button>
    </article>

    <!-- Festivals table -->
    <table v-else class="mobile-card-table">
      <thead>
        <tr>
          <th>Festival</th>
          <th>Zeitraum</th>
          <th>Status</th>
          <th>Kennzahlen</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="event in festivals" :key="event.id">
          <td data-label="Festival">
            <router-link :to="`/admin/festival/${event.id}`">
              <strong>{{ event.name }}</strong>
            </router-link>
            <br />
            <small>{{ event.location || 'Kein Ort angegeben' }}</small>
          </td>
          <td data-label="Zeitraum">
            {{ formatDateOnly(event.start_at) }} – {{ formatDateOnly(event.end_at) }}
          </td>
          <td data-label="Status">
            <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
              {{ formatEventStatus(event.status) }}
            </span>
          </td>
          <td data-label="Kennzahlen">
            <div>{{ (event.festival_slots || []).length }} Zeitfenster</div>
            <div class="capacity-note">Kapazität {{ event.capacity }}</div>
          </td>
        </tr>
      </tbody>
    </table>
  </article>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../../services/api'
import { formatDateOnly, formatEventStatus } from '../../../utils/formatters.js'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'

const router = useRouter()

const loading = ref(true)
const loadError = ref(null)
const festivals = ref([])

async function loadFestivals() {
  loading.value = true
  loadError.value = null
  try {
    const result = await adminApi.festival.listEvents()
    festivals.value = result.items || []
  } catch (err) {
    loadError.value = err.message || 'Festivals konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
}

function goToNew() {
  router.push('/admin/festival/new')
}

onMounted(loadFestivals)
</script>

<style scoped>
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

header button {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
}

.empty-state button {
  width: auto;
  min-height: 44px;
}

.capacity-note {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}
</style>
